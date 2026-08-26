import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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

# Custom CSS for Exact Match UI
st.markdown("""
    <style>
    .stApp { background-color: #0b0e14; color: #e1e6ed; }
    .card-box {
        background-color: #121721;
        border: 1px solid #1f2937;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 10px;
    }
    .news-box {
        background-color: #161114;
        border: 1px solid #3d1c1c;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 10px;
    }
    .status-wait-box {
        background-color: #1e1b0e;
        border: 1px solid #785a00;
        border-radius: 8px;
        padding: 14px;
        color: #fbbf24;
        margin-bottom: 10px;
    }
    .badge-red { background-color: #991b1b; color: #fca5a5; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; }
    .badge-green { background-color: #065f46; color: #6ee7b7; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; }
    .risk-tag {
        background-color: #211522;
        border: 1px solid #4a284e;
        color: #d8b4fe;
        padding: 3px 10px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: bold;
        display: inline-block;
        margin-right: 4px;
        margin-bottom: 4px;
    }
    .selling-pressure-btn {
        background-color: #7f1d1d;
        color: #fca5a5;
        border: 1px solid #991b1b;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: bold;
        font-size: 12px;
        float: right;
    }
    .bar-container {
        width: 100%;
        background-color: #ef4444;
        height: 8px;
        border-radius: 4px;
        overflow: hidden;
        margin: 8px 0;
    }
    .bar-fill { height: 100%; background-color: #10b981; }
    </style>
""", unsafe_allow_html=True)

# 1. Top Bar Header
h1, h2 = st.columns([3, 1])
with h1:
    st.markdown("### 🛡️ SPX 0DTE DEFENDER <span style='font-size: 14px; background-color: #1f2937; padding: 2px 6px; border-radius: 4px; color: #9ca3af;'>v12.0</span>", unsafe_allow_html=True)
with h2:
    st.markdown("<div style='text-align: right;'><span style='background-color: #1f2937; padding: 3px 8px; border-radius: 12px; font-size: 12px; color: #9ca3af;'>● Market Closed</span> &nbsp; <span style='color: #6b7280; font-size: 12px;'>🕒 22:56:27 ET</span></div>", unsafe_allow_html=True)

# 2. Breaking News Box
st.markdown("""
    <div class="news-box">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="color: #ef4444; font-weight: bold; font-size: 13px;">⚠️ BREAKING NEWS</span>
            <span style="color: #6b7280; font-size: 11px;">Google News Data as of 08/25 22:51:18 ET</span>
        </div>
        <p style="font-size: 13px; margin: 0; color: #e5e7eb;">
            Case for BoC rate hike crumbling as trade war ramps up — <a href="#" style="color: #60a5fa; text-decoration: none;">mpamag.com</a>
            <span style="float: right; color: #9ca3af; font-size: 12px;">9h ago</span>
        </p>
    </div>
""", unsafe_allow_html=True)

# 3. News Risks Bar
st.markdown("""
    <div class="card-box" style="padding: 10px 14px;">
        <span style="color: #f43f5e; font-weight: bold; font-size: 12px; margin-right: 8px;">⚡ NEWS RISKS:</span>
        <span class="risk-tag">INFLATION</span>
        <span class="risk-tag">FED</span>
        <span class="risk-tag">FOMC</span>
        <span class="risk-tag">WAR</span>
        <span class="risk-tag">BEAR</span>
        <span class="risk-tag">CPI</span>
        <span style="float: right; color: #6b7280; font-size: 11px; margin-top: 4px;">Latest item 08/25 22:51:18 ET</span>
    </div>
""", unsafe_allow_html=True)

