import sys
import os

# external_0dte 폴더 경로 추가
sys.path.append(os.path.join(os.path.dirname(__file__), 'external_0dte'))

import streamlit as st
import pandas as pd
# (이하 기존 app.py 코드 쭉 이어짐...)

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

# ---------------------------------------------------------
# 외부 퀀트 엔진 모듈 불러오기
# ---------------------------------------------------------
from quant_engine import SimonsBenterQuantEngine

# Page Configuration
st.set_page_config(
    page_title="SPX 0DTE DEFENDER",
    page_icon="🛡️",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ---------------------------------------------------------
# Mobile Optimized CSS
# ---------------------------------------------------------
st.markdown("""
<style>
.stApp { background-color: #0b0e14; color: #e1e6ed; }
.block-container {
    padding-top: 0.5rem !important;
    padding-bottom: 0.5rem !important;
    padding-left: 0.4rem !important;
    padding-right: 0.4rem !important;
    max-width: 100% !important;
}

[data-testid="stVerticalBlock"] > div {
    gap: 0.3rem !important;
}

.card-box {
    background-color: #121721;
    border: 1px solid #1f2937;
    border-radius: 6px;
    padding: 6px 8px;
    margin-bottom: 4px;
}
.news-box-alert {
    background-color: #2a1215;
    border: 1px solid #991b1b;
    border-radius: 6px;
    padding: 6px 8px;
    margin-bottom: 4px;
}
.news-box-neutral {
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
# Real-time Data & News Sensing Engine
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

@st.cache_data(ttl=60)
def fetch_latest_news_sentiment():
    try:
        ticker = yf.Ticker("ES=F")
        news_list = ticker.news
        if news_list and len(news_list) > 0:
            latest = news_list[0]
            title = latest.get('title', '')
            link = latest.get('link', '')
        else:
            title = "Case for BoC rate hike crumbling as trade war ramps up"
            link = "#"
    except Exception:
        title = "Case for BoC rate hike crumbling as trade war ramps up"
        link = "#"

    bearish_words = ["hike", "war", "inflation", "cpi", "drop", "plunge", "down", "crisis", "fall", "tariff", "risk"]
    bullish_words = ["cut", "easing", "rally", "gain", "soar", "surge", "cool", "growth", "jump", "boost"]

    title_lower = title.lower()
    bear_score = sum(1 for w in bearish_words if w in title_lower)
    bull_score = sum(1 for w in bullish_words if w in title_lower)

    if bear_score > bull_score:
        sentiment = "BEARISH"
        risk_level = "HIGH"
    elif bull_score > bear_score:
        sentiment = "BULLISH"
        risk_level = "MODERATE"
    else:
        sentiment = "NEUTRAL"
        risk_level = "LOW"

    return {
        "title": title,
        "sentiment": sentiment,
        "risk_level": risk_level,
        "link": link
    }

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

def calculate_dynamic_strikes(current_price, news_sentiment, distance_mult=1.0):
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

    base_r2 = int(round((current_price + (r2 - current_price) * distance_mult) / 5.0) * 5)
    base_r1 = int(round((current_price + (r1 - current_price) * distance_mult) / 5.0) * 5)
    base_s1 = int(round((current_price - (current_price - s1) * distance_mult) / 5.0) * 5)
    base_s2 = int(round((current_price - (current_price - s2) * distance_mult) / 5.0) * 5)

    sentiment = news_sentiment['sentiment']
    if sentiment == "BEARISH":
        call_strike = base_r1
        call_short = base_r1 + 5
        put_strike = base_s2 - 10
        put_short = base_s2 - 5
        adjust_note = "⚠️ 악재 감지: Put 지지선 추가 하향 (안전 확보)"
    elif sentiment == "BULLISH":
        call_strike = base_r2 + 10
        call_short = base_r2 + 15
        put_strike = base_s1
        put_short = base_s1 - 5
        adjust_note = "🚀 호재 감지: Call 저항선 추가 상향 (안전 확보)"
    else:
        call_strike = base_r2
        call_short = base_r1
        put_strike = base_s2
        put_short = base_s1
        adjust_note = "⚖️ 변동성 감지: Standard Pivot Strike 적용"

    return {
        'R2': base_r2, 'R1': base_r1, 'S1': base_s1, 'S2': base_s2,
        'dyn_call_sell': f"{call_short}/{call_strike}",
        'dyn_put_sell': f"{put_short}/{put_strike}",
        'call_target': call_strike,
        'put_target': put_strike,
        'adjust_note': adjust_note
    }

if "backtest_result" not in st.session_state:
    st.session_state["backtest_result"] = None

market_data = fetch_market_data()
news_sentiment = fetch_latest_news_sentiment()

est_tz = pytz.timezone('US/Eastern')
now_est = datetime.now(est_tz)

spx_p, spx_c, spx_pct = market_data['spx']
vix_p, vix_c, vix_pct = market_data['vix']
es_p, es_c, es_pct = market_data['es']

# ---------------------------------------------------------
# 퀀트 엔진 연동 및 계산
# ---------------------------------------------------------
es_df = fetch_es_history("5m")
news_score = SimonsBenterQuantEngine.advanced_news_scoring(news_sentiment['title'])

if es_df is not None and not es_df.empty:
    regime, distance_mult = SimonsBenterQuantEngine.detect_market_regime(es_df, vix_p)
    z_score = SimonsBenterQuantEngine.calculate_zscore_anomaly(es_df['Close'])
else:
    regime, distance_mult = "NORMAL_VOLATILITY", 1.0
    z_score = 0.0

strikes = calculate_dynamic_strikes(spx_p, news_sentiment, distance_mult)

# 1. Header
st.markdown(f"""
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
<span style="font-weight: bold; font-size: 14px;">🛡️ SPX 0DTE <span style="background-color: #1f2937; padding: 1px 4px; border-radius: 3px; font-size: 9px; color: #9ca3af;">v16.0 Quant Engine</span></span>
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

# 켈리 비중 계산 (백테스트 결과가 있으면 적용, 없으면 0)
if result:
    win_rate = result.get('win_rate', 0.0)
    loss_rate = result.get('loss_rate', round(100.0 - win_rate, 1))
    total_signals = result.get('total_signals', 0)
    ev = result.get('expected_value', 0.0)
    kelly_allocation = SimonsBenterQuantEngine.calculate_fractional_kelly(win_rate=win_rate, reward_to_risk_ratio=0.3)

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
else:
    kelly_allocation = 0.0

# 3. Dynamic News Alert Box
news_box_class = "news-box-alert" if news_sentiment['risk_level'] == "HIGH" else "news-box-neutral"
sent_color = "#ef4444" if news_sentiment['sentiment'] == "BEARISH" else ("#10b981" if news_sentiment['sentiment'] == "BULLISH" else "#facc15")

st.markdown(f"""
<div class="{news_box_class}">
<div style="display: flex; justify-content: space-between; align-items: center;">
<span style="color: {sent_color}; font-weight: bold; font-size: 10px;">⚡ BREAKING NEWS [{news_sentiment['sentiment']}]</span>
<span style="color: #6b7280; font-size: 8px;">{now_est.strftime('%m/%d %H:%M')} ET</span>
</div>
<div style="font-size: 10px; color: #e5e7eb; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px;">
{news_sentiment['title']}
</div>
<div style="font-size: 8px; color: #9ca3af; margin-top: 2px;">
🔍 {strikes['adjust_note']}
</div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# Simons & Benter 퀀트 진단 UI (쉬운 한글 설명 적용)
# ---------------------------------------------------------
if abs(z_score) >= 2.0:
    z_desc = "⚠️ 극단치 (반전주의)"
elif abs(z_score) >= 1.0:
    z_desc = "👀 약간 이탈"
else:
    z_desc = "✅ 정상 범위"

if kelly_allocation == 0:
    kelly_desc = "🚫 관망 추천 (진입 금지)"
else:
    kelly_desc = f"🎯 잔고의 {kelly_allocation}% 진입"

n_desc = "악재 우세" if news_score < 0 else ("호재 우세" if news_score > 0 else "중립")

st.markdown(f"""
<div class="card-box" style="border-left: 3px solid #8b5cf6;">
<div style="font-size: 10px; color: #a78bfa; font-weight: bold;">🧪 QUANT STATISTICAL METRICS (퀀트 진단)</div>
<div style="display: flex; justify-content: space-between; margin-top: 4px; font-size: 10px;">
<span>시장 상태: <b>{regime}</b></span>
<span>주가위치: <b>{z_score} σ ({z_desc})</b></span>
</div>
<div style="display: flex; justify-content: space-between; margin-top: 2px; font-size: 10px;">
<span>뉴스 점수: <b>{news_score} pts ({n_desc})</b></span>
<span>추천 비중: <b style="color: #facc15;">{kelly_desc}</b></span>
</div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="card-box" style="padding: 4px 6px;">
<span style="color: #f43f5e; font-weight: bold; font-size: 9px;">⚡ RISKS: </span>
<span class="risk-tag">INFLATION</span><span class="risk-tag">FED</span><span class="risk-tag">FOMC</span><span class="risk-tag">WAR</span><span class="risk-tag">CPI</span>
</div>
""", unsafe_allow_html=True)

# 4. Ticker Metrics Grid
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
    if news_sentiment['sentiment'] == "BEARISH":
        sig_title = "CALL CREDIT SPREAD (뉴스 우세)"
        sig_badge = '<span class="badge-red">NEWS ALERT</span>'
        sig_color = "#ef4444"
        confidence = 65
        sig_desc = "악재 뉴스 감지됨. 상승 제한 가능성 유의."
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

# 6. Dynamic Support / Resistance & Strike Recommendation
diff_r2 = round(strikes['call_target'] - spx_p, 1)
diff_s2 = round(spx_p - strikes['put_target'], 1)

st.markdown(f"""
<div class="grid-2col">
<div class="metric-card" style="border-left: 3px solid #ef4444;">
<div style="font-size: 10px; font-weight: bold; color: #fca5a5;">🔴 CALL CREDIT SPREAD</div>
<div style="font-size: 14px; font-weight: bold; margin-top: 2px;">{strikes['call_target']} Strike</div>
<div style="font-size: 9px; color: #10b981;">+{diff_r2} pt 차이</div>
<div style="font-size: 9px; color: #9ca3af; margin-top: 4px;">🎯 <b>{strikes['dyn_call_sell']} Call Sell</b></div>
</div>
<div class="metric-card" style="border-left: 3px solid #10b981;">
<div style="font-size: 10px; font-weight: bold; color: #6ee7b7;">🟢 PUT CREDIT SPREAD</div>
<div style="font-size: 14px; font-weight: bold; margin-top: 2px;">{strikes['put_target']} Strike</div>
<div style="font-size: 9px; color: #ef4444;">-{diff_s2} pt 차이</div>
<div style="font-size: 9px; color: #9ca3af; margin-top: 4px;">🎯 <b>{strikes['dyn_put_sell']} Put Sell</b></div>
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

es_df_chart = fetch_es_history(selected_tf)

if es_df_chart is not None and not es_df_chart.empty:
    dates_str = [d.strftime("%H:%M") for d in es_df_chart.index]
    total_vol = es_df_chart['Volume'].values
    close_vals = es_df_chart['Close'].values
    open_vals = es_df_chart['Open'].values
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
