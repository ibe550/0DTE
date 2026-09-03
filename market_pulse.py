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
import requests


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


CNN_FG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
_CNN_RATING_MAP = {
    "extreme fear": "Extreme Fear",
    "fear": "Fear",
    "neutral": "Neutral",
    "greed": "Greed",
    "extreme greed": "Extreme Greed",
}


def fetch_cnn_fear_greed():
    """
    CNN Fear & Greed Index를 실제로 가져온다.
    주의: CNN이 공식 문서화해서 제공하는 API가 아니라, CNN 웹페이지가 내부적으로
    쓰는 엔드포인트를 그대로 호출하는 것이다(널리 알려진 방법이지만 비공식).
    CNN이 예고 없이 구조를 바꾸면 이 함수도 깨질 수 있어서, 실패하면 앱이
    죽지 않고 근사치(calculate_fear_greed)로 자동 폴백하도록 만들어졌다.

    반환: (score, label, extras_dict, error_or_None)
    extras_dict: {'previous_close', 'one_week_ago', 'one_month_ago', 'one_year_ago'}
    """
    try:
        resp = requests.get(
            CNN_FG_URL,
            headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return None, None, None, f"CNN Fear&Greed 요청 실패: {e}"

    fg = data.get("fear_and_greed")
    if not fg:
        return None, None, None, f"CNN 응답 구조가 예상과 다릅니다 (최상위 키: {list(data.keys())})"

    try:
        score = round(float(fg["score"]))
    except Exception as e:
        return None, None, None, f"CNN 응답에서 score 파싱 실패: {e} (fear_and_greed 키: {list(fg.keys())})"

    rating_raw = str(fg.get("rating", "")).strip().lower()
    label = _CNN_RATING_MAP.get(rating_raw)
    if label is None:
        # 라벨을 못 찾으면 점수 기준으로 우리 기준을 적용 (그래도 숫자는 CNN 실제값)
        if score < 25:
            label = "Extreme Fear"
        elif score < 45:
            label = "Fear"
        elif score < 55:
            label = "Neutral"
        elif score < 75:
            label = "Greed"
        else:
            label = "Extreme Greed"

    extras = {
        "previous_close": fg.get("previous_close"),
        "one_week_ago": fg.get("previous_1_week"),
        "one_month_ago": fg.get("previous_1_month"),
        "one_year_ago": fg.get("previous_1_year"),
    }

    return score, label, extras, None
