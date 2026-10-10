function renderEconEvents(e) {
    const card = $('econ-card');
    card.classList.remove('hidden');
    setText('econ-source', (e && e.source) ? e.source : '공식 경제 캘린더 (ET 전용)');

    // 1. FLASH 실시간 속보 렌더링
    const flashBox = $('flash-news-box'), flashList =$('flash-news-list');
    const flashItems = (e && e.flash_news) ? e.flash_news : [];
    if (flashItems.length > 0) {
        flashBox.classList.remove('hidden');
        flashList.innerHTML = flashItems.map(item => {
            const badgeCls = item.tone === 'bull' ? 'bg-emerald-950 text-emerald-300 border-emerald-600' : (item.tone === 'bear' ? 'bg-rose-950 text-rose-300 border-rose-600' : 'bg-amber-950 text-amber-300 border-amber-600');
            return `<div class="py-1 flex items-center justify-between text-[11px] sm:text-xs bg-slate-950/60 p-1.5 rounded border border-slate-800/80 gap-2">
                <span class="flex items-center space-x-1.5 truncate">
                    <span class="text-[9px] sm:text-[10px] px-1.5 py-0.2 rounded font-black border ${badgeCls} shrink-0">${escapeHtml(item.tag)}</span>
                    <span class="text-slate-200 font-semibold truncate" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</span>
                </span>
                <span class="text-[9px] text-slate-500 font-mono shrink-0">${escapeHtml(item.source)}</span>
            </div>`;
        }).join('');
    } else {
        flashBox.classList.add('hidden');
    }

    // 2. 정규 경제 발표 일정 렌더링
    const items = (e && e.items) ? e.items : [];
    if (!items.length) {
        $('econ-list').innerHTML = '<div class="text-[11px] sm:text-xs lg:text-sm text-slate-500 py-0.5">현재 예정되거나 진행 중인 발표가 없습니다.</div>';
        return;
    }

    $('econ-list').innerHTML = items.map((it) => {
        const isPassed = it.passed, hasActual = it.has_actual, tone = it.eval_tone, tag = it.eval_tag;
        let statusBadge = '', dot = 'bg-slate-500', sentenceColor = 'text-slate-400';

        if (tone === 'bull') {
            dot = 'bg-emerald-400';
            statusBadge = `<span class="text-[9px] sm:text-[10px] lg:text-xs bg-emerald-950 text-emerald-300 border border-emerald-600 px-1.5 py-0.5 rounded font-black tracking-tight">${escapeHtml(tag)}</span>`;
            sentenceColor = 'text-emerald-300 font-bold';
        } else if (tone === 'bear') {
            dot = 'bg-rose-400';
            statusBadge = `<span class="text-[9px] sm:text-[10px] lg:text-xs bg-rose-950 text-rose-300 border border-rose-600 px-1.5 py-0.5 rounded font-black tracking-tight">${escapeHtml(tag)}</span>`;
            sentenceColor = 'text-rose-300 font-bold';
        } else if (tone === 'flat') {
            dot = 'bg-slate-400';
            statusBadge = `<span class="text-[9px] sm:text-[10px] lg:text-xs bg-slate-800 text-slate-300 border border-slate-600 px-1.5 py-0.5 rounded font-bold">${escapeHtml(tag || '발표 완료')}</span>`;
            sentenceColor = 'text-slate-300 font-medium';
        } else {
            if (isPassed) {
                dot = 'bg-amber-400 animate-pulse';
                statusBadge = `<span class="text-[9px] sm:text-[10px] lg:text-xs bg-amber-950 text-amber-300 border border-amber-600 px-1.5 py-0.5 rounded font-bold">${escapeHtml(tag || '⏳ 속보 수신 중')}</span>`;
                sentenceColor = 'text-amber-300/80 font-mono';
            } else {
                dot = 'bg-slate-500';
                if (it.forecast) statusBadge = `<span class="text-[9px] sm:text-[10px] lg:text-xs bg-slate-800 text-slate-400 border border-slate-700 px-1.5 py-0.5 rounded font-mono">예상 ${escapeHtml(it.forecast)}</span>`;
            }
        }

        const titleCls = (tone === 'bull') ? 'text-emerald-300 font-bold' : ((tone === 'bear') ? 'text-rose-300 font-bold' : (hasActual ? 'text-slate-200 font-bold' : 'text-slate-300'));
        const timeStatus = hasActual ? '발표완료' : (isPassed ? (tone === 'pending' ? '진행/속보' : '완료') : '예정');

        return `<div class="py-1.5 border-b border-slate-800/60 last:border-0">
            <div class="flex items-center justify-between text-[11px] sm:text-xs lg:text-sm gap-2">
                <span class="flex items-center space-x-1.5 flex-wrap gap-y-1 truncate">
                    <span class="w-1.5 h-1.5 rounded-full ${dot} inline-block shrink-0"></span>
                    <span class="${titleCls} truncate">${escapeHtml(it.title)}</span>
                    ${statusBadge}
                </span>
                <span class="font-mono text-[10px] sm:text-xs text-slate-400 shrink-0">${escapeHtml(it.time)} · ${timeStatus}</span>
            </div>
            ${it.eval_sentence ? `<div class="text-[10px] sm:text-[11px] lg:text-xs pl-3 mt-0.5 leading-snug break-words ${sentenceColor}">${escapeHtml(it.eval_sentence)}</div>` : ''}
        </div>`;
    }).join('');
}
