from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf

app = FastAPI()

# 프론트엔드(화면)에서 데이터를 에러 없이 가져갈 수 있도록 권한 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/market")
def get_market_data():
    # 1순위: Charles Schwab API (추후 연동)
    try:
        # TODO: 찰스스왑 연결 코드 작성 예정
        raise Exception("Schwab API 아직 연결 안 됨")
    
    except Exception as e1:
        # 2순위: Moomoo API (추후 연동)
        try:
            # TODO: Moomoo 연결 코드 작성 예정
            raise Exception("Moomoo API 아직 연결 안 됨")
            
        except Exception as e2:
            # 3순위: Yahoo Finance (현재 즉시 작동하는 백업)
            try:
                spx = yf.Ticker("^SPX")
                hist = spx.history(period="1d", interval="1m")
                current_price = hist['Close'].iloc[-1]
                
                return {
                    "status": "success",
                    "source": "Yahoo Finance",
                    "spx_price": round(current_price, 2)
                }
            except Exception as e3:
                return {"status": "fail", "error": "모든 데이터 소스 연결 실패"}