# 4. Ticker Metrics Grid (2x2 for clean mobile view)
col1, col2 = st.columns(2)
with col1:
    st.markdown("""
        <div class="card-box">
            <div style="font-size: 11px; color: #9ca3af; font-weight: bold;">SPX INDEX</div>
            <div style="font-size: 11px; color: #6b7280; margin-bottom: 4px;">Data as of 08/25 17:43:00 ET</div>
            <div style="font-size: 22px; font-weight: bold; color: #10b981;">7677.28</div>
            <div style="font-size: 12px; color: #10b981;">+24.42 (+0.32%)</div>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
        <div class="card-box">
            <div style="font-size: 11px; color: #9ca3af; font-weight: bold;">ES FUTURES &nbsp; <span style="background-color: #1e293b; color: #93c5fd; padding: 1px 5px; border-radius: 4px; font-size: 10px;">ACTIVE</span></div>
            <div style="font-size: 22px; font-weight: bold; color: #ef4444; margin-top: 4px;">7685.75</div>
            <div style="font-size: 12px; color: #ef4444;">-6.25 (-0.08%)</div>
            <div style="font-size: 11px; color: #6b7280; margin-top: 2px;">E-mini S&P 500</div>
            <div style="font-size: 10px; color: #4b5563;">Data as of 08/25 22:46:25 ET</div>
        </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
        <div class="card-box">
            <div style="font-size: 11px; color: #9ca3af; font-weight: bold;">VIX</div>
            <div style="font-size: 11px; color: #6b7280; margin-bottom: 4px;">Data as of 08/25 16:14:00 ET</div>
            <div style="font-size: 22px; font-weight: bold; color: #10b981;">15.45</div>
            <div style="font-size: 12px; color: #10b981;">+0.32 (+2.12%)</div>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
        <div class="card-box">
            <div style="font-size: 11px; color: #9ca3af; font-weight: bold;">FEAR & GREED</div>
            <div style="font-size: 11px; color: #6b7280; margin-bottom: 4px;">Data as of 08/25 19:59:53 ET</div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <div style="font-size: 18px; font-weight: bold; color: #10b981;">Greed</div>
                    <div style="font-size: 11px; color: #9ca3af;">1w ago: 55 | 1m ago: 41</div>
                </div>
                <div style="font-size: 18px; font-weight: bold; color: #10b981; background: #064e3b; padding: 8px 12px; border-radius: 50%;">59</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

st.divider()

# 5. Decision Signal & GEX Panel
c_left, c_right = st.columns([1, 1])

with c_left:
    st.markdown("#### 🚨 DECISION SIGNAL")
    st.markdown("""
        <div class="status-wait-box">
            <h4 style="margin:0; color: #fbbf24; font-size: 15px;">[WAIT] 신호 대기</h4>
            <p style="font-size: 12px; margin-top: 4px;">일부 데이터가 오래되어 새 진입을 제안하지 않습니다.<br><b>STALE as of 22:06:00 ET</b></p>
            <hr style="border-color: #785a00; margin: 8px 0;">
            <p style="font-size: 11px; margin: 0;"><b>CONFIDENCE:</b> 0% &nbsp;|&nbsp; <b>CREDIT DIRECTION:</b> WAIT</p>
        </div>
    """, unsafe_allow_html=True)

with c_right:
    st.markdown("#### ⚡ GEX & GAMMA CONTEXT")
    st.markdown("""
        <div class="card-box">
            <b>Gamma Zone:</b> <span class="badge-red">Explosive 구간</span><br>
            <i style="font-size: 12px; color: #9ca3af;">가격이 Gamma Flip(7660) 위. 딜러 헷징 상방 가속 가능성.</i>
            <hr style="border-color: #1f2937; margin: 8px 0;">
            <div style="font-size: 12px;">• <b>Gamma Flip:</b> 7660 &nbsp;|&nbsp; <b>Call/Put Wall:</b> 7670</div>
            <div style="font-size: 12px; margin-top: 4px;">• <b>Net Option Delta:</b> +94,588 <span class="badge-green">CALL</span></div>
        </div>
    """, unsafe_allow_html=True)

st.divider()

# 6. Volume + CVD Section with Timeframe Selector
st.markdown("#### 📊 VOLUME + CVD")

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

# Dynamic Chart Data Generation
tf_map = {"1m": 60, "5m": 48, "15m": 32, "30m": 24, "1H": 20}
n_bars = tf_map[selected_tf]

np.random.seed(42)
dates = pd.date_range(end=datetime.now(), periods=n_bars, freq=selected_tf.lower())
buy_vol = np.random.randint(10, 250, n_bars) * 1000000
sell_vol = np.random.randint(10, 280, n_bars) * 1000000
total_vol = buy_vol + sell_vol
cvd = np.cumsum(buy_vol - sell_vol) / 1000000 + 400
colors = ['#10b981' if b > s else '#ef4444' for b, s in zip(buy_vol, sell_vol)]

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Bar(x=dates, y=total_vol / 1000000, name="Volume", marker_color=colors, opacity=0.85), secondary_y=False)
fig.add_trace(go.Scatter(x=dates, y=cvd, name="CVD", line=dict(color='#facc15', width=2)), secondary_y=True)

fig.update_layout(
    template="plotly_dark",
    height=260,
    margin=dict(l=10, r=10, t=10, b=10),
    paper_bgcolor='#0b0e14',
    plot_bgcolor='#121721',
    showlegend=False,
    xaxis=dict(showgrid=True, gridcolor='#1f2937'),
    yaxis=dict(showgrid=True, gridcolor='#1f2937', title="Volume (M)"),
    yaxis2=dict(showgrid=False, title="CVD")
)
st.plotly_chart(fig, use_container_width=True)

# Buy/Sell Ratio & Flow Signal
buy_pct, sell_pct = 44, 56
st.markdown(f"""
    <div style="display: flex; justify-content: space-between; font-weight: bold; font-size: 13px;">
        <span style="color: #10b981;">▲ Buy {buy_pct}%</span>
        <span style="color: #ef4444;">▼ Sell {sell_pct}%</span>
    </div>
    <div class="bar-container">
        <div class="bar-fill" style="width: {buy_pct}%;"></div>
    </div>
""", unsafe_allow_html=True)

st.info(f"Moderate selling pressure — {sell_pct}% sell vs {buy_pct}% buy volume.")

st.markdown("""
    <div class="card-box">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-weight: bold; font-size: 12px; color: #9ca3af;">WEIGHTED FLOW SIGNAL</span>
            <span class="badge-green">📈 종합 상승</span>
        </div>
        <p style="font-size: 13px; margin-bottom: 4px;"><b>현재가가 Gamma Flip 위 — Selling Pressure 가중치 50%↓</b></p>
        <p style="font-size: 12px; color: #fbbf24; margin: 0;">
            ⚠️ <b>Bullish Absorption</b> — 주가는 0.30% 상승했지만 CVD는 4.9% 하락. 매도 물량을 매수세가 흡수하는 흐름으로 추정됩니다.
        </p>
    </div>
""", unsafe_allow_html=True)
