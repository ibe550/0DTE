# ─────────────────────────────────────────────────────────────
# 주요 경제 지표 캘린더 & 지수 영향 자동 판정
# ─────────────────────────────────────────────────────────────
ECON_TITLE_KR = {
    "Average Hourly Earnings m/m": "시간당 평균 임금 (MoM)",
    "Average Hourly Earnings y/y": "시간당 평균 임금 (YoY)",
    "Non-Farm Employment Change": "비농업 고용지수 (NFP)",
    "Unemployment Rate": "실업률",
    "Core PCE Price Index m/m": "근원 PCE 물가지수 (MoM)",
    "Core PCE Price Index y/y": "근원 PCE 물가지수 (YoY)",
    "PCE Price Index m/m": "PCE 물가지수 (MoM)",
    "PCE Price Index y/y": "PCE 물가지수 (YoY)",
    "CPI m/m": "소비자물가지수 (CPI MoM)",
    "CPI y/y": "소비자물가지수 (CPI YoY)",
    "Core CPI m/m": "근원 CPI (MoM)",
    "Core CPI y/y": "근원 CPI (YoY)",
    "PPI m/m": "생산자물가지수 (PPI MoM)",
    "Core PPI m/m": "근원 PPI (MoM)",
    "Unemployment Claims": "신규 실업수당 청구건수",
    "Advance GDP q/q": "GDP 성장률 (속보치)",
    "FOMC Statement": "FOMC 성명서 발표",
    "Federal Funds Rate": "연준 기준금리 결정",
    "FOMC Press Conference": "파월 의장 기자회견",
    "ISM Manufacturing PMI": "ISM 제조업 PMI",
    "ISM Services PMI": "ISM 서비스업 PMI",
    "Retail Sales m/m": "소매판매 (MoM)",
}

HIGH_IMPACT_KEYWORDS = [
    "pce", "cpi", "ppi", "employment", "non-farm", "unemployment", "claims",
    "gdp", "fomc", "fed ", "federal funds", "powell", "ism", "jolts",
    "retail sales", "hourly earnings"
]


def evaluate_econ_result(title_en, actual_str, forecast_str, previous_str):
    if not actual_str:
        return {
            "tag": None,
            "tone": "pending",
            "sentence": f"시장 예상치: {forecast_str}" + (f" (이전: {previous_str})" if previous_str else "")
        }

    act_num = _parse_val(actual_str)
    fc_num = _parse_val(forecast_str) if forecast_str else _parse_val(previous_str)
    cmp_label = "예상" if forecast_str else "이전"
    cmp_str = forecast_str or previous_str

    t_lower = title_en.lower()
    is_inflation = any(k in t_lower for k in ["cpi", "pce", "ppi", "hourly earnings", "price index"])
    is_unemployment = any(k in t_lower for k in ["unemployment rate", "unemployment claims", "jobless claims"])
    is_nfp = "non-farm" in t_lower or "employment change" in t_lower

    if act_num is not None and fc_num is not None:
        diff = act_num - fc_num
        if abs(diff) < 1e-5:
            return {
                "tag": "⚪ 부합 (중립)",
                "tone": "flat",
                "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 시장 예상 부합 (중립)"
            }

        if is_inflation:
            if diff > 0:
                return {
                    "tag": "🔴 임금/물가 과열 (하락)",
                    "tone": "bear",
                    "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 인플레 압력 상승 (지수 악재)"
                }
            return {
                "tag": "🟢 임금/물가 안정 (상승)",
                "tone": "bull",
                "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 인플레 둔화 (지수 호재)"
            }

        elif is_unemployment:
            if diff > 0:
                return {
                    "tag": "⚠️ 실업 증가 (하락)",
                    "tone": "bear",
                    "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 고용 둔화 및 경기 침체 우려"
                }
            return {
                "tag": "🟢 실업 감소 (상승)",
                "tone": "bull",
                "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 고용 시장 견조 (지수 호재)"
            }

        elif is_nfp:
            if diff > 0:
                return {
                    "tag": "🟢 고용 호조 (상승)",
                    "tone": "bull",
                    "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 고용 지표 강세 (경기 연착륙 호재)"
                }
            return {
                "tag": "🔴 고용 급감 (하락)",
                "tone": "bear",
                "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 고용 쇼크 (경기 둔화 악재)"
            }

        else:
            if diff > 0:
                return {
                    "tag": "🟢 경기 호조 (상승)",
                    "tone": "bull",
                    "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 지표 호조 (지수 호재)"
                }
            return {
                "tag": "🔴 경기 위축 (하락)",
                "tone": "bear",
                "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str} · 지표 부진 (지수 악재)"
            }

    return {
        "tag": "발표 완료",
        "tone": "flat",
        "sentence": f"실제 {actual_str} ({cmp_label}: {cmp_str})"
    }


