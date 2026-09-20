from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
from datetime import datetime

app = FastAPI()

# 프론트엔드(대시보드 화면)와의 원활한 통신 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/market-data")
def get_market_data():
    # ==========================================
    # 1순위: Charles Schwab API 연동 구간
    # ==========================================
    try:
        # TODO: 찰스스왑 OAuth 토큰 및 옵션 체인 API 호출 코드 작성
        # 예: response = requests.get("https://api.schwabapi.com/...", headers=...)
        # 정상 데이터를 받아오면 아래와 같이 리턴합니다.
        
        # 현재는 테스트를 위해 일부러 에러를 발생시켜 백업으로 넘어가게 합니다.
        raise Exception("Schwab API 토큰 대기 중")

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

            # 앞서 만든 대시보드 UI에 꽂아넣을 JSON 데이터 구조
            return {
                "status": "success",
                "source": "Yahoo Finance Fallback",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S ET"),
                "spx": {
                    "price": round(current_price, 2),
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2)
                },
                "vix": {"price": 14.81, "change": -0.63},
                "vix_9d": {"price": 12.27, "change": -1.12},
                "es": {"price": 7712.50, "change_pct": 0.07},
                "mag7": {"price": 70.51, "change_pct": -0.38},
                "yields": {
                    "y2": "4.756%", "y2_bp": "+6.6 bp",
                    "y10": "5.000%", "y10_bp": "+5.3 bp",
                    "y30": "5.328%", "y30_bp": "+3.2 bp",
                    "spread": "+24 bp"
                }
            }
        except Exception as e2:
            return {
                "status": "fail",
                "error": f"모든 데이터 소스 연결 실패 (Schwab: {e1}, Yahoo: {e2})"
            }
