import yfinance as yf
import pandas as pd
import numpy as np
import math


def run_probability_analysis(ticker="ES=F", period="1mo", interval="5m", lookahead_bars=6):
    """
    고도화된 퀀트 백테스트 엔진 (상승/하락 확률 양방향 대칭 분석)

    [변경 사항]
    기존 버전은 "상승 + 거래량 급증 + 고변동성" 조건에서만 신호를 잡았기 때문에,
    이미 위로 튄(pump) 캔들 뒤에서만 테스트하는 구조라 통계적으로 되돌림(하락) 쪽으로
    쏠릴 수밖에 없었다(단기 buying-climax 반전 효과). 지금은 상승 스파이크 신호와
    하락 스파이크 신호를 대칭으로 둘 다 계산해서 합산한다 -> 초기 방향에 상관없이
    "거래량 급증 + 고변동성 뒤엔 실제로 어느 쪽이 더 많이 나오는가"를 공정하게 측정한다.

    또한 표본 수가 작을 때 승률/하락률이 통계적으로 불안정하다는 걸 명확히 하기 위해
    신뢰도(confidence_level)와 95% 신뢰구간 오차범위(margin_of_error)를 함께 반환한다.
    """
    df = yf.download(tickers=ticker, period=period, interval=interval, progress=False)
    if df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # --- 파생 지표 계산 (수급, 변동성, 모멘텀) ---
    df['Returns'] = df['Close'].pct_change()
    df['Vol_MA'] = df['Volume'].rolling(10).mean()
    df['Vol_Spike'] = df['Volume'] > (df['Vol_MA'] * 1.8)  # 거래량 급증

    df['TR'] = np.maximum(df['High'] - df['Low'], abs(df['High'] - df['Close'].shift(1)))
    df['ATR'] = df['TR'].rolling(14).mean()
    df['Volatile_Market'] = df['TR'] > df['ATR']  # 변동성 확대 구간

    # N봉 뒤 가격 변화
    df['Future_Return'] = df['Close'].shift(-lookahead_bars) - df['Close']
    df['Target_Win'] = df['Future_Return'] > 0
    df['Target_Loss'] = df['Future_Return'] < 0

    # 데이터 끝부분(마지막 lookahead_bars개 봉)은 미래 값이 없어 Future_Return이 NaN이다.
    # 이 구간은 신호가 잡히더라도 승/패 판정이 불가능하므로 분석 대상에서 제외한다.
    has_future = df['Future_Return'].notna()

    # --- 대칭 신호: 상승 스파이크 / 하락 스파이크 둘 다 포함 ---
    bullish_signal = df['Vol_Spike'] & (df['Returns'] > 0) & df['Volatile_Market'] & has_future
    bearish_signal = df['Vol_Spike'] & (df['Returns'] < 0) & df['Volatile_Market'] & has_future
    combined_signal = bullish_signal | bearish_signal

    total_signals = int(combined_signal.sum())
    bullish_count = int(bullish_signal.sum())
    bearish_count = int(bearish_signal.sum())

    if total_signals == 0:
        return None

    win_signals = int((combined_signal & df['Target_Win']).sum())
    loss_signals = int((combined_signal & df['Target_Loss']).sum())

    win_rate = (win_signals / total_signals) * 100
    loss_rate = (loss_signals / total_signals) * 100

    avg_win = df[combined_signal & df['Target_Win']]['Future_Return'].mean()
    avg_loss = abs(df[combined_signal & df['Target_Loss']]['Future_Return'].mean())

    avg_win_val = avg_win if not np.isnan(avg_win) else 0.0
    avg_loss_val = avg_loss if not np.isnan(avg_loss) else 0.0

    ev = ((win_rate / 100) * avg_win_val) - ((loss_rate / 100) * avg_loss_val)

    # --- 통계적 신뢰도 (표본 수가 작으면 승률/하락률은 노이즈에 가깝다) ---
    p = win_rate / 100.0
    se = math.sqrt(p * (1 - p) / total_signals) if total_signals > 0 else 0.0
    margin_of_error = round(se * 1.96 * 100, 1)  # 95% 신뢰구간, %p 단위

    if total_signals < 30:
        confidence_level = "LOW"
    elif total_signals < 100:
        confidence_level = "MEDIUM"
    else:
        confidence_level = "HIGH"

    date_start = df.index[0].strftime("%m/%d %H:%M") if len(df) else None
    date_end = df.index[-1].strftime("%m/%d %H:%M") if len(df) else None

    return {
        "total_signals": total_signals,
        "bullish_signals": bullish_count,
        "bearish_signals": bearish_count,
        "win_rate": round(win_rate, 1),
        "loss_rate": round(loss_rate, 1),
        "avg_win": round(avg_win_val, 2),
        "avg_loss": round(avg_loss_val, 2),
        "expected_value": round(ev, 2),
        "confidence_level": confidence_level,
        "margin_of_error": margin_of_error,
        "date_start": date_start,
        "date_end": date_end,
    }
