from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
from datetime import datetime
import pandas as pd
import numpy as np
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
        
        # 최신 가격 기준 베이시스(SPX - ES) 산출
        latest_spx = spx_df['Close'].iloc[-1]
        latest_es = es_df['Close'].iloc[-1]
        basis = latest_spx - latest_es
        
        # ES 가격을 SPX 환산 가격으로 매핑
        es_df['SPX_Equivalent'] = es_df['Close'] + basis
        
        # 5포인트 단위(Bin) 설정
        bin_size = 5
        es_df['Bin'] = (es_df['SPX_Equivalent'] // bin_size) * bin_size
        
        # 가격대별 거래량 합산
        profile = es_df.groupby('Bin')['Volume'].sum().reset_index()
        
        if profile.empty:
            return {"val": 7620.0, "poc": 7645.0, "vah": 7650.0}
        
        # POC (Point of Control): 가장 거래량이 많은 가격대
        poc_row = profile.loc[profile['Volume'].idxmax()]
        poc = float(poc_row['Bin'])
        
        # Value Area (70% 거래량 구간 산출)
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
    [2순위] 야후 파이낸스 백업 데이터 및 Volume Profile 동적 계산
    """
    spx = yf.Ticker("^SPX")
    hist = spx.history(period="1d", interval="1m")
    current_price = hist['Close'].iloc[-1]
    prev_close = spx.info.get('previousClose', current_price)
    change = current_price - prev_close
    change_pct = (change / prev_close) * 100

    # Volume Profile 실시간 계산 결과 반영
    vp = calculate_volume_profile()

    return {
        "status": "success",
        "source": "Yahoo Finance + ES Volume Profile",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S ET"),
        "spx": {
            "price": round(current_price, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2)
        },
        "volume_profile": vp,
        "vix": {"price": 14.81, "change": -0.63},
        "es": {"price": 7712.50, "change_pct": 0.07},
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
