"""
야후 파이낸스 옵션 체인 기반 GEX(감마 노출도) 계산 모듈.

[중요 - 데이터 정확도 관련 주의사항]
- 야후 옵션 데이터는 약 15분 지연이다. 실시간 아님.
- 야후는 델타/감마 등 그릭스를 직접 안 준다. 대신 야후가 주는 내재변동성(IV)과
  미결제약정(OI)으로 Black-Scholes 공식을 이용해 델타/감마를 '직접 계산'한다.
  실제 거래소/브로커가 주는 그릭스와 약간 다를 수 있다 (모델 기반 근사치).
- SPX 지수 옵션 자체는 yfinance로 잘 조회되지 않아서, 대신 유동성이 훨씬 좋은
  SPY 옵션 체인을 쓰고 스트라이크에 10을 곱해서 SPX 환산값으로 보여준다
  (SPY ≈ SPX/10 트래킹). 완벽히 같지는 않다.
"""

import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytz
import yfinance as yf
import streamlit as st

EST_TZ = pytz.timezone("US/Eastern")


def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x):
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)


def black_scholes_delta_gamma(spot, strike, time_years, rate, iv, is_call):
    """
    Black-Scholes 델타/감마 계산.
    time_years, iv가 너무 작으면(만기 임박·IV 데이터 이상) (0.0, 0.0) 반환해서
    나눗셈 에러를 피한다.
    """
    if time_years <= 1e-6 or iv is None or iv <= 1e-4 or spot <= 0 or strike <= 0:
        return 0.0, 0.0

    try:
        d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * time_years) / (iv * math.sqrt(time_years))
    except (ValueError, ZeroDivisionError):
        return 0.0, 0.0

    gamma = _norm_pdf(d1) / (spot * iv * math.sqrt(time_years))
    delta = _norm_cdf(d1) if is_call else _norm_cdf(d1) - 1.0

    return delta, gamma


@st.cache_data(ttl=120, show_spinner=False)
def fetch_risk_free_rate():
    """13주 미 국채 금리(^IRX)를 무위험이자율 근사치로 사용. 실패하면 4.5% 기본값."""
    try:
        h = yf.download(tickers="^IRX", period="5d", interval="1d", progress=False)
        if isinstance(h.columns, pd.MultiIndex):
            h.columns = h.columns.get_level_values(0)
        if not h.empty:
            return float(h['Close'].iloc[-1]) / 100.0
    except Exception:
        pass
    return 0.045


@st.cache_data(ttl=120)
def fetch_0dte_chain_with_greeks(ticker="SPY"):
    """
    오늘 만기(0DTE) 옵션 체인을 가져와서 Black-Scholes로 델타/감마를 계산해 붙인다.
    반환: (DataFrame_or_None, error_or_None, time_years, rate)
    DataFrame 컬럼: strike, is_call, openInterest, impliedVolatility, delta, gamma
    """
    try:
        t = yf.Ticker(ticker)
        available_exps = t.options
    except Exception as e:
        return None, f"야후 옵션 만기 목록 조회 실패: {e}", None, None

    if not available_exps:
        return None, "이 티커에 옵션 데이터가 없습니다.", None, None

    now_et = datetime.now(EST_TZ)
    today_str = now_et.strftime("%Y-%m-%d")

    if today_str not in available_exps:
        return None, f"오늘({today_str}) 만기인 0DTE 옵션이 없습니다 (다음 만기: {available_exps[0]}).", None, None

    try:
        chain = t.option_chain(today_str)
    except Exception as e:
        return None, f"야후 옵션체인 조회 실패: {e}", None, None

    calls = chain.calls.copy()
    puts = chain.puts.copy()
    calls['is_call'] = True
    puts['is_call'] = False

    combined = pd.concat([calls, puts], ignore_index=True)
    if combined.empty:
        return None, "옵션체인 응답이 비어있습니다.", None, None

    # 장 마감(16:00 ET)까지 남은 시간을 연 단위로 환산 (0DTE 만기 시간가치 기준)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    seconds_left = max((market_close - now_et).total_seconds(), 60)  # 최소 1분은 남은 것으로 처리
    time_years = seconds_left / (365.0 * 24.0 * 3600.0)

    rate = fetch_risk_free_rate()

    return combined, None, time_years, rate


