"""
수정된 시세 조회 함수들.
app.py의 fetch_alpaca_stock_snapshot ~ fetch_market_data 부분을
아래 내용으로 통째로 교체하세요.
"""

import time
import yfinance as yf
import requests
import streamlit as st


def fetch_alpaca_stock_snapshot(symbol="SPY"):
    """Alpaca 스냅샷. 실패 시 (None, None, None) 반환 (0.0이 아님 -> 실패를 명확히 구분)."""
    if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
        return (None, None, None)
    try:
        url = f"https://data.alpaca.markets/v2/stocks/{symbol}/snapshot"
        headers = {
            "APCA-API-KEY-ID": ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
        }
        resp = requests.get(url, headers=headers, timeout=4)
        resp.raise_for_status()
        data = resp.json()
        latest_trade = data.get("latestTrade", {})
        prev_daily = data.get("prevDailyBar", {})

        price = float(latest_trade.get("p", 0.0))
        prev_close = float(prev_daily.get("c", 0.0))

        if price > 0 and prev_close > 0:
            chg = price - prev_close
            pct = (chg / prev_close) * 100.0
            return (price, chg, pct)
        elif price > 0:
            return (price, 0.0, 0.0)
    except Exception as e:
        st.session_state.setdefault("data_errors", []).append(f"Alpaca({symbol}): {e}")
    return (None, None, None)


def fetch_single_ticker(symbol, retries=2):
    """
    실시간에 가까운 가격을 가져온다.
    1) fast_info(가장 빠르고 실시간에 가까움) 우선 시도
    2) 실패하면 1분봉 history로 폴백
    3) 그래도 실패하면 (None, None, None) 반환 -> 절대 가짜 숫자를 만들지 않음
    """
    last_err = None
    for attempt in range(retries):
        try:
            t = yf.Ticker(symbol)

            # 1) fast_info로 실시간 가격 시도
            try:
                fi = t.fast_info
                price = float(fi.get("last_price") or fi.get("lastPrice") or 0.0)
                prev_close = float(fi.get("previous_close") or fi.get("previousClose") or 0.0)
                if price > 0 and prev_close > 0:
                    chg = price - prev_close
                    pct = (chg / prev_close) * 100.0
                    return (price, chg, pct)
            except Exception:
                pass

            # 2) 폴백: 최근 2일치 일봉으로 종가/전일종가 계산
            hist = t.history(period="5d", interval="1d")
            if not hist.empty:
                p = float(hist['Close'].iloc[-1])
                prev = float(hist['Close'].iloc[-2]) if len(hist) > 1 else p
                chg = p - prev
                pct = (chg / prev) * 100.0 if prev != 0 else 0.0
                if p > 0:
                    return (p, chg, pct)

            last_err = "empty response"
        except Exception as e:
            last_err = str(e)
        time.sleep(0.5)

    st.session_state.setdefault("data_errors", []).append(f"{symbol}: {last_err}")
    return (None, None, None)


@st.cache_data(ttl=5)
def fetch_market_data():
    st.session_state["data_errors"] = []  # 매 호출마다 에러 로그 초기화

    alp_spy_p, alp_spy_c, alp_spy_pct = fetch_alpaca_stock_snapshot("SPY")

    # 주의: Yahoo Finance의 S&P500 지수 티커는 ^SPX가 아니라 ^GSPC 입니다.
    spx_p, spx_c, spx_pct = fetch_single_ticker('^GSPC')
    es_p, es_c, es_pct = fetch_single_ticker('ES=F')
    vix_p, vix_c, vix_pct = fetch_single_ticker('^VIX')
    spy_p, spy_c, spy_pct = fetch_single_ticker('SPY')

    if alp_spy_p is not None:
        spy_p, spy_c, spy_pct = alp_spy_p, alp_spy_c, alp_spy_pct

    # SPX 조회가 실패했을 때만 SPY 기반으로 근사치 계산 (SPY 자체가 없으면 계산 안 함)
    if spx_p is None and spy_p is not None:
        spx_p, spx_c, spx_pct = spy_p * 10.0, spy_c * 10.0, spy_pct

    if es_p is None and spy_p is not None:
        es_p, es_c, es_pct = spy_p * 10.0, spy_c * 10.0, spy_pct

    # 더 이상 하드코딩된 가짜 숫자로 대체하지 않습니다.
    # None으로 두고, 화면에서 "N/A"로 명확히 표시합니다.
    return {
        'spx': (spx_p, spx_c, spx_pct),
        'vix': (vix_p, vix_c, vix_pct),
        'es': (es_p, es_c, es_pct),
        'spy': (spy_p, spy_c, spy_pct),
        'errors': st.session_state.get("data_errors", []),
    }
