import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Page Configuration
st.set_page_config(
    page_title="SPX 0DTE DEFENDER v12.0",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for Dark UI
st.markdown("""
    <style>
    .stApp { background-color: #0b0e14; color: #e1e6ed; }
    .card-box {
        background-color: #121721;
        border: 1px solid #1f2937;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
    }
    .status-wait-box {
        background-color: #1e1b0e;
        border: 1px solid #785a00;
        border-radius: 8px;
        padding: 16px;
        color: #fbbf24;
    }
    .badge-red { background-color: #991b1b; color: #fca5a5; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    .badge-green { background-color: #065f46; color: #6ee7b7; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    .badge-yellow { background-color: #78350f; color: #fde68a; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    .selling-pressure-btn {
        background-color: #7f1d1d;
        color: #fca5a5;
        border: 1px solid #991b1b;
        padding: 4px 12px;
        border-radius: 6px;
        font-weight: bold;
        float: right;
    }
    /* Custom Segmented Bar */
    .bar-container {
        width: 100%;
        background-color: #ef4444;
        height: 8px;
        border-radius: 4px;
        overflow: hidden;
        margin: 10px 0;
    }
    .bar-fill {
        height: 100%;
        background-color: #10b981;
    }
    </style>
""", unsafe_allow_html=True)

# Top Bar Header
h1, h2 = st.columns([3, 1])
with h1:
    st.markdown("### 🛡️ SPX 0DTE DEFENDER v12.0")
with h2:
    st.markdown("<p style='text-align: right; color: #6b7280; font-size: 13px;'>● Market Closed<br>Data as of 08/25 15:30:00 ET</p>", unsafe_allow_html=True)

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

# Decision Signal & GEX Panel
c_left, c_right = st.columns([1, 1])

with c_left:
    st.markdown("#### 🚨 DECISION SIGNAL")
    st.markdown("""
        <div class="status-wait-box">
            <h4 style="margin:0; color: #fbbf24;">[WAIT] 신호 대기</h4>
            <p style="font-size: 13px; margin-top: 5px;">신호 대기 - 일부 데이터가 오래되어 새 진입을 제안하지 않습니다.<br><b>STALE as of 22:06:00 ET</b></p>
            <hr style="border-color: #785a00;">
            <p style="font-size: 12px; margin: 0;"><b>CONFIDENCE:</b> 0% &nbsp;|&nbsp; <b>CREDIT DIRECTION:</b> WAIT (Put/Call Credit 대기)</p>
        </div>
    """, unsafe_allow_html=True)

with c_right:
    st.markdown("#### ⚡ GEX & GAMMA CONTEXT")
    st.markdown("""
        <div class="card-box">
            <b>Gamma Zone:</b> <span class="badge-red"> Explosive 폭발적 구간 </span><br>
            <i style="font-size: 13px; color: #9ca3af;">가격이 Gamma Flip(7660) 위. 딜러들이 추세 방향 헷징 상방 가속 가능성.</i>
            <hr style="border-color: #1f2937;">
            • <b>Gamma Flip:</b> 7660 &nbsp;|&nbsp; <b>Call Wall:</b> 7670 &nbsp;|&nbsp; <b>Put Wall:</b> 7670<br>
            • <b>0DTE Net Option Delta:</b> +94,588.18 <span class="badge-green">CALL BIASED</span>
        </div>
    """, unsafe_allow_html=True)

st.divider()

# ---------------------------------------------------------
# VOLUME + CVD Section (Interactive Timeframe Selector)
# ---------------------------------------------------------

st.markdown("#### 📊 VOLUME + CVD")

# 1. Timeframe Selection Bar
tf_col1, tf_col2 = st.columns([2, 3])
with tf_col1:
    selected_tf = st.radio(
        "Timeframe",
        ["1m", "5m", "15m", "30m", "1H"],
        index=4,
        horizontal=True,
        label_visibility="collapsed"
    )

with tf_col2:
    st.markdown("<div class='selling-pressure-btn'>↓ Selling Pressure</div>", unsafe_allow_html=True)

# 2. Dynamic Data Generation based on Timeframe
tf_map = {"1m": 60, "5m": 48, "15m": 32, "30m": 24, "1H": 20}
n_bars = tf_map[selected_tf]

np.random.seed(42)
dates = pd.date_range(end=datetime.now(), periods=n_bars, freq=selected_tf.lower())
buy_vol = np.random.randint(10, 250, n_bars) * 1000000
sell_vol = np.random.randint(10, 280, n_bars) * 1000000
total_vol = buy_vol + sell_vol
cvd = np.cumsum(buy_vol - sell_vol) / 1000000 + 400  # CVD Line Data

# Color mapping: Green for Net Buy bar, Red for Net Sell bar
colors = ['#10b981' if b > s else '#ef4444' for b, s in zip(buy_vol, sell_vol)]

# 3. Subplot Chart: Volume Bars + Overlay CVD Line
fig = make_subplots(specs=[[{"secondary_y": True}]])

# Volume Bars
fig.add_trace(
    go.Bar(
        x=dates,
        y=total_vol / 1000000,
        name="Volume",
        marker_color=colors,
        opacity=0.85
    ),
    secondary_y=False
)

# CVD Line (Yellow)
fig.add_trace(
    go.Scatter(
        x=dates,
        y=cvd,
        name="CVD",
        line=dict(color='#facc15', width=2)
    ),
    secondary_y=True
)

fig.update_layout(
    template="plotly_dark",
    height=280,
    margin=dict(l=10, r=10, t=10, b=10),
    paper_bgcolor='#0b0e14',
    plot_bgcolor='#121721',
    showlegend=False,
    xaxis=dict(showgrid=True, gridcolor='#1f2937'),
    yaxis=dict(showgrid=True, gridcolor='#1f2937', title="Volume (M)"),
    yaxis2=dict(showgrid=False, title="CVD")
)

st.plotly_chart(fig, use_container_width=True)

# 4. Buy / Sell Ratio Gauge & Message
buy_pct = 44
sell_pct = 56

st.markdown(f"""
    <div style="display: flex; justify-content: space-between; font-weight: bold; font-size: 14px;">
        <span style="color: #10b981;">▲ Buy {buy_pct}%</span>
        <span style="color: #ef4444;">▼ Sell {sell_pct}%</span>
    </div>
    <div class="bar-container">
        <div class="bar-fill" style="width: {buy_pct}%;"></div>
    </div>
""", unsafe_allow_html=True)

st.info(f"Moderate selling pressure — {sell_pct}% sell vs {buy_pct}% buy volume.")

# 5. Weighted Flow Signal Card
st.markdown("""
    <div class="card-box">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: bold; font-size: 13px; color: #9ca3af;">WEIGHTED FLOW SIGNAL</span>
            <span class="badge-green">📈 종합 상승</span>
        </div>
        <p style="font-size: 14px; margin-bottom: 6px;"><b>현재가가 Gamma Flip 위 — Selling Pressure 가중치 50%↓</b></p>
        <p style="font-size: 13px; color: #fbbf24; margin-bottom: 0;">
            ⚠️ <b>Bullish Absorption</b> — 주가는 0.30% 상승했지만 CVD는 4.9% 하락. 매도 물량을 매수세가 흡수하는 흐름으로 추정됩니다.
        </p>
    </div>
""", unsafe_allow_html=True)
