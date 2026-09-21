from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
from datetime import datetime
import pytz
import os
import requests
import pandas as pd
import numpy as np

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SCHWAB_CALLBACK_URL = "https://0-dte-seven.vercel.app/api/callback"
SCHWAB_BASE_URL = "https://api.schwabapi.com/marketdata/v1"

def get_schwab_access_token():
    app_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_SECRET")
    refresh_token = os.environ.get("SCHWAB_REFRESH_TOKEN")
    
    if not app_key or not refresh_token:
        raise Exception("환경 변수(SCHWAB_APP_KEY 또는 SCHWAB_REFRESH_TOKEN)가 설정되지 않았습니다.")
    
    auth_url = "https://api.schwabapi.com/v1/oauth/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": app_key
    }
    
    response = requests.post(auth_url, headers=headers, data=data, auth=(app_key, app_secret) if app_secret else None)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        # 토큰 갱신 과정에서 발생한 스왑 서버의 원본 에러를 그대로 전달
        raise Exception(f"스왑 토큰 갱신 실패 (HTTP {response.status_code}): {response.text}")

@app.get("/api/callback")
def auth_callback(code: str = None):
    if not code:
        return {"status": "fail", "detail": "인증 코드(code)가 전달되지 않았습니다."}
        
    app_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_SECRET")
    
    token_url = "https://api.schwabapi.com/v1/oauth/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": app_key,
        "redirect_uri": SCHWAB_CALLBACK_URL
    }
    
    try:
        response = requests.post(token_url, headers=headers, data=data, auth=(app_key, app_secret))
        if response.status_code == 200:
            token_data = response.json()
            return {
                "status": "success",
                "message": "🎉 찰스스왑 리프레시 토큰이 성공적으로 발급되었습니다!",
                "refresh_token": token_data.get("refresh_token"),
                "expires_in": token_data.get("expires_in")
            }
        else:
            return {"status": "fail", "detail": response.text}
    except Exception as e:
        return {"status": "fail", "detail": str(e)}

@app.get("/api/market-data")
def get_market_data():
    """
    [1단계 진단 모드] 
    야후 백업으로 숨기지 않고, 찰스스왑 API 통신 결과를 투명하게 진단합니다.
    """
    diagnostic_log = {}
    
    try:
        # 1. 토큰 발급 단계 진단
        diagnostic_log["step_1_token_request"] = "Attempting to get access token..."
        access_token = get_schwab_access_token()
        diagnostic_log["step_1_token_result"] = "Success"
        
        # 2. 마켓 데이터 요청 단계 진단
        headers = {"Authorization": f"Bearer {access_token}"}
        quote_url = f"{SCHWAB_BASE_URL}/quotes?symbols=%24SPX"
        
        diagnostic_log["step_2_quote_url"] = quote_url
        res = requests.get(quote_url, headers=headers)
        
        diagnostic_log["step_2_http_status"] = res.status_code
        diagnostic_log["step_2_raw_response"] = res.text[:500] # 응답 앞부분 500자 기록
        
        if res.status_code != 200:
            return {
                "status": "schwab_api_error",
                "diagnostic_info": diagnostic_log,
                "message": "찰스스왑 API가 비정상 응답을 반환했습니다."
            }
            
        data = res.json()
        return {
            "status": "success",
            "source": "Charles Schwab API (Verified)",
            "diagnostic_info": diagnostic_log,
            "raw_data": data
        }
        
    except Exception as e:
        return {
            "status": "diagnostic_exception",
            "error_detail": str(e),
            "diagnostic_info": diagnostic_log,
            "message": "찰스스왑 연동 과정에서 예외가 발생했습니다. 위 error_detail을 확인하세요."
        }
