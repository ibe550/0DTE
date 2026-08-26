import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime

# Page Configuration for Mobile Focus
st.set_page_config(
    page_title="SPX 0DTE DEFENDER",
    page_icon="🛡️",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Mobile-Optimized Custom CSS
st.markdown("""
    <style>
    .stApp { background-color: #0b0e14; color: #e1e6ed; max-width: 480px; margin: 0 auto; }
    .card-box {
        background-color: #121721;
        border: 1px solid #1f2937;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 10px;
    }
    .news-box {
        background-color: #161114;
        border: 1px solid #3d1c1c;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 10px;
    }
    .signal-box {
        background-color: #16150e;
        border: 1px solid #785a00;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 10px;
    }
    .credit-alert-box {
        background-color: #1a1510;
        border: 1px solid #523b11;
        border-radius: 6px;
        padding: 10px;
        margin-top: 8px;
        margin-bottom: 8px;
    }
    .badge-red { background-color: #991b1b; color: #fca5a5; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 11px; }
    .badge-green { background-color: #065f46; color: #6ee7b7; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 11px; }
    .badge-yellow { background-color: #78350f; color: #fde68a; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 11px; }
    .risk-tag {
        background-color: #211522;
        border: 1px solid #4a284e;
        color: #d8b4fe;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: bold;
        display: inline-block;
        margin-right: 3px;
        margin-bottom: 3px;
    }
    .bar-container {
        width: 100%;
        background-color: #ef4444;
        height: 8px;
        border-radius: 4px;
        overflow: hidden;
        margin: 6px 0;
    }
    .bar-fill { height: 100%; background-color: #10b981; }
    </style>
""", unsafe_allow_html=True)

# 1. Top Bar Header
st.markdown("""
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
    <span style="font-weight: bold; font-size: 16px;">🛡️ SPX 0DTE <span style="background-color: #1f2937; padding: 2px 5px; border-radius: 4px; font-size: 11px; color: #9ca3af;">v12.0</span></span>
    <span style="background-color: #1f2937; padding: 3px 8px; border-radius: 12px; font-size: 11px; color: #9ca3af;">● Closed | 🕒 22:56 ET</span>
</div>
""", unsafe_allow_html=True)

# 2. Breaking News & Risks
st.markdown("""
<div class="news-box">
    <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
        <span style="color: #ef4444; font-weight: bold; font-size: 12px;">⚠️ BREAKING NEWS</span>
        <span style="color: #6b7280; font-size: 10px;">08/25 22:51 ET</span>
    </div>
    <p style="font-size: 12px; margin: 0; color: #e5e7eb;">Case for BoC rate hike crumbling as trade war ramps up</p>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="card-box" style="padding: 8px 12px;">
    <span style="color: #f43f5e; font-weight: bold; font-size: 11px;">⚡ RISKS:</span>
    <span class="risk-tag">INFLATION</span><span class="risk-tag">FED</span><span class="risk-tag">FOMC</span><span class="risk-tag">WAR</span><span class="risk-tag">CPI</span>
</div>
""", unsafe_allow_html=True)

# 3. DECISION SIGNAL (Cleaned HTML)
st.markdown("""
<div class="signal-box">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 12px; font-weight: bold; color: #9ca3af;">🚨 DECISION SIGNAL &nbsp;<span style="font-size: 10px; color: #6b7280;">Rule-based</span></span>
        <span class="badge-yellow" style="font-size: 12px; padding: 3px 10px;">⏱️ WAIT</span>
    </div>
    <div style="margin-top: 8px;">
        <span style="font-size: 20px; font-weight: bold; color: #fbbf24;">대기</span>
        <span style="float: right; font-size: 11px; color: #9ca3af;">CONFIDENCE <b style="font-size: 16px; color: #fbbf24;">0%</b></span>
    </div>
    <p style="font-size: 12px; color: #d1d5db; margin: 4px 0;">신호 대기 – 일부 데이터가 오래되어 새 진입을 제안하지 않습니다.</p>
    <div style="font-size: 11px; color: #f59e0b; margin-bottom: 6px;">
        <span class="badge-red">STALE</span> as of 08/25 22:51:18 ET
    </div>
    <div class="credit-alert-box">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-size: 11px; color: #fbbf24; font-weight: bold;">🔔 CREDIT DIRECTION ALERT</span>
            <span class="badge-yellow">WAIT</span>
        </div>
        <div style="font-size: 13px; font-weight: bold; color: #fde68a; margin-top: 2px;">Put / Call Credit 대기</div>
        <div style="font-size: 11px; color: #9ca3af; margin-top: 2px;">신뢰할 수 있는 방향 신호가 없어 put·call credit을 추천하지 않습니다.</div>
    </div>
    <div style="font-size: 10px; color: #6b7280; font-family: monospace; margin-top: 6px;">
        WHY NO DRAFT: <span style="color: #fbbf24;">stale data</span>
    </div>
</div>
""", unsafe_allow_html=True)

# 4. 0DTE DECISION PANEL
st.markdown("""
<div class="card-box" style="border: 1px solid #1e3a8a;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
        <span style="font-size: 12px; font-weight: bold; color: #93c5fd;">⚡ 0DTE DECISION PANEL</span>
        <span style="font-size: 10px; color: #6b7280;">08/25 15:30 ET</span>
    </div>
    <div style="background-color: #0d1e18; border: 1px solid #065f46; border-radius: 6px; padding: 8px; margin-bottom: 8px;">
        <div style="display: flex; justify-content: space-between; font-size: 11px;">
            <span style="color: #6ee7b7; font-weight: bold;">0DTE TIME RISK</span>
            <span style="color: #6ee7b7;">LOW • Market Closed</span>
        </div>
        <div style="font-size: 11px; color: #d1d5db; margin-top: 2px;">정규장 외 시간 – 새로운 0DTE 진입은 피하세요.</div>
    </div>
    <div style="display: flex; gap: 6px;">
        <div style="background-color: #1a2234; padding: 8px; border-radius: 6px; flex: 1;">
            <div style="font-size: 10px; color: #9ca3af;">Expected Move used</div>
            <div style="font-size: 12px; font-weight: bold; color: #f3f4f6;">±3.0pt</div>
            <div style="font-size: 11px; color: #6b7280; margin-top: 4px;">RTH session unavailable</div>
        </div>
        <div style="background-color: #1a2234; padding: 8px; border-radius: 6px; flex: 1;">
            <div style="font-size: 10px; color: #9ca3af;">Intraday range / EM</div>
            <div style="font-size: 12px; font-weight: bold; color: #f3f4f6;">—</div>
            <div style="font-size: 11px; color: #6b7280; margin-top: 4px;">Regular-session unavailable</div>
        </div>
    </div>
    <div style="margin-top: 8px; font-size: 11px; color: #9ca3af;">
        <b>OPENING RANGE</b> <span style="float: right; color: #fbbf24; font-size: 10px;">Starts 09:30 ET</span>
        <div style="color: #6b7280; font-size: 10px;">Regular-session opening high and low</div>
    </div>
</div>
""", unsafe_allow_html=True)

# 5. Ticker Metrics
m1, m2 = st.columns(2)
with m1:
    st.markdown("""
    <div class="card-box">
        <div style="font-size: 10px; color: #9ca3af; font-weight: bold;">SPX INDEX</div>
        <div style="font-size: 18px; font-weight: bold; color: #10b981; margin: 2px 0;">7677.28</div>
        <div style="font-size: 11px; color: #10b981;">+24.42 (+0.32%)</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("""
    <div class="card-box">
        <div style="font-size: 10px; color: #9ca3af; font-weight: bold;">ES FUTURES</div>
        <div style="font-size: 18px; font-weight: bold; color: #ef4444; margin: 2px 0;">7685.75</div>
        <div style="font-size: 11px; color: #ef4444;">-6.25 (-0.08%)</div>
    </div>
    """, unsafe_allow_html=True)
with m2:
    st.markdown("""
    <div class="card-box">
        <div style="font-size: 10px; color: #9ca3af; font-weight: bold;">VIX INDEX</div>
        <div style="font-size: 18px; font-weight: bold; color: #10b981; margin: 2px 0;">15.45</div>
        <div style="font-size: 11px; color: #10b981;">+0.32 (+2.12%)</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("""
    <div class="card-box">
        <div style="font-size: 10px; color: #9ca3af; font-weight: bold;">FEAR & GREED</div>
        <div style="font-size: 16px; font-weight: bold; color: #10b981; margin: 2px 0;">59 (Greed)</div>
        <div style="font-size: 10px; color: #9ca3af;">1w: 55 | 1m: 41</div>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# 6. Volume + CVD Section with Timeframe Selector
st.markdown("#### 📊 VOLUME + CVD")

tf_col1, tf_col2 = st.columns([2, 3])
with tf_col1:
    selected_tf = st.radio(
        "TF",
        ["1m", "5m", "15m", "30m", "1H"],
        index=4,
        horizontal=True,
        label_visibility="collapsed"
    )
with tf_col2:
    st.markdown("<div style='background-color: #7f1d1d; color: #fca5a5; padding: 4px 8px; border-radius: 6px; font-weight: bold; font-size: 11px; text-align: center;'>↓ Selling Pressure</div>", unsafe_allow_html=True)

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
    height=240,
    margin=dict(l=5, r=5, t=5, b=5),
    paper_bgcolor='#0b0e14',
    plot_bgcolor='#121721',
    showlegend=False,
    xaxis=dict(showgrid=True, gridcolor='#1f2937'),
    yaxis=dict(showgrid=True, gridcolor='#1f2937', title=None),
    yaxis2=dict(showgrid=False, title=None)
)
st.plotly_chart(fig, use_container_width=True)

# Buy/Sell Ratio & Flow Signal
buy_pct, sell_pct = 44, 56
st.markdown(f"""
<div style="display: flex; justify-content: space-between; font-weight: bold; font-size: 12px;">
    <span style="color: #10b981;">▲ Buy {buy_pct}%</span>
    <span style="color: #ef4444;">▼ Sell {sell_pct}%</span>
</div>
<div class="bar-container">
    <div class="bar-fill" style="width: {buy_pct}%;"></div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="card-box" style="margin-top: 10px;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
        <span style="font-weight: bold; font-size: 11px; color: #9ca3af;">WEIGHTED FLOW SIGNAL</span>
        <span class="badge-green">📈 종합 상승</span>
    </div>
    <p style="font-size: 12px; margin-bottom: 4px;"><b>현재가가 Gamma Flip 위 — Selling Pressure 가중치 50%↓</b></p>
    <p style="font-size: 11px; color: #fbbf24; margin: 0;">
        ⚠️ <b>Bullish Absorption</b> — 주가는 0.30% 상승했지만 CVD는 4.9% 하락. 매도 물량을 매수세가 흡수하는 흐름입니다.
    </p>
</div>
""", unsafe_allow_html=True)
