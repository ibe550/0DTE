let _vix1dPrice = null;
let _vixPrice = null;

function updateVixRatio() {
    const card = $('vix-ratio-card');
    const badge = $('vix-status-badge');
    const desc = $('vix-status-desc');
    const ratioEl = $('vix-ratio-val');
    const dot = $('vix-status-dot');
    if (!card || !badge || !desc || !ratioEl || !dot) return;

    if (!isNum(_vix1dPrice) || !isNum(_vixPrice) || _vixPrice <= 0) {
        badge.className = 'px-2 py-0.5 rounded font-bold text-[9px] sm:text-xs bg-slate-800 text-slate-400 border border-slate-700';
        badge.innerText = '집계 대기';
        desc.innerText = 'VIX 1D 및 VIX 실시간 데이터를 확인하는 중...';
        ratioEl.innerText = 'Ratio --';
        dot.className = 'w-2 h-2 rounded-full bg-slate-500';
        card.className = 'card px-2.5 py-1.5 sm:px-3 sm:py-2 lg:px-4 lg:py-2.5 mb-2 lg:mb-3 flex items-center justify-between text-[10px] sm:text-xs lg:text-sm bg-slate-900/80 border-slate-800';
        return;
    }

    const ratio = _vix1dPrice / _vixPrice;
    ratioEl.innerText = `Ratio ${ratio.toFixed(2)}`;

    if (ratio <= 0.85) {
        card.className = 'card px-2.5 py-1.5 sm:px-3 sm:py-2 lg:px-4 lg:py-2.5 mb-2 lg:mb-3 flex items-center justify-between text-[10px] sm:text-xs lg:text-sm bg-emerald-950/25 border-emerald-800/70 shadow-sm transition-all';
        dot.className = 'w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]';
        badge.className = 'px-2 py-0.5 rounded font-black text-[9px] sm:text-xs bg-emerald-950 text-emerald-300 border border-emerald-500 tracking-tight';
        badge.innerText = '🟢 스프레드 진입 적격';
        desc.innerHTML = '<span class="text-emerald-300 font-bold">정상 콘탱고</span> · 당일 돌발 급변동 위험 낮음 (프리미엄 수취 최적)';
    } else if (ratio < 1.00) {
        card.className = 'card px-2.5 py-1.5 sm:px-3 sm:py-2 lg:px-4 lg:py-2.5 mb-2 lg:mb-3 flex items-center justify-between text-[10px] sm:text-xs lg:text-sm bg-amber-950/20 border-amber-800/60 transition-all';
        dot.className = 'w-2 h-2 rounded-full bg-amber-400';
        badge.className = 'px-2 py-0.5 rounded font-bold text-[9px] sm:text-xs bg-amber-950 text-amber-300 border border-amber-600 tracking-tight';
        badge.innerText = '🟡 일반 장세 (선별 진입)';
        desc.innerHTML = '<span class="text-amber-300 font-semibold">표준 변동성</span> · Wall 및 EM 이격 15pt 이상 확보 권장';
    } else {
        card.className = 'card px-2.5 py-1.5 sm:px-3 sm:py-2 lg:px-4 lg:py-2.5 mb-2 lg:mb-3 flex items-center justify-between text-[10px] sm:text-xs lg:text-sm bg-rose-950/40 border-rose-600/80 shadow-md transition-all';
        dot.className = 'w-2 h-2 rounded-full bg-rose-500 animate-ping';
        badge.className = 'px-2 py-0.5 rounded font-black text-[9px] sm:text-xs bg-rose-950 text-rose-300 border border-rose-500 tracking-tight animate-pulse';
        badge.innerText = '🚨 크레딧 스프레드 금지';
        desc.innerHTML = '<span class="text-rose-300 font-bold">변동성 커브 역전(백워데이션)</span> · 0DTE 폭주 및 감마 스퀴즈 경보 (매도 금지)';
    }
}

function renderQuote(pfx, q, opts = {}) {
    if (!q) {
        setText(pfx + '-price', NA); setText(pfx + '-change', NA); setText(pfx + '-source', NA);
        setTone(pfx + '-price', 'text-slate-500'); setTone(pfx + '-change', 'text-slate-500');
        if (pfx === 'vix1d') { _vix1dPrice = null; updateVixRatio(); }
        if (pfx === 'vix') { _vixPrice = null; updateVixRatio(); }
        return;
    }
    setText(pfx + '-price', fmt(q.price, 2));
