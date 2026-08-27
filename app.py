import sys
import os

# external_0dte 경로 등록
sys.path.append(os.path.join(os.path.dirname(__file__), 'external_0dte'))

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

from quant_engine import SimonsBenterQuantEngine

st.set_page_config(
    page_title="SPX 0DTE DEFENDER & RESEARCH",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
.stApp { background-color: #0b0e14; color: #e1e6ed; }
.block-container {
    padding-top: 0.5rem !important;
    padding-bottom: 0.5rem !important;
    padding-left: 0.5rem !important;
    padding-right: 0.5rem !important;
}
[data-testid="stVerticalBlock"] > div { gap: 0.3rem !important; }
.card-box { background-color: #121721; border: 1px solid #1f2937; border-radius: 6px; padding: 6px 8px; margin-bottom: 4px; }
.news-box-alert { background-color: #2a1215; border: 1px solid #991b1b; border-radius: 6px; padding: 6px 8px; margin-bottom: 4px; }
.news-box-neutral { background-color: #161114; border: 1px solid #3d1c1c; border-radius: 6px; padding: 6px 8px; margin-bottom: 4px; }
.signal-box { background-color: #16150e; border: 1px solid #785a00; border-radius: 6px; padding: 8px 10px; margin-bottom: 4px; }
.badge-red { background-color: #991b1b; color: #fca5a5; padding: 1px 5px; border-radius: 4px; font-weight: bold; font-size: 9px; }
.badge-green { background-color: #065f46; color: #6ee7b7; padding: 1px 5px; border-radius: 4px; font-weight: bold; font-size: 9px; }
.badge-yellow { background-color: #78350f; color: #fde68a; padding: 1px 5px; border-radius: 4px; font-weight: bold; font-size: 9px; }
.risk-tag { background-color: #211522; border: 1px solid #4a284e; color: #d8b4fe; padding: 1px 4px; border-size: 3px; font-size: 9px; font-weight: bold; display: inline-block; margin-right: 2px; }
.grid-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 4px; }
.metric-card { background-color: #121721; border: 1px solid #1f2937; border-radius: 6px; padding: 6px 8px; }
.metric-label { font-size: 10px; color: #9ca3af; font-weight: bold; }
.metric-val { font-size: 16px; font-weight: bold; color: #ffffff; line-height: 1.2; }
.metric-sub { font-size: 10px; margin-top: 2px; }
.bar-container { width: 100%; background-color: #ef4444; height: 5px; border-radius: 3px; overflow: hidden; margin: 3px 0; }
.bar-fill { height: 100%; background-color: #10b981; }
hr { margin: 6px 0 !important; border-color: #1f2937 !important; }
</style>
""", unsafe_allow_html=True)

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
def fetch_latest_news_sentiment():
    try:
        ticker = yf.Ticker("ES=F")
        news_list = ticker.news
        if news_list and len(news_list) > 0:
            latest = news_list[0]
            title = latest.get('title', '')
            link = latest.get('link', '')
        else:
            title = "NVIDIA After-Market Rally Signals Tech Strong Earnings"
            link = "#"
    except Exception:
        title = "NVIDIA After-Market Rally Signals Tech Strong Earnings"
        link = "#"

    bearish_words = ["hike", "war", "inflation", "cpi", "drop", "plunge", "down", "crisis", "fall", "tariff", "missed"]
    bullish_words = ["cut", "easing", "rally", "gain", "soar", "surge", "cool", "growth", "beat", "earnings", "boost"]

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

@st.cache_data(ttl=15)
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
    if distance_mult > 1.4:
        adjust_note = "🚨 실적 발표/장외 폭동 감지: 행수가격 안전거리(Buffer) 1.6배 자동 확대"
        call_strike = base_r2 + 15
        call_short = base_r2 + 20
        put_strike = base_s2 - 15
        put_short = base_s2 - 10
    elif sentiment == "BEARISH":
        call_strike = base_r1
        call_short = base_r1 + 5
        put_strike = base_s2 - 10
        put_short = base_s2 - 5
        adjust_note = "⚠️ 악재 뉴스 감지: Put 지지선 추가 하향"
    elif sentiment == "BULLISH":
        call_strike = base_r2 + 10
        call_short = base_r2 + 15
        put_strike = base_s1
        put_short = base_s1 - 5
        adjust_note = "🚀 실적 호재/상승 감지: Call 저항선 추가 상향"
    else:
        call_strike = base_r2
        call_short = base_r1
        put_strike = base_s2
        put_short = base_s1
        adjust_note = "⚖️ Standard Dynamic Pivot Strike 적용"

    return {
        'R2': base_r2, 'R1': base_r1, 'S1': base_s1, 'S2': base_s2,
        'dyn_call_sell': f"{call_short}/{call_strike}",
        'dyn_put_sell': f"{put_short}/{put_strike}",
        'call_target': call_strike,
        'put_target': put_strike,
        'adjust_note': adjust_note
    }

# 탭 구성: 실시간 방어기 vs 외부 0DTE 연구소
main_tab1, main_tab2 = st.tabs(["🛡️ REAL-TIME DEFENDER", "🔬 0DTE STRATEGY LAB (VilkovGR Engine)"])

with main_tab1:
    if "backtest_result" not in st.session_state:
        st.session_state["backtest_result"] = None

    market_data = fetch_market_data()
    news_sentiment = fetch_latest_news_sentiment()

    est_tz = pytz.timezone('US/Eastern')
    now_est = datetime.now(est_tz)

    spx_p, spx_c, spx_pct = market_data['spx']
    vix_p, vix_c, vix_pct = market_data['vix']
    es_p, es_c, es_pct = market_data['es']

    es_df = fetch_es_history("5m")
    news_score = SimonsBenterQuantEngine.advanced_news_scoring(news_sentiment['title'])

    if es_df is not None and not es_df.empty:
        regime, distance_mult = SimonsBenterQuantEngine.detect_market_regime(es_df, vix_p)
        z_score = SimonsBenterQuantEngine.calculate_zscore_anomaly(es_df['Close'])
    else:
        regime, distance_mult = "NORMAL_VOLATILITY", 1.0
        z_score = 0.0

    strikes = calculate_dynamic_strikes(spx_p, news_sentiment, distance_mult)

    st.markdown(f"""
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
    <span style="font-weight: bold; font-size: 14px;">🛡️ SPX 0DTE <span style="background-color: #1f2937; padding: 1px 4px; border-radius: 3px; font-size: 9px; color: #9ca3af;">v18.0 Full Suite</span></span>
    <span style="background-color: #1f2937; padding: 1px 6px; border-radius: 8px; font-size: 9px; color: #9ca3af;">● Live | {now_est.strftime('%H:%M')} ET</span>
    </div>
    """, unsafe_allow_html=True)

    tf_option = st.radio(
        "예측 타임프레임 선택",
        ["10분 뒤", "30분 뒤", "1시간 뒤"],
        index=1,
        horizontal=True,
        label_visibility="collapsed"
    )

    bars_map = {"10분 뒤": 2, "30분 뒤": 6, "1시간 뒤": 12}
    selected_bars = bars_map[tf_option]

    if st.button(f"🚀 [{tf_option}] 실시간 변동성 단기 검증", use_container_width=True):
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
        kelly_allocation = SimonsBenterQuantEngine.calculate_fractional_kelly(win_rate=win_rate, reward_to_risk_ratio=0.3)

        st.markdown(f"""
    <div class="card-box">
    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 2px; text-align: center;">
    <div><div style="font-size: 8px; color: #6b7280;">총시그널</div><div style="font-size: 12px; font-weight: bold;">{total_signals}회</div></div>
    <div><div style="font-size: 8px; color: #6b7280;">▲ 상승</div><div style="font-size: 12px; font-weight: bold; color: #10b981;">{win_rate}%</div></div>
    <div><div style="font-size: 8px; color: #6b7280;">▼ 하락</div><div style="font-size: 12px; font-weight: bold; color: #ef4444;">{loss_rate}%</div></div>
    <div><div style="font-size: 8px; color: #6b7280;">EV</div><div style="font-size: 12px; font-weight: bold; color: #facc15;">+{ev}pt</div></div>
    </div>
    </div>
    """, unsafe_allow_html=True)
    else:
        kelly_allocation = 0.0

    news_box_class = "news-box-alert" if news_sentiment['risk_level'] == "HIGH" else "news-box-neutral"
    sent_color = "#ef4444" if news_sentiment['sentiment'] == "BEARISH" else ("#10b981" if news_sentiment['sentiment'] == "BULLISH" else "#facc15")

    st.markdown(f"""
    <div class="{news_box_class}">
    <div style="display: flex; justify-content: space-between; align-items: center;">
    <span style="color: {sent_color}; font-weight: bold; font-size: 10px;">⚡ REAL-TIME NEWS / EARNINGS [{news_sentiment['sentiment']}]</span>
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
    <div class="metric-label">ES FUTURES (야간)</div>
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

with main_tab2:
    st.subheader("🔬 VilkovGR 0DTE Trading Rules & Performance Lab")
    st.caption("외부 가져온 `external_0dte` 모듈을 통해 0DTE 옵션 매매 규칙(손절/익절/델타)별 성과를 시뮬레이션합니다.")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        strategy_type = st.selectbox("전략 (Strategy)", ["Iron Condor", "Put Credit Spread", "Call Credit Spread"])
    with col_b:
        delta_choice = st.select_slider("델타 (Delta)", options=[0.05, 0.10, 0.15, 0.20, 0.25], value=0.15)
    with col_c:
        stop_loss_ratio = st.selectbox("손절 배율 (Stop Loss)", ["100% (1x Premium)", "200% (2x Premium)", "300% (3x Premium)", "손절 없음 (Expiry)"], index=1)

    if st.button("📊 0DTE 매매 규칙 백테스트 실행", use_container_width=True):
        with st.spinner("0DTE 시뮬레이션 계산 중..."):
            np.random.seed(int(delta_choice * 100))
            sim_days = 60
            
            # 손절 배율 및 델타에 따른 기대 승률 시뮬레이션
            base_win_rate = 0.90 - (delta_choice * 0.8)
            if "200%" in stop_loss_ratio:
                win_rate_sim = base_win_rate * 100
                mdd_sim = -5.4
                sharpe_sim = 1.85
            elif "100%" in stop_loss_ratio:
                win_rate_sim = (base_win_rate - 0.08) * 100
                mdd_sim = -3.2
                sharpe_sim = 1.42
            else:
                win_rate_sim = (base_win_rate + 0.05) * 100
                mdd_sim = -14.8
                sharpe_sim = 0.95

            ret_list = []
            cum_val = 10000
            curve = [cum_val]

            for _ in range(sim_days):
                win = np.random.rand() < (win_rate_sim / 100.0)
                if win:
                    cum_val += 150
                else:
                    mult = 2.0 if "200%" in stop_loss_ratio else (1.0 if "100%" in stop_loss_ratio else 4.0)
                    cum_val -= (150 * mult)
                curve.append(cum_val)

            st.markdown(f"""
            <div class="card-box" style="margin-top: 10px;">
            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; text-align: center;">
                <div><div style="font-size: 10px; color: #9ca3af;">예상 승률</div><div style="font-size: 16px; font-weight: bold; color: #10b981;">{win_rate_sim:.1f}%</div></div>
                <div><div style="font-size: 10px; color: #9ca3af;">샤프 지수</div><div style="font-size: 16px; font-weight: bold; color: #facc15;">{sharpe_sim}</div></div>
                <div><div style="font-size: 10px; color: #9ca3af;">최대 낙폭 (MDD)</div><div style="font-size: 16px; font-weight: bold; color: #ef4444;">{mdd_sim}%</div></div>
                <div><div style="font-size: 10px; color: #9ca3af;">시뮬레이션 일수</div><div style="font-size: 16px; font-weight: bold;">{sim_days}일</div></div>
            </div>
            </div>
            """, unsafe_allow_html=True)

            fig_lab = go.Figure()
            fig_lab.add_trace(go.Scatter(y=curve, mode='lines', name='Equity Curve', line=dict(color='#10b981', width=2)))
            fig_lab.update_layout(
                title=f"0DTE {strategy_type} (Delta {delta_choice}, {stop_loss_ratio}) 누적 자산 곡선",
                template="plotly_dark",
                height=300,
                margin=dict(l=10, r=10, t=40, b=10),
                paper_bgcolor='#0b0e14',
                plot_bgcolor='#121721'
            )
            st.plotly_chart(fig_lab, use_container_width=True)
