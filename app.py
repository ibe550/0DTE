import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time as dtime
import pytz
import time
import yfinance as yf
import requests

from backtest import run_probability_analysis, run_walk_forward_analysis
from quant_engine import SimonsBenterQuantEngine
import signal_tracker
import macro_calendar
import market_pulse
import news_feed
import yahoo_options
import schwab_client

# --- Alpaca 옵션 모듈 연동 체크 ---
try:
    from alpaca_options import AlpacaOptionEngine
    HAS_ALPACA_MODULE = True
except ImportError:
    HAS_ALPACA_MODULE = False

st.set_page_config(
    page_title="SPX 0DTE DEFENDER",
    page_icon="🛡️",
    layout="centered",
    initial_sidebar_state="collapsed"
)

ALPACA_API_KEY = st.secrets.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = st.secrets.get("ALPACA_SECRET_KEY", "")
TWELVEDATA_API_KEY = st.secrets.get("TWELVEDATA_API_KEY", "")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

.stApp {
    background-color: #0a0e17;
    color: #e1e6ed;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}
.block-container {
    padding-top: 0.5rem !important;
    padding-bottom: 0.5rem !important;
    padding-left: 0.4rem !important;
    padding-right: 0.4rem !important;
    max-width: 100% !important;
}
[data-testid="stVerticalBlock"] > div { gap: 0.3rem !important; }

/* 숫자 위주 값은 고정폭 monospace로 (스크린샷 스타일) */
.mono-num { font-family: 'JetBrains Mono', 'Courier New', monospace; font-variant-numeric: tabular-nums; }

.card-box { background-color: #121824; border: 1px solid #1e2635; border-radius: 8px; padding: 8px 10px; margin-bottom: 5px; }
.signal-box { background-color: #16150e; border: 1px solid #785a00; border-radius: 8px; padding: 8px 10px; margin-bottom: 5px; }

.badge-red { background-color: #991b1b; color: #fca5a5; padding: 2px 7px; border-radius: 999px; font-weight: 700; font-size: 9px; }
.badge-green { background-color: #065f46; color: #6ee7b7; padding: 2px 7px; border-radius: 999px; font-weight: 700; font-size: 9px; }
.badge-yellow { background-color: #78350f; color: #fde68a; padding: 2px 7px; border-radius: 999px; font-weight: 700; font-size: 9px; }
.badge-gray { background-color: #262b36; color: #9ca3af; padding: 2px 7px; border-radius: 999px; font-weight: 700; font-size: 9px; }
.badge-blue { background-color: #1e3a5f; color: #7dd3fc; padding: 2px 7px; border-radius: 999px; font-weight: 700; font-size: 9px; }

/* 뉴스 리스크 태그 pill */
.tag-pill { display:inline-block; background-color:#3f1d1d; color:#fca5a5; border:1px solid #7f1d1d;
            padding: 2px 8px; border-radius: 999px; font-weight: 700; font-size: 9px; margin-right: 4px; margin-bottom:3px; }

.grid-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 4px; }
.grid-4col { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 4px; margin-bottom: 4px; }

.metric-card { background-color: #121824; border: 1px solid #1e2635; border-radius: 8px; padding: 7px 9px; }
.metric-label { font-size: 9px; color: #7b8494; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase; }
.metric-val { font-family: 'JetBrains Mono', monospace; font-size: 16px; font-weight: 700; color: #ffffff; line-height: 1.25; }
.metric-sub { font-size: 9px; margin-top: 2px; font-family: 'JetBrains Mono', monospace; }

/* 섹션 헤더: 아이콘+제목(좌) / "Data as of..." (우) 패턴 */
.section-header { display:flex; justify-content:space-between; align-items:baseline; margin: 6px 0 3px 0; }
.section-title { font-size: 11px; font-weight: 700; color: #e1e6ed; }
.section-time { font-size: 8px; color: #5b6474; font-family: 'JetBrains Mono', monospace; }

.bar-container { width: 100%; background-color: #ef4444; height: 5px; border-radius: 3px; overflow: hidden; margin: 3px 0; }
.bar-fill { height: 100%; background-color: #10b981; }
hr { margin: 6px 0 !important; border-color: #1e2635 !important; }
</style>
""", unsafe_allow_html=True)


def section_header(icon, title, time_label=None):
    """스크린샷과 같은 '아이콘+제목 / Data as of ...' 섹션 헤더를 그린다."""
    time_html = f'<span class="section-time">{time_label}</span>' if time_label else ''
    st.markdown(f"""
    <div class="section-header">
    <span class="section-title">{icon} {title}</span>
    {time_html}
    </div>
    """, unsafe_allow_html=True)




# ============================================================
# 시세 조회 (수정됨: 가짜 fallback 제거, ^SPX -> ^GSPC, fast_info 사용)
# ============================================================

def fmt(val, fmt_str="{:,.2f}"):
    """None이면 'N/A' 문자열, 아니면 포맷된 숫자 문자열을 반환."""
    return fmt_str.format(val) if val is not None else "N/A"


def safe(val, default=0.0):
    """색상/부호 비교용: None이면 default로 대체."""
    return val if val is not None else default


def fetch_alpaca_stock_snapshot(symbol="SPY"):
    """
    Alpaca 스냅샷 조회. 실패 시 (None, None, None, error_msg) 반환.
    주의: 이 함수는 @st.cache_data 함수 내부에서 호출되므로
    절대 st.session_state를 직접 건드리지 않는다 (캐시/세션 상태 충돌 방지).
    """
    if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
        return (None, None, None, None)
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
            return (price, chg, pct, None)
        elif price > 0:
            return (price, 0.0, 0.0, None)
    except Exception as e:
        return (None, None, None, f"Alpaca({symbol}): {e}")
    return (None, None, None, None)


@st.cache_data(ttl=20, show_spinner=False)
def fetch_twelvedata_quotes(symbols_csv):
    """
    Twelve Data /quote 엔드포인트로 여러 심볼을 한 번에 조회 (콤마로 구분).
    무료 티어: 분당 8회, 하루 800회 -> 심볼을 한 번에 묶어서 호출 횟수를 아낀다.
    반환: ({symbol: (price, chg, pct) or (None,None,None)}, [에러메시지...])
    """
    symbols = symbols_csv.split(",")
    results = {s: (None, None, None) for s in symbols}
    if not TWELVEDATA_API_KEY:
        return results, []  # 키 없으면 조용히 스킵 (에러 아님, 다음 소스로 폴백)

    try:
        resp = requests.get(
            "https://api.twelvedata.com/quote",
            params={"symbol": symbols_csv, "apikey": TWELVEDATA_API_KEY},
            timeout=5,
        )
        data = resp.json()
    except Exception as e:
        return results, [f"TwelveData: {e}"]

    # 심볼이 1개면 바로 딕셔너리, 여러 개면 {symbol: {...}} 형태로 옴
    if len(symbols) == 1:
        data = {symbols[0]: data}

    errors = []
    for sym in symbols:
        entry = data.get(sym, {})
        if not isinstance(entry, dict) or entry.get("status") == "error" or "close" not in entry:
            errors.append(f"TwelveData({sym}): {entry.get('message', 'no data')}")
            continue
        try:
            price = float(entry["close"])
            prev_close = float(entry.get("previous_close", price))
            chg = float(entry.get("change", price - prev_close))
            pct = float(entry.get("percent_change", (chg / prev_close * 100.0) if prev_close else 0.0))
            results[sym] = (price, chg, pct)
        except Exception as e:
            errors.append(f"TwelveData({sym}): parse error {e}")

    return results, errors


YF_TICKERS = ['ES=F']


@st.cache_data(ttl=20, show_spinner=False)
def fetch_yf_batch(tickers):
    """
    티커들을 한 번의 HTTP 요청으로 가져온다 (야후 파이낸스 Rate Limit 완화 목적).
    Twelve Data/Alpaca가 실패했을 때만 폴백으로 호출되므로 평소엔 거의 안 쓰인다.
    일봉(1d) 기준이라 정확히 실시간 tick은 아니지만, 장중에는 당일 봉이
    계속 갱신되므로 충분히 현재가에 가깝다.

    tickers: 튜플 (캐시 키로 쓰이려면 리스트가 아니라 해시 가능한 타입이어야 함)
    반환: ({ticker: (price, chg, pct) or (None, None, None)}, [에러메시지...])
    """
    tickers = list(tickers)
    results = {t: (None, None, None) for t in tickers}
    errors = []
    if not tickers:
        return results, errors
    try:
        df = yf.download(
            tickers=tickers,
            period="5d",
            interval="1d",
            group_by="ticker",
            threads=False,
            progress=False,
            auto_adjust=False,
        )
    except Exception as e:
        return results, [f"yfinance batch: {e}"]

    if df is None or df.empty:
        return results, ["yfinance batch: empty response (rate limited일 가능성)"]

    for sym in tickers:
        try:
            sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
            closes = sub['Close'].dropna()
            if len(closes) >= 2:
                price = float(closes.iloc[-1])
                prev = float(closes.iloc[-2])
                chg = price - prev
                pct = (chg / prev) * 100.0 if prev else 0.0
                results[sym] = (price, chg, pct)
            elif len(closes) == 1:
                results[sym] = (float(closes.iloc[-1]), 0.0, 0.0)
            else:
                errors.append(f"{sym}: no data (rate limited일 가능성)")
        except Exception as e:
            errors.append(f"{sym}: {e}")

    return results, errors


@st.cache_data(ttl=20)
def fetch_market_data():
    # 주의: 이 함수는 @st.cache_data로 캐시되므로 내부에서 st.session_state를
    # 절대 읽거나 쓰지 않는다. 에러는 로컬 리스트에 모아서 반환값으로 전달한다.
    errors = []

    spx_p = spx_c = spx_pct = None
    vix_p = vix_c = vix_pct = None
    es_p = es_c = es_pct = None
    spy_p = spy_c = spy_pct = None

    # 0순위: Schwab API (SPX, VIX, SPY 실시간). 설정 안 돼있거나 refresh_token 만료 시 조용히 건너뜀.
    if schwab_client.is_configured():
        _schwab_results, _schwab_err = schwab_client.fetch_quotes(["$SPX", "$VIX", "SPY"])
        if _schwab_err:
            errors.append(f"Schwab quotes: {_schwab_err}")

        spx_p, spx_c, spx_pct = _schwab_results.get("$SPX", (None, None, None)) if _schwab_results else (None, None, None)
        vix_p, vix_c, vix_pct = _schwab_results.get("$VIX", (None, None, None)) if _schwab_results else (None, None, None)
        spy_p, spy_c, spy_pct = _schwab_results.get("SPY", (None, None, None)) if _schwab_results else (None, None, None)

        # quotes API가 지수(SPX/VIX)를 빈 값으로 주는 경우가 있어서, 그럴 때는
        # 이미 안정적으로 확인된 옵션체인 API의 underlying 필드로 대신 가져온다.
        if spx_p is None:
            _u_p, _u_c, _u_pct = schwab_client.fetch_underlying_price("$SPX")
            if _u_p is not None:
                spx_p, spx_c, spx_pct = _u_p, _u_c, _u_pct
            else:
                errors.append("Schwab: $SPX 시세를 quotes·chains 둘 다에서 못 가져옴")

        if vix_p is None:
            _u_p, _u_c, _u_pct = schwab_client.fetch_underlying_price("$VIX")
            if _u_p is not None:
                vix_p, vix_c, vix_pct = _u_p, _u_c, _u_pct

    # 1순위(SPY 폴백): Alpaca
    alp_spy_p, alp_spy_c, alp_spy_pct, alp_err = fetch_alpaca_stock_snapshot("SPY")
    if alp_err:
        errors.append(alp_err)
    if spy_p is None and alp_spy_p is not None:
        spy_p, spy_c, spy_pct = alp_spy_p, alp_spy_c, alp_spy_pct

    # 2순위(SPY 폴백): Twelve Data
    # 주의: Twelve Data 무료(Basic) 플랜은 지수(SPX, VIX)를 지원하지 않는다
    # (유료 Grow 플랜부터 지원). 그래서 SPX/VIX에는 사용하지 않는다.
    if spy_p is None:
        td_results, td_errors = fetch_twelvedata_quotes("SPY")
        errors.extend(td_errors)
        td_spy_p, td_spy_c, td_spy_pct = td_results.get("SPY", (None, None, None))
        if td_spy_p is not None:
            spy_p, spy_c, spy_pct = td_spy_p, td_spy_c, td_spy_pct

    # 3순위(SPX/VIX/ES 폴백): 야후. Schwab이 성공했으면 필요한 것만 골라서 호출.
    yf_symbols = []
    if spx_p is None:
        yf_symbols.append('^GSPC')
    if vix_p is None:
        yf_symbols.append('^VIX')
    yf_symbols += YF_TICKERS  # ES=F는 Schwab Trader API - Individual에서 지원 안 될 수 있어 항상 폴백 후보에 포함
    if spy_p is None:
        yf_symbols.append('SPY')

    yf_results, yf_errors = fetch_yf_batch(tuple(yf_symbols))
    errors.extend(yf_errors)

    if spx_p is None:
        spx_p, spx_c, spx_pct = yf_results.get('^GSPC', (None, None, None))
    if vix_p is None:
        vix_p, vix_c, vix_pct = yf_results.get('^VIX', (None, None, None))
    es_p, es_c, es_pct = yf_results.get('ES=F', (None, None, None))

    if spy_p is None:
        spy_p, spy_c, spy_pct = yf_results.get('SPY', (None, None, None))

    # 안전망: SPX를 못 구했으면 SPY 기반 근사치 (SPY는 SPX의 1/10 트래킹이라 오차가 작음)
    if spx_p is None and spy_p is not None:
        spx_p, spx_c, spx_pct = spy_p * 10.0, spy_c * 10.0, spy_pct

    # ES 선물도 못 구했으면 SPX로 근사 (실제 선물 베이시스는 반영 안 된 근사치)
    if es_p is None and spx_p is not None:
        es_p, es_c, es_pct = spx_p, spx_c, spx_pct

    return {
        'spx': (spx_p, spx_c, spx_pct),
        'vix': (vix_p, vix_c, vix_pct),
        'es': (es_p, es_c, es_pct),
        'spy': (spy_p, spy_c, spy_pct),
        'errors': errors,
    }


@st.cache_data(ttl=60)
def fetch_latest_news_sentiment():
    try:
        ticker = yf.Ticker("ES=F")
        news_list = ticker.news
        if news_list and len(news_list) > 0:
            latest = news_list[0]
            title = latest.get('title', '')
            link = latest.get('link', '')
        else:
            title = "Market Holds Steady Amid Economic Data Releases"
            link = "#"
    except Exception:
        title = "Market Holds Steady Amid Economic Data Releases"
        link = "#"

    bearish_words = ["hike", "war", "inflation", "cpi", "drop", "plunge", "down", "crisis", "fall", "tariff", "missed"]
    bullish_words = ["cut", "easing", "rally", "gain", "soar", "surge", "cool", "growth", "beat", "earnings", "boost"]

    title_lower = title.lower()
    bear_score = sum(1 for w in bearish_words if w in title_lower)
    bull_score = sum(1 for w in bullish_words if w in title_lower)

    if bear_score > bull_score:
        sentiment = "BEARISH"
    elif bull_score > bear_score:
        sentiment = "BULLISH"
    else:
        sentiment = "NEUTRAL"

    return {"title": title, "sentiment": sentiment, "link": link}


@st.cache_data(ttl=30)
def fetch_es_history(interval_str):
    try:
        yf_interval = "60m" if interval_str == "1H" else interval_str
        period = "1d" if interval_str in ["1m", "5m"] else "5d"
        t = yf.Ticker("ES=F")
        df = t.history(period=period, interval=yf_interval)
        if df.empty:
            return None

        df = df.tail(20).copy()
        est_tz = pytz.timezone('US/Eastern')
        df.index = df.index.tz_convert(est_tz)
        return df
    except Exception:
        return None


@st.cache_data(ttl=30)
def fetch_es_history_for_rsi(interval_str, num_bars=100):
    """
    RSI 등 지표 계산 전용 - fetch_es_history(볼륨차트용, 최근 20개 봉만)와 달리
    RSI-14가 제대로 웜업되도록 훨씬 긴 히스토리를 가져온다.
    """
    try:
        yf_interval = "60m" if interval_str == "1H" else interval_str
        period_map = {"1m": "5d", "5m": "5d", "15m": "1mo", "30m": "1mo", "1H": "3mo"}
        period = period_map.get(interval_str, "5d")
        t = yf.Ticker("ES=F")
        df = t.history(period=period, interval=yf_interval)
        if df.empty:
            return None

        df = df.tail(num_bars).copy()
        est_tz = pytz.timezone('US/Eastern')
        df.index = df.index.tz_convert(est_tz)
        return df
    except Exception:
        return None


@st.cache_data(ttl=10)
def fetch_alpaca_0dte_analytics(spy_price):
    if HAS_ALPACA_MODULE and ALPACA_API_KEY and ALPACA_SECRET_KEY and spy_price:
        try:
            engine = AlpacaOptionEngine(ALPACA_API_KEY, ALPACA_SECRET_KEY)
            return engine.get_0dte_chain_analytics(symbol="SPY", current_price=spy_price)
        except Exception:
            return None
    return None


def calculate_dynamic_strikes(current_price, news_sentiment, news_score, distance_mult=1.0, option_analytics=None):
    if current_price is None:
        return {
            'dyn_call_sell': "N/A",
            'dyn_put_sell': "N/A",
            'call_target': None,
            'put_target': None,
        }

    if option_analytics and option_analytics.get('call_15d_strike'):
        c_15d = option_analytics['call_15d_strike']
        p_15d = option_analytics['put_15d_strike']

        call_strike = int(round((c_15d * 10.0) / 5.0) * 5)
        put_strike = int(round((p_15d * 10.0) / 5.0) * 5)

        return {
            'dyn_call_sell': f"{call_strike+5}/{call_strike}",
            'dyn_put_sell': f"{put_strike-5}/{put_strike}",
            'call_target': call_strike,
            'put_target': put_strike,
        }

    base_span = 30.0 * distance_mult

    if news_score > 0:
        call_offset = base_span * (1.0 + (news_score * 0.2))
        put_offset = max(18.0, base_span * (1.0 - (news_score * 0.15)))
    elif news_score < 0:
        call_offset = max(18.0, base_span * (1.0 - (abs(news_score) * 0.15)))
        put_offset = base_span * (1.0 + (abs(news_score) * 0.2))
    else:
        call_offset = base_span
        put_offset = base_span

    call_target = int(round((current_price + call_offset) / 5.0) * 5)
    put_target = int(round((current_price - put_offset) / 5.0) * 5)

    return {
        'dyn_call_sell': f"{call_target+5}/{call_target}",
        'dyn_put_sell': f"{put_target-5}/{put_target}",
        'call_target': call_target,
        'put_target': put_target,
    }


if "backtest_result" not in st.session_state:
    st.session_state["backtest_result"] = None
if "data_errors" not in st.session_state:
    st.session_state["data_errors"] = []
if "walk_forward_result" not in st.session_state:
    st.session_state["walk_forward_result"] = None

# 지난 신호 중 확인 시점이 지난 게 있으면 실제 결과를 채워넣는다.
# (내부적으로 너무 잦은 호출은 자체적으로 막아둠 -> 매 새로고침마다 불러도 안전)
try:
    signal_tracker.resolve_pending_signals()
except Exception:
    pass  # 신호 추적 실패가 앱 전체를 죽이면 안 되므로 조용히 무시

market_data = fetch_market_data()
news_sentiment = fetch_latest_news_sentiment()
est_tz = pytz.timezone('US/Eastern')
now_est = datetime.now(est_tz)

spx_p, spx_c, spx_pct = market_data['spx']
vix_p, vix_c, vix_pct = market_data['vix']
es_p, es_c, es_pct = market_data['es']
spy_p, spy_c, spy_pct = market_data['spy']
data_errors = market_data.get('errors', [])

es_df = fetch_es_history("5m")
news_score = SimonsBenterQuantEngine.advanced_news_scoring(news_sentiment['title'])

if es_df is not None and not es_df.empty:
    regime, regime_mult = SimonsBenterQuantEngine.detect_market_regime(es_df, vix_p if vix_p is not None else 15.0)
    z_score = SimonsBenterQuantEngine.calculate_zscore_anomaly(es_df['Close'])
else:
    regime, regime_mult = "NORMAL_VOLATILITY", 1.0
    z_score = 0.0

# 0DTE는 같은 변동성이라도 시간대(세션)에 따라 감마/세타 위험이 다르므로
# 레짐 배수와 세션 배수를 곱해서 최종 안전거리 배수를 만든다.
session_name, session_mult = SimonsBenterQuantEngine.detect_trading_session(now_est)
session_risk_level, session_risk_title, session_risk_message = \
    SimonsBenterQuantEngine.get_session_risk_message(session_name)

# FOMC/CPI/NFP/옵션만기(OPEX) 같은 매크로 이벤트가 있는 날은 변동성이
# 완전히 다르게 튈 수 있어 별도 배수를 추가로 곱한다.
macro_mult, macro_events = macro_calendar.get_macro_risk_multiplier(now_est.date())

distance_mult = round(regime_mult * session_mult * macro_mult, 2)

@st.cache_data(ttl=300)
def fetch_spx_es_prev_close():
    """
    가장 최근 완료된 정규장 종가 시점의 SPX·ES 종가를 가져온다 (베이시스 계산용).
    반환: (spx_prev_close, es_prev_close) 또는 실패 시 (None, None).
    """
    try:
        h = yf.download(tickers=["^GSPC", "ES=F"], period="5d", interval="1d",
                         group_by="ticker", progress=False)
        if not isinstance(h.columns, pd.MultiIndex):
            return None, None
        spx_close = h["^GSPC"]["Close"].dropna()
        es_close = h["ES=F"]["Close"].dropna()
        if len(spx_close) < 1 or len(es_close) < 1:
            return None, None
        return float(spx_close.iloc[-1]), float(es_close.iloc[-1])
    except Exception:
        return None, None


def get_effective_spx_price():
    """
    스트라이크 계산·GEX에 공통으로 쓸 'SPX 유효 가격'을 정한다.
    - 정규장(09:30~16:00 ET) 중: 실시간 SPX 가격 그대로 사용.
    - 그 외 시간(프리마켓/애프터마켓): SPX는 지수라 실시간 시세가 없는 경우가 많으므로
      (조회 실패 시 None), ES 선물의 실시간 움직임으로 SPX를 추정한다.
      추정 SPX = 현재 ES가 - (마지막 정규장 종가 시점의 ES-SPX 가격차이)
    이렇게 하면 프리마켓에 SPX 값이 아예 없어서 스트라이크가 'N/A'로 나오는 문제를
    ES 기반 추정치로 메꿀 수 있다.
    반환: (spot_price_or_None, is_estimated: bool, note: str)
    """
    is_rth = dtime(9, 30) <= now_est.time() <= dtime(16, 0)

    if is_rth and spx_p is not None:
        return spx_p, False, "정규장 실시간 SPX"

    if es_p is None:
        return spx_p, False, "ES 데이터 없음 - SPX 값 그대로 사용 (주의: 지연/부정확하거나 없을 수 있음)"

    spx_prev_close, es_prev_close = fetch_spx_es_prev_close()
    if spx_prev_close is None or es_prev_close is None:
        return spx_p, False, "베이시스 계산 실패 - SPX 값 그대로 사용 (주의: 지연/부정확하거나 없을 수 있음)"

    basis = es_prev_close - spx_prev_close
    estimated_spx = es_p - basis
    return estimated_spx, True, f"ES 기반 추정 (베이시스 {basis:+.1f}pt)"


_effective_spx_price, _spx_is_estimated, _spx_estimate_note = get_effective_spx_price()

alpaca_analytics = fetch_alpaca_0dte_analytics(spy_p)
try:
    strikes = calculate_dynamic_strikes(_effective_spx_price, news_sentiment, news_score, distance_mult, alpaca_analytics)
    if not isinstance(strikes, dict):
        strikes = {}
except Exception:
    strikes = {}

# --- Header ---
st.markdown(f"""
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
<span style="font-weight: bold; font-size: 14px;">🛡️ SPX 0DTE DEFENDER <span style="background-color: #1f2937; padding: 1px 4px; border-radius: 3px; font-size: 9px; color: #9ca3af;">v25.0</span></span>
<span style="background-color: #1f2937; padding: 1px 6px; border-radius: 8px; font-size: 9px; color: #9ca3af;">● Live | {now_est.strftime('%H:%M')} ET</span>
</div>
""", unsafe_allow_html=True)

# --- 뉴스 리스크 티커 + 최신 뉴스 ---
try:
    _news_items = news_feed.fetch_news_list(ticker="ES=F", n=5)
    _risk_tags = news_feed.extract_risk_tags(_news_items)
except Exception:
    _news_items, _risk_tags = [], []

if _risk_tags:
    section_header("📰", "NEWS RISKS", f"Latest item {_news_items[0]['time_ago']}" if _news_items else None)
    _tags_html = "".join(f'<span class="tag-pill">{t}</span>' for t in _risk_tags)
    st.markdown(f'<div style="margin-bottom:4px;">{_tags_html}</div>', unsafe_allow_html=True)

if _news_items:
    _news_source = _news_items[0]['publisher'] if len(_news_items) == 1 else "Google News"
    section_header("📰", "LATEST HIGH-IMPACT NEWS",
                    f"{_news_source} · Latest item {now_est.strftime('%m/%d %H:%M:%S')} ET")
    _news_html = ""
    for _n in _news_items[:4]:
        _news_html += (
            '<div style="display:flex; justify-content:space-between; align-items:flex-start; '
            'padding:6px 0; border-bottom:1px solid #1e2635; gap:8px;">'
            f'<span style="font-size:10px; color:#d1d5db; line-height:1.4;">{_n["title"]}'
            f'<span style="color:#5b6474;"> - {_n["publisher"]}</span></span>'
            f'<span style="font-size:9px; color:#5b6474; white-space:nowrap; flex-shrink:0;">{_n["time_ago"]}</span>'
            '</div>'
        )
    st.markdown(f'<div class="card-box">{_news_html}</div>', unsafe_allow_html=True)

# --- 데이터 오류 배너 ---
if data_errors:
    err_text = " / ".join(data_errors[:3])
    st.markdown(f"""
    <div style="background-color:#3f1d1d; border:1px solid #7f1d1d; border-radius:6px;
                padding:4px 8px; margin-bottom:4px; font-size:10px; color:#fca5a5;">
    ⚠️ 일부 시세 조회 실패 (표시값은 N/A 또는 근사치일 수 있음): {err_text}
    </div>
    """, unsafe_allow_html=True)

# --- 0DTE 세션 리스크 배너 (신규) ---
_session_colors = {
    "EXTREME": ("#ef4444", "#2a1414"),
    "HIGH": ("#f97316", "#2a1c0e"),
    "MEDIUM": ("#facc15", "#241f0a"),
    "LOW": ("#60a5fa", "#111a24"),
}
_sr_fg, _sr_bg = _session_colors.get(session_risk_level, ("#9ca3af", "#161616"))
st.markdown(f"""
<div style="background-color:{_sr_bg}; border:1px solid {_sr_fg}55; border-radius:6px;
            padding:6px 8px; margin-bottom:4px;">
<div style="display:flex; justify-content:space-between; align-items:center;">
<span style="font-size:10px; font-weight:bold; color:{_sr_fg};">⏱️ 0DTE TIME RISK — {session_risk_title}</span>
<span style="font-size:9px; font-weight:bold; color:{_sr_fg}; background-color:{_sr_fg}22; padding:1px 6px; border-radius:4px;">{session_risk_level}</span>
</div>
<div style="font-size:10px; color:#d1d5db; margin-top:3px;">{session_risk_message}</div>
</div>
""", unsafe_allow_html=True)

# --- 매크로 이벤트 배너 ---
if macro_events:
    _risk_colors = {"EXTREME": "#ef4444", "HIGH": "#f97316", "MEDIUM_HIGH": "#facc15", "MEDIUM": "#9ca3af"}
    _events_html = ""
    for _ev in macro_events:
        _c = _risk_colors.get(_ev["risk"], "#9ca3af")
        _events_html += f"<span style='color:{_c}; font-weight:bold;'>[{_ev['risk']}]</span> {_ev['name']} &nbsp;&nbsp;"
    st.markdown(f"""
    <div style="background-color:#1f1a0e; border:1px solid #785a00; border-radius:6px;
                padding:5px 8px; margin-bottom:4px; font-size:10px; color:#fde68a;">
    📅 <b>오늘 매크로 이벤트</b> — {_events_html}<br>
    <span style="font-size:9px; color:#9ca3af;">스트라이크 안전거리 {macro_mult}배 확대 반영됨</span>
    </div>
    """, unsafe_allow_html=True)

# --- Top Cards ---
spx_color = "#10b981" if safe(spx_c) >= 0 else "#ef4444"
vix_color = "#ef4444" if safe(vix_c) >= 0 else "#10b981"
es_color = "#10b981" if safe(es_c) >= 0 else "#ef4444"
spy_color = "#10b981" if safe(spy_c) >= 0 else "#ef4444"

st.markdown(f"""
<div class="grid-4col">
<div class="metric-card"><div class="metric-label">SPX 지수</div><div class="metric-val">{fmt(spx_p)}</div><div class="metric-sub" style="color: {spx_color};">{fmt(spx_c, '{:+.2f}')} ({fmt(spx_pct, '{:+.2f}')}%)</div></div>
<div class="metric-card"><div class="metric-label">VIX 변동성</div><div class="metric-val">{fmt(vix_p)}</div><div class="metric-sub" style="color: {vix_color};">{fmt(vix_c, '{:+.2f}')} ({fmt(vix_pct, '{:+.2f}')}%)</div></div>
<div class="metric-card"><div class="metric-label">ES 선물</div><div class="metric-val">{fmt(es_p)}</div><div class="metric-sub" style="color: {es_color};">{fmt(es_c, '{:+.2f}')} ({fmt(es_pct, '{:+.2f}')}%)</div></div>
<div class="metric-card"><div class="metric-label">SPY ETF</div><div class="metric-val">{fmt(spy_p)}</div><div class="metric-sub" style="color: {spy_color};">{fmt(spy_c, '{:+.2f}')} ({fmt(spy_pct, '{:+.2f}')}%)</div></div>
</div>
""", unsafe_allow_html=True)

z_color = "#ef4444" if abs(z_score) > 2.0 else "#10b981"
z_desc = "⚠️ |Z|>2.0 이탈위험" if abs(z_score) > 2.0 else "🛡️ ±2.0 통계안정"
sent_color = "#ef4444" if news_sentiment['sentiment'] == "BEARISH" else ("#10b981" if news_sentiment['sentiment'] == "BULLISH" else "#facc15")

st.markdown(f"""
<div class="grid-4col">
<div class="metric-card"><div class="metric-label">REGIME</div><div style="font-size: 11px; font-weight: bold; color: #60a5fa; margin-top:2px;">{regime}</div><div class="metric-sub" style="color:#9ca3af;">{session_name} · 레짐{regime_mult} × 세션{session_mult} × 매크로{macro_mult} = {distance_mult}x</div></div>
<div class="metric-card"><div class="metric-label">Z-SCORE</div><div class="metric-val" style="color: {z_color};">{z_score:+.2f}</div><div class="metric-sub" style="color:#9ca3af;">{z_desc}</div></div>
<div class="metric-card"><div class="metric-label">DELTA TARGET</div><div class="metric-val">0.15 Δ</div><div class="metric-sub" style="color:#10b981;">Target 85% Win</div></div>
<div class="metric-card"><div class="metric-label">NEWS SCORE</div><div class="metric-val" style="color: {sent_color};">{news_score:+.2f}</div><div class="metric-sub" style="color:#9ca3af;">{news_sentiment['sentiment']}</div></div>
</div>
""", unsafe_allow_html=True)

# --- Fear & Greed 게이지 ---
@st.cache_data(ttl=300)
def fetch_vix_history_for_feargreed():
    """근사 Fear&Greed 계산용 최근 3개월 VIX 종가 (VIX 퍼센타일 + 추이차트 겸용)."""
    try:
        h = yf.download(tickers="^VIX", period="3mo", interval="1d", progress=False)
        if isinstance(h.columns, pd.MultiIndex):
            h.columns = h.columns.get_level_values(0)
        return h['Close'] if not h.empty else None
    except Exception:
        return None


@st.cache_data(ttl=300)
def fetch_spx_daily_for_momentum():
    """
    근사 Fear&Greed 모멘텀 계산용 SPX 일봉 종가 (최근 3개월).
    5분봉 같은 초단기 데이터로 모멘텀을 재면 노이즈에 너무 민감해서,
    CNN 방식(중기 이동평균 대비 위치)에 가깝게 일봉 기준으로 계산한다.
    """
    try:
        h = yf.download(tickers="^GSPC", period="3mo", interval="1d", progress=False)
        if isinstance(h.columns, pd.MultiIndex):
            h.columns = h.columns.get_level_values(0)
        return h['Close'] if not h.empty else None
    except Exception:
        return None


def compute_intraday_buy_pct(df):
    """
    당일 캔들의 상승/하락 방향 * 거래량으로 매수/매도 비중을 근사한다.
    (Volume+CVD 섹션과 동일한 방식 - 실제 매수/매도 체결 데이터가 아니라
    캔들 방향 기반 근사치임)
    """
    if df is None or df.empty or len(df) < 2:
        return 50.0
    try:
        close_vals = df['Close'].values
        open_vals = df['Open'].values
        total_vol = df['Volume'].values
        delta = close_vals - open_vals
        buy_mask = delta >= 0
        buy_vol = np.where(buy_mask, total_vol * 0.55, total_vol * 0.45)
        total_sum = np.sum(total_vol)
        if total_sum <= 0:
            return 50.0
        return float((np.sum(buy_vol) / total_sum) * 100)
    except Exception:
        return 50.0


_vix_hist = fetch_vix_history_for_feargreed()
_spx_daily_for_momentum = fetch_spx_daily_for_momentum()
_intraday_buy_pct = compute_intraday_buy_pct(es_df)

# 1순위: CNN 실제 Fear&Greed 지수 (비공식이지만 CNN이 실제 쓰는 데이터를 그대로 가져옴)
# 실패하면(엔드포인트 변경, 네트워크 문제 등) 자체 근사치로 폴백한다.
@st.cache_data(ttl=300)
def fetch_cnn_fg_cached():
    return market_pulse.fetch_cnn_fear_greed()

_fg_score, _fg_label, _fg_extras, _fg_cnn_err = fetch_cnn_fg_cached()
_fg_is_real_cnn = _fg_cnn_err is None and _fg_score is not None

if not _fg_is_real_cnn:
    _fg_score, _fg_label = market_pulse.calculate_fear_greed(
        _vix_hist, _spx_daily_for_momentum, volume_buy_pct=_intraday_buy_pct
    )
    _fg_extras = None

_fg_colors = {"Extreme Fear": "#ef4444", "Fear": "#f97316", "Neutral": "#facc15",
              "Greed": "#84cc16", "Extreme Greed": "#10b981"}
_fg_color = _fg_colors.get(_fg_label, "#9ca3af")

_fg_source_note = "CNN 공식 지수" if _fg_is_real_cnn else "자체 근사치 (CNN 접속 실패)"
section_header("😨", "FEAR & GREED · VIX", f"{_fg_source_note} · {now_est.strftime('%H:%M:%S')} ET")

_fg_col1, _fg_col2 = st.columns([1, 1])

with _fg_col1:
    _fg_fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=_fg_score,
        number={'font': {'size': 22, 'color': _fg_color}, 'suffix': ""},
        gauge={
            'axis': {'range': [0, 100], 'tickcolor': '#5b6474', 'tickfont': {'size': 7, 'color': '#5b6474'}},
            'bar': {'color': _fg_color, 'thickness': 0.25},
            'bgcolor': '#121824',
            'borderwidth': 0,
            'steps': [
                {'range': [0, 25], 'color': '#3f1d1d'},
                {'range': [25, 45], 'color': '#3d2410'},
                {'range': [45, 55], 'color': '#302b0e'},
                {'range': [55, 75], 'color': '#243312'},
                {'range': [75, 100], 'color': '#0f2e22'},
            ],
        }
    ))
    _fg_fig.update_layout(
        height=115, margin=dict(l=10, r=10, t=5, b=5),
        paper_bgcolor='rgba(0,0,0,0)', font={'color': '#e1e6ed'}
    )
    components.html(_fg_fig.to_html(include_plotlyjs='cdn', full_html=False,
                                     config={'staticPlot': True, 'displayModeBar': False}),
                     height=120)
    st.markdown(f'<div style="text-align:center; font-size:12px; font-weight:700; color:{_fg_color}; margin-top:-8px;">{_fg_label}</div>',
                unsafe_allow_html=True)

    if _fg_is_real_cnn and _fg_extras:
        _wk = _fg_extras.get('one_week_ago')
        _mo = _fg_extras.get('one_month_ago')
        _wk_str = f"{round(_wk)}" if _wk is not None else "N/A"
        _mo_str = f"{round(_mo)}" if _mo is not None else "N/A"
        st.markdown(
            f'<div style="text-align:center; font-size:9px; color:#9ca3af; margin-top:2px;">'
            f'1w ago: {_wk_str} · 1m ago: {_mo_str}</div>',
            unsafe_allow_html=True,
        )

with _fg_col2:
    # --- VIX 추이 미니차트 (신규) ---
    if _vix_hist is not None and len(_vix_hist) >= 5:
        _vix_recent = _vix_hist.tail(30)
        _vix_now = float(_vix_recent.iloc[-1])
        _vix_chg30 = float(_vix_recent.iloc[-1] - _vix_recent.iloc[0])
        _vix_trend_color = "#ef4444" if _vix_chg30 > 0 else "#10b981"

        _vix_fig = go.Figure()
        _vix_fig.add_trace(go.Scatter(
            x=list(range(len(_vix_recent))), y=_vix_recent.values,
            line=dict(color=_vix_trend_color, width=1.5),
            fill='tozeroy', fillcolor=f"{_vix_trend_color}22",
        ))
        _vix_fig.update_layout(
            height=115, margin=dict(l=0, r=0, t=5, b=5),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            showlegend=False,
        )
        components.html(_vix_fig.to_html(include_plotlyjs='cdn', full_html=False,
                                          config={'staticPlot': True, 'displayModeBar': False}),
                         height=120)
        st.markdown(
            f'<div style="text-align:center; font-size:12px; font-weight:700; color:{_vix_trend_color}; margin-top:-8px;">'
            f'VIX {_vix_now:.2f} <span style="font-size:9px;">({_vix_chg30:+.2f} / 30일)</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div style="font-size:10px; color:#9ca3af; text-align:center; padding-top:30px;">VIX 추이 데이터 없음</div>',
                     unsafe_allow_html=True)

if _fg_is_real_cnn:
    st.markdown('<div style="text-align:center; font-size:8px; color:#5b6474; margin-bottom:4px;">* CNN Fear & Greed Index 실제 값 (비공식 엔드포인트 사용, CNN이 구조를 바꾸면 일시적으로 근사치로 전환될 수 있음)</div>',
                unsafe_allow_html=True)
else:
    st.markdown(f'<div style="text-align:center; font-size:8px; color:#f87171; margin-bottom:4px;">⚠️ CNN 접속 실패({_fg_cnn_err}) - VIX 3개월 퍼센타일·SPX 모멘텀·거래량 기반 자체 근사치를 대신 표시 중</div>',
                unsafe_allow_html=True)

# --- GEX · 감마 노출도 (Schwab 실시간 우선, 실패 시 야후 15분지연 폴백) ---
_gex_source_label = None
_gex_result = None
_gex_err = None

# 스트라이크 계산에도 같은 추정 로직을 재사용하려고 위쪽으로 옮겨뒀다
# (get_effective_spx_price 정의는 이 파일 앞부분, strikes 계산 직전에 있음)
_gex_spot, _gex_is_estimated, _gex_spot_note = _effective_spx_price, _spx_is_estimated, _spx_estimate_note

if schwab_client.is_configured() and _gex_spot is not None:
    _chain, _chain_err = schwab_client.fetch_option_chain(
        symbol="$SPX", contract_type="ALL", strike_count=40,
        expiration_date=now_est.strftime("%Y-%m-%d"),
    )
    if _chain_err:
        _gex_err = f"Schwab: {_chain_err}"
    else:
        _gex_result = schwab_client.calculate_gex_from_chain(_chain, _gex_spot)
        if _gex_result is None:
            _gex_err = "Schwab 응답은 받았지만 계산할 데이터가 없습니다 (0DTE 만기가 없는 날일 수 있음)."
        else:
            _gex_source_label = ("실시간 (Schwab) · " + _gex_spot_note) if not _gex_is_estimated \
                else ("Schwab 체인 + " + _gex_spot_note)

    # --- 디버그 패널 ---
    # Put/Call Wall이 똑같이 나오는 등 이상하면, 실제 Schwab 응답 구조가
    # 코드가 가정한 필드명과 다를 가능성이 높다. 이 패널로 원본을 직접 확인한다.
    with st.expander("🔍 Schwab 옵션체인 원본 디버그 (문제 있을 때 펼쳐서 확인)"):
        st.write(f"GEX 계산에 사용된 스팟가격: {_gex_spot} ({_gex_spot_note})")
        if _chain is None:
            st.write("응답 자체가 없습니다 (요청 실패).")
        else:
            st.write("최상위 키:", list(_chain.keys()))

            underlying = _chain.get("underlying")
            st.write("underlying 필드:", underlying)

            call_map = _chain.get("callExpDateMap", {})
            put_map = _chain.get("putExpDateMap", {})
            st.write(f"callExpDateMap 만기 개수: {len(call_map)}, putExpDateMap 만기 개수: {len(put_map)}")
            st.write("callExpDateMap 만기 키 목록:", list(call_map.keys()))

            if call_map:
                first_exp = list(call_map.keys())[0]
                st.write("첫 콜 만기 키:", first_exp)
                first_strikes = call_map[first_exp]
                st.write(f"그 만기의 스트라이크 개수: {len(first_strikes)}")
                first_strike_key = list(first_strikes.keys())[0]
                st.write("첫 스트라이크 키:", first_strike_key)
                st.write("그 스트라이크의 원본 contract 데이터:")
                st.json(first_strikes[first_strike_key])
            else:
                st.write("callExpDateMap이 비어있습니다.")

            if put_map:
                first_exp_p = list(put_map.keys())[0]
                first_strikes_p = put_map[first_exp_p]
                first_strike_key_p = list(first_strikes_p.keys())[0]
                st.write("첫 풋 계약 원본 데이터:")
                st.json(first_strikes_p[first_strike_key_p])

            # --- daysToExpiration 필터가 실제로 뭘 걸러내는지 진단 (신규) ---
            st.markdown("---")
            st.write("**필터링 진단** (Put Wall = Call Wall 원인 파악용)")
            total_contracts = 0
            passed_filter = 0
            dte_values = {}
            zero_gamma_count = 0
            zero_oi_count = 0
            strikes_after_filter = set()

            for exp_map_key in ("callExpDateMap", "putExpDateMap"):
                exp_map = _chain.get(exp_map_key, {})
                for _exp_date, _strikes_in_exp in exp_map.items():
                    for strike_str, contracts in _strikes_in_exp.items():
                        for c in contracts:
                            total_contracts += 1
                            dte = c.get("daysToExpiration")
                            dte_values[dte] = dte_values.get(dte, 0) + 1
                            if dte not in (0, None):
                                continue
                            passed_filter += 1
                            if not (c.get("gamma") or 0):
                                zero_gamma_count += 1
                            if not (c.get("openInterest") or 0):
                                zero_oi_count += 1
                            if (c.get("gamma") or 0) and (c.get("openInterest") or 0):
                                strikes_after_filter.add(c.get("strikePrice"))

            st.write(f"전체 계약 수: {total_contracts}")
            st.write("daysToExpiration 값 분포:", dte_values)
            st.write(f"daysToExpiration==0(또는 None) 필터 통과: {passed_filter}")
            st.write(f"필터 통과했지만 gamma=0인 계약: {zero_gamma_count}")
            st.write(f"필터 통과했지만 openInterest=0인 계약: {zero_oi_count}")
            st.write(f"gamma>0 AND OI>0 모두 만족하는 고유 스트라이크 수: {len(strikes_after_filter)}")
            st.write("그 스트라이크들:", sorted(strikes_after_filter))

# Schwab이 설정 안 됐거나 실패했으면 야후로 폴백
if _gex_result is None and spy_p is not None:
    _yo_chain, _yo_err, _yo_T, _yo_r = yahoo_options.fetch_0dte_chain_with_greeks(ticker="SPY")
    if _yo_err:
        # Schwab 에러가 이미 있으면 같이 보여주고, 없으면 야후 에러만
        _gex_err = (f"{_gex_err} / 야후도 실패: {_yo_err}") if _gex_err else _yo_err
    else:
        _gex_result = yahoo_options.calculate_gex_from_yahoo_chain(
            _yo_chain, spot_price=spy_p, time_years=_yo_T, rate=_yo_r, scale_to_spx=10.0
        )
        if _gex_result is not None:
            _gex_source_label = "15분 지연 (야후, Schwab 대신 사용됨)" if schwab_client.is_configured() \
                else "15분 지연 (야후)"
        elif not _gex_err:
            _gex_err = "계산 가능한 옵션 데이터가 부족합니다."

section_header("🧲", "GEX · 감마 노출도", _gex_source_label or "데이터 없음")

if _gex_err and _gex_result is None:
    st.markdown(f"""
    <div class="card-box" style="font-size:10px; color:#fca5a5;">⚠️ {_gex_err}</div>
    """, unsafe_allow_html=True)
elif _gex_result is None:
    st.markdown("""
    <div class="card-box" style="font-size:10px; color:#9ca3af;">SPX/SPY 현재가를 못 가져와서 GEX 계산을 건너뜁니다.</div>
    """, unsafe_allow_html=True)
else:
    _put_wall = _gex_result['put_wall']
    _call_wall = _gex_result['call_wall']
    _gamma_flip = _gex_result['gamma_flip']
    _net_gex = _gex_result['net_gex_total']
    _net_delta = _gex_result['net_delta_total']

    _regime_label = "Pinning (핀 고정)" if _net_gex > 0 else "Explosive (변동성 확대 위험)"
    _regime_color = "#10b981" if _net_gex > 0 else "#ef4444"

    st.markdown(f"""
    <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:4px; margin-bottom:4px;">
    <div class="metric-card" style="border-left:3px solid #ef4444;">
    <div class="metric-label">PUT WALL</div>
    <div class="metric-val mono-num">{f'{_put_wall:,.0f}' if _put_wall is not None else 'N/A'}</div>
    <div class="metric-sub" style="color:#9ca3af;">지지</div>
    </div>
    <div class="metric-card" style="border-left:3px solid #facc15;">
    <div class="metric-label">GAMMA FLIP</div>
    <div class="metric-val mono-num">{f'{_gamma_flip:,.0f}' if _gamma_flip else 'N/A'}</div>
    <div class="metric-sub" style="color:#9ca3af;">변곡점</div>
    </div>
    <div class="metric-card" style="border-left:3px solid #10b981;">
    <div class="metric-label">CALL WALL</div>
    <div class="metric-val mono-num">{f'{_call_wall:,.0f}' if _call_wall is not None else 'N/A'}</div>
    <div class="metric-sub" style="color:#9ca3af;">저항</div>
    </div>
    </div>
    <div class="card-box" style="display:flex; justify-content:space-between; align-items:center;">
    <span style="font-size:10px; font-weight:700; color:{_regime_color};">{_regime_label}</span>
    <span style="font-size:9px; color:#9ca3af;">Net Δ <b class="mono-num" style="color:#e1e6ed;">{_net_delta:,.0f}</b></span>
    </div>
    """, unsafe_allow_html=True)

    if _gex_is_estimated:
        st.markdown(
            '<div style="font-size:8px; color:#facc15; margin-bottom:2px;">'
            f'⚠️ 정규장 외 시간이라 SPX 현재가를 ES 선물 기반으로 추정해서 계산했습니다 ({_gex_spot_note}). '
            '실제 SPX 값과 다를 수 있습니다.'
            '</div>',
            unsafe_allow_html=True,
        )

    if _gex_source_label and "Schwab" in _gex_source_label and "야후" not in _gex_source_label:
        st.markdown(
            '<div style="font-size:8px; color:#5b6474; margin-bottom:4px;">'
            '* SPX 옵션체인(Schwab) 기준 GEX. 실제 딜러 포지셔닝과는 다를 수 있음.'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="font-size:8px; color:#5b6474; margin-bottom:4px;">'
            '* 야후 SPY 0DTE 옵션체인(15분 지연) 기준. 그릭스는 야후가 안 주는 값이라 IV+Black-Scholes로 '
            '직접 계산한 모델 근사치이며, 실제 거래소 그릭스·실시간 딜러 포지셔닝과 다를 수 있습니다.'
            '</div>',
            unsafe_allow_html=True,
        )

# --- Backtest Controls ---
tf_option = st.radio("타임프레임", ["10분 뒤", "30분 뒤", "1시간 뒤"], index=1, horizontal=True, label_visibility="collapsed")
bars_map = {"10분 뒤": 2, "30분 뒤": 6, "1시간 뒤": 12}
selected_bars = bars_map[tf_option]

if st.button(f"🚀 [{tf_option}] 승률/기대값 검증 실행", use_container_width=True):
    with st.spinner("과거 데이터 분석 중..."):
        res = run_probability_analysis("ES=F", period="1mo", interval="5m", lookahead_bars=selected_bars)
        if res:
            res["tf_option"] = tf_option
            st.session_state["backtest_result"] = res

            # --- 신호 기록 (신규) ---
            # 지금 이 순간의 판단(방향/신뢰도/스트라이크)을 DB에 남겨서,
            # timeframe_minutes 뒤 실제로 어떻게 됐는지 나중에 자동으로 채워지고,
            # 그걸 누적하면 "이 시스템이 실제로 얼마나 맞는지" 스스로 검증할 수 있다.
            try:
                _win = res.get('win_rate', 0.0)
                _loss = res.get('loss_rate', 0.0)
                _ev = res.get('expected_value', 0.0)
                if _win > _loss and _ev > 0:
                    _direction = "BULLISH"
                elif _loss > _win:
                    _direction = "BEARISH"
                else:
                    _direction = "WAIT"
                _confidence = min(round(abs(_win - _loss) * 2), 100)

                if spx_p is not None:
                    signal_tracker.log_signal(
                        spot_price=spx_p,
                        direction=_direction,
                        confidence=_confidence,
                        win_rate=_win,
                        loss_rate=_loss,
                        call_strike=strikes.get('call_target'),
                        put_strike=strikes.get('put_target'),
                        timeframe_label=tf_option,
                        timeframe_minutes=selected_bars * 5,
                    )
            except Exception:
                pass  # 기록 실패가 백테스트 결과 표시를 막으면 안 됨

result = st.session_state.get("backtest_result")

if result:
    win_rate = result.get('win_rate', 0.0)
    loss_rate = result.get('loss_rate', round(100.0 - win_rate, 1))
    total_signals = result.get('total_signals', 0)
    ev = result.get('expected_value', 0.0)
    bullish_signals = result.get('bullish_signals')
    bearish_signals = result.get('bearish_signals')
    confidence_level = result.get('confidence_level')
    margin_of_error = result.get('margin_of_error')
    date_start = result.get('date_start')
    date_end = result.get('date_end')
    call_spread_win_rate = result.get('call_spread_win_rate')
    put_spread_win_rate = result.get('put_spread_win_rate')
    spread_sample_size = result.get('spread_sample_size', 0)
    spread_offset_mult = result.get('spread_offset_atr_mult')

    st.markdown(f"""
<div class="card-box">
<div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 2px; text-align: center;">
<div><div style="font-size: 8px; color: #6b7280;">총시그널</div><div style="font-size: 12px; font-weight: bold;">{total_signals}회</div></div>
<div><div style="font-size: 8px; color: #6b7280;">▲ 상승</div><div style="font-size: 12px; font-weight: bold; color: #10b981;">{win_rate}%</div></div>
<div><div style="font-size: 8px; color: #6b7280;">▼ 하락</div><div style="font-size: 12px; font-weight: bold; color: #ef4444;">{loss_rate}%</div></div>
<div><div style="font-size: 8px; color: #6b7280;">EV</div><div style="font-size: 12px; font-weight: bold; color: #facc15;">+{ev}pt</div></div>
</div>
</div>
""", unsafe_allow_html=True)

    # --- 스프레드 브리치 기준 승률 (신규) ---
    # 위 win_rate/loss_rate는 "N봉 뒤 방향"만 본 것이고, 아래는 "그 구간에
    # 스트라이크를 실제로 건드렸는지"까지 반영한 훨씬 실전에 가까운 수치다.
    if call_spread_win_rate is not None and put_spread_win_rate is not None:
        st.markdown(f"""
<div class="card-box" style="font-size: 9px; color: #9ca3af;">
<div style="font-weight:bold; color:#e1e6ed; margin-bottom:2px;">📐 스프레드 브리치 기준 승률 (ATR×{spread_offset_mult} 근사 스트라이크, n={spread_sample_size})</div>
<div style="display:flex; justify-content:space-between;">
<span>🔴 CALL 스프레드 안 건드림: <b style="color:#10b981;">{call_spread_win_rate}%</b></span>
<span>🟢 PUT 스프레드 안 건드림: <b style="color:#10b981;">{put_spread_win_rate}%</b></span>
</div>
<div style="margin-top:2px; color:#6b7280;">* 실제 옵션 IV/프리미엄 데이터가 아직 없어 ATR 기반 근사치입니다.</div>
</div>
""", unsafe_allow_html=True)

    # --- 신뢰도 / 표본 구성 안내 ---
    if confidence_level is not None:
        conf_colors = {"LOW": "#ef4444", "MEDIUM": "#facc15", "HIGH": "#10b981"}
        conf_labels = {"LOW": "낮음", "MEDIUM": "보통", "HIGH": "높음"}
        conf_color = conf_colors.get(confidence_level, "#9ca3af")
        conf_label = conf_labels.get(confidence_level, confidence_level)

        low_conf_warning = ""
        if confidence_level == "LOW":
            low_conf_warning = ("<div style='margin-top:2px; color:#fca5a5;'>"
                                 "⚠️ 표본이 30개 미만이라 승률/하락률이 노이즈일 가능성이 높습니다. "
                                 "참고용으로만 활용하세요.</div>")

        period_str = f"{date_start} ~ {date_end}" if date_start and date_end else ""

        st.markdown(f"""
<div class="card-box" style="font-size: 9px; color: #9ca3af;">
<div style="display:flex; justify-content:space-between;">
<span>신뢰도: <b style="color:{conf_color};">{conf_label}</b> (오차범위 ±{margin_of_error}%p, 95% 신뢰구간)</span>
<span>상승신호 {bullish_signals}회 / 하락신호 {bearish_signals}회</span>
</div>
<div style="margin-top:2px;">분석 구간: {period_str}</div>
{low_conf_warning}
</div>
""", unsafe_allow_html=True)

    # --- 켈리 공식 기반 포지션 사이징 (신규: 기존에 정의만 되고 안 쓰이던 함수를 연결) ---
    avg_win = result.get('avg_win', 0.0)
    avg_loss = result.get('avg_loss', 0.0)
    if avg_loss and avg_loss > 0:
        reward_to_risk = avg_win / avg_loss
        kelly_pct = SimonsBenterQuantEngine.calculate_fractional_kelly(
            win_rate, reward_to_risk, fraction=0.25
        )
        kelly_color = "#10b981" if kelly_pct > 0 else "#9ca3af"
        kelly_desc = (f"손익비 {round(reward_to_risk, 2)} · 1/4 켈리 기준"
                       if kelly_pct > 0 else "승률/손익비 조합상 배팅 근거 부족 (0% 권장)")
        st.markdown(f"""
<div class="card-box" style="display:flex; justify-content:space-between; align-items:center; font-size:10px;">
<span style="color:#9ca3af;">💰 권장 포지션 크기 (Kelly)</span>
<span style="text-align:right;">
<b style="font-size:14px; color:{kelly_color};">{kelly_pct}%</b>
<div style="font-size:9px; color:#9ca3af;">{kelly_desc}</div>
</span>
</div>
""", unsafe_allow_html=True)

# --- Decision Signal Box ---
if result:
    win = result.get('win_rate', 0.0)
    loss = result.get('loss_rate', 0.0)
    ev_val = result.get('expected_value', 0.0)
    confidence = min(round(abs(win - loss) * 2), 100)

    if win > loss and ev_val > 0:
        sig_title = "PUT CREDIT SPREAD"
        sig_badge = '<span class="badge-green">BULLISH</span>'
        sig_color = "#10b981"
        sig_desc = f"상승 확률({win}%) 우세. Put Credit Spread 권장."
    elif loss > win:
        sig_title = "CALL CREDIT SPREAD"
        sig_badge = '<span class="badge-red">BEARISH</span>'
        sig_color = "#ef4444"
        sig_desc = f"하락 확률({loss}%) 우세. Call Credit Spread 권장."
    else:
        sig_title = "관망 (NEUTRAL)"
        sig_badge = '<span class="badge-yellow">WAIT</span>'
        sig_color = "#fbbf24"
        sig_desc = "방향성 불분명. 수급 추가 확인 필요."
else:
    sig_title = "백테스트 검증 필요"
    sig_badge = '<span class="badge-yellow">⏱️ READY</span>'
    sig_color = "#fbbf24"
    confidence = 0
    sig_desc = "상단 버튼을 눌러 승률을 검증하세요."

st.markdown(f"""
<div class="signal-box">
<div style="display: flex; justify-content: space-between; align-items: center;">
<span style="font-size: 10px; font-weight: bold; color: #9ca3af;">🚨 DECISION SIGNAL</span>
{sig_badge}
</div>
<div style="margin-top: 2px; display: flex; justify-content: space-between; align-items: center;">
<span style="font-size: 15px; font-weight: bold; color: {sig_color};">{sig_title}</span>
<span style="font-size: 9px; color: #9ca3af;">CONF <b style="font-size: 12px; color: {sig_color};">{confidence}%</b></span>
</div>
<div style="font-size: 10px; color: #d1d5db; margin-top: 2px;">{sig_desc}</div>
</div>
""", unsafe_allow_html=True)

# --- Dynamic Recommended Strikes ---
_strikes_call_target = strikes.get('call_target') if isinstance(strikes, dict) else None
_strikes_put_target = strikes.get('put_target') if isinstance(strikes, dict) else None
_strikes_dyn_call_sell = strikes.get('dyn_call_sell', 'N/A') if isinstance(strikes, dict) else 'N/A'
_strikes_dyn_put_sell = strikes.get('dyn_put_sell', 'N/A') if isinstance(strikes, dict) else 'N/A'

# --- 상시 진단 라인 (신규) ---
# "N/A"가 왜 나오는지 매번 캡처해서 물어보는 대신, 여기서 바로 원인을 보이게 한다.
with st.expander("🔍 스트라이크 계산 진단 (N/A로 나올 때 펼쳐서 확인)", expanded=(_strikes_call_target is None)):
    st.write(f"spx_p (원본 SPX 실시간): {spx_p}")
    st.write(f"es_p (ES 선물 실시간): {es_p}")
    st.write(f"_effective_spx_price (스트라이크 계산에 실제 쓰인 값): {_effective_spx_price}")
    st.write(f"_spx_is_estimated (ES 기반 추정 여부): {_spx_is_estimated}")
    st.write(f"_spx_estimate_note: {_spx_estimate_note}")
    st.write(f"strikes 딕셔너리 원본: {strikes}")
    st.write(f"alpaca_analytics: {alpaca_analytics}")

if _effective_spx_price is not None and _strikes_call_target is not None and _strikes_put_target is not None:
    diff_r2 = round(_strikes_call_target - _effective_spx_price, 1)
    diff_s2 = round(_effective_spx_price - _strikes_put_target, 1)
    call_target_str = _strikes_call_target
    put_target_str = _strikes_put_target
    diff_r2_str = f"+{diff_r2} pt 차이"
    diff_s2_str = f"-{diff_s2} pt 차이"
else:
    call_target_str = "N/A"
    put_target_str = "N/A"
    diff_r2_str = "데이터 없음"
    diff_s2_str = "데이터 없음"

if _spx_is_estimated and _strikes_call_target is not None:
    st.markdown(
        f'<div style="font-size:9px; color:#facc15; margin-bottom:2px;">'
        f'⚠️ 정규장 외 시간이라 SPX를 ES 기반으로 추정해서 스트라이크를 계산했습니다 ({_spx_estimate_note}).'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown(f"""
<div class="grid-2col">
<div class="metric-card" style="border-left: 3px solid #ef4444;">
<div style="font-size: 10px; font-weight: bold; color: #fca5a5;">🔴 CALL CREDIT SPREAD</div>
<div style="font-size: 14px; font-weight: bold; margin-top: 2px;">{call_target_str} Strike</div>
<div style="font-size: 9px; color: #10b981;">{diff_r2_str}</div>
<div style="font-size: 9px; color: #9ca3af; margin-top: 4px;">🎯 <b>{_strikes_dyn_call_sell} Call Sell</b></div>
</div>
<div class="metric-card" style="border-left: 3px solid #10b981;">
<div style="font-size: 10px; font-weight: bold; color: #6ee7b7;">🟢 PUT CREDIT SPREAD</div>
<div style="font-size: 14px; font-weight: bold; margin-top: 2px;">{put_target_str} Strike</div>

<div style="font-size: 9px; color: #ef4444;">{diff_s2_str}</div>
<div style="font-size: 9px; color: #9ca3af; margin-top: 4px;">🎯 <b>{_strikes_dyn_put_sell} Put Sell</b></div>
</div>
</div>
""", unsafe_allow_html=True)

# --- VWAP 밴드 + RSI + 1시간 차트 (신규) ---
@st.cache_data(ttl=30)
def fetch_today_session_1m():
    """오늘 정규장(09:30 ET~) 1분봉. VWAP은 매일 09:30에 리셋되는 게 관례라 오늘 데이터만 쓴다."""
    try:
        t = yf.Ticker("ES=F")
        df = t.history(period="1d", interval="1m")
        if df.empty:
            return None
        est_tz = pytz.timezone('US/Eastern')
        df.index = df.index.tz_convert(est_tz)
        today = datetime.now(est_tz).date()
        session_start = est_tz.localize(datetime.combine(today, datetime.min.time()).replace(hour=9, minute=30))
        df = df[(df.index.date == today) & (df.index >= session_start)]
        return df if not df.empty else None
    except Exception:
        return None

section_header("📈", "1H 차트 · VWAP BANDS", f"Data as of {now_est.strftime('%H:%M:%S')} ET")

_session_df = fetch_today_session_1m()

if _session_df is not None and len(_session_df) >= 5:
    _vwap_series, _vwap_std = market_pulse.calculate_vwap_bands(_session_df)
    _last_vwap = _vwap_series.iloc[-1]
    _last_std = _vwap_std.iloc[-1]
    _last_close = _session_df['Close'].iloc[-1]

    if _last_close > _last_vwap + _last_std:
        _vwap_note = "현재 상단 밴드 위 — 과열 구간일 수 있습니다."
    elif _last_close < _last_vwap - _last_std:
        _vwap_note = "현재 하단 밴드 아래 — 과매도 구간일 수 있습니다."
    else:
        _vwap_note = "현재 정상 세션 VWAP 밴드 안에 있습니다."

    _vwap_fig = go.Figure()
    _vwap_fig.add_trace(go.Scatter(x=_session_df.index, y=_session_df['Close'], name="가격",
                                    line=dict(color='#e1e6ed', width=1.5)))
    _vwap_fig.add_trace(go.Scatter(x=_session_df.index, y=_vwap_series, name="VWAP",
                                    line=dict(color='#facc15', width=1.5, dash='dot')))
    _vwap_fig.add_trace(go.Scatter(x=_session_df.index, y=_vwap_series + _vwap_std, name="+1σ",
                                    line=dict(color='#3b82f680', width=1)))
    _vwap_fig.add_trace(go.Scatter(x=_session_df.index, y=_vwap_series - _vwap_std, name="-1σ",
                                    line=dict(color='#3b82f680', width=1), fill='tonexty',
                                    fillcolor='rgba(59,130,246,0.07)'))
    _vwap_fig.add_trace(go.Scatter(x=_session_df.index, y=_vwap_series + 2 * _vwap_std, name="+2σ",
                                    line=dict(color='#3b82f640', width=1, dash='dash')))
    _vwap_fig.add_trace(go.Scatter(x=_session_df.index, y=_vwap_series - 2 * _vwap_std, name="-2σ",
                                    line=dict(color='#3b82f640', width=1, dash='dash')))
    _vwap_fig.update_layout(
        template="plotly_dark", height=210, margin=dict(l=0, r=0, t=10, b=20),
        paper_bgcolor='#0a0e17', plot_bgcolor='#121824', showlegend=False,
        xaxis=dict(showgrid=False, fixedrange=True, tickfont=dict(size=9, color='#7b8494')),
        yaxis=dict(showgrid=True, gridcolor='#1e2635', fixedrange=True, tickfont=dict(size=9, color='#7b8494')),
    )
    components.html(_vwap_fig.to_html(include_plotlyjs='cdn', full_html=False,
                                       config={'staticPlot': True, 'displayModeBar': False}), height=215)

    st.markdown(f"""
    <div class="card-box" style="font-size:10px;">
    <span style="color:#facc15;">— </span>
    <b>VWAP {round(_last_vwap,2)}</b>
    <span style="color:#9ca3af;"> · {_vwap_note}</span>
    </div>
    """, unsafe_allow_html=True)

    # --- RSI(14) - 타임프레임 선택 가능, SPX 실데이터(Schwab) 우선 ---
    section_header("📉", "RSI (14)", None)
    _rsi_tf = st.radio("RSI TF", ["1m", "5m", "15m", "30m", "1H"], index=0,
                        horizontal=True, label_visibility="collapsed", key="rsi_timeframe")

    _rsi_df = None
    _rsi_source = None
    if schwab_client.is_configured():
        _rsi_df, _rsi_err = schwab_client.fetch_price_history_tf(symbol="$SPX", timeframe=_rsi_tf)
        if _rsi_df is not None:
            _rsi_source = "SPX 실시간 (Schwab)"

    if _rsi_df is None:
        _rsi_df = fetch_es_history_for_rsi(_rsi_tf)
        if _rsi_df is not None:
            _rsi_source = "ES 선물 (야후, Schwab 대신 사용됨)" if schwab_client.is_configured() else "ES 선물 (야후)"

    if _rsi_df is not None and len(_rsi_df) >= 15:
        st.markdown(f'<div style="font-size:8px; color:#5b6474; margin-bottom:2px;">데이터: {_rsi_source}</div>',
                    unsafe_allow_html=True)
        _rsi_series = market_pulse.calculate_rsi(_rsi_df['Close'], period=14)
        _last_rsi = _rsi_series.iloc[-1]
        _rsi_color = "#ef4444" if _last_rsi > 70 else ("#3b82f6" if _last_rsi < 30 else "#10b981")
        _rsi_label = "과매수" if _last_rsi > 70 else ("과매도" if _last_rsi < 30 else "중립")

        _rsi_fig = go.Figure()
        _rsi_fig.add_trace(go.Scatter(x=_rsi_df.index, y=_rsi_series, line=dict(color=_rsi_color, width=1.5)))
        _rsi_fig.add_hline(y=70, line_dash="dot", line_color="#ef444460", line_width=1)
        _rsi_fig.add_hline(y=30, line_dash="dot", line_color="#3b82f660", line_width=1)
        _rsi_fig.update_layout(
            template="plotly_dark", height=110, margin=dict(l=0, r=0, t=5, b=15),
            paper_bgcolor='#0a0e17', plot_bgcolor='#121824', showlegend=False,
            xaxis=dict(showgrid=False, fixedrange=True, showticklabels=False),
            yaxis=dict(showgrid=False, fixedrange=True, range=[0, 100], tickfont=dict(size=8, color='#7b8494')),
        )
        components.html(_rsi_fig.to_html(include_plotlyjs='cdn', full_html=False,
                                          config={'staticPlot': True, 'displayModeBar': False}), height=115)
        st.markdown(f"""
        <div style="text-align:right; font-size:11px; margin-top:-6px;">
        <span class="mono-num" style="color:{_rsi_color}; font-weight:700;">{round(_last_rsi,1)}</span>
        <span style="color:#9ca3af;"> {_rsi_label} · {_rsi_tf}</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="card-box" style="font-size:10px; color:#9ca3af;">
        이 타임프레임의 RSI 계산에 데이터가 부족합니다. 잠시 후 다시 확인해주세요.
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown("""
    <div class="card-box" style="font-size:10px; color:#9ca3af;">
    오늘 세션 데이터를 아직 못 가져왔습니다 (장 시작 직후이거나 데이터 지연). 잠시 후 다시 확인해주세요.
    </div>
    """, unsafe_allow_html=True)

# --- Volume & CVD Chart ---
st.markdown("<div style='font-size: 11px; font-weight: bold; margin-top: 4px;'>📊 VOLUME + CVD (ES=F)</div>", unsafe_allow_html=True)

selected_tf = st.radio("TF", ["1m", "5m", "15m", "30m", "1H"], index=2, horizontal=True, label_visibility="collapsed")
es_df_chart = fetch_es_history(selected_tf)

if es_df_chart is not None and not es_df_chart.empty:
    dates_str = [d.strftime("%m/%d %H:%M") for d in es_df_chart.index]
    total_vol = es_df_chart['Volume'].values
    close_vals = es_df_chart['Close'].values
    open_vals = es_df_chart['Open'].values
    delta = close_vals - open_vals

    buy_mask = delta >= 0
    buy_vol = np.where(buy_mask, total_vol * 0.55, total_vol * 0.45)
    sell_vol = total_vol - buy_vol

    cvd = np.cumsum(buy_vol - sell_vol) / 1000
    colors = ['#10b981' if b else '#ef4444' for b in buy_mask]

    total_buy = np.sum(buy_vol)
    total_sum = np.sum(total_vol) if np.sum(total_vol) > 0 else 1
    buy_pct = int((total_buy / total_sum) * 100)
    sell_pct = 100 - buy_pct
    chart_data_is_live = True
else:
    n_bars = 15
    dates_str = [(now_est - timedelta(hours=i)).strftime("%m/%d %H:%M") for i in range(n_bars)][::-1]
    total_vol = np.zeros(n_bars)
    cvd = np.zeros(n_bars)
    colors = ['#374151' for _ in range(n_bars)]
    buy_pct, sell_pct = 0, 0
    chart_data_is_live = False

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Bar(
    x=dates_str,
    y=total_vol,
    name="Volume",
    marker_color=colors,
    opacity=0.9,
    marker_line_width=0
), secondary_y=False)

fig.add_trace(go.Scatter(
    x=dates_str,
    y=cvd,
    name="CVD",
    line=dict(color='#facc15', width=2)
), secondary_y=True)

fig.update_layout(
    template="plotly_dark",
    height=205,
    margin=dict(l=0, r=0, t=10, b=32),
    paper_bgcolor='#0b0e14',
    plot_bgcolor='#121721',
    showlegend=False,
    bargap=0.2,
    xaxis=dict(
        showgrid=False,
        fixedrange=True,
        type='category',
        tickfont=dict(size=10, color='#e1e6ed'),
        nticks=6
    ),
    yaxis=dict(
        showgrid=True,
        gridcolor='#1f2937',
        title=None,
        fixedrange=True,
        tickfont=dict(size=8, color='#9ca3af')
    ),
    yaxis2=dict(
        showgrid=False,
        title=None,
        fixedrange=True,
        showticklabels=False
    )
)

html_fig = fig.to_html(include_plotlyjs='cdn', full_html=False, config={'staticPlot': True, 'displayModeBar': False})
components.html(f"""
<div style="pointer-events: none; user-select: none; width:100%; height:205px;">
{html_fig}
</div>
""", height=210)

if chart_data_is_live:
    st.markdown(f"""
    <div style="display: flex; justify-content: space-between; font-weight: bold; font-size: 10px; margin-top: 2px;">
    <span style="color: #10b981;">▲ Buy {buy_pct}%</span>
    <span style="color: #ef4444;">▼ Sell {sell_pct}%</span>
    </div>
    <div class="bar-container">
    <div class="bar-fill" style="width: {buy_pct}%;"></div>
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
    <div style="font-size: 10px; color: #9ca3af; text-align:center; margin-top:2px;">
    ES=F 데이터를 불러오지 못했습니다.
    </div>
    """, unsafe_allow_html=True)

# ============================================================
# 워크포워드 / 아웃오브샘플 검증 (신규)
# ============================================================
st.markdown("<hr>", unsafe_allow_html=True)
st.markdown("<div style='font-size: 11px; font-weight: bold; margin-top: 4px;'>🔬 워크포워드 검증 (기간별 안정성 체크)</div>", unsafe_allow_html=True)
st.markdown("<div style='font-size:9px; color:#9ca3af; margin-bottom:4px;'>같은 규칙을 여러 구간에 나눠 적용해서, 결과가 우연이 아니라 꾸준히 재현되는지 확인합니다. (3개월치 데이터 사용, 계산에 시간이 좀 걸릴 수 있음)</div>", unsafe_allow_html=True)

if st.button("🔬 워크포워드 검증 실행 (4구간)", use_container_width=True):
    with st.spinner("3개월치 데이터를 4구간으로 나눠 분석 중... (시간이 좀 걸립니다)"):
        wf_res = run_walk_forward_analysis("ES=F", period="3mo", interval="5m",
                                            lookahead_bars=selected_bars, n_windows=4)
        st.session_state["walk_forward_result"] = wf_res if wf_res is not None else "EMPTY"

wf_result = st.session_state.get("walk_forward_result")

if wf_result is None:
    st.markdown("""
    <div class="card-box" style="font-size:10px; color:#9ca3af;">
    아직 실행 안 됨. 버튼을 누르면 최근 3개월을 4구간으로 나눠서 같은 신호 규칙을
    각각 따로 검증합니다.
    </div>
    """, unsafe_allow_html=True)
elif wf_result == "EMPTY":
    st.markdown("<div style='font-size:10px; color:#ef4444;'>데이터가 부족해서 구간을 나눌 수 없습니다.</div>", unsafe_allow_html=True)
else:
    _windows = wf_result["windows"]
    _std = wf_result["stability_std"]
    _consistent = wf_result["consistent_direction"]

    # 구간별 카드
    _cols_html = "<div style='display:grid; grid-template-columns:repeat(4,1fr); gap:4px;'>"
    for w in _windows:
        _wr = w["win_rate"]
        _wr_str = f"{_wr}%" if _wr is not None else "N/A"
        _wr_color = "#10b981" if (_wr is not None and _wr > 50) else ("#ef4444" if _wr is not None else "#6b7280")
        _cols_html += f"""
        <div class="metric-card" style="padding:4px 6px;">
        <div style="font-size:8px; color:#6b7280;">구간{w['window']} ({w['date_start']}~{w['date_end']})</div>
        <div style="font-size:13px; font-weight:bold; color:{_wr_color};">{_wr_str}</div>
        <div style="font-size:8px; color:#9ca3af;">n={w['total_signals']}</div>
        </div>
        """
    _cols_html += "</div>"
    st.markdown(_cols_html, unsafe_allow_html=True)

    # 안정성 종합 판정
    if _consistent is None:
        _verdict = "판정 불가 (유효한 구간이 2개 미만)"
        _verdict_color = "#9ca3af"
    elif _consistent and _std is not None and _std < 10:
        _verdict = "✅ 안정적 — 모든 구간에서 같은 방향, 편차도 작습니다."
        _verdict_color = "#10b981"
    elif _consistent:
        _verdict = "🟡 방향은 일관되지만 구간별 편차가 큽니다 — 참고용으로만 쓰세요."
        _verdict_color = "#facc15"
    else:
        _verdict = "⚠️ 불안정 — 구간마다 결과가 뒤집힙니다. 지금까지의 백테스트 결과는 특정 기간의 우연일 가능성이 높습니다 (과최적화 위험)."
        _verdict_color = "#ef4444"

    _std_str = f"±{_std}%p" if _std is not None else "N/A"
    st.markdown(f"""
    <div class="card-box" style="font-size:10px; color:#d1d5db;">
    <div style="font-weight:bold; color:{_verdict_color};">{_verdict}</div>
    <div style="margin-top:2px; color:#9ca3af;">구간별 승률 표준편차: {_std_str}</div>
    </div>
    """, unsafe_allow_html=True)

# ============================================================
# 신호 히스토리 · 자체 적중률 검증
# ============================================================
st.markdown("<hr>", unsafe_allow_html=True)
st.markdown("<div style='font-size: 11px; font-weight: bold; margin-top: 4px;'>📊 신호 히스토리 · 자체 적중률 검증</div>", unsafe_allow_html=True)

try:
    _stats = signal_tracker.get_accuracy_stats()
except Exception as _e:
    _stats = None
    st.markdown(f"<div style='font-size:9px; color:#6b7280;'>적중률 통계를 불러오지 못했습니다: {_e}</div>", unsafe_allow_html=True)

if _stats is None:
    st.markdown("""
    <div class="card-box" style="font-size: 10px; color: #9ca3af;">
    아직 결과가 확인된 신호가 없습니다. 상단에서 백테스트를 실행하면 신호가 기록되고,
    선택한 타임프레임(예: 30분 뒤)이 지나면 자동으로 실제 결과와 비교되어 여기 쌓입니다.
    </div>
    """, unsafe_allow_html=True)
else:
    acc_color = "#10b981" if _stats["overall_accuracy"] >= 50 else "#ef4444"
    st.markdown(f"""
    <div class="grid-2col">
    <div class="metric-card"><div class="metric-label">전체 적중률</div><div class="metric-val" style="color:{acc_color};">{_stats['overall_accuracy']}%</div><div class="metric-sub" style="color:#9ca3af;">확인된 신호 {_stats['total_resolved']}건</div></div>
    <div class="metric-card"><div class="metric-label">해석</div><div style="font-size:10px; color:#d1d5db; margin-top:2px;">50% 미만이면 이 시스템의 방향성 신호가 동전던지기보다 못하다는 뜻입니다.</div></div>
    </div>
    """, unsafe_allow_html=True)

    # 신뢰도 구간별 적중률 (캘리브레이션 체크) — 높음 구간이 실제로 더 잘 맞아야 정상
    by_conf = _stats["by_confidence"]
    if not by_conf.empty:
        rows_html = ""
        for tier, row in by_conf.iterrows():
            n = int(row['count'])
            m = row['mean']
            m_str = f"{m}%" if pd.notna(m) else "N/A"
            rows_html += f"<div style='display:flex; justify-content:space-between; padding:2px 0;'><span>{tier}</span><span>{m_str} (n={n})</span></div>"
        st.markdown(f"""
        <div class="card-box" style="font-size:10px; color:#d1d5db;">
        <div style="font-weight:bold; margin-bottom:2px; color:#e1e6ed;">신뢰도 구간별 실제 적중률 (캘리브레이션)</div>
        {rows_html}
        <div style="margin-top:2px; font-size:9px; color:#6b7280;">* "높음" 구간 적중률이 "낮음" 구간보다 낮다면, 신뢰도 표시 자체를 다시 손봐야 한다는 신호입니다.</div>
        </div>
        """, unsafe_allow_html=True)

    with st.expander("최근 신호 상세 기록 보기"):
        _hist = signal_tracker.get_signal_history(limit=50)
        if _hist.empty:
            st.markdown("기록 없음")
        else:
            _display_cols = ['logged_at', 'direction', 'confidence', 'spot_price',
                              'call_strike', 'put_strike', 'resolved', 'actual_direction', 'correct']
            _display_cols = [c for c in _display_cols if c in _hist.columns]
            st.dataframe(_hist[_display_cols], use_container_width=True, hide_index=True)
