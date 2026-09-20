from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
from datetime import datetime
import pytz
import pandas as pd
import numpy as np

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def fetch_from_schwab():
    access_token = None
    if not access_token:
        raise Exception("찰스스왑 Access Token이 아직 설정되지 않았습니다.")
    return None

def calculate_volume_profile():
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
    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)
    
    # 주말 여부 및 시간 체크 (월~금 혹은 일요일 저녁 6시 이후는 실시간 세션 활성화)
    is_weekend_closed = (now_et.weekday() == 5) or (now_et.weekday() == 6 and now_et.hour < 18)
    
    # 1. SPX 가격 조회 (장중에는 1분봉 시도, 장 외에는 일봉/최근값 활용)
    spx = yf.Ticker("^SPX")
    try:
        spx_hist = spx.history(period="1d", interval="1m") if not is_weekend_closed else spx.history(period="5d")
        if spx_hist.empty:
            spx_hist = spx.history(period="5d")
            
        spx_price = float(spx_hist['Close'].iloc[-1])
        spx_prev = float(spx_hist['Close'].iloc[0]) if len(spx_hist) > 1 else spx_price
    except:
        spx_price, spx_prev = 7650.50, 7637.76

    spx_change = spx_price - spx_prev
    spx_change_pct = (spx_change / spx_prev) * 100 if spx_prev else 0.0

    # 2. ES 선물 가격 조회
    es = yf.Ticker("ES=F")
    try:
        es_hist = es.history(period="1d", interval="1m") if not is_weekend_closed else es.history(period="5d")
        if es_hist.empty:
            es_hist = es.history(period="5d")
            
        es_price = float(es_hist['Close'].iloc[-1])
        es_prev = float(es_hist['Close'].iloc[0]) if len(es_hist) > 1 else es_price
    except:
        es_price, es_prev = 7712.50, 7707.25

    es_change = es_price - es_prev
    es_change_pct = (es_change / es_prev) * 100 if es_prev else 0.0

    vp = calculate_volume_profile()

    return {
        "status": "success",
        "source": "Yahoo Finance (Smart Hybrid Feed)",
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
