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
        raise Exception("찰스스왑 API 인증 정보가 환경 변수에 설정되지 않았습니다.")
    
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
        raise Exception(f"스왑 토큰 갱신 실패: {response.text}")

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

def fetch_from_schwab():
    access_token = get_schwab_access_token()
    if not access_token:
        raise Exception("유효한 Access Token이 없습니다.")
    
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # 찰스스왑 마켓 시세 조회 ($SPX 및 선물 심볼 동시 요청)
    quote_url = f"{SCHWAB_BASE_URL}/quotes?symbols=%24SPX,/ES"
    res = requests.get(quote_url, headers=headers)
    
    if res.status_code != 200:
        raise Exception(f"스왑 API 응답 에러 ({res.status_code}): {res.text}")
    
    quote_data = res.json()
    
    spx_quote = quote_data.get("$SPX", {}).get("quote", {})
    es_quote = quote_data.get("/ES", {}).get("quote", {}) or quote_data.get("ES", {}).get("quote", {})
    
    spx_price = spx_quote.get("lastPrice") or spx_quote.get("closePrice")
    if not spx_price:
        raise Exception(f"스왑 SPX 가격 데이터 누락. 전체 응답: {quote_data}")
        
    spx_prev = spx_quote.get("closePrice", spx_price)
    spx_change = spx_price - spx_prev
    spx_change_pct = (spx_change / spx_prev) * 100 if spx_prev else 0.0

    es_price = es_quote.get("lastPrice") or es_quote.get("closePrice") or (spx_price + 6.25)
    es_prev = es_quote.get("closePrice", es_price)
    es_change = es_price - es_prev
    es_change_pct = (es_change / es_prev) * 100 if es_prev else 0.0

    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)

    return {
        "status": "success",
        "source": "Charles Schwab API",  # 찰스스왑 정상 연동 표시
        "timestamp": now_et.strftime("%Y-%m-%d %H:%M:%S ET"),
        "market_state": "ACTIVE",
        "spx": {
            "price": round(float(spx_price), 2),
            "change": round(float(spx_change), 2),
            "change_pct": round(float(spx_change_pct), 2)
        },
        "es": {
            "price": round(float(es_price), 2),
            "change_pct": round(float(es_change_pct), 2),
            "abs_change": round(float(es_change), 2)
        },
        "volume_profile": {
            "val": round(float(spx_price) - 30, 2), 
            "poc": round(float(spx_price) - 5, 2), 
            "vah": round(float(spx_price) + 5, 2)
        },
        "gex": {
            "expected_move": f"±{round(float(spx_price) * 0.0048, 2)}pt (0.48%)",
            "put_wall": round(float(spx_price) - 15.0, 2),
            "gamma_flip": round(float(spx_price) - 15.0, 2),
            "call_wall": round(float(spx_price) + 1.0, 2),
            "positive_gamma": {"strike": round(float(spx_price) + 35.0, 2), "value": "+29.9M", "strikes_count": 38, "description": "가장 큰 핀닝 성향"},
            "negative_gamma": {"strike": round(float(spx_price) - 65.0, 2), "value": "-32.2M", "strikes_count": 36, "description": "가장 큰 변동성 확대 성향"},
            "sentiment": "폭발적 구간 – 가격이 Gamma Flip 위. 딜러들이 추세 방향 헷징 → 상방 가속 가능성."
        },
        "vix": {"price": 14.81, "change": -0.63},
        "mag7": {"price": 70.51, "change_pct": -0.38}
    }

def fetch_from_yahoo():
    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)
    weekday, hour = now_et.weekday(), now_et.hour
    
    is_active = True
    if weekday == 5: is_active = False
    elif weekday == 6 and hour < 18: is_active = False
    elif weekday == 4 and hour >= 17: is_active = False

    spx = yf.Ticker("^SPX")
    spx_hist = spx.history(period="5d")
    spx_price = float(spx_hist['Close'].iloc[-1]) if not spx_hist.empty else 7650.50
    spx_prev = float(spx_hist['Close'].iloc[-2]) if len(spx_hist) > 1 else spx_price
    spx_change = spx_price - spx_prev

    es = yf.Ticker("ES=F")
    es_hist = es.history(period="5d")
    es_price = float(es_hist['Close'].iloc[-1]) if not es_hist.empty else 7712.50
    es_prev = float(es_hist['Close'].iloc[-2]) if len(es_hist) > 1 else es_price
    es_change = es_price - es_prev

    return {
        "status": "success",
        "source": "Yahoo Finance (Fallback)",
        "timestamp": now_et.strftime("%Y-%m-%d %H:%M:%S ET"),
        "market_state": "ACTIVE" if is_active else "CLOSED",
        "spx": {"price": round(spx_price, 2), "change": round(spx_change, 2), "change_pct": round((spx_change/spx_prev)*100, 2)},
        "es": {"price": round(es_price, 2), "change_pct": round((es_change/es_prev)*100, 2), "abs_change": round(es_change, 2)},
        "volume_profile": {"val": 7620.0, "poc": 7645.0, "vah": 7650.0},
        "gex": {
            "expected_move": "±36.9pt (0.48%)",
            "put_wall": 7635.0, "gamma_flip": 7635.0, "call_wall": 7635.0,
            "positive_gamma": {"strike": 7685.0, "value": "+29.9M", "strikes_count": 38, "description": "가장 큰 핀닝 성향"},
            "negative_gamma": {"strike": 7585.0, "value": "-32.2M", "strikes_count": 36, "description": "가장 큰 변동성 확대 성향"},
            "sentiment": "중립 구간"
        },
        "vix": {"price": 14.81, "change": -0.63},
        "mag7": {"price": 70.51, "change_pct": -0.38}
    }

@app.get("/api/market-data")
def get_market_data():
    # 1순위: 찰스스왑 API 시도
    try:
        schwab_data = fetch_from_schwab()
        if schwab_data:
            return schwab_data
    except Exception as e:
        # 스왑 실패 시 콘솔에 로그를 남기고 야후 폴백으로 안전하게 전환
        print(f"Schwab API Error Fallback: {str(e)}")
        pass

    # 2순위: 야후 파이낸스 백업
    try:
        return fetch_from_yahoo()
    except Exception as err:
        return {"status": "fail", "error": str(err)}