def fetch_global_econ_calendar():
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=4.5)
        if r.status_code != 200:
            return None
        data = r.json()
        parsed = []
        for it in data:
            if it.get("country") != "USD":
                continue
            title = (it.get("title") or "").strip()
            impact = it.get("impact", "")
            t_lower = title.lower()

            if not ((impact == "High") or any(k in t_lower for k in HIGH_IMPACT_KEYWORDS)):
                continue

            raw_date = it.get("date", "")
            if not raw_date:
                continue

            try:
                dt_obj = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).astimezone(ET)
            except Exception:
                continue

            kr_name = ECON_TITLE_KR.get(title, title)
            parsed.append({
                "title": kr_name,
                "title_en": title,
                "dt": dt_obj,
                "ts": dt_obj.timestamp(),
                "time": dt_obj.strftime("%H:%M ET"),
                "impact": impact,
                "forecast": (it.get("forecast") or "").strip(),
                "previous": (it.get("previous") or "").strip(),
                "actual": (it.get("actual") or "").strip()
            })
        return parsed
    except Exception:
        return None


def get_today_econ_events(now_et):
    # 캐시를 900초에서 30초로 단축하여 실시간 발표치 즉시 반영
    events = cached("econ_events_data", 30, fetch_global_econ_calendar)
    now_ts = now_et.timestamp()

    if not events:
        return {"items": [], "source": "N/A", "error": "경제 캘린더 조회 실패"}

    today = now_et.date()
    tomorrow = today + timedelta(days=1)

    today_items = [e for e in events if e["dt"].date() == today]
    active_today_items = [e for e in today_items if (e["ts"] > now_ts) or (now_ts - e["ts"] <= 3600)]

    target_items = active_today_items
    is_tomorrow = False
    if not active_today_items and now_et.hour >= 16:
        tomorrow_items = [e for e in events if e["dt"].date() == tomorrow]
        if tomorrow_items:
            target_items = tomorrow_items
            is_tomorrow = True

    target_items.sort(key=lambda x: x["ts"])

    out_items = []
    for it in target_items:
        passed = (it["ts"] <= now_ts)
        has_actual = bool(it["actual"])
        prefix = f"[{it['dt'].strftime('%m/%d')}] " if is_tomorrow else ""
        eval_res = evaluate_econ_result(it["title_en"], it["actual"], it["forecast"], it["previous"])

        out_items.append({
            "title": f"{prefix}{it['title']}",
            "title_en": it["title_en"],
            "time": it["time"],
            "ts": it["ts"],
            "passed": passed,
            "has_actual": has_actual,
            "impact": it.get("impact", "High"),
            "actual": it["actual"],
            "forecast": it["forecast"],
            "previous": it["previous"],
            "eval_tag": eval_res["tag"],
            "eval_tone": eval_res["tone"],
            "eval_sentence": eval_res["sentence"],
        })

    return {
        "items": out_items,
        "source": "공식 경제 캘린더 (실시간 판정 · ET 전용)",
        "error": None
    }
