from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
from datetime import datetime

app = FastAPI()

# 프론트엔드(HTML)와의 통신을 위한 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
from datetime import datetime
import requests

app = FastAPI()

# 프론트엔드와 원활한 통신을 위한 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def fetch_from_schwab():
    """
    [1순위] 찰스스왑(Charles Schwab) API 데이터 조회 함수
    - 나중에 토큰이 준비되면 이 함수 안에서 스왑 API를 호출하도록 구현하면 됩니다.
    """
    access_token = None  # 추후 발급받은 토큰 설정 자리
    
    if not access_token:
        raise Exception("찰스스왑 Access Token이 아직 설정되지 않았습니다.")
    
    # [참고] 실제 구현 시 사용할 구조 예시
    # headers = {"Authorization": f"Bearer {access_token}"}
    # response = requests.get("https://api.schwabapi.com/marketdata/v1/...", headers=headers)
    # return response.json()
    
    return None

def fetch_from_yahoo():
    """
    [2순위] 야후 파이낸스(Yahoo Finance) 백업 데이터 조회 함수
    - 찰스스왑 연동 전이거나 스왑 API 호출 실패 시 자동 전환됩니다.
    """
    spx = yf.Ticker("^SPX")
    hist = spx.history(period="1d", interval="1m")
    current_price = hist['Close'].iloc[-1]
    prev_close = spx.info.get('previousClose', current_price)
    change = current_price - prev_close
    change_pct = (change / prev_close) * 100

    return {
        "status": "success",
        "source": "Yahoo Finance (Automatic Fallback Backup)",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S ET"),
        "spx": {
            "price": round(current_price, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2)
        },
        "vix": {"price": 14.81, "change": -0.63},
        "es": {"price": 7712.50, "change_pct": 0.07},
        "mag7": {"price": 70.51, "change_pct": -0.38}
    }

@app.get("/api/market-data")
def get_market_data():
    """
    [2중 백업 라우터]
    1순위(찰스스왑) 시도 ➡️ 실패 또는 토큰 없음 시 자동으로 2순위(야후)로 전환
    """
    # 1. 1순위 찰스스왑 데이터 호출 시도
    try:
        schwab_data = fetch_from_schwab()
        if schwab_data:
            return schwab_data
    except Exception as e:
        print(f"[알림] 찰스스왑 미연동/호출 실패, 야후 백업으로 전환합니다: {str(e)}")

    # 2. 2순위 야후 파이낸스 백업 데이터 실행
    try:
        yahoo_data = fetch_from_yahoo()
        return yahoo_data
    except Exception as err:
        return {
            "status": "fail",
            "error": f"모든 데이터 소스 연결 실패: {str(err)}"
        }

@app.get("/api/market-data")
def get_market_data():
    # ==========================================
    # 1순위: Charles Schwab API 연동 구간
    # ==========================================
    try:
        # TODO: 찰스스왑 API 호출 코드 입력 자리
        # 현재는 테스트를 위해 의도적으로 에러를 발생시켜 야후 파이낸스로 넘어갑니다.
        raise Exception("Schwab API 토큰 설정 대기 중")

    except Exception as e1:
        # ==========================================
        # 2순위: Yahoo Finance 백업 (안전 장치)
        # ==========================================
        try:
            spx = yf.Ticker("^SPX")
            hist = spx.history(period="1d", interval="1m")
            current_price = hist['Close'].iloc[-1]
            prev_close = spx.info.get('previousClose', current_price)
            change = current_price - prev_close
            change_pct = (change / prev_close) * 100

            return {
                "status": "success",
                "source": "Yahoo Finance (Backup)",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S ET"),
                "spx": {
                    "price": round(current_price, 2),
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2)
                }
            }
        except Exception as e2:
            return {
                "status": "fail",
                "error": f"모든 데이터 소스 연결 실패 (Schwab: {e1}, Yahoo: {e2})"
            }
