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

# 2. Modern UI CSS (Mobile-Optimized)
st.markdown("""
    <style>
    .block-container { 
        padding-top: 1.5rem !important; 
        padding-bottom: 1.5rem !important; 
        padding-left: 0.6rem !important; 
        padding-right: 0.6rem !important; 
    }
    .stApp { background-color: #080a0f; color: #94a3b8; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    
    .header-box { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .header-title { font-size: 18px; font-weight: 800; color: #ffffff; display: flex; align-items: center; gap: 8px; }
    .v-badge { background-color: #1e1b4b; color: #818cf8; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; }
    .market-status { background-color: #171923; border: 1px solid #2d3748; color: #a0aec0; padding: 3px 8px; border-radius: 12px; font-size: 11px; display: flex; align-items: center; gap: 6px; }

    .dash-card { background-color: #0f131c; border: 1px solid #1e2638; border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; }
    .dash-card-red { background-color: #12090d; border: 1px solid #450a0a; border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; }
    .status-wait-box { background-color: #1e1b0e; border: 1px solid #785a00; border-radius: 8px; padding: 12px 14px; color: #fbbf24; margin-bottom: 10px; font-size: 12px; line-height: 1.5; }

    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
    .card-title { font-size: 12px; font-weight: 700; color: #cbd5e1; }
    .card-time { font-size: 10px; color: #64748b; }

    .val-large-green { font-size: 26px; font-weight: 800; color: #10b981; margin: 4px 0 2px 0; }
    .val-large-red { font-size: 26px; font-weight: 800; color: #f43f5e; margin: 4px 0 2px 0; }
    .val-sub-green { font-size: 12px; font-weight: 600; color: #10b981; }
    .val-sub-red { font-size: 12px; font-weight: 600; color: #f43f5e; }
    
    .badge-active { background-color: #1e1b4b; color: #818cf8; font-size: 10px; padding: 1px 5px; border-radius: 3px; font-weight: bold; }
    .tag-red { background-color: #450a0a; color: #fca5a5; border: 1px solid #7f1d1d; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
    .tag-green { background-color: #064e3b; color: #34d399; border: 1px solid #065f46; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
    
    .bar-container { width: 100%; background-color: #ef4444; height: 6px; border-radius: 3px; overflow: hidden; margin: 4px 0 8px 0; }
    .bar-fill { height: 100%; background-color: #10b981; }

    div[role="radiogroup"] { display: flex; justify-content: space-between; width: 100%; gap: 4px; margin-bottom: 8px; }
    div[role="radiogroup"] label { background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; padding: 4px 6px !important; margin: 0 !important; flex-grow: 1; text-align: center; }
    div[role="radiogroup"] label[data-checked="true"] { background-color: #3b82f6 !important; border-color: #60a5fa !important; }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# 3. Header & Dashboard Metrics
st.markdown(f"""
    <div class="header-box">
        <div class="header-title">
            <span style="color: #6366f1;">🛡️</span> SPX 0DTE DEFENDER <span class="v-badge">v12.0</span>
        </div>
        <div class="market-status">
            <span style="color: #6366f1;">●</span> Closed &nbsp; 🕒 {now_et.strftime('%H:%M')}
        </div>
    </div>
""", unsafe_allow_html=True)

st.markdown("""
    <div class="dash-card-red">
        <div class="card-header">
            <span class="card-title" style="color: #f87171;">⚠️ BREAKING NEWS</span>
            <span class="card-time"><span style="color: #ef4444;">Google News</span> 08/25 22:01 ET</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
            <span style="color: #f1f5f9; font-size: 13px; font-weight: 600;">
                Case for BoC rate hike crumbling as trade war ramps up
            </span>
            <span style="font-size: 11px; color: #64748b; white-space: nowrap; margin-left: 10px;">9h ago</span>
        </div>
    </div>
""", unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    st.markdown("""
        <div class="dash-card">
            <div class="card-title">SPX INDEX</div>
            <div class="card-time">Data as of 08/25 17:43:00 ET</div>
            <div class="val-large-green">7677.28</div>
            <div class="val-sub-green">+24.42 (+0.32%)</div>
        </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown("""
        <div class="dash-card">
            <div class="card-header">
                <span class="card-title">ES FUTURES</span>
                <span class="badge-active">ACTIVE</span>
            </div>
            <div class="val-large-red">7679.50</div>
            <div class="val-sub-red">-12.50 (-0.16%)</div>
        </div>
    """, unsafe_allow_html=True)

# 4. Signals & GEX
st.markdown("""
    <div class="status-wait-box">
        <b>🚨 DECISION SIGNAL: [WAIT] 신호 대기</b><br>
        <span style="color: #d4d4d8;">일부 데이터가 오래되어 새 진입을 제안하지 않습니다 (STALE)</span>
        <hr style="border-color: #785a00; margin: 6px 0;">
        <b>CONFIDENCE:</b> 0% &nbsp;|&nbsp; <b>DIRECTION:</b> WAIT
    </div>
""", unsafe_allow_html=True)

st.markdown("""
    <div class="dash-card">
        <b>⚡ GEX:</b> <span class="tag-red"> Explosive 폭발적 구간 </span><br>
        <div style="margin-top: 4px; color: #cbd5e1; font-size: 12px;">
            • <b>Flip:</b> 7660 &nbsp;|&nbsp; <b>Call Wall:</b> 7670 &nbsp;|&nbsp; <b>Put Wall:</b> 7670<br>
            • <b>Net Delta:</b> +94,588 <span class="tag-green">CALL BIASED</span>
        </div>
    </div>
""", unsafe_allow_html=True)

# 5. Volume + CVD Chart Section (Fixed timezone argument conflict)
st.markdown("<div style='margin-top: 15px; margin-bottom: 5px; font-weight: bold; color: #ffffff;'>📊 VOLUME + CVD</div>", unsafe_allow_html=True)

selected_tf = st.radio(
    "Timeframe",
    ["1m", "5m", "15m", "30m", "1H"],
    index=4,
    horizontal=True,
    label_visibility="collapsed"
)

freq_map = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1H": "60min"}
bar_count_map = {"1m": 20, "5m": 18, "15m": 16, "30m": 14, "1H": 10}

n_bars = bar_count_map[selected_tf]
pd_freq = freq_map[selected_tf]

np.random.seed(42)
# tz 파라미터 제거 (now_et가 이미 타임존을 포함하므로 충돌 방지)
dates = pd.date_range(end=now_et, periods=n_bars, freq=pd_freq)

buy_vol = np.random.randint(10, 250, n_bars) * 1000000
sell_vol = np.random.randint(10, 280, n_bars) * 1000000
total_vol = buy_vol + sell_vol
cvd = np.cumsum(buy_vol - sell_vol) / 1000000 + 100

colors = ['#10b981' if b > s else '#f43f5e' for b, s in zip(buy_vol, sell_vol)]

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Bar(x=dates, y=total_vol / 1000000, name="Volume", marker_color=colors), secondary_y=False)
fig.add_trace(go.Scatter(x=dates, y=cvd, name="CVD", line=dict(color='#eab308', width=2.5)), secondary_y=True)

