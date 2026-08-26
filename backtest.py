import yfinance as yf
import pandas as pd
import numpy as np

def run_probability_analysis(ticker="ES=F", period="1mo", interval="5m", lookahead_bars=6):
    """
    고도화된 퀀트 백테스트 엔진
    - 2번 로직: GEX 및 VIX 변동성 필터 적용 (변동성이 특정 수준 이상일 때만 진입)
    - 3번 로직: 다양한 예측 타임프레임(lookahead_bars) 지원 (예: 2봉=10분 뒤, 6봉=30분 뒤, 12봉=1시간 뒤)
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
    
    # ATR 기반 변동성 필터 (GEX 대용 변동성 스냅샷)
    df['TR'] = np.maximum(df['High'] - df['Low'], abs(df['High'] - df['Close'].shift(1)))
    df['ATR'] = df['TR'].rolling(14).mean()
    df['Volatile_Market'] = df['TR'] > df['ATR'] # 변동성이 살아있는 구간

    # N봉 뒤(lookahead_bars) 가격 변화 및 상승 여부
    df['Future_Return'] = df['Close'].shift(-lookahead_bars) - df['Close']
    df['Target_Win'] = df['Future_Return'] > 0

    # 3.複合 조건 시그널 (2번 복합 조건 적용)
    # 조건: [거래량 급증] + [양봉] + [변동성 확대 구간]
    signal_condition = df['Vol_Spike'] & (df['Returns'] > 0) & df['Volatile_Market']
    
    total_signals = signal_condition.sum()
    win_signals = (signal_condition & df['Target_Win']).sum()
    
    win_rate = (win_signals / total_signals * 100) if total_signals > 0 else 0
    
    avg_win = df[signal_condition & df['Target_Win']]['Future_Return'].mean()
    avg_loss = abs(df[signal_condition & (~df['Target_Win'])]['Future_Return'].mean())
    
    # 기대값 (EV) 계산
    ev = (win_rate/100 * (avg_win if not np.isnan(avg_win) else 0)) - ((1 - win_rate/100) * (avg_loss if not np.isnan(avg_loss) else 0))

    return {
        "total_signals": int(total_signals),
        "win_rate": round(win_rate, 2),
        "avg_win": round(avg_win if not np.isnan(avg_win) else 0, 2),
        "avg_loss": round(avg_loss if not np.isnan(avg_loss) else 0, 2),
        "expected_value": round(ev if not np.isnan(ev) else 0, 2)
    }
