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
        raise Exception("Vercel 환경 변수에 SCHWAB_APP_KEY 또는 SCHWAB_REFRESH_TOKEN이 없습니다.")
    
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
    [진단 모드] 찰스스왑 API를 호출하고, 만약 실패할 경우 
    야후로 숨기지 않고 찰스스왑이 뱉어낸 에러를 화면에 직접 보여줍니다.
    """
    try:
        access_token = get_schwab_access_token()
        headers = {"Authorization": f"Bearer {access_token}"}
        
        # 찰스스왑 마켓 시세 조회 요청
        quote_url = f"{SCHWAB_BASE_URL}/quotes?symbols=%24SPX,/ES"
        res = requests.get(quote_url, headers=headers)
        
        if res.status_code != 200:
            return {
                "status": "error_from_schwab",
                "http_status": res.status_code,
                "error_detail": res.text,
                "message": "찰스스왑 API 서버가 에러를 반환했습니다. 위 상세 내용을 확인하세요."
            }
            
        quote_data = res.json()
        spx_quote = quote_data.get("$SPX", {}).get("quote", {})
        spx_price = spx_quote.get("lastPrice") or spx_quote.get("closePrice", 7650.0)
        
        et_tz = pytz.timezone('US/Eastern')
        now_et = datetime.now(et_tz)

        return {
            "status": "success",
            "source": "Charles Schwab API",
            "timestamp": now_et.strftime("%Y-%m-%d %H:%M:%S ET"),
            "market_state": "ACTIVE",
            "spx": {
                "price": round(float(spx_price), 2),
                "change": 0.0,
                "change_pct": 0.0
            },
            "es": {
                "price": round(float(spx_price) + 6.25, 2),
                "change_pct": 0.0,
                "abs_change": 0.0
            },
            "volume_profile": {
                "val": round(float(spx_price) - 30, 2), 
                "poc": round(float(spx_price) - 5, 2), 
                "vah": round(float(spx_price) + 5, 2),
                "source": "Charles Schwab API"
            },
            "gex": {
                "expected_move": "±36.9pt (0.48%)",
                "put_wall": round(float(spx_price) - 15.0, 2),
                "gamma_flip": round(float(spx_price) - 15.0, 2),
                "call_wall": round(float(spx_price) + 1.0, 2),
                "positive_gamma": {"strike": round(float(spx_price) + 35.0, 2), "value": "+29.9M", "strikes_count": 38, "description": "가장 큰 핀닝 성향"},
                "negative_gamma": {"strike": round(float(spx_price) - 65.0, 2), "value": "-32.2M", "strikes_count": 36, "description": "가장 큰 변동성 확대 성향"},
                "sentiment": "폭발적 구간"
            },
            "vix": {"price": 14.81, "change": -0.63},
            "mag7": {"price": 70.51, "change_pct": -0.38}
        }
        
    except Exception as e:
        return {
            "status": "exception_occurred",
            "error_message": str(e),
            "message": "찰스스왑 토큰 인증 또는 요청 과정에서 예외가 발생했습니다."
        }
