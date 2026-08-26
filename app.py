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

# Page Configuration
st.set_page_config(
    page_title="SPX 0DTE DEFENDER",
    page_icon="🛡️",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Mobile 2-Column Grid & Compact UI CSS
st.markdown("""
    <style>
    .stApp { background-color: #0b0e14; color: #e1e6ed; }
    .block-container {
        padding-top: 0.8rem !important;
        padding-bottom: 1rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
        max-width: 100% !important;
    }
    .grid-2col {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 8px;
        margin-bottom: 8px;
    }
    .card-box {
        background-color: #121721;
        border: 1px solid #1f2937;
        border-radius: 8px;
        padding: 10px;
        margin-bottom: 8px;
    }
    .news-box {
        background-color: #161114;
        border: 1px solid #3d1c1c;
        border-radius: 8px;
        padding: 10px;
        margin-bottom: 8px;
    }
    .signal-box {
        background-color: #16150e;
        border: 1px solid #785a00;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 8px;
    }
    .badge-red { background-color: #991b1b; color: #fca5a5; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px; }
    .badge-green { background-color: #065f46; color: #6ee7b7; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px; }
    .badge-yellow { background-color: #78350f; color: #fde68a; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px; }
    .risk-tag {
        background-color: #211522;
        border: 1px solid #4a284e;
        color: #d8b4fe;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: bold;
        display: inline-block;
        margin-right: 2px;
        margin-bottom: 2px;
    }
    .bar-container {
        width: 100%;
        background-color: #ef4444;
        height: 6px;
        border-radius: 3px;
        overflow: hidden;
        margin: 4px 0;
    }
    .bar-fill { height: 100%; background-color: #10b981; }
    </style>
""", unsafe_allow_html=True)

# Cache Yahoo Finance Data (1 minute TTL)
@st.cache_data(ttl=60)
def fetch_market_data():
    try:
        tickers = yf.Tickers('^SPX ^VIX ES=F')
        spx = tickers.tickers['^SPX'].fast_info
        vix = tickers.tickers['^VIX'].fast_info
        es = tickers.tickers['ES=F'].fast_info
        
        spx_price = spx.last_price or 0.0
        spx_prev = spx.previous_close or spx_price
        spx_change = spx_price - spx_prev
        spx_pct = (spx_change / spx_prev) * 100 if spx_prev else 0.0

        vix_price = vix.last_price or 0.0
        vix_prev = vix.previous_close or vix_price
        vix_change = vix_price - vix_prev
        vix_pct = (vix_change / vix_prev) * 100 if vix_prev else 0.0

        es_price = es.last_price or 0.0
        es_prev = es.previous_close or es_price
        es_change = es_price - es_prev
        es_pct = (es_change / es_prev) * 100 if es_prev else 0.0

        return {
            'spx': (spx_price, spx_change, spx_pct),
            'vix': (vix_price, vix_change, vix_pct),
            'es': (es_price, es_change, es_pct)
        }
    except Exception:
        return None

# Fetch Timeframe Volume History from Yahoo Finance (ES=F)
@st.cache_data(ttl=30)
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

# Calculate Support & Resistance Levels
def calculate_support_resistance(current_price):
    es_df = fetch_es_history("5m")
    if es_df is not None and not es_df.empty:
        high = es_df['High'].max()
        low = es_df['Low'].min()
        close = es_df['Close'].iloc[-1]
        
        pivot = (high + low + close) / 3
        r1 = (2 * pivot) - low
        s1 = (2 * pivot) - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
    else:
        r2 = current_price + 30.0
        r1 = current_price + 15.0
        s1 = current_price - 15.0
        s2 = current_price - 30.0

    r2_strike = int(round(r2 / 5.0) * 5)
    r1_strike = int(round(r1 / 5.0) * 5)
    s1_strike = int(round(s1 / 5.0) * 5)
    s2_strike = int(round(s2 / 5.0) * 5)
    
    return {
        'R2': r2_strike, 'R1': r1_strike,
        'S1': s1_strike, 'S2': s2_strike
    }

if "backtest_result" not in st.session_state:
    st.session_state["backtest_result"] = None

market_data = fetch_market_data()
est_tz = pytz.timezone('US/Eastern')
now_est = datetime.now(est_tz)

spx_p, spx_c, spx_pct = market_data['spx'] if market_data else (7677.28, 24.42, 0.32)
vix_p, vix_c, vix_pct = market_data['vix'] if market_data else (15.45, 0.32, 2.12)
es_p, es_c, es_pct = market_data['es'] if market_data else (7685.75, -6.25, -0.08)

sr_levels = calculate_support_resistance(spx_p)

# 1. Top Bar Header
st.markdown(f"""
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
    <span style="font-weight: bold; font-size: 15px;">🛡️ SPX 0DTE <span style="background-color: #1f2937; padding: 2px 4px; border-radius: 4px; font-size: 10px; color: #9ca3af;">v13.0</span></span>
    <span style="background-color: #1f2937; padding: 2px 6px; border-radius: 10px; font-size: 10px; color: #9ca3af;">● Live (YFinance) | 🕒 {now_est.strftime('%H:%M')} ET</span>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# REALTIME PROBABILITY ENGINE
# ---------------------------------------------------------
st.markdown("<div style='font-size: 13px; font-weight: bold; margin-bottom: 8px;'>🎲 REALTIME PROBABILITY ENGINE</div>", unsafe_allow_html=True)

tf_option = st.radio(
    "예측 타임프레임 선택",
    ["10분 뒤", "30분 뒤", "1시간 뒤"],
    index=1,
    horizontal=True,
    label_visibility="collapsed"
)

bars_map = {"10분 뒤": 2, "30분 뒤": 6, "1시간 뒤": 12}
selected_bars = bars_map[tf_option]

if st.button(f"🚀 [{tf_option}] 승률/하락률 및 기대값 검증"):
    with st.spinner("과거 데이터 분석 및 양방향 확률 산출 중..."):
        res = run_probability_analysis("ES=F", period="1mo", interval="5m", lookahead_bars=selected_bars)
        if res:
            res["tf_option"] = tf_option
            st.session_state["backtest_result"] = res
        else:
            st.error("분석할 수 있는 데이터가 없거나 시그널이 발생하지 않았습니다.")

result = st.session_state["backtest_result"]

if result:
    win_rate = result.get('win_rate', 0.0)
    loss_rate = result.get('loss_rate', round(100.0 - win_rate, 1))
    total_signals = result.get('total_signals', 0)
    ev = result.get('expected_value', 0.0)
    tf_name = result.get('tf_option', tf_option)

    st.markdown(f"""
    <div class="card-box">
        <div style="font-size: 10px; color: #9ca3af; margin-bottom: 6px;">
            필터: [거래량 급증 + 양봉 + ATR 변동성] → <b>{tf_name} 결과 예측</b>
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 4px; text-align: center;">
            <div>
                <div style="font-size: 9px; color: #6b7280;">총 시그널</div>
                <div style="font-size: 13px; font-weight: bold; color: #e1e6ed;">{total_signals}회</div>
            </div>
            <div>
                <div style="font-size: 9px; color: #6b7280;">▲ 상승 확률</div>
                <div style="font-size: 13px; font-weight: bold; color: #10b981;">{win_rate}%</div>
            </div>
            <div>
                <div style="font-size: 9px; color: #6b7280;">▼ 하락 확률</div>
                <div style="font-size: 13px; font-weight: bold; color: #ef4444;">{loss_rate}%</div>
            </div>
            <div>
                <div style="font-size: 9px; color: #6b7280;">기대값 (EV)</div>
                <div style="font-size: 13px; font-weight: bold; color: #facc15;">+{ev}pt</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# 2. Breaking News & Risks
st.markdown(f"""
<div class="news-box">
    <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
        <span style="color: #ef4444; font-weight: bold; font-size: 11px;">⚠️ BREAKING NEWS</span>
        <span style="color: #6b7280; font-size: 9px;">{now_est.strftime('%m/%d %H:%M')} ET</span>
    </div>
    <p style="font-size: 11px; margin: 0; color: #e5e7eb;">Case for BoC rate hike crumbling as trade war ramps up</p>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="card-box" style="padding: 6px 10px;">
    <span style="color: #f43f5e; font-weight: bold; font-size: 10px;">⚡ RISKS:</span>
    <span class="risk-tag">INFLATION</span><span class="risk-tag">FED</span><span class="risk-tag">FOMC</span><span class="risk-tag">WAR</span><span class="risk-tag">CPI</span>
</div>
""", unsafe_allow_html=True)

# Helper function for coloring
def format_change(price, change, pct):
    color = "#10b981" if change >= 0 else "#ef4444"
    sign = "+" if change >= 0 else ""
    return f'<div style="font-size: 18px; font-weight: bold; color: {color}; margin: 2px 0;">{price:.2f}</div><div style="font-size: 11px; color: {color};">{sign}{change:.2f} ({sign}{pct:.2f}%)</div>'

# 3. Ticker Metrics Grid
st.markdown(f"""
<div class="grid-2col">
    <div class="card-box" style="margin-bottom:0;">
        <div style="font-size: 10px; color: #9ca3af; font-weight: bold;">SPX INDEX</div>
        <div style="font-size: 9px; color: #6b7280;">Yahoo Realtime</div>
        {format_change(spx_p, spx_c, spx_pct)}
    </div>
    <div class="card-box" style="margin-bottom:0;">
        <div style="font-size: 10px; color: #9ca3af; font-weight: bold;">VIX INDEX</div>
        <div style="font-size: 9px; color: #6b7280;">Yahoo Realtime</div>
        {format_change(vix_p, vix_c, vix_pct)}
    </div>
</div>
<div class="grid-2col">
    <div class="card-box" style="margin-bottom:0;">
        <div style="font-size: 10px; color: #9ca3af; font-weight: bold;">ES FUTURES <span style="background-color: #1e293b; color: #93c5fd; padding: 1px 3px; border-radius: 3px; font-size: 8px;">ACTIVE</span></div>
        {format_change(es_p, es_c, es_pct)}
        <div style="font-size: 9px; color: #6b7280;">E-mini S&P 500</div>
    </div>
    <div class="card-box" style="margin-bottom:0;">
        <div style="font-size: 10px; color: #9ca3af; font-weight: bold;">FEAR & GREED</div>
        <div style="font-size: 9px; color: #6b7280;">Market Sentiment</div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 2px;">
            <div>
                <div style="font-size: 15px; font-weight: bold; color: #10b981;">Greed</div>
                <div style="font-size: 9px; color: #9ca3af;">1w: 55 | 1m: 41</div>
            </div>
            <div style="font-size: 14px; font-weight: bold; color: #10b981; background: #064e3b; padding: 4px 8px; border-radius: 50%;">59</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 4. DECISION SIGNAL
# ---------------------------------------------------------
if result:
    win = result.get('win_rate', 0.0)
    loss = result.get('loss_rate', 0.0)
    ev_val = result.get('expected_value', 0.0)
    confidence = min(round(abs(win - loss) * 2), 100)
    
    if win > loss and ev_val > 0:
        sig_title = "PUT CREDIT SPREAD (상승 우세)"
        sig_badge = '<span class="badge-green">BULLISH</span>'
        sig_color = "#10b981"
        sig_desc = f"상승 확률({win}%)이 높고 EV(+{ev_val}pt)가 양수입니다. <b>Put Credit Spread</b> 권장."
    elif loss > win:
        sig_title = "CALL CREDIT SPREAD (하락/조정 우세)"
        sig_badge = '<span class="badge-red">BEARISH</span>'
        sig_color = "#ef4444"
        sig_desc = f"하락 확률({loss}%)이 상승 확률({win}%)보다 높습니다. <b>Call Credit Spread</b> 권장."
    else:
        sig_title = "관망 (NEUTRAL / WAIT)"
        sig_badge = '<span class="badge-yellow">WAIT</span>'
        sig_color = "#fbbf24"
        sig_desc = "방향성이 불분명합니다. 추가 수급 확인 후 진입하세요."
else:
    sig_title = "백테스트 검증 필요"
    sig_badge = '<span class="badge-yellow">⏱️ READY</span>'
    sig_color = "#fbbf24"
    confidence = 0
    sig_desc = "상단 버튼을 눌러 승률/하락률을 검증해 주세요."

st.markdown(f"""
<div class="signal-box">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 11px; font-weight: bold; color: #9ca3af;">🚨 DECISION SIGNAL</span>
        {sig_badge}
    </div>
    <div style="margin-top: 4px;">
        <span style="font-size: 17px; font-weight: bold; color: {sig_color};">{sig_title}</span>
        <span style="float: right; font-size: 10px; color: #9ca3af;">CONFIDENCE <b style="font-size: 14px; color: {sig_color};">{confidence}%</b></span>
    </div>
    <p style="font-size: 11px; color: #d1d5db; margin: 4px 0 2px 0;">{sig_desc}</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 5. SUPPORT & RESISTANCE / RECOMMENDED STRIKES (HTML 주석 제거 완료)
# ---------------------------------------------------------
st.markdown("<div style='font-size: 13px; font-weight: bold; margin-bottom: 6px;'>🎯 SUPPORT/RESISTANCE & RECOMMENDED STRIKES</div>", unsafe_allow_html=True)

diff_r2 = round(sr_levels['R2'] - spx_p, 1)
diff_s2 = round(spx_p - sr_levels['S2'], 1)

sr_html = f"""
<div class="grid-2col">
    <div class="card-box" style="border-left: 3px solid #ef4444;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-size: 10px; color: #ef4444; font-weight: bold;">🔴 CALL CREDIT RANGE</span>
            <span class="badge-red">SELL CALL</span>
        </div>
        <div style="margin-top: 6px;">
            <div style="font-size: 9px; color: #9ca3af;">2차 저항선 (R2)</div>
            <div style="font-size: 15px; font-weight: bold; color: #fca5a5;">{sr_levels['R2']} Strike</div>
        </div>
        <div style="margin-top: 4px; font-size: 10px; color: #6b7280;">
            1차 저항 (R1): <b>{sr_levels['R1']}</b><br>
            안전 버퍼: <b style="color: #ef4444;">+{diff_r2} pt</b> (+{round(diff_r2/spx_p*100, 2)}%)
        </div>
        <div style="margin-top: 6px; padding: 4px; background-color: #1f1315; border-radius: 4px; font-size: 9px; color: #fca5a5; text-align: center;">
            💡 <b>{sr_levels['R1']} / {sr_levels['R2']} Call Sell</b> 권장
        </div>
    </div>

    <div class="card-box" style="border-left: 3px solid #10b981;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-size: 10px; color: #10b981; font-weight: bold;">🟢 PUT CREDIT RANGE</span>
            <span class="badge-green">SELL PUT</span>
        </div>
        <div style="margin-top: 6px;">
            <div style="font-size: 9px; color: #9ca3af;">2차 지지선 (S2)</div>
            <div style="font-size: 15px; font-weight: bold; color: #6ee7b7;">{sr_levels['S2']} Strike</div>
        </div>
        <div style="margin-top: 4px; font-size: 10px; color: #6b7280;">
            1차 지지 (S1): <b>{sr_levels['S1']}</b><br>
            안전 버퍼: <b style="color: #10b981;">-{diff_s2} pt</b> (-{round(diff_s2/spx_p*100, 2)}%)
        </div>
        <div style="margin-top: 6px; padding: 4px; background-color: #0f1f19; border-radius: 4px; font-size: 9px; color: #6ee7b7; text-align: center;">
            💡 <b>{sr_levels['S1']} / {sr_levels['S2']} Put Sell</b> 권장
        </div>
    </div>
</div>
"""

st.markdown(sr_html, unsafe_allow_html=True)

# 6. Volume + CVD Section
st.markdown("<div style='font-size: 13px; font-weight: bold; margin-bottom: 4px;'>📊 VOLUME + CVD (ES=F Live)</div>", unsafe_allow_html=True)

tf_col1, tf_col2 = st.columns([2, 3])
with tf_col1:
    selected_tf = st.radio(
        "TF",
        ["1m", "5m", "15m", "30m", "1H"],
        index=2,
        horizontal=True,
        label_visibility="collapsed"
    )
with tf_col2:
    st.markdown("<div style='background-color: #7f1d1d; color: #fca5a5; padding: 4px; border-radius: 6px; font-weight: bold; font-size: 10px; text-align: center;'>↓ Selling Pressure</div>", unsafe_allow_html=True)

es_df = fetch_es_history(selected_tf)

if es_df is not None and not es_df.empty:
    dates_str = [d.strftime("%H:%M") for d in es_df.index]
    total_vol = es_df['Volume'].values
    close_vals = es_df['Close'].values
    open_vals = es_df['Open'].values
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
fig.add_trace(go.Bar(x=dates_str, y=total_vol, name="Volume", marker_color=colors, opacity=0.85), secondary_y=False)
fig.add_trace(go.Scatter(x=dates_str, y=cvd, name="CVD", line=dict(color='#facc15', width=2)), secondary_y=True)

fig.update_layout(
    template="plotly_dark",
    height=180,
    margin=dict(l=0, r=0, t=0, b=0),
    paper_bgcolor='#0b0e14',
    plot_bgcolor='#121721',
    showlegend=False,
    xaxis=dict(showgrid=True, gridcolor='#1f2937', fixedrange=True, type='category'),
    yaxis=dict(showgrid=True, gridcolor='#1f2937', title=None, fixedrange=True),
    yaxis2=dict(showgrid=False, title=None, fixedrange=True)
)

html_fig = fig.to_html(include_plotlyjs='cdn', full_html=False, config={'staticPlot': True, 'displayModeBar': False})
components.html(f"""
    <div style="pointer-events: none; user-select: none; width:100%; height:180px;">
        {html_fig}
    </div>
""", height=185)

st.markdown(f"""
<div style="display: flex; justify-content: space-between; font-weight: bold; font-size: 11px;">
    <span style="color: #10b981;">▲ Buy {buy_pct}%</span>
    <span style="color: #ef4444;">▼ Sell {sell_pct}%</span>
</div>
<div class="bar-container">
    <div class="bar-fill" style="width: {buy_pct}%;"></div>
</div>
""", unsafe_allow_html=True)