def calculate_gex_from_yahoo_chain(chain_df, spot_price, time_years, rate, scale_to_spx=10.0,
                                     moneyness_band=0.10):
    """
    야후 0DTE 체인(calls+puts 합친 DataFrame)에서 스트라이크별 GEX를 계산한다.
    strike는 scale_to_spx를 곱해서 SPX 환산값으로 표시한다 (SPY 체인 기준일 때 10).

    moneyness_band: 스팟 대비 ±비율(기본 10%) 밖 스트라이크는 제외한다.
    0DTE는 거래량/OI가 스팟 근처에 몰리고, 멀리 떨어진 스트라이크는 유동성이 거의 없어
    야후 데이터에서 IV/OI가 결측치·이상치로 찍히는 경우가 많다. 그런 노이즈가
    Put Wall/Call Wall 계산을 왜곡하는 걸 막기 위한 필터다.

    반환: dict (schwab_client.calculate_gex_from_chain과 동일한 형태) 또는 None
    """
    if chain_df is None or chain_df.empty or spot_price is None or spot_price <= 0:
        return None

    strike_gex = {}
    net_delta_total = 0.0
    low_bound = spot_price * (1 - moneyness_band)
    high_bound = spot_price * (1 + moneyness_band)

    for _, row in chain_df.iterrows():
        strike_raw = row.get('strike')
        oi = row.get('openInterest')
        iv = row.get('impliedVolatility')
        is_call = row.get('is_call')

        # NaN은 <=0 비교에서 안 걸러지므로 반드시 명시적으로 체크한다
        # (야후 옵션 데이터는 유동성 낮은 스트라이크에서 OI가 NaN으로 오는 경우가 흔함).
        if strike_raw is None or pd.isna(strike_raw):
            continue
        if oi is None or pd.isna(oi) or oi <= 0:
            continue
        if iv is None or pd.isna(iv) or iv <= 0.01 or iv > 3.0:  # 비정상 IV(이상치) 배제
            continue
        if not (low_bound <= strike_raw <= high_bound):  # 스팟에서 너무 먼 스트라이크 배제
            continue

        delta, gamma = black_scholes_delta_gamma(spot_price, strike_raw, time_years, rate, iv, is_call)
        if gamma == 0.0 and delta == 0.0:
            continue

        gex = oi * gamma * 100 * (spot_price ** 2) * 0.01
        delta_exposure = oi * delta * 100

        strike_display = round(strike_raw * scale_to_spx, 0)
        if strike_display not in strike_gex:
            strike_gex[strike_display] = {"call_gex": 0.0, "put_gex": 0.0}

        if is_call:
            strike_gex[strike_display]["call_gex"] += gex
        else:
            strike_gex[strike_display]["put_gex"] -= gex

        net_delta_total += delta_exposure

    if not strike_gex:
        return None

    by_strike = []
    for strike in sorted(strike_gex.keys()):
        call_gex = strike_gex[strike]["call_gex"]
        put_gex = strike_gex[strike]["put_gex"]
        by_strike.append({
            "strike": strike,
            "call_gex": call_gex,
            "put_gex": put_gex,
            "net_gex": call_gex + put_gex,
        })

    call_wall = max(by_strike, key=lambda x: x["call_gex"])["strike"]
    put_wall = min(by_strike, key=lambda x: x["put_gex"])["strike"]
    net_gex_total = sum(x["net_gex"] for x in by_strike)

    gamma_flip = None
    cumulative = 0.0
    for row in by_strike:
        prev_cumulative = cumulative
        cumulative += row["net_gex"]
        if prev_cumulative != 0 and (
            (prev_cumulative < 0 <= cumulative) or (prev_cumulative > 0 >= cumulative)
        ):
            gamma_flip = row["strike"]
            break

    return {
        "by_strike": by_strike,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "gamma_flip": gamma_flip,
        "net_gex_total": net_gex_total,
        "net_delta_total": net_delta_total,
    }
