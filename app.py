import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import datetime

# 1. 페이지 및 테마 설정 (Dark Theme)
st.set_page_config(
    page_title="SPX 0DTE DEFENDER v12.0",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for Dark/Professional Dashboard Styling
st.markdown("""
    <style>
    .stApp { background-color: #0b0e14; color: #e1e6ed; }
    .metric-card {
        background-color: #161b22;
        border: 1px solid #21262d;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 10px;
    }
    .status-wait {
        background-color: #3d2c00;
        border: 1px solid #855d00;
        color: #ffc107;
        padding: 10px;
        border-radius: 6px;
        font-weight: bold;
    }
    .badge-red { background-color: #da3633; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
    .badge-green { background-color: #238636; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
    </style>
""", unsafe_allow_html=True)

# 2. 헤더 타이틀 및 장 상태
col_head1, col_head2 = st.columns([3, 1])
with col_head1:
    st.title("🛡️ SPX 0DTE DEFENDER v12.0")
with col_head2:
    st.markdown("<div style='text-align: right; color: #8b949e; margin-top: 15px;'>● Market Closed | 22:17:47 ET</div>", unsafe_allow_html=True)

st.divider()

# 3. 최상단 지수 타일 (SPX, VIX, ES Futures, Fear & Greed)
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown("<div class='metric-card'><h4>SPX INDEX</h4><h2>7677.28</h2><span style='color:#3fb950;'>+24.42 (+0.32%)</span></div>", unsafe_allow_html=True)
with c2:
    st.markdown("<div class='metric-card'><h4>VIX INDEX</h4><h2>15.45</h2><span style='color:#f85149;'>+0.32 (+2.12%)</span></div>", unsafe_allow_html=True)
with c3:
    st.markdown("<div class='metric-card'><h4>ES FUTURES</h4><h2>7672.75</h2><span style='color:#f85149;'>-19.25 (-0.25%)</span></div>", unsafe_allow_html=True)
with c4:
    st.markdown("<div class='metric-card'><h4>FEAR & GREED</h4><h2>59 (Greed)</h2><span style='color:#8b949e;'>1w ago: 55 | 1m ago: 41</span></div>", unsafe_allow_html=True)

st.write("")

# 4. 의사결정 패널 (DECISION SIGNAL) & GEX 분석
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("🚨 DECISION SIGNAL")
    st.markdown("""
        <div class='status-wait'>
            <h3>[WAIT] 신호 대기</h3>
            <p>일부 데이터가 stale 상태이거나 정규장 외 시간이므로 새 0DTE 진입을 제안하지 않습니다.</p>
            <b>CONFIDENCE: 0% | CREDIT DIRECTION: WAIT</b>
        </div>
    """, unsafe_allow_html=True)
    
    st.write("")
    st.subheader("📊 Session Levels & Volatility Profile")
    st.write("• **Opening Range (First 15m):** 7714 / 7681")
    st.write("• **ES Overnight Range:** 7714 / 7670")
    st.write("• **Realized Volatility:** 13.4% (9-Day Implied Volatility Proxy)")

with col_right:
    st.subheader("⚡ GEX & GAMMA CONTEXT")
    st.markdown("""
        <div class='metric-card'>
            <b>Gamma Status:</b> <span class='badge-red'>Explosive 구간</span><br>
            - <b>Gamma Flip:</b> 7660<br>
            - <b>Call Wall:</b> 7670 | <b>Put Wall:</b> 7670<br>
            - <b>0DTE Option Net Delta:</b> +94,588.18 (Call Biased)<br>
            <i>가격이 Gamma Flip(7660) 위에 위치하여 딜러 추세 헷징으로 인한 상방 가속 가능성이 존재합니다.</i>
        </div>
    """, unsafe_allow_html=True)

st.divider()

# 5. 차트 분석 영역 (Plotly 차트)
st.subheader("📈 SPX 1H Chart & Volume / CVD Profile")

# 더미 차트 데이터 생성
dates = pd.date_range(end=datetime.datetime.now(), periods=30, freq='1H')
prices = np.linspace(7640, 7677, 30) + np.random.normal(0, 5, 30)
volumes = np.random.randint(100, 500, 30)

fig = go.Figure()
fig.add_trace(go.Scatter(x=dates, y=prices, mode='lines+markers', name='SPX Price', line=dict(color='#58a6ff', width=2)))
fig.update_layout(template="plotly_dark", height=300, margin=dict(l=20, r=20, t=20, b=20))
st.plotly_chart(fig, use_container_width=True)

# 6. 하단 Weighted Flow Signal & 뉴스
col_f1, col_f2 = st.columns(2)
with col_f1:
    st.subheader("🌊 WEIGHTED FLOW SIGNAL")
    st.success("🟢 **Bullish Absorption:** 주가는 0.30% 상승했으나 CVD는 4.9% 하락. 매도 물량을 매수세가 흡수하는 흐름으로 추정됩니다.")
    st.write("**Selling vs Buying Volume:** 56% Sell vs 44% Buy")

with col_f2:
    st.subheader("📅 UPCOMING HIGH-IMPACT EVENTS")
    st.write("• **Core PCE Price Index m/m:** 8.2% (10h 12m 남음)")
    st.write("• **Prelim GDP q/q:** 1.5% (10h 12m 남음)")
    st.write("• **Fed Chairman Warsh Speaks:** (2d 11h 남음)")
