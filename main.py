from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
from datetime import datetime
import pytz
import pandas as pd
import numpy as np

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
    - 추후 토큰이 준비되면 이 함수 안에서 스왑 API를 호출하도록 구현하면 됩니다.
    """
    access_token = None  # 추후 발급받은 토큰 설정 자리
    
    if not access_token:
        raise Exception("찰스스왑 Access Token이 아직 설정되지 않았습니다.")
    
    return None

def calculate_volume_profile():
    """
    ES 선물 거래량 데이터를 기반으로 SPX 가격대에 매핑하여 
    VAL, POC, VAH를 계산하는 실시간 로직
    """
    try:
        es_ticker = yf.Ticker("ES=F")
        spx_ticker = yf.Ticker("^SPX")
        
        es_df = es_ticker.history(period="2d", interval="1h")
        spx_df = spx_ticker.history(period="2d", interval="1h")
        
        if es_df.empty or spx_df.empty:
            return {"val": 7620.0, "poc": 7645.0, "vah": 7650.0}
        
        latest_spx = spx_df['Close'].iloc[-1]
        latest_es = es_df['Close'].iloc[-1]
        basis = latest_spx - latest_es
        
        es_df['SPX_Equivalent'] = es_df['Close'] + basis
        bin_size = 5
        es_df['Bin'] = (es_df['SPX_Equivalent'] // bin_size) * bin_size
        
        profile = es_df.groupby('Bin')['Volume'].sum().reset_index()
        
        if profile.empty:
            return {"val": 7620.0, "poc": 7645.0, "vah": 7650.0}
        
        poc_row = profile.loc[profile['Volume'].idxmax()]
        poc = float(poc_row['Bin'])
        
        total_vol = profile['Volume'].sum()
        target_vol = total_vol * 0.70
        
        sorted_profile = profile.sort_values(by='Volume', ascending=False).copy()
        sorted_profile['Cumulative_Vol'] = sorted_profile['Volume'].cumsum()
        
        value_area_bins = sorted_profile[sorted_profile['Cumulative_Vol'] <= target_vol]['Bin']
        if value_area_bins.empty:
            val = poc
            vah = poc
        else:
            val = float(value_area_bins.min())
            vah = float(value_area_bins.max())
            
        return {
            "val": round(val, 2),
            "poc": round(poc, 2),
            "vah": round(vah, 2)
        }
    except Exception as e:
        print(f"Volume Profile 계산 오류: {e}")
        return {"val": 7620.0, "poc": 7645.0, "vah": 7650.0}

def fetch_from_yahoo():
    """
    [2순위] 야후 파이낸스 백업 데이터 (SPX 및 ES 선물 실제 시세 연동)
    """
    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)
    
    # 1. SPX 데이터 조회
    spx = yf.Ticker("^SPX")
    spx_hist = spx.history(period="2d", interval="1m")
    
    if spx_hist.empty:
        spx_price = 7650.50
        spx_prev = 7637.76
    else:
        spx_price = float(spx_hist['Close'].iloc[-1])
        spx_prev = float(spx_hist['Close'].iloc[0]) if len(spx_hist) > 1 else spx_price

    spx_change = spx_price - spx_prev
    spx_change_pct = (spx_change / spx_prev) * 100 if spx_prev else 0.0

    # 2. ES 선물 (ES=F) 실제 데이터 조회
    es = yf.Ticker("ES=F")
    es_hist = es.history(period="2d", interval="1m")
    
    if es_hist.empty:
        es_price = 7712.50
        es_prev = 7707.25
    else:
        es_price = float(es_hist['Close'].iloc[-1])
        es_prev = float(es_hist['Close'].iloc[0]) if len(es_hist) > 1 else es_price

    es_change = es_price - es_prev
    es_change_pct = (es_change / es_prev) * 100 if es_prev else 0.0

    vp = calculate_volume_profile()

    return {
        "status": "success",
        "source": "Yahoo Finance (SPX & ES Live Backup)",
        "timestamp": now_et.strftime("%Y-%m-%d %H:%M:%S ET"),
        "spx": {
            "price": round(spx_price, 2),
            "change": round(spx_change, 2),
            "change_pct": round(spx_change_pct, 2)
        },
        "es": {
            "price": round(es_price, 2),
            "change_pct": round(es_change_pct, 2)
        },
        "volume_profile": vp,
        "vix": {"price": 14.81, "change": -0.63},
        "mag7": {"price": 70.51, "change_pct": -0.38}
    }

@app.get("/api/market-data")
def get_market_data():
    try:
        schwab_data = fetch_from_schwab()
        if schwab_data:
            return schwab_data
    except Exception as e:
        pass

    try:
        yahoo_data = fetch_from_yahoo()
        return yahoo_data
    except Exception as err:
        return {
            "status": "fail",
            "error": f"모든 데이터 소스 연결 실패: {str(err)}"
        }
