"""
app.py에서 market_data를 언패킹하는 부분 아래에 추가하세요.
(spx_p, spx_c, spx_pct = market_data['spx'] 등을 가져온 직후)
"""

def fmt(val, fmt_str="{:,.2f}"):
    """None이면 'N/A'를 반환, 아니면 포맷팅."""
    return fmt_str.format(val) if val is not None else "N/A"

def safe(val, default=0.0):
    """계산용: None이면 0.0으로 (색상/부호 계산이 죽지 않게)."""
    return val if val is not None else default


# --- 사용 예 (헤더 카드 부분 교체) ---
# 기존:
#   spx_color = "#10b981" if spx_c >= 0 else "#ef4444"
# 수정:
spx_color = "#10b981" if safe(spx_c) >= 0 else "#ef4444"
vix_color = "#ef4444" if safe(vix_c) >= 0 else "#10b981"
es_color = "#10b981" if safe(es_c) >= 0 else "#ef4444"
spy_color = "#10b981" if safe(spy_c) >= 0 else "#ef4444"

# 카드 렌더링 시 f-string 안의 {spx_p:,.2f} 대신 {fmt(spx_p)} 사용
# 예: <div class="metric-val">{fmt(spx_p)}</div>

# --- 에러 배너 (헤더 아래에 추가) ---
errors = market_data.get('errors', [])
if errors:
    err_text = " / ".join(errors[:3])
    st.markdown(f"""
    <div style="background-color:#3f1d1d; border:1px solid #7f1d1d; border-radius:6px;
                padding:4px 8px; margin-bottom:4px; font-size:10px; color:#fca5a5;">
    ⚠️ 일부 데이터 조회 실패: {err_text}
    </div>
    """, unsafe_allow_html=True)
