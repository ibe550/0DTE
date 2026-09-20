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
)

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
