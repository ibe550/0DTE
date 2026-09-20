from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/market")
def get_market_data():
    try:
        raise Exception("Schwab API 아직 연결 안 됨")
    
    except Exception as e1:
        try:
            raise Exception("Moomoo API 아직 연결 안 됨")
            
        except Exception as e2:
            try:
                spx = yf.Ticker("^SPX")
                # 주말 에러를 막기 위해 '오늘 하루' 대신 '최근 5일' 데이터를 가져와 가장 마지막 값을 씁니다.
                hist = spx.history(period="5d")
                
                if hist.empty:
                    raise Exception("데이터 없음")
                    
                current_price = hist['Close'].iloc[-1]
                
                return {
                    "status": "success",
                    "source": "Yahoo Finance (Backup)",
                    "spx_price": round(current_price, 2)
                }
            except Exception as e3:
                return {"status": "fail", "error": str(e3)}