fig.update_layout(
    template="plotly_dark",
    height=220,
    margin=dict(l=0, r=0, t=5, b=0),
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
    showlegend=False,
    autosize=True,
    xaxis=dict(showgrid=False, tickformat="%H:%M", nticks=5),
    yaxis=dict(showgrid=True, gridcolor='#1e2638', title="Vol", titlefont=dict(size=10)),
    yaxis2=dict(showgrid=False, title="CVD", titlefont=dict(size=10))
)

st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

buy_pct, sell_pct = 44, 56
st.markdown(f"""
    <div style="display: flex; justify-content: space-between; font-size: 11px; font-weight: bold; margin-top: -10px;">
        <span style="color: #10b981;">▲ Buy {buy_pct}%</span>
        <span style="color: #f43f5e;">▼ Sell {sell_pct}%</span>
    </div>
    <div class="bar-container"><div class="bar-fill" style="width: {buy_pct}%;"></div></div>
""", unsafe_allow_html=True)

st.markdown("""
    <div class="dash-card">
        <b>🌊 WEIGHTED FLOW:</b> <span class="tag-green">📈 종합 상승</span><br>
        <span style="color: #fbbf24; font-size: 12px;">⚠️ <b>Bullish Absorption</b> — 매도 물량을 매수세가 흡수하는 흐름입니다.</span>
    </div>
""", unsafe_allow_html=True)
