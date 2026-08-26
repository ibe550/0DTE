import yfinance as yf
import pandas as pd
import numpy as np

def run_probability_analysis(ticker="ES=F", period="1mo", interval="5m", lookahead_bars=6):
    """
    고도화된 퀀트 백테스트 엔진 (상승/하락 확률 양방향 분석)
    """
    # 1. 과거 선물 및 VIX 데이터 다운로드
    df = yf.download(tickers=ticker, period=period, interval=interval, progress=False)
    if df.empty:
        return None
        
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 2. 파생 지표 계산 (수급, 변동성, 모멘텀)
    df['Returns'] = df['Close'].pct_change()
    df['Vol_MA'] = df['Volume'].rolling(10).mean()
    df['Vol_Spike'] = df['Volume'] > (df['Vol_MA'] * 1.8) # 거래량 급증
    
    # ATR 기반 변동성 필터
    df['TR'] = np.maximum(df['High'] - df['Low'], abs(df['High'] - df['Close'].shift(1)))
    df['ATR'] = df['TR'].rolling(14).mean()
    df['Volatile_Market'] = df['TR'] > df['ATR'] # 변동성 확대 구간

    # N봉 뒤 가격 변화
    df['Future_Return'] = df['Close'].shift(-lookahead_bars) - df['Close']
    df['Target_Win'] = df['Future_Return'] > 0
    df['Target_Loss'] = df['Future_Return'] < 0

    # 3. 복합 조건 시그널
    signal_condition = df['Vol_Spike'] & (df['Returns'] > 0) & df['Volatile_Market']
    
    total_signals = int(signal_condition.sum())
    
    if total_signals == 0:
        return None

    win_signals = int((signal_condition & df['Target_Win']).sum())
    loss_signals = int((signal_condition & df['Target_Loss']).sum())
    
    win_rate = (win_signals / total_signals) * 100
    loss_rate = (loss_signals / total_signals) * 100
    
    avg_win = df[signal_condition & df['Target_Win']]['Future_Return'].mean()
    avg_loss = abs(df[signal_condition & df['Target_Loss']]['Future_Return'].mean())
    
    avg_win_val = avg_win if not np.isnan(avg_win) else 0.0
    avg_loss_val = avg_loss if not np.isnan(avg_loss) else 0.0
    
    # 기대값 (EV) 계산
    ev = ((win_rate / 100) * avg_win_val) - ((loss_rate / 100) * avg_loss_val)

    return {
        "total_signals": total_signals,
        "win_rate": round(win_rate, 1),
        "loss_rate": round(loss_rate, 1),
        "avg_win": round(avg_win_val, 2),
        "avg_loss": round(avg_loss_val, 2),
        "expected_value": round(ev, 2)
    }
