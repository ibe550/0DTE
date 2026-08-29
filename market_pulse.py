"""
시장 심리/기술적 지표 계산 모듈.
RSI, VWAP 밴드, Fear & Greed 근사 지수를 계산한다.

[Fear & Greed 관련 주의사항]
CNN의 공식 Fear & Greed Index는 7개 지표(모멘텀, 강도, 폭, 풋/콜 비율,
정크본드 수요, 시장 변동성, 안전자산 수요)를 쓰는데 그 중 상당수는 유료
데이터가 필요하다. 여기서는 우리가 이미 갖고 있는 데이터(VIX, 가격 모멘텀,
당일 매수/매도 비중)만으로 근사치를 계산한다. CNN 지수와 다를 수 있다.
"""

import numpy as np
import pandas as pd


def calculate_rsi(close_series, period=14):
    """RSI(상대강도지수) 계산. 데이터 부족하면 50(중립)으로 채운다."""
    delta = close_series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def calculate_vwap_bands(df):
    """
    당일 세션 바(High/Low/Close/Volume)로 VWAP과 표준편차 밴드(±1σ, ±2σ)를 계산한다.
    df는 반드시 '오늘' 세션 데이터만 포함해야 한다 (전일 데이터 섞이면 왜곡됨).
    반환: (vwap_series, std_series)
    """
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3.0
    cum_vol = df['Volume'].cumsum()
    cum_vol_safe = cum_vol.replace(0, np.nan)

    cum_vol_price = (typical_price * df['Volume']).cumsum()
    vwap = cum_vol_price / cum_vol_safe

    price_diff_sq = (typical_price - vwap) ** 2
    cum_var = (price_diff_sq * df['Volume']).cumsum() / cum_vol_safe
    std = np.sqrt(cum_var)

    return vwap.bfill(), std.bfill()


def calculate_fear_greed(vix_history, price_history, volume_buy_pct=50.0):
    """
    근사 Fear & Greed 지수 (0~100).
    - vix_history: 최근 1~3개월 VIX 종가 Series (percentile 계산용)
    - price_history: 최근 가격 Series (모멘텀 계산용, 20개 이상 권장)
    - volume_buy_pct: 오늘 세션 매수 비중 (0~100, Volume+CVD 섹션 값 재사용)

    반환: (score 0~100, label)
    """
    # VIX 퍼센타일 (낮을수록 탐욕 쪽)
    if vix_history is not None and len(vix_history.dropna()) >= 5:
        vix_clean = vix_history.dropna()
        vix_now = vix_clean.iloc[-1]
        vix_percentile = (vix_clean < vix_now).mean() * 100
        vix_score = 100 - vix_percentile
    else:
        vix_score = 50.0

    # 가격 모멘텀 (20개 이동평균 대비)
    if price_history is not None and len(price_history.dropna()) >= 20:
        p = price_history.dropna()
        ma20 = p.rolling(20).mean().iloc[-1]
        now = p.iloc[-1]
        if ma20 and not np.isnan(ma20) and ma20 != 0:
            momentum_pct = (now - ma20) / ma20 * 100
            momentum_score = 50 + max(min(momentum_pct * 20, 50), -50)
        else:
            momentum_score = 50.0
    else:
        momentum_score = 50.0

    volume_score = max(0.0, min(100.0, volume_buy_pct))

    combined = (vix_score * 0.4) + (momentum_score * 0.3) + (volume_score * 0.3)
    combined = max(0.0, min(100.0, combined))

    if combined < 25:
        label = "Extreme Fear"
    elif combined < 45:
        label = "Fear"
    elif combined < 55:
        label = "Neutral"
    elif combined < 75:
        label = "Greed"
    else:
        label = "Extreme Greed"

    return round(combined), label
