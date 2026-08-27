import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import yfinance as yf
from backtest import run_probability_analysis

# Page Configuration
st.set_page_config(
    page_title="SPX 0DTE DEFENDER",
    page_icon="🛡️",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ---------------------------------------------------------
# Mobile Optimized CSS (여백 및 폰트 축소, 모바일 2열 그리드)
# ---------------------------------------------------------
st.markdown("""
<style>
/* 기본 배경 및 여백 제거 */
.stApp { background-color: #0b0e14; color: #e1e6ed; }
.block-container {
    padding-top: 0.5rem !important;
    padding-bottom: 0.5rem !important;
    padding-left: 0.4rem !important;
    padding-right: 0.4rem !important;
    max-width: 100% !important;
}

/* Streamlit 기본 위젯 간격 축소 */
[data-testid="stVerticalBlock"] > div {
    gap: 0.3rem !important;
}

/* 카드 및 박스 스타일 지정 */
.card-box {
    background-color: #121721;
    border: 1px solid #1f2937;
    border-radius: 6px;
    padding: 6px 8px;
    margin-bottom: 4px;
}
.news-box {
    background-color: #161114;
    border: 1px solid #3d1c1c;
    border-radius: 6px;
    padding: 6px 8px;
    margin-bottom: 4px;
}
.signal-box {
    background-color: #16150e;
    border: 1px solid #785a00;
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 4px;
}

/* 뱃지 및 태그 */
.badge-red { background-color: #991b1b; color: #fca5a5; padding: 1px 5px; border-radius: 4px; font-weight: bold; font-size: 9px; }
.badge-green { background-color: #065f46; color: #6ee7b7; padding: 1px 5px; border-radius: 4px; font-weight: bold; font-size: 9px; }
.badge-yellow { background-color: #78350f; color: #fde68a; padding: 1px 5px; border-radius: 4px; font-weight: bold; font-size: 9px; }
.risk-tag {
    background-color: #211522;
    border: 1px solid #4a284e;
    color: #d8b4fe;
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 9px;
    font-weight: bold;
    display: inline-block;
    margin-right: 2px;
}

/* 모바일 전용 2열 타일 레이아웃 */
.grid-2col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
    margin-bottom: 4px;
}
.metric-card {
    background-color: #121721;
    border: 1px solid #1f2937;
    border-radius: 6px;
    padding: 6px 8px;
}
.metric-label { font-size: 10px; color: #9ca3af; font-weight: bold; }
.metric-val { font-size: 16px; font-weight: bold; color: #ffffff; line-height: 1.2; }
.metric-sub { font-size: 10px; margin-top: 2px; }

/* 프로그레스 바 */
.bar-container {
    width: 100%;
    background-color: #ef4444;
    height: 5px;
    border-radius: 3px;
    overflow: hidden;
    margin: 3px 0;
}
.bar-fill { height: 100%; background-color: #10b981; }

hr { margin: 6px 0 !important; border-color: #1f2937 !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# Real-time Fast Fetch Engine
# ---------------------------------------------------------
@st.cache_data(ttl=5)
def fetch_market_data():
    def get_price(symbol):
        try:
            t = yf.Ticker(symbol)
            price = t.fast_info.last_price
            prev = t.fast_info.previous_close
            if price is None or np.isnan(price):
                hist = t.history(period="2d")
                if not hist.empty:
                    price = hist['Close'].iloc[-1]
                    prev = hist['Close'].iloc[-2] if len(hist) > 1 else price
            price = float(price or 0.0)
            prev = float(prev or price)
            change = price - prev
            pct = (change / prev) * 100 if prev != 0 else 0.0
            return (price, change, pct)
        except Exception:
            return (0.0, 0.0, 0.0)

    spx = get_price('^SPX')
    vix = get_price('^VIX')
    es = get_price('ES=F')

    if spx[0] == 0.0 and es[0] != 0.0:
        spx = es

    return {'spx': spx, 'vix': vix, 'es': es}

@st.cache_data(ttl=30)
def fetch_es_history(interval_str):
    try:
        yf_interval = "60m" if interval_str == "1H" else interval_str
        period = "1d" if interval_str in ["1m", "5m"] else "5d"
        
        df = yf.download(tickers="ES=F", period=period, interval=yf_interval, progress=False)
        if df.empty:
            return None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.tail(100).copy()
        est_tz = pytz.timezone('US/Eastern')
        df.index = df.index.tz_convert(est_tz)
        return df
    except Exception:
        return None

def calculate_support_resistance(current_price):
    es_df = fetch_es_history("5m")
    if es_df is not None and not es_df.empty:
        high = es_df['High'].max()
        low = es_df['Low'].min()
        close = es_df['Close'].iloc[-1]
        
        pivot = (high + low + close) / 3
        r1 = (2 * pivot) - low
        s1 = (2 * pivot) - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
    else:
        r2 = current_price + 30.0
        r1 = current_price + 15.0
        s1 = current_price - 15.0
        s2 = current_price - 30.0

    return {
        'R2': int(round(r2 / 5.0) * 5),
        'R1': int(round(r1 / 5.0) * 5),
        'S1': int(round(s1 / 5.0) * 5),
        'S2': int(round(s2 / 5.0) * 5)
    }

if "backtest_result" not in st.session_state:
    st.session_state["backtest_result"] = None

market_data = fetch_market_data()
est_tz = pytz.timezone('US/Eastern')
now_est = datetime.now(est_tz)

spx_p, spx_c, spx_pct = market_data['spx']
vix_p, vix_c, vix_pct = market_data['vix']
es_p, es_c, es_pct = market_data['es']

sr_levels = calculate_support_resistance(spx_p)

# 1. Header
st.markdown(f"""
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
    <span style="font-weight: bold; font-size: 14px;">🛡️ SPX 0DTE <span style="background-color: #1f2937; padding: 1px 4px; border-radius: 3px; font-size: 9px; color: #9ca3af;">v14.2 Mobile</span></span>
    <span style="background-color: #1f2937; padding: 1px 6px; border-radius: 8px; font-size: 9px; color: #9ca3af;">● Live | {now_est.strftime('%H:%M')} ET</span>
</div>
""", unsafe_allow_html=True)

# 2. Probability Engine
tf_option = st.radio(
    "예측 타임프레임 선택",
    ["10분 뒤", "30분 뒤", "1시간 뒤"],
    index=1,
    horizontal=True,
    label_visibility="collapsed"
)

bars_map = {"10분 뒤": 2, "30분 뒤": 6, "1시간 뒤": 12}
selected_bars = bars_map[tf_option]

if st.button(f"🚀 [{tf_option}] 승률/기대값 검증", use_container_width=True):
    with st.spinner("과거 데이터 분석 중..."):
        res = run_probability_analysis("ES=F", period="1mo", interval="5m", lookahead_bars=selected_bars)
        if res:
            res["tf_option"] = tf_option
            st.session_state["backtest_result"] = res

result = st.session_state["backtest_result"]

if result:
    win_rate = result.get('win_rate', 0.0)
    loss_rate = result.get('loss_rate', round(100.0 - win_rate, 1))
    total_signals = result.get('total_signals', 0)
    ev = result.get('expected_value', 0.0)
    tf_name = result.get('tf_option', tf_option)

    st.markdown(f"""
<div class="card-box">
    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 2px; text-align: center;">
        <div>
            <div style="font-size: 8px; color: #6b7280;">총시그널</div>
            <div style="font-size: 12px; font-weight: bold;">{total_signals}회</div>
        </div>
        <div>
            <div style="font-size: 8px; color: #6b7280;">▲ 상승</div>
            <div style="font-size: 12px; font-weight: bold; color: #10b981;">{win_rate}%</div>
        </div>
        <div>
            <div style="font-size: 8px; color: #6b7280;">▼ 하락</div>
            <div style="font-size: 12px; font-weight: bold; color: #ef4444;">{loss_rate}%</div>
        </div>
        <div>
            <div style="font-size: 8px; color: #6b7280;">EV</div>
            <div style="font-size: 12px; font-weight: bold; color: #facc15;">+{ev}pt</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# 3. News & Risk
st.markdown(f"""
<div class="news-box">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="color: #ef4444; font-weight: bold; font-size: 10px;">⚠️ NEWS</span>
        <span style="color: #6b7280; font-size: 8px;">{now_est.strftime('%m/%d %H:%M')} ET</span>
    </div>
    <div style="font-size: 10px; color: #e5e7eb; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Case for BoC rate hike crumbling as trade war ramps up</div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="card-box" style="padding: 4px 6px;">
    <span style="color: #f43f5e; font-weight: bold; font-size: 9px;">⚡ RISKS: </span>
    <span class="risk-tag">INFLATION</span><span class="risk-tag">FED</span><span class="risk-tag">FOMC</span><span class="risk-tag">WAR</span><span class="risk-tag">CPI</span>
</div>
""", unsafe_allow_html=True)

# 4. Ticker Metrics Grid (모바일 2열 고정)
spx_color = "#10b981" if spx_c >= 0 else "#ef4444"
es_color = "#10b981" if es_c >= 0 else "#ef4444"
vix_color = "#ef4444" if vix_c >= 0 else "#10b981"

st.markdown(f"""
<div class="grid-2col">
    <div class="metric-card">
        <div class="metric-label">SPX INDEX</div>
        <div class="metric-val">{spx_p:.2f}</div>
        <div class="metric-sub" style="color: {spx_color};">{spx_c:+.2f} ({spx_pct:+.2f}%)</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">ES FUTURES</div>
        <div class="metric-val">{es_p:.2f}</div>
        <div class="metric-sub" style="color: {es_color};">{es_c:+.2f} ({es_pct:+.2f}%)</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">VIX INDEX</div>
        <div class="metric-val">{vix_p:.2f}</div>
        <div class="metric-sub" style="color: {vix_color};">{vix_c:+.2f} ({vix_pct:+.2f}%)</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">FEAR & GREED</div>
        <div class="metric-val" style="font-size: 14px;">59 (Greed)</div>
        <div class="metric-sub" style="color: #9ca3af;">1w: 55 | 1m: 41</div>
    </div>
</div>
""", unsafe_allow_html=True)

# 5. Decision Signal
if result:
    win = result.get('win_rate', 0.0)
    loss = result.get('loss_rate', 0.0)
    ev_val = result.get('expected_value', 0.0)
    confidence = min(round(abs(win - loss) * 2), 100)
    
    if win > loss and ev_val > 0:
        sig_title = "PUT CREDIT SPREAD"
        sig_badge = '<span class="badge-green">BULLISH</span>'
        sig_color = "#10b981"
        sig_desc = f"상승 확률({win}%) 우세. Put Credit Spread 권장."
    elif loss > win:
        sig_title = "CALL CREDIT SPREAD"
        sig_badge = '<span class="badge-red">BEARISH</span>'
        sig_color = "#ef4444"
        sig_desc = f"하락 확률({loss}%) 우세. Call Credit Spread 권장."
    else:
        sig_title = "관망 (NEUTRAL)"
        sig_badge = '<span class="badge-yellow">WAIT</span>'
        sig_color = "#fbbf24"
        sig_desc = "방향성 불분명. 수급 추가 확인 필요."
else:
    sig_title = "백테스트 검증 필요"
    sig_badge = '<span class="badge-yellow">⏱️ READY</span>'
    sig_color = "#fbbf24"
    confidence = 0
    sig_desc = "상단 버튼을 눌러 승률을 검증하세요."

st.markdown(f"""
<div class="signal-box">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 10px; font-weight: bold; color: #9ca3af;">🚨 DECISION SIGNAL</span>
        {sig_badge}
    </div>
    <div style="margin-top: 2px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 15px; font-weight: bold; color: {sig_color};">{sig_title}</span>
        <span style="font-size: 9px; color: #9ca3af;">CONF <b style="font-size: 12px; color: {sig_color};">{confidence}%</b></span>
    </div>
    <div style="font-size: 10px; color: #d1d5db; margin-top: 2px;">{sig_desc}</div>
</div>
""", unsafe_allow_html=True)

# 6. Support / Resistance (모바일 2열 카드)
diff_r2 = round(sr_levels['R2'] - spx_p, 1)
diff_s2 = round(spx_p - sr_levels['S2'], 1)

st.markdown(f"""
<div class="grid-2col">
    <div class="metric-card" style="border-left: 3px solid #ef4444;">
        <div style="font-size: 10px; font-weight: bold; color: #fca5a5;">🔴 CALL CREDIT</div>
        <div style="font-size: 14px; font-weight: bold; margin-top: 2px;">{sr_levels['R2']} Strike</div>
        <div style="font-size: 9px; color: #10b981;">+{diff_r2} pt (R2)</div>
        <div style="font-size: 9px; color: #9ca3af; margin-top: 4px;">💡 <b>{sr_levels['R1']}/{sr_levels['R2']} Call Sell</b></div>
    </div>
    <div class="metric-card" style="border-left: 3px solid #10b981;">
        <div style="font-size: 10px; font-weight: bold; color: #6ee7b7;">🟢 PUT CREDIT</div>
        <div style="font-size: 14px; font-weight: bold; margin-top: 2px;">{sr_levels['S2']} Strike</div>
        <div style="font-size: 9px; color: #ef4444;">-{diff_s2} pt (S2)</div>
        <div style="font-size: 9px; color: #9ca3af; margin-top: 4px;">💡 <b>{sr_levels['S1']}/{sr_levels['S2']} Put Sell</b></div>
    </div>
</div>
""", unsafe_allow_html=True)

# 7. Volume + CVD Chart
st.markdown("<div style='font-size: 11px; font-weight: bold; margin-top: 4px;'>📊 VOLUME + CVD (ES=F)</div>", unsafe_allow_html=True)

selected_tf = st.radio(
    "TF",
    ["1m", "5m", "15m", "30m", "1H"],
    index=2,
    horizontal=True,
    label_visibility="collapsed"
)

es_df = fetch_es_history(selected_tf)

if es_df is not None and not es_df.empty:
    dates_str = [d.strftime("%H:%M") for d in es_df.index]
    total_vol = es_df['Volume'].values
    close_vals = es_df['Close'].values
    open_vals = es_df['Open'].values
    delta = close_vals - open_vals
    
    buy_mask = delta >= 0
    buy_vol = np.where(buy_mask, total_vol * 0.55, total_vol * 0.45)
    sell_vol = total_vol - buy_vol
    
    cvd = np.cumsum(buy_vol - sell_vol) / 1000
    colors = ['#10b981' if b else '#ef4444' for b in buy_mask]
    
    total_buy = np.sum(buy_vol)
    total_sum = np.sum(total_vol) if np.sum(total_vol) > 0 else 1
    buy_pct = int((total_buy / total_sum) * 100)
    sell_pct = 100 - buy_pct
else:
    n_bars = 16
    dates_str = [(now_est - timedelta(minutes=i*15)).strftime("%H:%M") for i in range(n_bars)][::-1]
    total_vol = np.random.randint(100, 1000, n_bars) * 100
    cvd = np.cumsum(np.random.randint(-50, 50, n_bars))
    colors = ['#10b981' if i % 2 == 0 else '#ef4444' for i in range(n_bars)]
    buy_pct, sell_pct = 48, 52

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Bar(x=dates_str, y=total_vol, name="Vol", marker_color=colors, opacity=0.85), secondary_y=False)
fig.add_trace(go.Scatter(x=dates_str, y=cvd, name="CVD", line=dict(color='#facc15', width=1.5)), secondary_y=True)

fig.update_layout(
    template="plotly_dark",
    height=140,
    margin=dict(l=0, r=0, t=0, b=0),
    paper_bgcolor='#0b0e14',
    plot_bgcolor='#121721',
    showlegend=False,
    xaxis=dict(showgrid=True, gridcolor='#1f2937', fixedrange=True, type='category', tickfont=dict(size=8)),
    yaxis=dict(showgrid=True, gridcolor='#1f2937', title=None, fixedrange=True, tickfont=dict(size=8)),
    yaxis2=dict(showgrid=False, title=None, fixedrange=True, tickfont=dict(size=8))
)

html_fig = fig.to_html(include_plotlyjs='cdn', full_html=False, config={'staticPlot': True, 'displayModeBar': False})
components.html(f"""
<div style="pointer-events: none; user-select: none; width:100%; height:140px;">
    {html_fig}
</div>
""", height=145)

st.markdown(f"""
<div style="display: flex; justify-content: space-between; font-weight: bold; font-size: 10px; margin-top: -5px;">
    <span style="color: #10b981;">▲ Buy {buy_pct}%</span>
    <span style="color: #ef4444;">▼ Sell {sell_pct}%</span>
</div>
<div class="bar-container">
    <div class="bar-fill" style="width: {buy_pct}%;"></div>
</div>
""", unsafe_allow_html=True)
