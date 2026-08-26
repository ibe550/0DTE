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

# 2. Modern UI CSS (Image Style Matching)
st.markdown("""
    <style>
    .block-container { 
        padding-top: 1rem !important; 
        padding-bottom: 1rem !important; 
        padding-left: 0.8rem !important; 
        padding-right: 0.8rem !important; 
    }
    .stApp { background-color: #080a0f; color: #94a3b8; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    
    /* Header Bar */
    .header-box {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
    }
    .header-title {
        font-size: 18px;
        font-weight: 800;
        color: #ffffff;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .v-badge {
        background-color: #1e1b4b;
        color: #818cf8;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: bold;
    }
    .market-status {
        background-color: #171923;
        border: 1px solid #2d3748;
        color: #a0aec0;
        padding: 3px 8px;
        border-radius: 12px;
        font-size: 11px;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    /* Cards Common Style */
    .dash-card {
        background-color: #0f131c;
        border: 1px solid #1e2638;
        border-radius: 8px;
        padding: 12px 14px;
        margin-bottom: 10px;
        position: relative;
    }
    .dash-card-red {
        background-color: #12090d;
        border: 1px solid #450a0a;
        border-radius: 8px;
        padding: 12px 14px;
        margin-bottom: 10px;
    }

    /* Header text inside cards */
    .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 4px;
    }
    .card-title {
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.5px;
        color: #cbd5e1;
    }
    .card-time {
        font-size: 10px;
        color: #64748b;
    }

    /* Values & Badges */
    .val-large-green { font-size: 26px; font-weight: 800; color: #10b981; margin: 4px 0 2px 0; }
    .val-large-red { font-size: 26px; font-weight: 800; color: #f43f5e; margin: 4px 0 2px 0; }
    .val-sub-green { font-size: 12px; font-weight: 600; color: #10b981; }
    .val-sub-red { font-size: 12px; font-weight: 600; color: #f43f5e; }
    
    .badge-active { background-color: #1e1b4b; color: #818cf8; font-size: 10px; padding: 1px 5px; border-radius: 3px; font-weight: bold; }
    .tag-red { background-color: #450a0a; color: #fca5a5; border: 1px solid #7f1d1d; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
    .tag-dark { background-color: #18181b; color: #a1a1aa; border: 1px solid #27272a; font-size: 10px; padding: 2px 6px; border-radius: 4px; }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# 3. Header Section
st.markdown(f"""
    <div class="header-box">
        <div class="header-title">
            <span style="color: #6366f1;">🛡️</span> SPX 0DTE DEFENDER <span class="v-badge">v12.0</span>
        </div>
        <div class="market-status">
            <span style="color: #6366f1;">●</span> Market Closed &nbsp; 🕒 {now_et.strftime('%H:%M:%S')}
        </div>
    </div>
""", unsafe_allow_html=True)

# 4. Breaking News Card
st.markdown("""
    <div class="dash-card-red">
        <div class="card-header">
            <span class="card-title" style="color: #f87171;">⚠️ BREAKING NEWS</span>
            <span class="card-time"><span style="color: #ef4444;">Google News</span> Data as of 08/25 22:01:00 ET</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
            <a href="#" style="color: #f1f5f9; font-size: 13px; font-weight: 600; text-decoration: underline;">
                Case for BoC rate hike crumbling as trade war ramps up - mpamag.com
            </a>
            <span style="font-size: 11px; color: #64748b;">9h ago</span>
        </div>
    </div>
""", unsafe_allow_html=True)

# 5. High Impact Events Card
st.markdown("""
    <div class="dash-card">
        <div class="card-title" style="margin-bottom: 8px;">📅 TODAY'S HIGH-IMPACT EVENTS (USD)</div>
        <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px;">
            <span><span style="color: #eab308;">●</span> <b>Core PCE Price Index m/m</b> <span style="color: #64748b;">f:0.2%</span></span>
            <span style="color: #64748b;">9h 48m</span>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 12px;">
            <span><span style="color: #eab308;">●</span> <b>Prelim GDP q/q</b> <span style="color: #64748b;">f:1.5%</span></span>
            <span style="color: #64748b;">9h 48m</span>
        </div>
    </div>
""", unsafe_allow_html=True)

# 6. News Risks Card
st.markdown("""
    <div class="dash-card">
        <div class="card-header">
            <span class="card-title">📈 NEWS RISKS:</span>
            <span class="card-time">Latest item 08/25 22:01:00 ET</span>
        </div>
        <div style="display: flex; gap: 6px; margin-top: 6px;">
            <span class="tag-red">INFLATION</span>
            <span class="tag-dark">FED</span>
            <span class="tag-dark">FOMC</span>
            <span class="tag-red">WAR</span>
        </div>
    </div>
""", unsafe_allow_html=True)

# 7. Ticker Grid (2x2)
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

    st.markdown("""
        <div class="dash-card">
            <div class="card-header">
                <span class="card-title">ES FUTURES</span>
                <span class="badge-active">ACTIVE</span>
            </div>
            <div class="val-large-red">7679.50</div>
            <div class="val-sub-red">-12.50 (-0.16%)</div>
            <div style="font-size: 10px; color: #64748b; margin-top: 2px;">E-mini S&P 500</div>
            <div class="card-time" style="margin-top: 2px;">Data as of 08/25 22:30:42 ET</div>
        </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
        <div class="dash-card">
            <div class="card-title">VIX</div>
            <div class="card-time">Data as of 08/25 16:14:00 ET</div>
            <div class="val-large-green">15.45</div>
            <div class="val-sub-red">+0.32 (+2.12%)</div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("""
        <div class="dash-card">
            <div class="card-title">FEAR & GREED</div>
            <div class="card-time">Data as of 08/25 19:59:53 ET</div>
            <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 6px;">
                <div style="width: 50px; height: 50px; border-radius: 50%; border: 4px solid #10b981; border-bottom-color: transparent; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #fff;">59</div>
                <div>
                    <div style="color: #10b981; font-size: 16px; font-weight: 800;">Greed</div>
                    <div style="font-size: 10px; color: #64748b;">1w ago: 55</div>
                    <div style="font-size: 10px; color: #64748b;">1m ago: 41</div>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

# 8. VIX Trend Card
st.markdown("""
    <div class="dash-card" style="display: flex; justify-content: space-between; align-items: center;">
        <div style="display: flex; align-items: center; gap: 8px;">
            <span class="card-title">VIX TREND</span>
            <span class="tag-dark">— VIX Stable</span>
        </div>
        <div style="font-size: 10px; color: #64748b;">1pt</div>
    </div>
""", unsafe_allow_html=True)
