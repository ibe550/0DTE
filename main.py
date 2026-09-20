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

# Upstash Redis 주소 (Vercel 자동 생성)
KV_URL = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
KV_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")

# --- [토큰 발급 및 로그인 라우터] ---

@app.get("/api/login")
def login():
    """1. 사용자가 이 주소로 들어오면 찰스스왑 로그인 화면으로 보냅니다."""
    auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?client_id={APP_KEY}&redirect_uri={REDIRECT_URI}"
    return RedirectResponse(url=auth_url)

@app.get("/api/callback")
def callback(code: str):
    """2. 로그인 성공 시 찰스스왑이 이쪽으로 'code'를 보내주면 토큰으로 교환합니다."""
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{APP_KEY}:{APP_SECRET}'.encode()).decode()}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    
    # 토큰 발급 요청
    res = requests.post("https://api.schwabapi.com/v1/oauth/token", headers=headers, data=data)
    
    if res.status_code == 200:
        token_data = res.json()
        # 발급받은 토큰을 Upstash Redis 금고에 저장
        kv_headers = {"Authorization": f"Bearer {KV_TOKEN}"}
        requests.post(f"{KV_URL}/set/schwab_token", headers=kv_headers, json=json.dumps(token_data))
        
        return {"status": "success", "message": "찰스스왑 토큰 발급 및 저장 성공! 이제 앱 화면을 열어보세요."}
    
    return {"status": "fail", "error": "토큰 교환 실패", "details": res.json()}

# --- [실시간 시장 데이터 라우터] ---

@app.get("/api/market")
def get_market_data():
    try:
        # 1. Upstash Redis 금고에서 토큰 꺼내기
        kv_headers = {"Authorization": f"Bearer {KV_TOKEN}"}
        token_res = requests.get(f"{KV_URL}/get/schwab_token", headers=kv_headers)
        
        if token_res.status_code != 200 or not token_res.json().get('result'):
            raise Exception("토큰이 없습니다. 먼저 /api/login 에 접속해서 로그인하세요.")
            
        token_data = json.loads(token_res.json()['result'])
        access_token = token_data['access_token']
        
        # 2. 찰스스왑 API로 SPX 실시간 가격 가져오기
        schwab_headers = {"Authorization": f"Bearer {access_token}"}
        # 찰스스왑은 SPX 티커를 $SPX 로 씁니다
        quote_res = requests.get("https://api.schwabapi.com/marketdata/v1/quotes?symbols=$SPX", headers=schwab_headers)
        
        if quote_res.status_code == 200:
            quote_data = quote_res.json()
            # 찰스스왑에서 넘겨준 가격 뽑아내기
            current_price = quote_data['$SPX']['quote']['lastPrice']
            return {
                "status": "success", 
                "source": "Charles Schwab (실시간)", 
                "spx_price": current_price
            }
        else:
            raise Exception(f"찰스스왑 API 오류: {quote_res.text}")
            
    except Exception as e:
        # 찰스스왑 에러 발생 시 자동으로 야후 파이낸스(백업)로 전환
        try:
            spx = yf.Ticker("^SPX")
            hist = spx.history(period="5d")
            current_price = hist['Close'].iloc[-1]
            return {
                "status": "success", 
                "source": "Yahoo Finance (Backup)", 
                "spx_price": round(current_price, 2)
            }
        except Exception:
            return {"status": "fail", "error": str(e)}
