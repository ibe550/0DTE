import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import time
import yfinance as yf
import requests

from backtest import run_probability_analysis
from quant_engine import SimonsBenterQuantEngine

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
.stApp { background-color: #0b0e14; color: #e1e6ed; }
.block-container {
    padding-top: 0.5rem !important;
    padding-bottom: 0.5rem !important;
    padding-left: 0.4rem !important;
    padding-right: 0.4rem !important;
    max-width: 100% !important;
}
[data-testid="stVerticalBlock"] > div { gap: 0.3rem !important; }
.card-box { background-color: #121721; border: 1px solid #1f2937; border-radius: 6px; padding: 6px 8px; margin-bottom: 4px; }
.signal-box { background-color: #16150e; border: 1px solid #785a00; border-radius: 6px; padding: 8px 10px; margin-bottom: 4px; }
.badge-red { background-color: #991b1b; color: #fca5a5; padding: 1px 5px; border-radius: 4px; font-weight: bold; font-size: 9px; }
.badge-green { background-color: #065f46; color: #6ee7b7; padding: 1px 5px; border-radius: 4px; font-weight: bold; font-size: 9px; }
.badge-yellow { background-color: #78350f; color: #fde68a; padding: 1px 5px; border-radius: 4px; font-weight: bold; font-size: 9px; }
.grid-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 4px; }
.grid-4col { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 4px; margin-bottom: 4px; }
.metric-card { background-color: #121721; border: 1px solid #1f2937; border-radius: 6px; padding: 6px 8px; }
.metric-label { font-size: 10px; color: #9ca3af; font-weight: bold; }
.metric-val { font-size: 15px; font-weight: bold; color: #ffffff; line-height: 1.2; }
.metric-sub { font-size: 9px; margin-top: 2px; }
.bar-container { width: 100%; background-color: #ef4444; height: 5px; border-radius: 3px; overflow: hidden; margin: 3px 0; }
.bar-fill { height: 100%; background-color: #10b981; }
hr { margin: 6px 0 !important; border-color: #1f2937 !important; }
</style>
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

    # 1순위: Alpaca (SPY, 실시간)
    alp_spy_p, alp_spy_c, alp_spy_pct, alp_err = fetch_alpaca_stock_snapshot("SPY")
    if alp_err:
        errors.append(alp_err)

    # 2순위: Twelve Data (SPY) - Alpaca 실패했을 때만 보조 실시간 소스로 사용.
    # 주의: Twelve Data 무료(Basic) 플랜은 지수(SPX, VIX)를 지원하지 않는다
    # (유료 Grow 플랜부터 지원). 그래서 SPX/VIX에는 사용하지 않는다.
    td_spy_p = td_spy_c = td_spy_pct = None
    if alp_spy_p is None:
        td_results, td_errors = fetch_twelvedata_quotes("SPY")
        errors.extend(td_errors)
        td_spy_p, td_spy_c, td_spy_pct = td_results.get("SPY", (None, None, None))

    spy_p, spy_c, spy_pct = (alp_spy_p, alp_spy_c, alp_spy_pct) if alp_spy_p is not None \
        else (td_spy_p, td_spy_c, td_spy_pct)

    # SPX/VIX/ES: 무료로 지수·선물을 실제 값으로 주는 곳이 마땅치 않아 야후를 사용.
    # 배치 조회 + 캐시로 rate limit 위험은 최대한 줄여둔 상태.
    yf_symbols = ['^GSPC', '^VIX'] + YF_TICKERS  # YF_TICKERS = ['ES=F']
    if spy_p is None:
        yf_symbols.append('SPY')

    yf_results, yf_errors = fetch_yf_batch(tuple(yf_symbols))
    errors.extend(yf_errors)

    spx_p, spx_c, spx_pct = yf_results.get('^GSPC', (None, None, None))
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
    regime, distance_mult = SimonsBenterQuantEngine.detect_market_regime(es_df, vix_p if vix_p is not None else 15.0)
    z_score = SimonsBenterQuantEngine.calculate_zscore_anomaly(es_df['Close'])
else:
    regime, distance_mult = "NORMAL_VOLATILITY", 1.0
    z_score = 0.0

alpaca_analytics = fetch_alpaca_0dte_analytics(spy_p)
strikes = calculate_dynamic_strikes(spx_p, news_sentiment, news_score, distance_mult, alpaca_analytics)

# --- Header ---
st.markdown(f"""
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
<span style="font-weight: bold; font-size: 14px;">🛡️ SPX 0DTE DEFENDER <span style="background-color: #1f2937; padding: 1px 4px; border-radius: 3px; font-size: 9px; color: #9ca3af;">v24.1</span></span>
<span style="background-color: #1f2937; padding: 1px 6px; border-radius: 8px; font-size: 9px; color: #9ca3af;">● Live | {now_est.strftime('%H:%M')} ET</span>
</div>
""", unsafe_allow_html=True)

# --- 데이터 오류 배너 (신규) ---
if data_errors:
    err_text = " / ".join(data_errors[:3])
    st.markdown(f"""
    <div style="background-color:#3f1d1d; border:1px solid #7f1d1d; border-radius:6px;
                padding:4px 8px; margin-bottom:4px; font-size:10px; color:#fca5a5;">
    ⚠️ 일부 시세 조회 실패 (표시값은 N/A 또는 근사치일 수 있음): {err_text}
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
<div class="metric-card"><div class="metric-label">REGIME</div><div style="font-size: 11px; font-weight: bold; color: #60a5fa; margin-top:2px;">{regime}</div><div class="metric-sub" style="color:#9ca3af;">Dist Mult: {distance_mult}x</div></div>
<div class="metric-card"><div class="metric-label">Z-SCORE</div><div class="metric-val" style="color: {z_color};">{z_score:+.2f}</div><div class="metric-sub" style="color:#9ca3af;">{z_desc}</div></div>
<div class="metric-card"><div class="metric-label">DELTA TARGET</div><div class="metric-val">0.15 Δ</div><div class="metric-sub" style="color:#10b981;">Target 85% Win</div></div>
<div class="metric-card"><div class="metric-label">NEWS SCORE</div><div class="metric-val" style="color: {sent_color};">{news_score:+.2f}</div><div class="metric-sub" style="color:#9ca3af;">{news_sentiment['sentiment']}</div></div>
</div>
""", unsafe_allow_html=True)

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

    # --- 신뢰도 / 표본 구성 안내 (신규) ---
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
if spx_p is not None and strikes['call_target'] is not None:
    diff_r2 = round(strikes['call_target'] - spx_p, 1)
    diff_s2 = round(spx_p - strikes['put_target'], 1)
    call_target_str = strikes['call_target']
    put_target_str = strikes['put_target']
    diff_r2_str = f"+{diff_r2} pt 차이"
    diff_s2_str = f"-{diff_s2} pt 차이"
else:
    call_target_str = "N/A"
    put_target_str = "N/A"
    diff_r2_str = "데이터 없음"
    diff_s2_str = "데이터 없음"

st.markdown(f"""
<div class="grid-2col">
<div class="metric-card" style="border-left: 3px solid #ef4444;">
<div style="font-size: 10px; font-weight: bold; color: #fca5a5;">🔴 CALL CREDIT SPREAD</div>
<div style="font-size: 14px; font-weight: bold; margin-top: 2px;">{call_target_str} Strike</div>
<div style="font-size: 9px; color: #10b981;">{diff_r2_str}</div>
<div style="font-size: 9px; color: #9ca3af; margin-top: 4px;">🎯 <b>{strikes['dyn_call_sell']} Call Sell</b></div>
</div>
<div class="metric-card" style="border-left: 3px solid #10b981;">
<div style="font-size: 10px; font-weight: bold; color: #6ee7b7;">🟢 PUT CREDIT SPREAD</div>
<div style="font-size: 14px; font-weight: bold; margin-top: 2px;">{put_target_str} Strike</div>
<div style="font-size: 9px; color: #ef4444;">{diff_s2_str}</div>
<div style="font-size: 9px; color: #9ca3af; margin-top: 4px;">🎯 <b>{strikes['dyn_put_sell']} Put Sell</b></div>
</div>
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
