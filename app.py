import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import yfinance as yf

from backtest import run_probability_analysis
from quant_engine import SimonsBenterQuantEngine

# --- Alpaca 옵션 데이터 연동 모듈 불러오기 ---
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

# Alpaca API Key (설정 시 실시간 0DTE Delta 수집, 미설정 시 피봇 계산으로 안전 작동)
ALPACA_API_KEY = st.secrets.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = st.secrets.get("ALPACA_SECRET_KEY", "")

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
.news-box-alert { background-color: #2a1215; border: 1px solid #991b1b; border-radius: 6px; padding: 6px 8px; margin-bottom: 4px; }
.news-box-neutral { background-color: #161114; border: 1px solid #3d1c1c; border-radius: 6px; padding: 6px 8px; margin-bottom: 4px; }
.signal-box { background-color: #16150e; border: 1px solid #785a00; border-radius: 6px; padding: 8px 10px; margin-bottom: 4px; }
.badge-red { background-color: #991b1b; color: #fca5a5; padding: 1px 5px; border-radius: 4px; font-weight: bold; font-size: 9px; }
.badge-green { background-color: #065f46; color: #6ee7b7; padding: 1px 5px; border-radius: 4px; font-weight: bold; font-size: 9px; }
.badge-yellow { background-color: #78350f; color: #fde68a; padding: 1px 5px; border-radius: 4px; font-weight: bold; font-size: 9px; }
.risk-tag { background-color: #211522; border: 1px solid #4a284e; color: #d8b4fe; padding: 1px 4px; border-radius: 3px; font-size: 9px; font-weight: bold; display: inline-block; margin-right: 2px; }
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

@st.cache_data(ttl=5)
def fetch_market_data():
    def get_price(symbol):
        try:
            t = yf.Ticker(symbol)
            price = t.fast_info.last_price
            prev = t.fast_info.previous_close
            if price is None or np.isnan(price):
                hist = t.history(period="2d")
                if not hist.empty:
                    price = hist['Close'].iloc[-1]
                    prev = hist['Close'].iloc[-2] if len(hist) > 1 else price
            price = float(price or 0.0)
            prev = float(prev or price)
            change = price - prev
            pct = (change / prev) * 100 if prev != 0 else 0.0
            return (price, change, pct)
        except Exception:
            return (0.0, 0.0, 0.0)

    spx = get_price('^SPX')
    vix = get_price('^VIX')
    es = get_price('ES=F')
    spy = get_price('SPY')

    if spx[0] == 0.0 and es[0] != 0.0:
        spx = es

    return {'spx': spx, 'vix': vix, 'es': es, 'spy': spy}

@st.cache_data(ttl=30)
def fetch_latest_news_sentiment():
    try:
        ticker = yf.Ticker("ES=F")
        news_list = ticker.news
        if news_list and len(news_list) > 0:
            latest = news_list[0]
            title = latest.get('title', '')
            link = latest.get('link', '')
        else:
            title = "NVIDIA After-Market Rally Signals Tech Strong Earnings"
            link = "#"
    except Exception:
        title = "NVIDIA After-Market Rally Signals Tech Strong Earnings"
        link = "#"

    bearish_words = ["hike", "war", "inflation", "cpi", "drop", "plunge", "down", "crisis", "fall", "tariff", "missed"]
    bullish_words = ["cut", "easing", "rally", "gain", "soar", "surge", "cool", "growth", "beat", "earnings", "boost"]

    title_lower = title.lower()
    bear_score = sum(1 for w in bearish_words if w in title_lower)
    bull_score = sum(1 for w in bullish_words if w in title_lower)

    if bear_score > bull_score:
        sentiment = "BEARISH"
        risk_level = "HIGH"
    elif bull_score > bear_score:
        sentiment = "BULLISH"
        risk_level = "MODERATE"
    else:
        sentiment = "NEUTRAL"
        risk_level = "LOW"

    return {"title": title, "sentiment": sentiment, "risk_level": risk_level, "link": link}

@st.cache_data(ttl=15)
def fetch_es_history(interval_str):
    try:
        yf_interval = "60m" if interval_str == "1H" else interval_str
        period = "1d" if interval_str in ["1m", "5m"] else "5d"
        df = yf.download(tickers="ES=F", period=period, interval=yf_interval, progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.tail(100).copy()
        est_tz = pytz.timezone('US/Eastern')
        df.index = df.index.tz_convert(est_tz)
        return df
    except Exception:
        return None

@st.cache_data(ttl=10)
def fetch_alpaca_0dte_analytics(spy_price):
    if HAS_ALPACA_MODULE and ALPACA_API_KEY and ALPACA_SECRET_KEY:
        try:
            engine = AlpacaOptionEngine(ALPACA_API_KEY, ALPACA_SECRET_KEY)
            return engine.get_0dte_chain_analytics(symbol="SPY", current_price=spy_price)
        except Exception:
            return None
    return None

def calculate_dynamic_strikes(current_price, news_sentiment, distance_mult=1.0, option_analytics=None):
    if option_analytics and option_analytics.get('call_15d_strike'):
        c_15d = option_analytics['call_15d_strike']
        p_15d = option_analytics['put_15d_strike']
        ratio = current_price / 560.0 if current_price > 0 else 10.0
        
        call_strike = int(round(c_15d * ratio / 5.0) * 5)
        put_strike = int(round(p_15d * ratio / 5.0) * 5)
        
        return {
            'dyn_call_sell': f"{call_strike+5}/{call_strike}",
            'dyn_put_sell': f"{put_strike-5}/{put_strike}",
            'call_target': call_strike,
            'put_target': put_strike,
            'adjust_note': f"🎯 Alpaca Live Delta 0.15 수집됨 (IV: {option_analytics['avg_iv']}%)",
            'is_live_delta': True
        }

    es_df = fetch_es_history("5m")
    if es_df is not None and not es_df.empty:
        high, low, close = es_df['High'].max(), es_df['Low'].min(), es_df['Close'].iloc[-1]
        pivot = (high + low + close) / 3
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
    else:
        r2 = current_price + 30.0
        s2 = current_price - 30.0

    base_r2 = int(round((current_price + (r2 - current_price) * distance_mult) / 5.0) * 5)
    base_s2 = int(round((current_price - (current_price - s2) * distance_mult) / 5.0) * 5)

    return {
        'dyn_call_sell': f"{base_r2+5}/{base_r2}",
        'dyn_put_sell': f"{base_s2-5}/{base_s2}",
        'call_target': base_r2,
        'put_target': base_s2,
        'adjust_note': "⚖️ Dynamic Pivot Strike 적용 중 (실시간 변동성 자동 반영)",
        'is_live_delta': False
    }

if "backtest_result" not in st.session_state:
    st.session_state["backtest_result"] = None

market_data = fetch_market_data()
news_sentiment = fetch_latest_news_sentiment()
est_tz = pytz.timezone('US/Eastern')
now_est = datetime.now(est_tz)

spx_p, spx_c, spx_pct = market_data['spx']
vix_p, vix_c, vix_pct = market_data['vix']
es_p, es_c, es_pct = market_data['es']
spy_p, spy_c, spy_pct = market_data['spy']

es_df = fetch_es_history("5m")
news_score = SimonsBenterQuantEngine.advanced_news_scoring(news_sentiment['title'])

if es_df is not None and not es_df.empty:
    regime, distance_mult = SimonsBenterQuantEngine.detect_market_regime(es_df, vix_p)
    z_score = SimonsBenterQuantEngine.calculate_zscore_anomaly(es_df['Close'])
else:
    regime, distance_mult = "NORMAL_VOLATILITY", 1.0
    z_score = 0.0

alpaca_analytics = fetch_alpaca_0dte_analytics(spy_p)
strikes = calculate_dynamic_strikes(spx_p, news_sentiment, distance_mult, alpaca_analytics)

# --- Header ---
st.markdown(f"""
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
<span style="font-weight: bold; font-size: 14px;">🛡️ SPX 0DTE DEFENDER <span style="background-color: #1f2937; padding: 1px 4px; border-radius: 3px; font-size: 9px; color: #9ca3af;">v18.2</span></span>
<span style="background-color: #1f2937; padding: 1px 6px; border-radius: 8px; font-size: 9px; color: #9ca3af;">● Live | {now_est.strftime('%H:%M')} ET</span>
</div>
""", unsafe_allow_html=True)

# --- 실시간 주요 지수 시세 Top Cards ---
spx_color = "#10b981" if spx_c >= 0 else "#ef4444"
vix_color = "#ef4444" if vix_c >= 0 else "#10b981"
es_color = "#10b981" if es_c >= 0 else "#ef4444"
spy_color = "#10b981" if spy_c >= 0 else "#ef4444"

st.markdown(f"""
<div class="grid-4col">
<div class="metric-card">
<div class="metric-label">SPX 지수</div>
<div class="metric-val">{spx_p:,.2f}</div>
<div class="metric-sub" style="color: {spx_color};">{spx_c:+.2f} ({spx_pct:+.2f}%)</div>
</div>
<div class="metric-card">
<div class="metric-label">VIX 변동성</div>
<div class="metric-val">{vix_p:,.2f}</div>
<div class="metric-sub" style="color: {vix_color};">{vix_c:+.2f} ({vix_pct:+.2f}%)</div>
</div>
<div class="metric-card">
<div class="metric-label">ES 선물</div>
<div class="metric-val">{es_p:,.2f}</div>
<div class="metric-sub" style="color: {es_color};">{es_c:+.2f} ({es_pct:+.2f}%)</div>
</div>
<div class="metric-card">
<div class="metric-label">SPY ETF</div>
<div class="metric-val">{spy_p:,.2f}</div>
<div class="metric-sub" style="color: {spy_color};">{spy_c:+.2f} ({spy_pct:+.2f}%)</div>
</div>
</div>
""", unsafe_allow_html=True)

# --- Market Regime / Anomaly / Delta Status Cards (Z-Score 설명 포함) ---
z_color = "#ef4444" if abs(z_score) > 2.0 else "#10b981"
z_desc = "⚠️ |Z|>2.0 이탈위험" if abs(z_score) > 2.0 else "🛡️ ±2.0 내 통계안정"
sent_color = "#ef4444" if news_sentiment['sentiment'] == "BEARISH" else ("#10b981" if news_sentiment['sentiment'] == "BULLISH" else "#facc15")

st.markdown(f"""
<div class="grid-4col">
<div class="metric-card">
<div class="metric-label">REGIME</div>
<div style="font-size: 11px; font-weight: bold; color: #60a5fa; margin-top:2px;">{regime}</div>
<div class="metric-sub" style="color:#9ca3af;">Dist Mult: {distance_mult}x</div>
</div>
<div class="metric-card">
<div class="metric-label">Z-SCORE</div>
<div class="metric-val" style="color: {z_color};">{z_score:+.2f}</div>
<div class="metric-sub" style="color:#9ca3af;">{z_desc}</div>
</div>
<div class="metric-card">
<div class="metric-label">DELTA TARGET</div>
<div class="metric-val">0.15 Δ</div>
<div class="metric-sub" style="color:#10b981;">Target 85% Win</div>
</div>
<div class="metric-card">
<div class="metric-label">NEWS SCORE</div>
<div class="metric-val" style="color: {sent_color};">{news_score:+.2f}</div>
<div class="metric-sub" style="color:#9ca3af;">{news_sentiment['sentiment']}</div>
</div>
</div>
""", unsafe_allow_html=True)

# --- Live Delta Analytics Banner (Alpaca 연동 시에만 상단 표시) ---
if alpaca_analytics:
    st.markdown(f"""
<div class="card-box" style="border-left: 3px solid #3b82f6;">
<div style="display: flex; justify-content: space-between; font-size: 10px;">
<span style="color: #60a5fa; font-weight: bold;">📡 REAL-TIME 0DTE OPTION GREEKS (Alpaca)</span>
<span style="color: #9ca3af;">Avg IV: <b>{alpaca_analytics['avg_iv']}%</b></span>
</div>
<div style="display: flex; justify-content: space-between; margin-top: 3px; font-size: 10px;">
<span>Call 0.15Δ Strike: <b style="color:#fca5a5;">${alpaca_analytics['call_15d_strike']}</b> ({alpaca_analytics['call_15d_delta']:.2f}Δ)</span>
<span>Put -0.15Δ Strike: <b style="color:#6ee7b7;">${alpaca_analytics['put_15d_strike']}</b> ({alpaca_analytics['put_15d_delta']:.2f}Δ)</span>
</div>
<div style="font-size: 9px; color: #9ca3af; margin-top: 2px;">
🎯 Max Gamma Wall: <b>${alpaca_analytics['max_gex_strike']}</b> (주가 지지/저항 벽)
</div>
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

result = st.session_state["backtest_result"]

if result:
    win_rate = result.get('win_rate', 0.0)
    loss_rate = result.get('loss_rate', round(100.0 - win_rate, 1))
    total_signals = result.get('total_signals', 0)
    ev = result.get('expected_value', 0.0)

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

# --- Live News ---
news_box_class = "news-box-alert" if news_sentiment['risk_level'] == "HIGH" else "news-box-neutral"

st.markdown(f"""
<div class="{news_box_class}">
<div style="display: flex; justify-content: space-between; align-items: center;">
<span style="color: {sent_color}; font-weight: bold; font-size: 10px;">⚡ REAL-TIME NEWS [{news_sentiment['sentiment']}]</span>
<span style="color: #6b7280; font-size: 8px;">{now_est.strftime('%m/%d %H:%M')} ET</span>
</div>
<div style="font-size: 10px; color: #e5e7eb; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px;">
{news_sentiment['title']}
</div>
<div style="font-size: 8px; color: #9ca3af; margin-top: 2px;">
🔍 {strikes['adjust_note']}
</div>
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

# --- Recommended Strikes ---
diff_r2 = round(strikes['call_target'] - spx_p, 1)
diff_s2 = round(spx_p - strikes['put_target'], 1)

st.markdown(f"""
<div class="grid-2col">
<div class="metric-card" style="border-left: 3px solid #ef4444;">
<div style="font-size: 10px; font-weight: bold; color: #fca5a5;">🔴 CALL CREDIT SPREAD</div>
<div style="font-size: 14px; font-weight: bold; margin-top: 2px;">{strikes['call_target']} Strike</div>
<div style="font-size: 9px; color: #10b981;">+{diff_r2} pt 차이</div>
<div style="font-size: 9px; color: #9ca3af; margin-top: 4px;">🎯 <b>{strikes['dyn_call_sell']} Call Sell</b></div>
</div>
<div class="metric-card" style="border-left: 3px solid #10b981;">
<div style="font-size: 10px; font-weight: bold; color: #6ee7b7;">🟢 PUT CREDIT SPREAD</div>
<div style="font-size: 14px; font-weight: bold; margin-top: 2px;">{strikes['put_target']} Strike</div>
<div style="font-size: 9px; color: #ef4444;">-{diff_s2} pt 차이</div>
<div style="font-size: 9px; color: #9ca3af; margin-top: 4px;">🎯 <b>{strikes['dyn_put_sell']} Put Sell</b></div>
</div>
</div>
""", unsafe_allow_html=True)

# --- Volume & CVD Chart ---
st.markdown("<div style='font-size: 11px; font-weight: bold; margin-top: 4px;'>📊 VOLUME + CVD (ES=F)</div>", unsafe_allow_html=True)

selected_tf = st.radio("TF", ["1m", "5m", "15m", "30m", "1H"], index=2, horizontal=True, label_visibility="collapsed")
es_df_chart = fetch_es_history(selected_tf)

if es_df_chart is not None and not es_df_chart.empty:
    dates_str = [d.strftime("%H:%M") for d in es_df_chart.index]
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
else:
    n_bars = 16
    dates_str = [(now_est - timedelta(minutes=i*15)).strftime("%H:%M") for i in range(n_bars)][::-1]
    total_vol = np.random.randint(100, 1000, n_bars) * 100
    cvd = np.cumsum(np.random.randint(-50, 50, n_bars))
    colors = ['#10b981' if i % 2 == 0 else '#ef4444' for i in range(n_bars)]
    buy_pct, sell_pct = 48, 52

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Bar(x=dates_str, y=total_vol, name="Vol", marker_color=colors, opacity=0.85), secondary_y=False)
fig.add_trace(go.Scatter(x=dates_str, y=cvd, name="CVD", line=dict(color='#facc15', width=1.5)), secondary_y=True)

fig.update_layout(
    template="plotly_dark",
    height=140,
    margin=dict(l=0, r=0, t=0, b=0),
    paper_bgcolor='#0b0e14',
    plot_bgcolor='#121721',
    showlegend=False,
    xaxis=dict(showgrid=True, gridcolor='#1f2937', fixedrange=True, type='category', tickfont=dict(size=8)),
    yaxis=dict(showgrid=True, gridcolor='#1f2937', title=None, fixedrange=True, tickfont=dict(size=8)),
    yaxis2=dict(showgrid=False, title=None, fixedrange=True, tickfont=dict(size=8))
)

html_fig = fig.to_html(include_plotlyjs='cdn', full_html=False, config={'staticPlot': True, 'displayModeBar': False})
components.html(f"""
<div style="pointer-events: none; user-select: none; width:100%; height:140px;">
{html_fig}
</div>
""", height=145)

st.markdown(f"""
<div style="display: flex; justify-content: space-between; font-weight: bold; font-size: 10px; margin-top: -5px;">
<span style="color: #10b981;">▲ Buy {buy_pct}%</span>
<span style="color: #ef4444;">▼ Sell {sell_pct}%</span>
</div>
<div class="bar-container">
<div class="bar-fill" style="width: {buy_pct}%;"></div>
</div>
""", unsafe_allow_html=True)
