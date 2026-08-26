import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import datetime

# Page Configuration
st.set_page_config(
    page_title="SPX 0DTE DEFENDER v12.0",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Dark Theme Custom CSS
st.markdown("""
    <style>
    .main { background-color: #0d1117; color: #c9d1d9; }
    .stMetric { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 10px; }
    .card-box {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 12px;
    }
    .badge-red { background-color: #da3633; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    .badge-green { background-color: #238636; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    .badge-yellow { background-color: #9e6a03; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    .status-wait-box {
        background-color: #261c00;
        border: 1px solid #855d00;
        border-radius: 8px;
        padding: 15px;
        color: #f2cc60;
    }
    </style>
""", unsafe_allow_html=True)

# Top Bar Header
h1, h2 = st.columns([3, 1])
with h1:
    st.markdown("### 🛡️ SPX 0DTE DEFENDER v12.0")
with h2:
    st.markdown("<p style='text-align: right; color: #8b949e; font-size: 13px;'>● Market Closed<br>22:17:47 ET</p>", unsafe_allow_html=True)

# Ticker Metrics Banner
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric(label="SPX INDEX", value="7677.28", delta="+24.42 (+0.32%)")
with m2:
    st.metric(label="VIX INDEX", value="15.45", delta="+0.32 (+2.12%)", delta_color="inverse")
with m3:
    st.metric(label="ES FUTURES", value="7672.75", delta="-19.25 (-0.25%)", delta_color="inverse")
with m4:
    st.metric(label="FEAR & GREED", value="59 (Greed)", delta="1w: 55 | 1m: 41", delta_color="off")

st.divider()

# Decision Signal & Risk Panel
c_left, c_right = st.columns([1, 1])

with c_left:
    st.markdown("#### 🚨 DECISION SIGNAL")
    st.markdown("""
        <div class="status-wait-box">
            <h4 style="margin-0; color: #ffc107;">[WAIT] 신호 대기</h4>
            <p style="font-size: 13px; margin-top: 5px;">신호 대기 - 일부 데이터가 오래되어 새 진입을 제안하지 않습니다.<br><b>STALE as of 22:06:00 ET</b></p>
            <hr style="border-color: #855d00;">
            <p style="font-size: 12px; margin: 0;"><b>CONFIDENCE:</b> 0% &nbsp;|&nbsp; <b>CREDIT DIRECTION:</b> WAIT (Put/Call Credit 대기)</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.write("")
    st.markdown("#### 🕒 0DTE TIME RISK & SESSION LEVELS")
    st.markdown("""
        <div class="card-box">
            <span class="badge-yellow"> 정규장 외 시간 </span> &nbsp; 새로운 0DTE 진입은 피하세요.<br><br>
            • <b>Opening Range (First 15m):</b> 7714 / 7681<br>
            • <b>ES Overnight Range:</b> 7714 / 7670<br>
            • <b>Realized Volatility:</b> 13.4%
        </div>
    """, unsafe_allow_html=True)

with c_right:
    st.markdown("#### ⚡ GEX & GAMMA CONTEXT")
    st.markdown("""
        <div class="card-box">
            <b>Gamma Zone:</b> <span class="badge-red"> Explosive 폭발적 구간 </span><br>
            <i>가격이 Gamma Flip(7660) 위. 딜러들이 추세 방향 헷징 상방 가속 가능성.</i><hr style="border-color: #30363d;">
            • <b>Gamma Flip:</b> 7660<br>
            • <b>Call Wall:</b> 7670 | <b>Put Wall:</b> 7670<br>
            • <b>0DTE Net Option Delta:</b> +94,588.18 <span class="badge-green">CALL BIASED</span>
        </div>
    """, unsafe_allow_html=True)

st.divider()

# SPX Chart & Technical Indicators
st.markdown("#### 📈 SPX 1H Chart & Technical Context")

# Chart Data Generation
dates = pd.date_range(end=datetime.now(), periods=24, freq='h')
np.random.seed(42)
prices = 7650 + np.cumsum(np.random.normal(1, 4, 24))

fig = go.Figure()
fig.add_trace(go.Scatter(x=dates, y=prices, mode='lines+markers', name='SPX Price', line=dict(color='#58a6ff', width=2)))
fig.update_layout(
    template="plotly_dark",
    height=320,
    margin=dict(l=10, r=10, t=10, b=10),
    paper_bgcolor='#0d1117',
    plot_bgcolor='#161b22',
    xaxis=dict(showgrid=True, gridcolor='#30363d'),
    yaxis=dict(showgrid=True, gridcolor='#30363d')
)
st.plotly_chart(fig, use_container_width=True)

# Flow Signals & Upcoming High-Impact Events
f1, f2 = st.columns(2)

with f1:
    st.markdown("#### 🌊 WEIGHTED FLOW SIGNAL")
    st.markdown("""
        <div class="card-box">
            <span class="badge-green"> Bullish Absorption </span><br><br>
            주가는 0.30% 상승했지만 CVD는 4.9% 하락. 매도 물량을 매수세가 흡수하는 흐름으로 추정됩니다.<br><br>
            • <b>Selling Pressure:</b> Sell 56% vs Buy 44%<br>
            • <b>RSI (14):</b> 46.0 (Neutral)
        </div>
    """, unsafe_allow_html=True)

with f2:
    st.markdown("#### 📅 UPCOMING HIGH-IMPACT EVENTS")
    st.markdown("""
        <div class="card-box">
            • <b>Core PCE Price Index m/m:</b> 8.2% (10h 12m)<br>
            • <b>Prelim GDP q/q:</b> 1.5% (10h 12m)<br>
            • <b>Fed Chairman Warsh Speaks:</b> (2d 11h)<br>
            • <b>Prelim Benchmark Payrolls Revision:</b> (2d 11h)
        </div>
    """, unsafe_allow_html=True)
