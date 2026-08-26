import sqlite3
import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
import time

# 1. DB 연결 및 테이블 생성
def init_db():
    conn = sqlite3.connect('quant_data.db')
    cursor = conn.cursor()
    
    # 1분봉 시세 및 수급 적재 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS market_data (
            timestamp TEXT PRIMARY KEY,
            ticker TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            est_time TEXT
        )
    ''')
    conn.commit()
    conn.close()

# 2. 데이터 수집 및 DB 저장 함수
def collect_and_store():
    init_db()
    conn = sqlite3.connect('quant_data.db')
    
    # S&P 500 선물(ES=F) 및 주요 지수 수집
    tickers = ['ES=F', '^VIX', '^SPX']
    est_tz = pytz.timezone('US/Eastern')
    
    for ticker in tickers:
        try:
            # 최근 1분봉 데이터 획득
            df = yf.download(tickers=ticker, period='1d', interval='1m', progress=False)
            if df.empty:
                continue
                
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            latest = df.iloc[-1]
            raw_time = df.index[-1]
            
            # 시간대 동부시(ET) 변환
            if raw_time.tzinfo is None:
                est_time = pytz.utc.localize(raw_time).astimezone(est_tz)
            else:
                est_time = raw_time.astimezone(est_tz)
                
            time_str = est_time.strftime('%Y-%m-%d %H:%M:%S')
            
            # DB 저장 (중복 시 IGNORE)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO market_data 
                (timestamp, ticker, open, high, low, close, volume, est_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                f"{time_str}_{ticker}",
                ticker,
                float(latest['Open']),
                float(latest['High']),
                float(latest['Low']),
                float(latest['Close']),
                int(latest['Volume']),
                time_str
            ))
            conn.commit()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Saved {ticker} data at {time_str}")
            
        except Exception as e:
            print(f"Error collecting {ticker}: {e}")
            
    conn.close()

if __name__ == "__main__":
    # 주기적 수집 실행 (예: 60초 마다)
    print("🚀 Quant Data Pipeline Collector Started...")
    while True:
        collect_and_store()
        time.sleep(60)
