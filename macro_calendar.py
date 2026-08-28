"""
매크로 이벤트 캘린더.

0DTE 옵션은 FOMC/CPI/고용지표(NFP) 발표일, 옵션 만기일(OPEX)에 변동성이
평소와 완전히 다르게 튄다. 이 모듈은 그런 날을 감지해서 스트라이크 안전거리를
얼마나 넓혀야 하는지 배수로 알려준다.

[데이터 출처 및 주의사항]
- FOMC 일정: 연준(Federal Reserve) 공식 발표 기준 (2026년 확정, 2027년은 잠정)
- CPI/NFP 일정: 미국 노동통계국(BLS) 공식 발표 캘린더 기준 (2026년)
- 마지막 확인일: 2026-08-23
- 이 날짜들은 하드코딩되어 있어서, 2027년 CPI/NFP 실제 일정이나 2028년 이후
  데이터는 없다. 주기적으로 아래 표를 업데이트해야 한다
  (FOMC: federalreserve.gov/monetarypolicy/fomccalendars.htm,
   CPI/NFP: bls.gov/schedule).
- 목록에 없는 날짜는 그냥 "매크로 이벤트 없음"으로 처리된다 (에러 없이 안전하게).
"""

from datetime import date
import calendar

# --- FOMC 금리 결정일 (2일 회의의 둘째 날, 오후 2시 ET 발표) ---
FOMC_DATES = {
    # 2026 (연준 공식 확정 일정)
    "2026-01-28": "FOMC 금리결정",
    "2026-03-18": "FOMC 금리결정 (SEP·점도표)",
    "2026-04-29": "FOMC 금리결정",
    "2026-06-17": "FOMC 금리결정 (SEP·점도표)",
    "2026-07-29": "FOMC 금리결정",
    "2026-09-16": "FOMC 금리결정 (SEP·점도표)",
    "2026-10-28": "FOMC 금리결정",
    "2026-12-09": "FOMC 금리결정 (SEP·점도표)",
    # 2027 (연준 잠정 일정 - 직전 회의에서 최종 확정됨)
    "2027-01-27": "FOMC 금리결정",
    "2027-03-17": "FOMC 금리결정 (SEP·점도표)",
    "2027-04-28": "FOMC 금리결정",
    "2027-06-09": "FOMC 금리결정 (SEP·점도표)",
    "2027-07-28": "FOMC 금리결정",
    "2027-09-15": "FOMC 금리결정 (SEP·점도표)",
    "2027-10-27": "FOMC 금리결정",
    "2027-12-08": "FOMC 금리결정 (SEP·점도표)",
}

# --- CPI(소비자물가지수) 발표일, 오전 8:30 ET ---
CPI_DATES = {
    "2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10",
    "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12",
    "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10",
}

# --- NFP(비농업 고용지표) 발표일, 오전 8:30 ET ---
NFP_DATES = {
    "2026-01-09", "2026-02-11", "2026-03-06", "2026-04-03",
    "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07",
    "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
}


def _third_friday(year, month):
    """해당 월의 세 번째 금요일 (옵션 월간 만기일)."""
    c = calendar.Calendar(firstweekday=calendar.MONDAY)
    fridays = [d for d in c.itermonthdates(year, month)
               if d.month == month and d.weekday() == calendar.FRIDAY]
    return fridays[2]


def _build_opex_dates(years):
    """분기 만기(쿼드위칭: 3/6/9/12월)와 월간 만기를 구분해서 계산."""
    opex = {}
    for year in years:
        for month in range(1, 13):
            d = _third_friday(year, month)
            if month in (3, 6, 9, 12):
                opex[d.isoformat()] = "쿼드위칭 (분기 옵션 만기)"
            else:
                opex[d.isoformat()] = "월간 옵션 만기 (OPEX)"
    return opex


OPEX_DATES = _build_opex_dates([2026, 2027])

# 이벤트 유형별 위험도 및 스트라이크 안전거리 배수
_RISK_MULT = {
    "FOMC": ("EXTREME", 2.0),
    "CPI": ("HIGH", 1.6),
    "NFP": ("HIGH", 1.6),
    "QUAD_WITCH": ("MEDIUM_HIGH", 1.3),
    "OPEX": ("MEDIUM", 1.15),
}


def get_todays_macro_events(check_date=None):
    """
    주어진 날짜(기본값: 오늘)에 해당하는 매크로 이벤트 목록을 반환한다.
    반환: [{"name": str, "type": str, "risk": str, "mult": float}, ...]
    """
    if check_date is None:
        check_date = date.today()
    date_str = check_date.isoformat()
    events = []

    if date_str in FOMC_DATES:
        risk, mult = _RISK_MULT["FOMC"]
        events.append({"name": FOMC_DATES[date_str], "type": "FOMC", "risk": risk, "mult": mult})

    if date_str in CPI_DATES:
        risk, mult = _RISK_MULT["CPI"]
        events.append({"name": "CPI(소비자물가) 발표 08:30 ET", "type": "CPI", "risk": risk, "mult": mult})

    if date_str in NFP_DATES:
        risk, mult = _RISK_MULT["NFP"]
        events.append({"name": "고용지표(NFP) 발표 08:30 ET", "type": "NFP", "risk": risk, "mult": mult})

    if date_str in OPEX_DATES:
        opex_name = OPEX_DATES[date_str]
        event_type = "QUAD_WITCH" if "쿼드위칭" in opex_name else "OPEX"
        risk, mult = _RISK_MULT[event_type]
        events.append({"name": opex_name, "type": event_type, "risk": risk, "mult": mult})

    return events


def get_macro_risk_multiplier(check_date=None):
    """
    오늘 매크로 이벤트가 있으면 그 중 가장 위험한 배수를 반환.
    이벤트가 없으면 (1.0, []) 반환.
    """
    events = get_todays_macro_events(check_date)
    if not events:
        return 1.0, []
    mult = max(e["mult"] for e in events)
    return mult, events
