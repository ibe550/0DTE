from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import requests
import os
import base64
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. 환경 변수 금고에서 정보 불러오기
APP_KEY = os.environ.get("SCHWAB_APP_KEY")
APP_SECRET = os.environ.get("SCHWAB_APP_SECRET")
REDIRECT_URI = "https://0-dte-seven.vercel.app/api/callback"

# Upstash Redis 주소
KV_URL = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
KV_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")

# --- [토큰 발급 및 로그인 라우터] ---

@app.get("/api/login")
def login():
    auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?client_id={APP_KEY}&redirect_uri={REDIRECT_URI}"
    return RedirectResponse(url=auth_url)

@app.get("/api/callback")
def callback(code: str):
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{APP_KEY}:{APP_SECRET}'.encode()).decode()}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    
    res = requests.post("https://api.schwabapi.com/v1/oauth/token", headers=headers, data=data)
    
    if res.status_code == 200:
        token_data = res.json()
        kv_headers = {"Authorization": f"Bearer {KV_TOKEN}"}
        requests.post(f"{KV_URL}/set/schwab_token", headers=kv_headers, json=json.dumps(token_data))
        return {"status": "success", "message": "찰스스왑 토큰 발급 및 저장 성공!"}
    
    return {"status": "fail", "error": "토큰 교환 실패", "details": res.json()}

# --- [실시간 시장 데이터 및 백업 라우터] ---

@app.get("/api/market")
def get_market_data():
    try:
        kv_headers = {"Authorization": f"Bearer {KV_TOKEN}"}
        token_res = requests.get(f"{KV_URL}/get/schwab_token", headers=kv_headers)
        
        if token_res.status_code != 200 or not token_res.json().get('result'):
            raise Exception("토큰 없음")
            
        token_data = json.loads(token_res.json()['result'])
        access_token = token_data['access_token']
        
        schwab_headers = {"Authorization": f"Bearer {access_token}"}
        quote_res = requests.get("https://api.schwabapi.com/marketdata/v1/quotes?symbols=$SPX", headers=schwab_headers)
        
        if quote_res.status_code == 200:
            current_price = quote_res.json()['$SPX']['quote']['lastPrice']
            return {
                "status": "success", 
                "source": "Charles Schwab", 
                "spx_price": current_price
            }
        else:
            raise Exception("찰스스왑 응답 에러")
            
    except Exception as e:
        try:
            spx = yf.Ticker("^SPX")
            hist = spx.history(period="5d")
            current_price = hist['Close'].iloc[-1]
            
            expirations = spx.options
            if expirations:
                nearest_expiry = expirations[0] 
                opt_chain = spx.option_chain(nearest_expiry)
                
                total_call_volume = int(opt_chain.calls['volume'].fillna(0).sum())
                total_put_volume = int(opt_chain.puts['volume'].fillna(0).sum())
            else:
                total_call_volume = 0
                total_put_volume = 0

            return {
                "status": "success", 
                "source": "Yahoo Finance (Backup)", 
                "spx_price": round(current_price, 2),
                "options_data": {
                    "expiry": nearest_expiry if expirations else "N/A",
                    "total_call_volume": total_call_volume,
                    "total_put_volume": total_put_volume
                }
            }
        except Exception as backup_error:
            return {"status": "fail", "error": f"백업 서버도 실패: {str(backup_error)}"}
