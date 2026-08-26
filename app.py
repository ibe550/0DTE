import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime
import pytz

# 1. Page Configuration
st.set_page_config(
    page_title="SPX 0DTE DEFENDER v12.0",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Eastern Timezone Fix (UTC 시간 문제 해결)
et_tz = pytz.timezone('US/Eastern')
now_et = datetime.now(et_tz)

# 2. Custom CSS (Clean Dark & Compact Buttons)
st.markdown("""
    <style>
    .block-container { padding-top: 1rem; padding-bottom: 1rem; padding-left: 0.5rem; padding-right: 0.5rem; }
    .stApp { background-color: #0b0e14; color: #e1e6ed; }
    
    .card-box {
        background-color: #121721;
        border: 1px solid #1f2937;
        border-radius: 6px;
        padding: 10px;
        margin-bottom: 8px;
        font-size: 13px;
    }
    .status-wait-box {
        background-color: #1e1b0e;
        border: 1px solid #785a00;
        border-radius: 6px;
        padding: 10px;
        color: #fbbf24;
        font-size: 13px;
    }
    .badge-red { background-color: #991b1b; color: #fca5a5; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 11px; }
    .badge-green { background-color: #065f46; color: #6ee7b7; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 11px; }
    
    .bar-container { width: 100%; background-color: #ef4444; height: 6px; border-radius: 3px; overflow: hidden; margin: 6px 0; }
    .bar-fill { height: 100%; background-color: #10b981; }
    
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# Header
st.markdown("### 🛡️ SPX 0DTE DEFENDER v12.0")
st.caption(f"● Market Closed | Data as of {now_et.strftime('%m/%d %H:%M:%S')} ET")

# Ticker Metrics Grid
m1, m2 = st.columns(2)
with m1:
    st.metric(label="SPX INDEX", value="7677.28", delta="+24.42 (+0.32%)")
    st.metric(label="ES FUTURES", value="7672.75", delta="-19.25 (-0.25%)", delta_color="inverse")
with m2:
    st.metric(label="VIX INDEX", value="15.45", delta="+0.32 (+2.12%)", delta_color="inverse")
    st.metric(label="FEAR & GREED", value="59 (Greed)", delta="1w: 55", delta_color="off")

# Cards
st.markdown("""
    <div class="status-wait-box">
        <b>🚨 DECISION SIGNAL: [WAIT] 신호 대기</b><br>
        <span style="font-size: 12px;">일부 데이터가 오래되어 새 진입을 제안하지 않습니다 (STALE)</span><br>
        <hr style="border-color: #785a00; margin: 5px 0;">
        <b>CONFIDENCE:</b> 0% &nbsp;|&nbsp; <b>CREDIT DIRECTION:</b> WAIT
    </div>
""", unsafe_allow_html=True)

st.markdown("""
    <div class="card-box">
        <b>⚡ GEX:</b> <span class="badge-red"> Explosive 폭발적 구간 </span><br>
        • <b>Flip:</b> 7660 &nbsp;|&nbsp; <b>Call Wall:</b> 7670 &nbsp;|&nbsp; <b>Put Wall:</b> 7670<br>
        • <b>Net Delta:</b> +94,588 <span class="badge-green">CALL BIASED</span>
    </div>
""", unsafe_allow_html=True)

st.divider()

# VOLUME + CVD Section
st.markdown("**📊 VOLUME + CVD**")

# 깔끔한 버튼 셀렉터
col_tf, col_sp = st.columns([3, 1])
with col_tf:
    selected_tf = st.radio(
        "Timeframe",
        ["1m", "5m", "15m", "30m", "1H"],
        index=4,
        horizontal=True,
        label_visibility="collapsed"
    )
with col_sp:
    st.markdown("<div style='text-align:right;'><span class='badge-red'>↓ Selling Pressure</span></div>", unsafe_allow_html=True)

# Eastern Time 타임프레임 연산
freq_map = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1H": "1h"}
bar_count_map = {"1m": 30, "5m": 24, "15m": 20, "30m": 16, "1H": 12}

n_bars = bar_count_map[selected_tf]
pd_freq = freq_map[selected_tf]

np.random.seed(42)
dates = pd.date_range(end=now_et, periods=n_bars, freq=pd_freq, tz=et_tz)

buy_vol = np.random.randint(10, 250, n_bars) * 1000000
sell_vol = np.random.randint(10, 280, n_bars) * 1000000
total_vol = buy_vol + sell_vol
cvd = np.cumsum(buy_vol - sell_vol) / 1000000 + 100

colors = ['#10b981' if b > s else '#ef4444' for b, s in zip(buy_vol, sell_vol)]

# Plotly Subplot Chart
fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Bar(x=dates, y=total_vol / 1000000, name="Volume", marker_color=colors), secondary_y=False)
fig.add_trace(go.Scatter(x=dates, y=cvd, name="CVD", line=dict(color='#facc15', width=2)), secondary_y=True)

fig.update_layout(
    template="plotly_dark",
    height=240,
    margin=dict(l=10, r=10, t=10, b=10),
    paper_bgcolor='#0b0e14',
    plot_bgcolor='#121721',
    showlegend=False,
    xaxis=dict(showgrid=False, tickformat="%H:%M"),
    yaxis=dict(showgrid=True, gridcolor='#1f2937', title="Volume"),
    yaxis2=dict(showgrid=False, title="CVD")
)

st.plotly_chart(fig, use_container_width=True)

# Gauge Bar & Flow Signal Card
buy_pct, sell_pct = 44, 56
st.markdown(f"""
    <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: bold;">
        <span style="color: #10b981;">▲ Buy {buy_pct}%</span>
        <span style="color: #ef4444;">▼ Sell {sell_pct}%</span>
    </div>
    <div class="bar-container"><div class="bar-fill" style="width: {buy_pct}%;"></div></div>
""", unsafe_allow_html=True)

st.markdown("""
    <div class="card-box">
        <b>🌊 WEIGHTED FLOW:</b> <span class="badge-green">📈 종합 상승</span><br>
        <span style="color: #fbbf24;">⚠️ <b>Bullish Absorption</b> — 매도 물량을 매수세가 흡수하는 흐름입니다.</span>
    </div>
""", unsafe_allow_html=True)
