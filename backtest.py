import yfinance as yf
import pandas as pd
import numpy as np

def run_probability_analysis(ticker="ES=F", period="1mo", interval="5m"):
    """
    저장소(DB)를 쓰지 않고 메모리 상에서 과거 데이터를 불러와 
    조건별 '상승 확률(True Probability)'과 '기대값(EV)'을 계산하는 벤터 스타일 분석 엔진
    """
    # 1. 과거 데이터 메모리 적재
    df = yf.download(tickers=ticker, period=period, interval=interval, progress=False)
    if df.empty:
        return None
        
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 2. 파생 지표 계산 (수급 및 변동성 조건)
    df['Returns'] = df['Close'].pct_change()
    df['Vol_MA'] = df['Volume'].rolling(10).mean()
    df['Vol_Spike'] = df['Volume'] > (df['Vol_MA'] * 1.8) # 거래량 급증 조건
    
    # N봉(예: 30분 뒤 = 5분봉 기준 6개 뒤) 가격 변화
    lookahead = 6
    df['Future_Return'] = df['Close'].shift(-lookahead) - df['Close']
    df['Target_Win'] = df['Future_Return'] > 0 # 상승 여부 (True/False)

    # 3. 확률 계산 (Conditional Probability)
    # 조건: 거래량이 급증하면서 양봉이 터졌을 때
    signal_condition = df['Vol_Spike'] & (df['Returns'] > 0)
    
    total_signals = signal_condition.sum()
    win_signals = (signal_condition & df['Target_Win']).sum()
    
    win_rate = (win_signals / total_signals * 100) if total_signals > 0 else 0
    
    avg_win = df[signal_condition & df['Target_Win']]['Future_Return'].mean()
    avg_loss = abs(df[signal_condition & (~df['Target_Win'])]['Future_Return'].mean())
    
    # 기대값 (Expected Value) 계산
    ev = (win_rate/100 * avg_win) - ((1 - win_rate/100) * avg_loss)

    return {
        "total_signals": int(total_signals),
        "win_rate": round(win_rate, 2),
        "avg_win": round(avg_win if not np.isnan(avg_win) else 0, 2),
        "avg_loss": round(avg_loss if not np.isnan(avg_loss) else 0, 2),
        "expected_value": round(ev if not np.isnan(ev) else 0, 2)
    }
