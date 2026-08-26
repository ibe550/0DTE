import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

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
    .credit-alert-box {
        background-color: #1a1510;
        border: 1px solid #523b11;
        border-radius: 6px;
        padding: 8px;
        margin-top: 6px;
        margin-bottom: 6px;
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

# 1. Top Bar Header
st.markdown("""
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
    <span style="font-weight: bold; font-size: 15px;">🛡️ SPX 0DTE <span style="background-color: #1f2937; padding: 2px 4px; border-radius: 4px; font-size: 10px; color: #9ca3af;">v12.0</span></span>
    <span style="background-color: #1f2937; padding: 2px 6px; border-radius: 10px; font-size: 10px; color: #9ca3af;">● Closed | 🕒 23:16 ET</span>
</div>
""", unsafe_allow_html=True)

# 2. Breaking News & Risks
st.markdown("""
<div class="news-box">
    <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
        <span style="color: #ef4444; font-weight: bold; font-size: 11px;">⚠️ BREAKING NEWS</span>
        <span style="color: #6b7280; font-size: 9px;">08/25 22:51 ET</span>
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

# 3. Ticker Metrics Grid
st.markdown("""
<div class="grid-2col">
    <div class="card-box" style="margin-bottom:0;">
        <div style="font-size: 10px; color: #9ca3af; font-weight: bold;">SPX INDEX</div>
        <div style="font-size: 9px; color: #6b7280;">08/25 17:43 ET</div>
        <div style="font-size: 18px; font-weight: bold; color: #10b981; margin: 2px 0;">7677.28</div>
        <div style="font-size: 11px; color: #10b981;">+24.42 (+0.32%)</div>
    </div>
    <div class="card-box" style="margin-bottom:0;">
        <div style="font-size: 10px; color: #9ca3af; font-weight: bold;">VIX INDEX</div>
        <div style="font-size: 9px; color: #6b7280;">08/25 16:14 ET</div>
        <div style="font-size: 18px; font-weight: bold; color: #10b981; margin: 2px 0;">15.45</div>
        <div style="font-size: 11px; color: #10b981;">+0.32 (+2.12%)</div>
    </div>
</div>
<div class="grid-2col">
    <div class="card-box" style="margin-bottom:0;">
        <div style="font-size: 10px; color: #9ca3af; font-weight: bold;">ES FUTURES <span style="background-color: #1e293b; color: #93c5fd; padding: 1px 3px; border-radius: 3px; font-size: 8px;">ACTIVE</span></div>
        <div style="font-size: 18px; font-weight: bold; color: #ef4444; margin: 2px 0;">7685.75</div>
        <div style="font-size: 11px; color: #ef4444;">-6.25 (-0.08%)</div>
        <div style="font-size: 9px; color: #6b7280;">E-mini S&P 500</div>
    </div>
    <div class="card-box" style="margin-bottom:0;">
        <div style="font-size: 10px; color: #9ca3af; font-weight: bold;">FEAR & GREED</div>
        <div style="font-size: 9px; color: #6b7280;">08/25 19:59 ET</div>
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

# 4. DECISION SIGNAL
st.markdown("""
<div class="signal-box">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 11px; font-weight: bold; color: #9ca3af;">🚨 DECISION SIGNAL</span>
        <span class="badge-yellow">⏱️ WAIT</span>
    </div>
    <div style="margin-top: 4px;">
        <span style="font-size: 18px; font-weight: bold; color: #fbbf24;">대기</span>
        <span style="float: right; font-size: 10px; color: #9ca3af;">CONFIDENCE <b style="font-size: 14px; color: #fbbf24;">0%</b></span>
    </div>
    <p style="font-size: 11px; color: #d1d5db; margin: 2px 0;">일부 데이터가 오래되어 새 진입을 제안하지 않습니다.</p>
    <div style="font-size: 10px; color: #f59e0b; margin-bottom: 4px;">
        <span class="badge-red">STALE</span> as of 08/25 22:51:18 ET
    </div>
    <div class="credit-alert-box">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-size: 10px; color: #fbbf24; font-weight: bold;">🔔 CREDIT DIRECTION ALERT</span>
            <span class="badge-yellow">WAIT</span>
        </div>
        <div style="font-size: 12px; font-weight: bold; color: #fde68a; margin-top: 1px;">Put / Call Credit 대기</div>
        <div style="font-size: 10px; color: #9ca3af;">신뢰할 수 있는 방향 신호가 없어 추천하지 않습니다.</div>
    </div>
    <div style="font-size: 9px; color: #6b7280; font-family: monospace;">
        WHY NO DRAFT: <span style="color: #fbbf24;">stale data</span>
    </div>
</div>
""", unsafe_allow_html=True)

# 5. 0DTE DECISION PANEL
st.markdown("""
<div class="card-box" style="border: 1px solid #1e3a8a;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
        <span style="font-size: 11px; font-weight: bold; color: #93c5fd;">⚡ 0DTE DECISION PANEL</span>
        <span style="font-size: 9px; color: #6b7280;">08/25 15:30 ET</span>
    </div>
    <div style="background-color: #0d1e18; border: 1px solid #065f46; border-radius: 6px; padding: 6px; margin-bottom: 6px;">
        <div style="display: flex; justify-content: space-between; font-size: 10px;">
            <span style="color: #6ee7b7; font-weight: bold;">0DTE TIME RISK</span>
            <span style="color: #6ee7b7;">LOW • Closed</span>
        </div>
        <div style="font-size: 10px; color: #d1d5db; margin-top: 1px;">정규장 외 시간 – 새로운 진입은 피하세요.</div>
    </div>
    <div class="grid-2col" style="margin-bottom: 4px;">
        <div style="background-color: #1a2234; padding: 6px; border-radius: 6px;">
            <div style="font-size: 9px; color: #9ca3af;">Expected Move</div>
            <div style="font-size: 11px; font-weight: bold; color: #f3f4f6;">±3.0pt</div>
            <div style="font-size: 9px; color: #6b7280;">RTH unavailable</div>
        </div>
        <div style="background-color: #1a2234; padding: 6px; border-radius: 6px;">
            <div style="font-size: 9px; color: #9ca3af;">Intraday range / EM</div>
            <div style="font-size: 11px; font-weight: bold; color: #f3f4f6;">—</div>
            <div style="font-size: 9px; color: #6b7280;">No data</div>
        </div>
    </div>
    <div style="font-size: 10px; color: #9ca3af;">
        <b>OPENING RANGE</b> <span style="float: right; color: #fbbf24; font-size: 9px;">Starts 09:30 ET</span>
    </div>
</div>
""", unsafe_allow_html=True)

st.divider()

# 6. Volume + CVD Section (Dynamic TF Sensitivity)
st.markdown("<div style='font-size: 13px; font-weight: bold; margin-bottom: 4px;'>📊 VOLUME + CVD</div>", unsafe_allow_html=True)

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
    st.markdown("<div style='background-color: #7f1d1d; color: #fca5a5; padding: 4px; border-radius: 6px; font-weight: bold; font-size: 10px; text-align: center;'>↓ Selling Pressure</div>", unsafe_allow_html=True)

# Timeframe mapping (minutes per step & unique seed for dynamic variation)
tf_config = {
    "1m": (1, 101, 15),
    "5m": (5, 202, 35),
    "15m": (15, 303, 80),
    "30m": (30, 404, 150),
    "1H": (60, 505, 300)
}

step_min, seed_val, vol_multiplier = tf_config.get(selected_tf, (60, 505, 300))
n_bars = 16

# US/Eastern Time Handling
est_tz = pytz.timezone('US/Eastern')
now_est = datetime.now(est_tz)

dates = [now_est - timedelta(minutes=i * step_min) for i in range(n_bars)][::-1]
dates_str = [d.strftime("%H:%M") for d in dates]

# Dynamic Data Generation according to Timeframe
np.random.seed(seed_val)
buy_vol = np.random.randint(10, 250, n_bars) * vol_multiplier * 10000
sell_vol = np.random.randint(10, 280, n_bars) * vol_multiplier * 10000
total_vol = buy_vol + sell_vol
cvd = np.cumsum(buy_vol - sell_vol) / 1000000 + (seed_val % 100)
colors = ['#10b981' if b > s else '#ef4444' for b, s in zip(buy_vol, sell_vol)]

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Bar(x=dates_str, y=total_vol / 1000000, name="Volume", marker_color=colors, opacity=0.85), secondary_y=False)
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

# Render Non-interactive Static HTML Component
html_fig = fig.to_html(include_plotlyjs='cdn', full_html=False, config={'staticPlot': True, 'displayModeBar': False})
components.html(f"""
    <div style="pointer-events: none; user-select: none; width:100%; height:180px;">
        {html_fig}
    </div>
""", height=185)

# Buy/Sell Ratio & Flow Signal
buy_pct = int((np.sum(buy_vol) / np.sum(total_vol)) * 100)
sell_pct = 100 - buy_pct

st.markdown(f"""
<div style="display: flex; justify-content: space-between; font-weight: bold; font-size: 11px;">
    <span style="color: #10b981;">▲ Buy {buy_pct}%</span>
    <span style="color: #ef4444;">▼ Sell {sell_pct}%</span>
</div>
<div class="bar-container">
    <div class="bar-fill" style="width: {buy_pct}%;"></div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="card-box" style="margin-top: 6px;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
        <span style="font-weight: bold; font-size: 10px; color: #9ca3af;">WEIGHTED FLOW SIGNAL</span>
        <span class="badge-green">📈 종합 상승</span>
    </div>
    <p style="font-size: 11px; margin-bottom: 2px;"><b>현재가가 Gamma Flip 위 — Selling Pressure 가중치 50%↓</b></p>
    <p style="font-size: 10px; color: #fbbf24; margin: 0;">
        ⚠️ <b>Bullish Absorption</b> — 주가는 상승했으나 CVD는 하락. 매도세 흡수 중.
    </p>
</div>
""", unsafe_allow_html=True)
