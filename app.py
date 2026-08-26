import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

# 1. Page Config
st.set_page_config(
    page_title="SPX 0DTE DEFENDER v12.0",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

et_tz = ZoneInfo("America/New_York")
now_et = datetime.now(et_tz)

# 2. Compact & Sleek Mobile Grid CSS
st.markdown("""
    <style>
    .block-container { 
        padding-top: 1rem !important; 
        padding-bottom: 1rem !important; 
        padding-left: 0.5rem !important; 
        padding-right: 0.5rem !important; 
    }
    .stApp { background-color: #0b0e14; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    
    /* Header */
    .header-box { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 1px solid #1e293b; padding-bottom: 6px; }
    .header-title { font-size: 16px; font-weight: 800; color: #ffffff; display: flex; align-items: center; gap: 6px; }
    .v-badge { background-color: #1e1b4b; color: #818cf8; padding: 1px 5px; border-radius: 4px; font-size: 10px; font-weight: bold; }
    .market-status { font-size: 11px; color: #94a3b8; display: flex; align-items: center; gap: 4px; }

    /* Compact Card Grid */
    .mini-card { background-color: #121721; border: 1px solid #1f2937; border-radius: 6px; padding: 8px 10px; margin-bottom: 6px; }
    .mini-card-red { background-color: #160b0e; border: 1px solid #450a0a; border-radius: 6px; padding: 8px 10px; margin-bottom: 6px; }
    .mini-card-yellow { background-color: #18150a; border: 1px solid #785a00; border-radius: 6px; padding: 8px 10px; margin-bottom: 6px; }

    .card-title { font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }
    
    /* Values */
    .val-main { font-size: 20px; font-weight: 800; color: #ffffff; margin: 2px 0; }
    .val-green { font-size: 12px; font-weight: 700; color: #10b981; }
    .val-red { font-size: 12px; font-weight: 700; color: #f43f5e; }
    
    /* Tags & Badges */
    .tag-red { background-color: #450a0a; color: #fca5a5; font-size: 9px; padding: 1px 4px; border-radius: 3px; font-weight: bold; }
    .tag-green { background-color: #064e3b; color: #34d399; font-size: 9px; padding: 1px 4px; border-radius: 3px; font-weight: bold; }
    .tag-dark { background-color: #1e293b; color: #cbd5e1; font-size: 9px; padding: 1px 4px; border-radius: 3px; }

    /* Gauge Bar */
    .bar-container { width: 100%; background-color: #f43f5e; height: 5px; border-radius: 3px; overflow: hidden; margin: 3px 0 6px 0; }
    .bar-fill { height: 100%; background-color: #10b981; }

    /* Radio Tabs */
    div[role="radiogroup"] { display: flex; justify-content: space-between; width: 100%; gap: 3px; margin-bottom: 6px; }
    div[role="radiogroup"] label { background-color: #121721; border: 1px solid #1f2937; border-radius: 4px; padding: 2px 4px !important; margin: 0 !important; flex-grow: 1; text-align: center; font-size: 11px; }
    div[role="radiogroup"] label[data-checked="true"] { background-color: #2563eb !important; border-color: #3b82f6 !important; color: white !important; }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# 3. Header Bar
st.markdown(f"""
    <div class="header-box">
        <div class="header-title">
            <span>🛡️</span> SPX 0DTE <span class="v-badge">v12.0</span>
        </div>
        <div class="market-status">
            <span style="color: #6366f1;">●</span> Closed &nbsp;|&nbsp; 🕒 {now_et.strftime('%H:%M')} ET
        </div>
    </div>
""", unsafe_allow_html=True)

# 4. Breaking News (Compact)
st.markdown("""
    <div class="mini-card-red" style="padding: 6px 10px;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="color: #f87171; font-size: 11px; font-weight: 700;">⚠️ BREAKING</span>
            <span style="font-size: 9px; color: #64748b;">9h ago</span>
        </div>
        <div style="color: #f1f5f9; font-size: 11px; font-weight: 600; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
            Case for BoC rate hike crumbling as trade war ramps up
        </div>
    </div>
""", unsafe_allow_html=True)

# 5. Core Metrics Grid (2 columns x 2 rows - 꽉 찬 정보 구조)
c1, c2 = st.columns(2)

with c1:
    st.markdown("""
        <div class="mini-card">
            <div class="card-title">SPX INDEX</div>
            <div class="val-main">7,677.28</div>
            <div class="val-green">▲ +24.42 (+0.32%)</div>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
        <div class="mini-card">
            <div style="display: flex; justify-content: space-between;">
                <span class="card-title">ES FUTURES</span>
                <span class="tag-dark">ACTIVE</span>
            </div>
            <div class="val-main" style="color: #f43f5e;">7,679.50</div>
            <div class="val-red">▼ -12.50 (-0.16%)</div>
        </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown("""
        <div class="mini-card">
            <div class="card-title">VIX INDEX</div>
            <div class="val-main" style="color: #10b981;">15.45</div>
            <div class="val-red">▲ +0.32 (+2.12%)</div>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
        <div class="mini-card" style="display: flex; align-items: center; justify-content: space-between; padding: 11px 10px;">
            <div>
                <div class="card-title">FEAR & GREED</div>
                <div style="font-size: 14px; font-weight: 800; color: #10b981; margin-top: 2px;">59 (Greed)</div>
                <div style="font-size: 9px; color: #64748b;">1w: 55 | 1m: 41</div>
            </div>
            <div style="width: 34px; height: 34px; border-radius: 50%; border: 3px solid #10b981; border-bottom-color: transparent; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: bold;">59</div>
        </div>
    """, unsafe_allow_html=True)

# 6. GEX & Decision Signal (Compact Row)
st.markdown("""
    <div class="mini-card-yellow">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-size: 11px; font-weight: bold; color: #fbbf24;">🚨 SIGNAL: WAIT (STALE)</span>
            <span class="tag-red">Explosive GEX</span>
        </div>
        <div style="font-size: 10px; color: #cbd5e1; margin-top: 3px;">
            <b>Flip:</b> 7660 | <b>Call Wall:</b> 7670 | <b>Put Wall:</b> 7670 | <b>Net Delta:</b> +94.5k <span class="tag-green">CALL</span>
        </div>
    </div>
""", unsafe_allow_html=True)

# 7. Volume + CVD Chart Section (Compact Height)
st.markdown("<div style='font-size: 11px; font-weight: bold; color: #ffffff; margin-top: 6px; margin-bottom: 2px;'>📊 VOLUME + CVD FLOW</div>", unsafe_allow_html=True)

selected_tf = st.radio(
    "Timeframe",
    ["1m", "5m", "15m", "30m", "1H"],
    index=4,
    horizontal=True,
    label_visibility="collapsed"
)

freq_map = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1H": "60min"}
bar_count_map = {"1m": 16, "5m": 15, "15m": 14, "30m": 12, "1H": 10}

n_bars = bar_count_map[selected_tf]
pd_freq = freq_map[selected_tf]

np.random.seed(42)
dates = pd.date_range(end=now_et, periods=n_bars, freq=pd_freq)

buy_vol = np.random.randint(10, 250, n_bars) * 1000000
sell_vol = np.random.randint(10, 280, n_bars) * 1000000
total_vol = buy_vol + sell_vol
cvd = np.cumsum(buy_vol - sell_vol) / 1000000 + 100

colors = ['#10b981' if b > s else '#f43f5e' for b, s in zip(buy_vol, sell_vol)]

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Bar(x=dates, y=total_vol / 1000000, name="Volume", marker_color=colors), secondary_y=False)
fig.add_trace(go.Scatter(x=dates, y=cvd, name="CVD", line=dict(color='#eab308', width=2)), secondary_y=True)

fig.update_layout(
    template="plotly_dark",
    height=160,
    margin=dict(l=0, r=0, t=2, b=0),
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
    showlegend=False,
    autosize=True,
    xaxis=dict(showgrid=False, tickformat="%H:%M", nticks=4, tickfont=dict(size=9)),
    yaxis=dict(showgrid=True, gridcolor='#1e2938', title=dict(text="Vol", font=dict(size=8)), tickfont=dict(size=8)),
    yaxis2=dict(showgrid=False, title=dict(text="CVD", font=dict(size=8)), tickfont=dict(size=8))
)

st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

# Gauge & Flow Summary
buy_pct, sell_pct = 44, 56
st.markdown(f"""
    <div style="display: flex; justify-content: space-between; font-size: 10px; font-weight: bold; margin-top: -4px;">
        <span style="color: #10b981;">▲ Buy {buy_pct}%</span>
        <span style="color: #f43f5e;">▼ Sell {sell_pct}%</span>
    </div>
    <div class="bar-container"><div class="bar-fill" style="width: {buy_pct}%;"></div></div>
    <div class="mini-card" style="padding: 6px 10px; font-size: 11px;">
        <b>🌊 WEIGHTED FLOW:</b> <span class="tag-green">📈 종합 상승</span> &nbsp;|&nbsp; <span style="color: #fbbf24;">Bullish Absorption</span>
    </div>
""", unsafe_allow_html=True)
