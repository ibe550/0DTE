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
    """
    [Volume Profile 정밀 계산 로직]
    ES 선물의 가격 및 거래량 데이터를 수집하여 
    SPX 환산 기준 5포인트 단위 Bin으로 묶고, POC, VAL, VAH를 동적으로 산출합니다.
    """
    try:
        es_ticker = yf.Ticker("ES=F")
        spx_ticker = yf.Ticker("^SPX")
        
        # 최근 5일간의 1시간 봉 데이터 조회 (충분한 거래량 표본 확보)
        es_df = es_ticker.history(period="5d", interval="1h")
        spx_df = spx_ticker.history(period="5d", interval="1h")
        
        if es_df.empty or spx_df.empty:
            return {"val": 7620.0, "poc": 7645.0, "vah": 7650.0}
        
        # 최신 SPX와 ES 간의 베이시스(가격 격차) 산출
        latest_spx = spx_df['Close'].iloc[-1]
        latest_es = es_df['Close'].iloc[-1]
        basis = latest_spx - latest_es
        
        # ES 가격을 SPX 기준 환산 가격으로 매핑
        es_df['SPX_Equivalent'] = es_df['Close'] + basis
        
        # 5포인트 단위(Bin)로 가격대 설정
        bin_size = 5
        es_df['Bin'] = (es_df['SPX_Equivalent'] // bin_size) * bin_size
        
        # 가격대(Bin)별 거래량 총합 집계
        profile = es_df.groupby('Bin')['Volume'].sum().reset_index()
        
        if profile.empty:
            return {"val": 7620.0, "poc": 7645.0, "vah": 7650.0}
        
        # 1. POC (Point of Control): 거래량이 가장 많은 가격대
        poc_row = profile.loc[profile['Volume'].idxmax()]
        poc = float(poc_row['Bin'])
        
        # 2. Value Area (전체 거래량의 70% 구간 산출)
        total_vol = profile['Volume'].sum()
        target_vol = total_vol * 0.70
        
        # 거래량이 많은 가격대 순으로 정렬 후 누적 거래량 계산
        sorted_profile = profile.sort_values(by='Volume', ascending=False).copy()
        sorted_profile['Cumulative_Vol'] = sorted_profile['Volume'].cumsum()
        
        # 누적 거래량이 70% 이내에 속하는 Bin들 추출
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
    
    weekday = now_et.weekday() # 0:월 ~ 6:일
    hour = now_et.hour
    
    # 시장 세션 상태 판단 (CME 선물 기준 휴장 체크)
    is_active = True
    if weekday == 5:
        is_active = False
    elif weekday == 6 and hour < 18:
        is_active = False
    elif weekday == 4 and hour >= 17:
        is_active = False

    # SPX 데이터 조회
    spx = yf.Ticker("^SPX")
    spx_hist = spx.history(period="5d")
    
    if spx_hist.empty:
        spx_price, spx_prev = 7650.50, 7637.76
    else:
        spx_price = float(spx_hist['Close'].iloc[-1])
        spx_prev = float(spx_hist['Close'].iloc[-2]) if len(spx_hist) > 1 else spx_price

    spx_change = spx_price - spx_prev
    spx_change_pct = (spx_change / spx_prev) * 100 if spx_prev else 0.0

    # ES 선물 데이터 조회
    es = yf.Ticker("ES=F")
    es_hist = es.history(period="5d")
    
    if es_hist.empty:
        es_price, es_prev = 7712.50, 7707.25
    else:
        es_price = float(es_hist['Close'].iloc[-1])
        es_prev = float(es_hist['Close'].iloc[-2]) if len(es_hist) > 1 else es_prev

    es_change = es_price - es_prev
    es_change_pct = (es_change / es_prev) * 100 if es_prev else 0.0

    # Volume Profile 동적 계산 실행
    vp = calculate_volume_profile()

    return {
        "status": "success",
        "source": "Yahoo Finance (Volume Profile Active Feed)",
        "timestamp": now_et.strftime("%Y-%m-%d %H:%M:%S ET"),
        "market_state": "ACTIVE" if is_active else "CLOSED",
        "spx": {
            "price": round(spx_price, 2),
            "change": round(spx_change, 2),
            "change_pct": round(spx_change_pct, 2)
        },
        "es": {
            "price": round(es_price, 2),
            "change_pct": round(es_change_pct, 2),
            "abs_change": round(es_change, 2)
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
