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

def fetch_yahoo_direct(symbol: str):
    """
    야후 웹사이트가 사용하는 실시간 차트/시세 원본 엔드포인트를 직접 찔러
    정둘러대거나 거짓말하는 것이 아니라, **웹사이트 화면에 보이는 데이터와 무료 오픈소스 라이브러리(`yfinance` 등)가 호출하는 엔드포인트의 데이터 구조가 다르기 때문에** 발생하는 전형적인 문제입니다. 

웹사이트에서 실시간으로 가격이 깜빡이는데도 파이썬 코드로 호출하면 예전 가격이나 멈춘 가격이 나오는 이유는 크게 세 가지입니다.

---

### 1. 웹사이트와 API가 바라보는 내부 엔드포인트 차이
* **야후 파이낸스 웹 브라우저:** 
  사용자가 페이지를 보고 있을 때는 웹소켓(WebSocket) 스트리밍이나 내부 캐싱이 거의 없는 별도의 실시간 스트림 API(`push` 방식)를 통해 BATS/EDGX 등의 호가/체결가를 즉각 밀어넣어 숫자를 갱신합니다.
* **`yfinance` 등 비공식 API 라이브러리:** 
  야후의 공식 승인 API가 아니라 웹용 REST 엔드포인트(`query1.finance.yahoo.com/v8/finance/chart/...` 등)를 호출합니다. 이 REST 엔드포인트는 서버 단에서 15분 지연이 걸려 있거나, 정규장 외 시간(애프터마켓/프리마켓/주말)에는 업데이트 주기가 매우 길고 CDN 캐시가 걸려 있어 최신 틱을 즉시 반영하지 않습니다.

### 2. 정규장과 장외(Pre/Post Market) 데이터 필드 분리
야후 웹사이트는 장외 시간에 접속하면 메인 숫자 아래에 **"At close: $XX.XX"** 와 **"After hours: $YY.YY"** 를 분리해서 표시합니다.
* 파이썬 등에서 단순 `ticker.info['currentPrice']`나 기본 차트 데이터를 부르면 장마감 기준가(`regularMarketPrice`)만 그대로 유지되는 경우가 많습니다.
* 장외 시간 실시간 체결가를 보려면 `postMarketPrice`나 `preMarketPrice` 필드를 따로 지정해서 읽어야 웹사이트에 뜨는 변동 가격과 일치합니다.

### 3. ETF(MAGS) 특유의 유동성 및 호가 갱신 지연
개별 대형주(애플, 엔비디아 등)에 비해 MAGS 같은 테마형 ETF는 정규장 외 시간(또는 거래량이 적은 시간대)에 실제 체결(Last Sale) 빈도가 낮을 수 있습니다. 웹사이트는 매수/매도 호가(Bid/Ask) 변동만 있어도 숫자를 깜빡이지만, API 차트/가격 응답은 **실제 체결가**만 반영해 정지된 것처럼 보일 수 있습니다.

---

### 확인 및 해결 방법

1. **필드 분리 조회 (`yfinance` 기준)**
   정규장 마감 후라면 `regularMarketPrice` 대신 아래 필드를 직접 찍어보셔야 합니다.
   ```python
   import yfinance as yf

   mags = yf.Ticker("MAGS")
   fast_info = mags.fast_info

   # fast_info의 last_price 또는 info의 postMarketPrice 확인
   print("Last Price:", fast_info.last_price)
   print("Post Market:", mags.info.get("postMarketPrice"))
