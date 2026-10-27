"""SPX 0DTE DEFENDER - market-data API (FastAPI on Vercel)"""
import html as html_lib
import hmac as hmac_lib
import json
import math
import os
import re as re_lib
import secrets as secrets_lib
import time
import threading

# DEPLOY_MARKER: 2026-10-18 auth-v2 (배포 확인용)
# AUTH_DISABLED: True면 비밀번호/토큰 검사 없이 모두 통과 (임시 테스트용)
# 진단 모드: False로 두면 아래 _dashboard_users()가 상세 진단 정보를 반환
AUTH_DISABLED = False
AUTH_DIAG_MODE = False  # True면 로그인 실패 시 값의 메타정보(길이·문자코드) 반환 (비밀번호 노출 없음)
import xml.etree.ElementTree as ET_xml
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional

import pytz
import requests
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI()
handler = app
application = app

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ET = pytz.timezone("US/Eastern")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
SCHWAB_BASE_URL = "https://api.schwabapi.com/marketdata/v1"
SRC_SCHWAB = "Charles Schwab"
SRC_YAHOO = "Yahoo Finance"
SECONDS_PER_YEAR = 365.0 * 24 * 3600


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _parse_val(s):
    if not s or not isinstance(s, str):
        return None
    cleaned = (
        s.replace("%", "")
        .replace("K", "")
        .replace("k", "")
        .replace("M", "")
        .replace("m", "")
        .replace("B", "")
        .replace(",", "")
        .strip()
    )
    try:
        return float(cleaned)
    except ValueError:
        return None


_CACHE = {}
_REFRESHING = set()


def cached(key, ttl, fn):
    """인메모리 캐시 + SWR(Stale-While-Revalidate):
    - 신선하면(TTL 내) 캐시 반환
    - 만료했지만 유예 구간(TTL×3) 안이면 옛 값을 즉시 반환하고 백그라운드로 갱신
      → 폴링이 느린 외부 조회(Schwab 등)를 기다리지 않아 응답이 일정해진다
    - 유예 구간도 지났거나 캐시가 없으면 동기 계산 (기존 동작)
    """
    now = time.time()
    hit = _CACHE.get(key)
    if hit:
        age = now - hit[0]
        if age < ttl:
            return hit[1]
        if age < ttl * 3 and key not in _REFRESHING:
            _REFRESHING.add(key)

            def _bg():
                try:
                    v = fn()
                    if v is not None:
                        _CACHE[key] = (time.time(), v)
                except Exception:
                    pass
                finally:
                    _REFRESHING.discard(key)

            threading.Thread(target=_bg, daemon=True).start()
            return hit[1]
    val = fn()
    if val is not None:
        _CACHE[key] = (now, val)
        return val
    if hit:
        return hit[1]
    return None


def fmt_dollars(x):
    sign = "+" if x >= 0 else "-"
    a = abs(x)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if a >= div:
            return f"{sign}{a / div:.1f}{unit}"
    return f"{sign}{a:.0f}"


def src_kind(s):
    if not s:
        return "na"
    if s.startswith(SRC_SCHWAB):
        return "schwab"
    if s.startswith("Yahoo"):
        return "yahoo"
    return "other"


# ─────────────────────────────────────────────────────────────
# 관리용 엔드포인트 보호 (선택)
#  - Vercel 환경변수 CRON_SECRET 을 설정하면 test-alert / refresh-token 이 보호됩니다.
#  - 설정하지 않으면 기존처럼 열려 있습니다.
#  - Vercel Cron 은 CRON_SECRET 이 설정되어 있으면 Authorization: Bearer 헤더를 자동으로 보냅니다.
# ─────────────────────────────────────────────────────────────
def _admin_ok(request: Request):
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        return True
    if request.headers.get("authorization", "") == f"Bearer {secret}":
        return True
    return request.query_params.get("key") == secret


# ─────────────────────────────────────────────────────────────
# 영속 저장소 (Vercel KV / Redis)
# ─────────────────────────────────────────────────────────────
def _kv_config():
    url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    return (url.rstrip("/"), token) if url and token else (None, None)


def kv_cmd(*args):
    url, token = _kv_config()
    if not url:
        return None
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=list(args),
            timeout=4,
        )
        if r.status_code == 200:
            return r.json().get("result")
    except Exception:
        pass
    return None


def kv_get(key):
    return kv_cmd("GET", key)


def kv_set(key, value, ex_seconds=None):
    if ex_seconds:
        return kv_cmd("SET", key, value, "EX", str(int(ex_seconds))) is not None
    return kv_cmd("SET", key, value) is not None


KV_AVAILABLE = _kv_config()[0] is not None
_TOKEN = {"value": None, "exp": 0.0}
SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
KV_KEY_ACCESS = "schwab:access_token"
KV_KEY_ACCESS_EXP = "schwab:access_token_exp"
KV_KEY_REFRESH = "schwab:refresh_token"
REFRESH_TOKEN_TTL = 8 * 24 * 3600


# ─────────────────────────────────────────────────────────────
# 텔레그램 실시간 알림 시스템
#  - 방향별 쿨다운 10분 (DROP/SURGE 각각 — 반전 시그널이 묻히지 않음)
#  - 메모리 + Upstash KV 이중 기록 (Vercel 멀티인스턴스 중복 방지)
#  - 테스트 발송(force_test)은 쿨다운을 오염시키지 않음
#  - 전송 실패 시 1회 재시도
# ─────────────────────────────────────────────────────────────
_LAST_TELEGRAM_SHOCK = {}  # {type: ts}
TELEGRAM_COOLDOWN_SEC = 600


def send_telegram_shock_alert(shock_alert, spx_price, force_test=False):
    if not shock_alert or (not shock_alert.get("active") and not force_test):
        return {"status": "skipped", "reason": "알림 비활성"}
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_ids_raw = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_ids_raw:
        return {"status": "error", "reason": "환경변수 누락"}

    now_ts = time.time()
    s_type = shock_alert.get("type") or "GENERAL"
    kv_key = f"alert:telegram:last_ts:{s_type}"

    if not force_test:
        kv_last_ts = num(kv_get(kv_key)) if KV_AVAILABLE else None
        last_ts = max(_LAST_TELEGRAM_SHOCK.get(s_type, 0.0), kv_last_ts or 0.0)
        if now_ts - last_ts < TELEGRAM_COOLDOWN_SEC:
            return {"status": "skipped", "reason": f"쿨다운 침묵 중 ({s_type})"}

    title = shock_alert.get("title", "⚡ [변동성 쇼크]")
    time_info = shock_alert.get("elapsed_text") or shock_alert.get("timestamp") or ""
    details_str = "\n".join(f"• {d}" for d in shock_alert.get("details", []))
    price_str = f"{spx_price:.2f}" if spx_price else "N/A"

    msg = (
        f"{title}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📍 SPX 현재가: {price_str}\n"
        f"⏱ 발생 시각: {time_info}\n\n"
        f"🔍 상세 감지 내역:\n"
        f"{details_str}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"SPX 0DTE DEFENDER Realtime Alert"
    )

    chat_ids = [cid.strip() for cid in chat_ids_raw.split(",") if cid.strip()]
    results = []
    for cid in chat_ids:
        ok, err = False, None
        for _ in range(2):  # 1회 재시도 (일시적 네트워크 오류 대응)
            try:
                r = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": cid, "text": msg},
                    timeout=4,
                )
                if r.status_code == 200:
                    ok = True
                    break
                err = f"HTTP {r.status_code}"
            except Exception as e:
                err = str(e)[:120]
            time.sleep(1)
        results.append({"chat_id": cid, "ok": ok, **({} if ok else {"error": err})})

    # 테스트 발송은 쿨다운을 건드리지 않음 (실제 알람 억제 방지)
    if not force_test:
        _LAST_TELEGRAM_SHOCK[s_type] = now_ts
        if KV_AVAILABLE:
            kv_set(kv_key, str(now_ts), ex_seconds=TELEGRAM_COOLDOWN_SEC)

    return {"status": "sent", "results": results}


_LAST_REVERSAL_TG = {}  # {flip_key: ts} — 인스턴스 내 중복 발송 방지


def send_telegram_reversal_alert(flip, spx_price):
    """추세 전환 확정 텔레그램 알림. 같은 전환은 하루 1회만 (KV + 메모리 이중 가드)."""
    if not flip or not flip.get("at"):
        return {"status": "skipped", "reason": "전환 정보 없음"}
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_ids_raw = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_ids_raw:
        return {"status": "error", "reason": "환경변수 누락"}

    today = datetime.now(ET).strftime("%Y-%m-%d")
    gkey = f"{today}:{flip.get('at')}:{flip.get('to')}"
    kv_key = f"rev-tg:{gkey}"
    if gkey in _LAST_REVERSAL_TG:
        return {"status": "skipped", "reason": "이미 발송됨 (메모리)"}
    if KV_AVAILABLE and kv_get(kv_key):
        _LAST_REVERSAL_TG[gkey] = time.time()
        return {"status": "skipped", "reason": "이미 발송됨 (KV)"}
    _LAST_REVERSAL_TG[gkey] = time.time()
    if KV_AVAILABLE:
        try:
            kv_set(kv_key, "1", ex_seconds=36 * 3600)
        except Exception:
            pass

    frm = "상승" if flip.get("from") == "up" else "하락"
    to = "상승" if flip.get("to") == "up" else "하락"
    arrow = "📈" if flip.get("to") == "up" else "📉"
    price_str = f"{spx_price:,.2f}" if spx_price else "N/A"
    msg = (
        f"🔄 [추세 전환 확정]\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{arrow} {frm} 추세 → {to} 전환\n"
        f"📍 SPX 현재가: {price_str}\n"
        f"⏱ 확정 시각: {flip.get('at')} ET\n\n"
        f"🔍 충족 신호:\n"
        f"• VWAP 반대 마감 (10분봉 2연속)\n"
        f"• 구조 방어선 종가 돌파\n"
        f"• CVD 흐름 반전\n"
        f"━━━━━━━━━━━━━━━\n"
        f"SPX 0DTE DEFENDER Realtime Alert"
    )

    chat_ids = [cid.strip() for cid in chat_ids_raw.split(",") if cid.strip()]
    results = []
    for cid in chat_ids:
        ok, err = False, None
        for _ in range(2):
            try:
                r = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": cid, "text": msg},
                    timeout=4,
                )
                if r.status_code == 200:
                    ok = True
                    break
                err = f"HTTP {r.status_code}"
            except Exception as e:
                err = str(e)[:120]
            time.sleep(1)
        results.append({"chat_id": cid, "ok": ok, **({} if ok else {"error": err})})
    return {"status": "sent", "results": results}


_LAST_WARN_TG = {}  # {warn_key: ts} — 인스턴스 내 중복 발송 방지


def send_telegram_warn_alert(warn, spx_price):
    """추세 전환 경보(신호 2/3 충족) 텔레그램. 같은 세그먼트에서는 1회만 (KV + 메모리 이중 가드)."""
    if not warn or not warn.get("seg_from"):
        return {"status": "skipped", "reason": "경보 정보 없음"}
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_ids_raw = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_ids_raw:
        return {"status": "error", "reason": "환경변수 누락"}

    today = datetime.now(ET).strftime("%Y-%m-%d")
    gkey = f"{today}:{warn.get('seg_from')}:{warn.get('seg_dir')}"
    kv_key = f"rev-warn-tg:{gkey}"
    if gkey in _LAST_WARN_TG:
        return {"status": "skipped", "reason": "이미 발송됨 (메모리)"}
    if KV_AVAILABLE and kv_get(kv_key):
        _LAST_WARN_TG[gkey] = time.time()
        return {"status": "skipped", "reason": "이미 발송됨 (KV)"}
    _LAST_WARN_TG[gkey] = time.time()
    if KV_AVAILABLE:
        try:
            kv_set(kv_key, "1", ex_seconds=36 * 3600)
        except Exception:
            pass

    cur_dir = "상승" if warn.get("seg_dir") == "up" else "하락"
    new_dir = "하락" if warn.get("seg_dir") == "up" else "상승"
    arrow = "📉" if warn.get("seg_dir") == "up" else "📈"
    price_str = f"{spx_price:,.2f}" if spx_price else "N/A"
    msg = (
        f"⚠️ [추세 전환 경보]\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{arrow} {cur_dir} 추세 → {new_dir} 전환 신호 {warn.get('sig_count')}/{warn.get('sig_total')} 충족\n"
        f"📍 SPX 현재가: {price_str}\n"
        f"⏱ {warn.get('at')} ET 완성봉 기준\n\n"
        f"아직 확정 아님 — 다음 봉에서 확정 또는 소멸합니다.\n"
        f"━━━━━━━━━━━━━━━\n"
        f"SPX 0DTE DEFENDER Realtime Alert"
    )
    chat_ids = [cid.strip() for cid in chat_ids_raw.split(",") if cid.strip()]
    results = []
    for cid in chat_ids:
        ok, err = False, None
        for _ in range(2):
            try:
                r = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": cid, "text": msg},
                    timeout=4,
                )
                if r.status_code == 200:
                    ok = True
                    break
                err = f"HTTP {r.status_code}"
            except Exception as e:
                err = str(e)[:120]
            time.sleep(1)
        results.append({"chat_id": cid, "ok": ok, **({} if ok else {"error": err})})
    return {"status": "sent", "results": results}


_LAST_INV_TG = {}  # {inv_key: ts} — 인스턴스 내 중복 발송 방지


def send_telegram_invalidation_alert(inv, spx_price):
    """추세 전환 무효(확정가 이탈) 텔레그램. 같은 전환은 1회만 (KV + 메모리 이중 가드)."""
    if not inv or not inv.get("at"):
        return {"status": "skipped", "reason": "무효 정보 없음"}
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_ids_raw = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_ids_raw:
        return {"status": "error", "reason": "환경변수 누락"}

    today = datetime.now(ET).strftime("%Y-%m-%d")
    gkey = f"{today}:{inv.get('at')}:{inv.get('to')}"
    kv_key = f"rev-inv-tg:{gkey}"
    if gkey in _LAST_INV_TG:
        return {"status": "skipped", "reason": "이미 발송됨 (메모리)"}
    if KV_AVAILABLE and kv_get(kv_key):
        _LAST_INV_TG[gkey] = time.time()
        return {"status": "skipped", "reason": "이미 발송됨 (KV)"}
    _LAST_INV_TG[gkey] = time.time()
    if KV_AVAILABLE:
        try:
            kv_set(kv_key, "1", ex_seconds=36 * 3600)
        except Exception:
            pass

    to_dir = "상승" if inv.get("to") == "up" else "하락"
    arrow = "📈" if inv.get("to") == "up" else "📉"
    price_str = f"{spx_price:,.2f}" if spx_price else "N/A"
    px_str = f"{inv['px']:,.1f}" if inv.get("px") else "-"
    msg = (
        f"❌ [추세 전환 무효]\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{arrow} {inv.get('at')} {to_dir} 전환 확정 → 무효 (확정가 이탈)\n"
        f"📍 SPX 현재가: {price_str}\n"
        f"🎯 확정가: {px_str} — 반대 방향 5pt 이상 이탈\n"
        f"━━━━━━━━━━━━━━━\n"
        f"SPX 0DTE DEFENDER Realtime Alert"
    )
    chat_ids = [cid.strip() for cid in chat_ids_raw.split(",") if cid.strip()]
    results = []
    for cid in chat_ids:
        ok, err = False, None
        for _ in range(2):
            try:
                r = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": cid, "text": msg},
                    timeout=4,
                )
                if r.status_code == 200:
                    ok = True
                    break
                err = f"HTTP {r.status_code}"
            except Exception as e:
                err = str(e)[:120]
            time.sleep(1)
        results.append({"chat_id": cid, "ok": ok, **({} if ok else {"error": err})})
    return {"status": "sent", "results": results}


# ─────────────────────────────────────────────────────────────
# Schwab 토큰 인증 관리
# ─────────────────────────────────────────────────────────────
def get_schwab_token(force_refresh=False):
    now = time.time()
    if not force_refresh and _TOKEN["value"] and now < _TOKEN["exp"]:
        return _TOKEN["value"], "연결됨 (캐시)"

    app_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_SECRET")
    if not app_key:
        return None, "Schwab 환경변수 없음 (SCHWAB_APP_KEY)"

    if not force_refresh:
        kv_exp = num(kv_get(KV_KEY_ACCESS_EXP))
        if kv_exp and now < kv_exp - 30:
            kv_access = kv_get(KV_KEY_ACCESS)
            if kv_access:
                _TOKEN["value"] = kv_access
                _TOKEN["exp"] = kv_exp - 30
                return kv_access, "연결됨 (공유 캐시)"

    refresh_token = kv_get(KV_KEY_REFRESH) or os.environ.get("SCHWAB_REFRESH_TOKEN")
    if not refresh_token:
        return None, "refresh_token 없음 - /api/callback 으로 인증 필요"

    try:
        res = requests.post(
            SCHWAB_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(app_key, app_secret) if app_secret else None,
            timeout=6,
        )
        if res.status_code == 200:
            body = res.json()
            access_token = body.get("access_token")
            new_refresh = body.get("refresh_token")
            ttl = int(num(body.get("expires_in")) or 1800)
            _TOKEN["value"] = access_token
            _TOKEN["exp"] = now + max(60, ttl - 120)
            if KV_AVAILABLE:
                kv_set(KV_KEY_ACCESS, access_token, ex_seconds=ttl)
                kv_set(KV_KEY_ACCESS_EXP, str(now + ttl), ex_seconds=ttl)
                if new_refresh:
                    kv_set(KV_KEY_REFRESH, new_refresh, ex_seconds=REFRESH_TOKEN_TTL)
            return access_token, "연결됨 (새로 갱신)"
        print(f"[schwab] token refresh failed: HTTP {res.status_code}")
    except Exception as e:
        print(f"[schwab] token refresh error: {e}")
    return None, "Schwab 토큰 갱신 실패"


_SCHWAB_429_UNTIL = 0.0
_SCHWAB_429_COUNT = 0


def schwab_get(token, path, params=None, timeout=4):
    global _SCHWAB_429_UNTIL, _SCHWAB_429_COUNT
    if not token:
        return None
    # 429 백오프 중이면 호출 자체를 생략 (프론트는 캐시/CNBC 폴백으로 표시)
    now = time.time()
    if now < _SCHWAB_429_UNTIL:
        return None
    try:
        r = requests.get(
            f"{SCHWAB_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params=params,
            timeout=timeout,
        )
        if r.status_code == 200:
            _SCHWAB_429_COUNT = 0
            return r.json()
        if r.status_code == 429:
            _SCHWAB_429_COUNT += 1
            backoff = min(60.0, 5.0 * (2 ** (_SCHWAB_429_COUNT - 1)))
            _SCHWAB_429_UNTIL = now + backoff
            print(f"[schwab] 429 rate-limited on {path} — backing off {backoff:.0f}s")
        else:
            print(f"[schwab] GET {path} -> HTTP {r.status_code}")
    except Exception as e:
        print(f"[schwab] GET {path} error: {e}")
    return None


# ─────────────────────────────────────────────────────────────
# 실시간 시세 (Schwab 일괄 조회 + 못 받은 항목만 Yahoo 폴백)
# ─────────────────────────────────────────────────────────────
# 키(왼쪽)는 프론트엔드가 쓰는 이름, 값(오른쪽)은 Schwab 심볼
SCHWAB_QUOTES = OrderedDict([
    ("spx", "$SPX"),
    ("vix1d", "$VIX1D"),
    ("vix", "$VIX"),
    ("spy", "SPY"),
    ("es", "/ES"),
    ("wti", "/CL"),
    ("brent", "/BZ"),
    ("uso", "USO"),
    ("mag7", "MAGS"),
    ("yield-3m", "$IRX"),
    ("yield-10y", "$TNX"),
    ("yield-30y", "$TYX"),
])

# Schwab 에서 못 받았을 때만 사용하는 폴백
YAHOO_FUTURES = OrderedDict([
    ("es", "ES=F"),
    ("wti", "CL=F"),
    ("brent", "BZ=F"),
])

YIELD_SYMBOLS = ("$IRX", "$TNX", "$TYX")
FUT_MONTH_CODES = "FGHJKMNQUVXZ"


def make_quote(price, prev, change, source):
    price = num(price)
    if price is None:
        return None
    prev = num(prev)
    change = num(change)
    if change is None and prev is not None:
        change = price - prev
    if prev is None and change is not None:
        prev = price - change
    pct = (change / prev * 100.0) if (change is not None and prev) else None
    return {
        "price": price,
        "change": round(change, 2) if change is not None else None,
        "change_pct": round(pct, 2) if pct is not None else None,
        "source": source,
    }


def _find_quote(data, sym):
    """응답 키가 요청 심볼과 다를 수 있는 선물 대응 (/ES -> /ESZ26)"""
    info = data.get(sym)
    if isinstance(info, dict) and isinstance(info.get("quote"), dict):
        return info
    for k, v in data.items():
        if k == "errors" or not isinstance(v, dict):
            continue
        if (v.get("reference") or {}).get("product") == sym and isinstance(v.get("quote"), dict):
            return v
    return None


def _futures_candidates(root, now):
    """'/ES' 같은 루트 심볼이 거부될 때 시도할 개별 월물 심볼 목록 (예: /ESZ26)"""
    out = []
    quarterly = (root == "/ES")
    for i in range(0, 10):
        idx = now.month - 1 + i
        mm = idx % 12 + 1
        yy = now.year + idx // 12
        if quarterly and mm % 3 != 0:
            continue
        out.append(f"{root}{FUT_MONTH_CODES[mm - 1]}{str(yy)[-2:]}")
        if len(out) >= 3:
            break
    return out


def _quote_to_item(sym, label_sym, info):
    q = info.get("quote") if info else None
    if not isinstance(q, dict):
        return None
    p = q.get("lastPrice") or q.get("mark")
    if not p:  # None 또는 0 이면 건너뜀 (0.00 표시 방지)
        return None
    prev, chg = q.get("closePrice"), q.get("netChange")
    # Schwab 금리 지수($IRX/$TNX/$TYX)는 항상 10배 단위(예: 42.5 = 4.25%)로 옴.
    # 예전엔 "값 > 20"일 때만 나눠서 금리가 2% 밑으로 내려가면 10배로 표시되는 버그가 있었음.
    if sym in YIELD_SYMBOLS and num(p) is not None:
        p = num(p) / 10.0
        prev = (num(prev) / 10.0) if num(prev) is not None else None
        chg = (num(chg) / 10.0) if num(chg) is not None else None
    return make_quote(p, prev, chg, f"{SRC_SCHWAB} ({label_sym})")


def fetch_schwab_quotes(token, symbols):
    if not token:
        return {}
    out = {}
    data = schwab_get(token, "/quotes", {"symbols": ",".join(symbols), "fields": "quote,reference"})
    if not isinstance(data, dict):
        return out

    bad = (data.get("errors") or {}).get("invalidSymbols")
    if bad:
        print(f"[schwab] invalid symbols: {bad}")

    for sym in symbols:
        item = _quote_to_item(sym, sym, _find_quote(data, sym))
        if item:
            out[sym] = item

    # 선물 루트 심볼(/ES 등)이 거부되었으면 개별 월물로 재시도
    missing_futs = [s for s in symbols if s.startswith("/") and s not in out]
    if missing_futs:
        now = datetime.now(ET)
        cand_map = {root: _futures_candidates(root, now) for root in missing_futs}
        all_cands = [c for lst in cand_map.values() for c in lst]
        data2 = schwab_get(token, "/quotes", {"symbols": ",".join(all_cands), "fields": "quote,reference"})
        if isinstance(data2, dict):
            for root, cands in cand_map.items():
                for c in cands:
                    info = data2.get(c)
                    if not isinstance(info, dict):
                        continue
                    if (info.get("reference") or {}).get("futureIsActive") is False:
                        continue
                    item = _quote_to_item(root, c, info)
                    if item:
                        out[root] = item
                        break
    return out


def fetch_yahoo_realtime_future(ysym):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}?interval=1m&range=1d"
        res = requests.get(url, headers=HEADERS, timeout=3.5)
        if res.status_code == 200:
            meta = ((res.json().get("chart", {}).get("result") or [{}])[0] or {}).get("meta") or {}
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            return make_quote(meta.get("regularMarketPrice"), prev, None, f"Yahoo ({ysym})")
    except Exception:
        pass
    return None


def _yahoo_prev_ref(ysym):
    """선물 기준가(정산가) 조회.
    Schwab 선물 quote의 closePrice가 부정확해(2026-10-21 야간 ES: 실제 -30인데 +16 표시)
    Yahoo 메타의 전일 정산가를 기준가로 쓴다. CNBC도 같은 기준이라 등락 부호가 일치한다."""

    def load():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}?interval=1m&range=1d"
            res = requests.get(url, headers=HEADERS, timeout=3.5)
            if res.status_code == 200:
                meta = ((res.json().get("chart", {}).get("result") or [{}])[0] or {}).get("meta") or {}
                return num(meta.get("chartPreviousClose") or meta.get("previousClose"))
        except Exception:
            pass
        return None

    return cached(f"yahoo-prev:{ysym}", 300, load)


def get_all_quotes(token):
    def load():
        result = {}
        schwab_data = fetch_schwab_quotes(token, list(SCHWAB_QUOTES.values())) or {}
        for key, ssym in SCHWAB_QUOTES.items():
            result[key] = schwab_data.get(ssym)

        # Schwab 에서 못 받은 선물만 Yahoo 로 채움
        missing = {k: y for k, y in YAHOO_FUTURES.items() if result.get(k) is None}
        if missing:
            with ThreadPoolExecutor(max_workers=3) as ex:
                futs = {k: ex.submit(fetch_yahoo_realtime_future, y) for k, y in missing.items()}
            for k, f in futs.items():
                try:
                    result[k] = f.result()
                except Exception:
                    result[k] = None

        # 선물 3종: 가격은 Schwab 유지, 등락 기준가만 Yahoo 정산가로 교체
        # (Schwab closePrice가 틀려서 야간에 등락 부호가 뒤집히는 문제)
        fut_keys = [k for k in YAHOO_FUTURES if result.get(k)]
        if fut_keys:
            with ThreadPoolExecutor(max_workers=3) as ex:
                refs = {k: ex.submit(_yahoo_prev_ref, YAHOO_FUTURES[k]) for k in fut_keys}
            for k, f in refs.items():
                try:
                    prev = f.result()
                except Exception:
                    prev = None
                if prev:
                    result[k] = make_quote(result[k]["price"], prev, None, result[k]["source"]) or result[k]

        return result if any(result.values()) else None

    return cached("quotes", 4, load) or {}


# ─────────────────────────────────────────────────────────────
# FLASH 실시간 속보 엔진
# ─────────────────────────────────────────────────────────────
def fetch_flash_market_news():
    def _fetch():
        try:
            url = "https://news.google.com/rss/search?q=(S%26P500+OR+Stock+market+OR+Federal+Reserve+OR+Crude+Oil)+AND+(stocks+OR+economy+OR+rates)+when:2h&hl=en-US&gl=US&ceid=US:en"
            r = requests.get(url, headers=HEADERS, timeout=4.0)
            if r.status_code != 200:
                return []
            root = ET_xml.fromstring(r.text)
            news_items = []

            EXCLUDE_WORDS = [
                "shooting", "shooter", "gun", "police", "killed", "dead", "murder",
                "hurricane", "tornado", "floods", "storm", "crash", "arrested"
            ]

            for it in root.findall(".//item"):
                if len(news_items) >= 4:
                    break
                title = it.findtext("title", "")
                source = title.rsplit(" - ", 1)[1] if " - " in title else "Flash Wire"
                title = title.rsplit(" - ", 1)[0] if " - " in title else title
                t_lower = title.lower()

                if any(w in t_lower for w in EXCLUDE_WORDS):
                    continue

                bull_words = ["surge", "rally", "soar", "gain", "rate cut", "easing", "inflation cools"]
                bear_words = ["plunge", "tumble", "slump", "tariff", "rate hike", "recession", "sanction"]

                is_bull = any(w in t_lower for w in bull_words)
                is_bear = any(w in t_lower for w in bear_words)

                if is_bull and not is_bear:
                    tag = "🟢 지수 호재 (Bullish)"
                    tone = "bull"
                elif is_bear:
                    tag = "🔴 지수 악재 (Bearish)"
                    tone = "bear"
                else:
                    tag = "⚡ 실시간 속보 (Catalyst)"
                    tone = "pending"

                news_items.append({
                    "title": title.strip(),
                    "source": source.strip(),
                    "tag": tag,
                    "tone": tone,
                    "time": "속보",
                })
            return news_items
        except Exception:
            return []

    return cached("flash_market_news", 180, _fetch) or []


# ─────────────────────────────────────────────────────────────
# 연준 위원 발언 & 경제 캘린더
# ─────────────────────────────────────────────────────────────
FED_SPEAKERS = {
    # 2026-10 기준 현직 (분기별 점검 필요)
    "warsh": {"name": "워시 의장", "stance": "매파(Hawkish)", "note": "2026.5월 취임 · 인플레 억제 우선, 백악관 인하 압박에도 인상 단행"},
    "jefferson": {"name": "제퍼슨 부의장", "stance": "중립(Centrist)", "note": "연준 핵심 지도부 컨센서스 대변"},
    "bowman": {"name": "보우만 이사", "stance": "매파(Hawkish)", "note": "추가 인상 희박/완화 발언 시 강력한 숏스퀴즈 호재"},
    "powell": {"name": "파월 이사(전 의장)", "stance": "중립(Centrist)", "note": "의장직 종료(2026.5) 후 이사 잔류 · 발언 영향력 여전"},
    "waller": {"name": "월러 이사", "stance": "매파/실세(Hawkish)", "note": "금리 경로 선행 지표 위원"},
    "cook": {"name": "쿡 이사", "stance": "비둘기파(Dovish)", "note": "해임 소송 중 · 법적으론 현직 유지"},
    "barr": {"name": "바 이사", "stance": "중립(Centrist)", "note": "전 감독 부의장"},
    "williams": {"name": "윌리엄스 총재", "stance": "중립/부의장(Centrist)", "note": "NY연은 · FOMC 부의장"},
    "goolsbee": {"name": "굴스비 총재", "stance": "비둘기파(Dovish)", "note": "선제적 금리 인하 지지파"},
    "kashkari": {"name": "카시카리 총재", "stance": "매파(Hawkish)", "note": "고금리 장기화 선호 위원"},
    "bostic": {"name": "보스틱 총재", "stance": "중립/신중(Centrist)", "note": "완만한 완화 속도 선호"},
    "daly": {"name": "데일리 총재", "stance": "비둘기파(Dovish)", "note": "고용 냉각 경계 및 완화 지지"},
}


def fetch_speaker_headline(speaker_key):
    def _get():
        try:
            url = f"https://news.google.com/rss/search?q=Fed+{speaker_key}+interest+rates&hl=en-US&gl=US&ceid=US:en"
            r = requests.get(url, headers=HEADERS, timeout=3.5)
            if r.status_code == 200:
                root = ET_xml.fromstring(r.text)
                for it in root.findall(".//item")[:3]:
                    t = it.findtext("title", "")
                    if speaker_key.lower() in t.lower() or "fed" in t.lower():
                        return t.rsplit(" - ", 1)[0] if " - " in t else t
        except Exception:
            pass
        return None

    return cached(f"fed_news:{speaker_key}", 180, _get)


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
    "gdp", "fomc", "fed ", "federal funds", "powell", "ism", "services pmi",
    "manufacturing pmi", "retail sales", "hourly earnings", "speaks", "speech"
]


def evaluate_econ_result(title_en, actual_str, forecast_str, previous_str, is_passed, elapsed_sec, market_reaction):
    t_lower = title_en.lower()
    is_speech = any(w in t_lower for w in ["speaks", "speech", "testifies", "press conference", "panel"])

    if is_speech:
        speaker_key = next((k for k in FED_SPEAKERS if k in t_lower), None)
        spk = FED_SPEAKERS.get(speaker_key, {"name": "연준 위원", "stance": "통화정책 위원", "note": "금리 발언 주의"})
        if not is_passed:
            return {"tag": f"🎙️ {spk['name']} 발언 예정", "tone": "flat", "sentence": f"{spk['stance']} · {spk['note']}"}

        headline = fetch_speaker_headline(speaker_key) if speaker_key else None
        if headline:
            h_lower = headline.lower()
            is_dovish = any(w in h_lower for w in ["unlikely", "cut", "cool", "ease", "progress", "slow", "no hike", "less likely"])
            is_hawkish = any(w in h_lower for w in ["hike", "raise", "sticky", "high for longer", "not ready", "too soon"])
            if is_dovish and not is_hawkish:
                return {"tag": "🟢 비둘기 발언 (호재)", "tone": "bull", "sentence": f"↳ 헤드라인: \"{headline}\" (추가 인상 희박/완화)"}
            elif is_hawkish:
                return {"tag": "🔴 매파 발언 (경계)", "tone": "bear", "sentence": f"↳ 헤드라인: \"{headline}\" (긴축 유지 경계)"}
            return {"tag": "🎙️ 발언 헤드라인", "tone": "flat", "sentence": f"↳ 헤드라인: \"{headline}\""}

        if market_reaction and market_reaction.get("detected"):
            mr = market_reaction
            tag = "🟢 시장 호재 반응" if mr["dir"] == "bull" else ("🔴 시장 악재 반응" if mr["dir"] == "bear" else "⚪ 시장 중립")
            return {"tag": f"{tag} ({mr['diff_str']})", "tone": mr["dir"], "sentence": f"{spk['name']} 발언 직후 SPX {mr['diff_str']} 변동 감지"}

        return {"tag": f"🎙️ {spk['name']} 발언 진행/종료", "tone": "flat", "sentence": f"{spk['stance']} · {spk['note']}"}

    act_num = _parse_val(actual_str)
    fc_num = _parse_val(forecast_str) if forecast_str else _parse_val(previous_str)
    cmp_label = "예상" if forecast_str else "이전"
    cmp_str = forecast_str or previous_str

    if act_num is not None and fc_num is not None:
        diff = act_num - fc_num
        is_inflation = any(k in t_lower for k in ["cpi", "pce", "ppi", "hourly earnings", "price index"])
        is_unemployment = any(k in t_lower for k in ["unemployment rate", "unemployment claims", "jobless claims"])
        is_nfp = "non-farm" in t_lower or "employment change" in t_lower
        is_pmi = "ism" in t_lower or "pmi" in t_lower

        if abs(diff) < 1e-5:
            tone, tag_label = "flat", "⚪ 부합 (중립)"
        elif is_pmi:
            tone, tag_label = ("bull", "🟢 서비스/제조업 확장 (상승)") if diff > 0 else ("bear", "🔴 서비스/제조업 위축 (하락)")
        elif is_inflation:
            tone, tag_label = ("bear", "🔴 물가 과열 (하락)") if diff > 0 else ("bull", "🟢 물가 안정 (상승)")
        elif is_unemployment:
            tone, tag_label = ("bear", "⚠️ 실업 증가 (하락)") if diff > 0 else ("bull", "🟢 실업 감소 (상승)")
        elif is_nfp:
            tone, tag_label = ("bull", "🟢 고용 서프라이즈 (상승)") if diff > 0 else ("bear", "🔴 고용 쇼크 (하락)")
        else:
            tone, tag_label = ("bull", "🟢 지표 호조 (상승)") if diff > 0 else ("bear", "🔴 지표 부진 (하락)")

        mr_suffix = f" · 시장 {market_reaction['diff_str']}" if (market_reaction and market_reaction.get("detected")) else ""
        return {"tag": tag_label, "tone": tone, "sentence": f"실제 {actual_str} vs {cmp_label} {cmp_str}{mr_suffix}"}

    if is_passed:
        if market_reaction and market_reaction.get("detected"):
            mr = market_reaction
            if mr["dir"] == "bull":
                return {"tag": f"🟢 시장 호재 반응 ({mr['diff_str']})", "tone": "bull", "sentence": f"수치 지연 중이나 발표 직후 SPX {mr['diff_str']} 급반등 (시장 호재 소화)"}
            elif mr["dir"] == "bear":
                return {"tag": f"🔴 시장 악재 반응 ({mr['diff_str']})", "tone": "bear", "sentence": f"수치 지연 중이나 발표 직후 SPX {mr['diff_str']} 급락 발생 (시장 악재 소화)"}
            else:
                return {"tag": "⚪ 시장 중립 소화", "tone": "flat", "sentence": f"발표 직후 지수 변동 미미 ({mr['diff_str']}) · 시장 중립/흡수 소화"}

        if elapsed_sec <= 600:
            return {"tag": "⏳ 속보 수신 중", "tone": "pending", "sentence": f"시장 예상치: {forecast_str or 'N/A'} (초기 체결 분석 중)"}

        return {"tag": "⚪ 발표 완료", "tone": "flat", "sentence": f"예상치 {forecast_str or 'N/A'} · 발표 완료 (시장 기저 반영)"}

    return {"tag": None, "tone": "pending", "sentence": f"시장 예상치: {forecast_str}" + (f" (이전: {previous_str})" if previous_str else "")}


def detect_event_market_reaction(event_ts, spy_5m_candles, ratio):
    if not spy_5m_candles or not ratio:
        return None
    matched_idx = None
    for idx, cd in enumerate(spy_5m_candles):
        if abs(cd["t"] - event_ts) < 240:
            matched_idx = idx
            break
    if matched_idx is None:
        for idx, cd in enumerate(spy_5m_candles):
            if cd["t"] >= event_ts:
                matched_idx = idx
                break
    if matched_idx is None or matched_idx >= len(spy_5m_candles):
        return None

    target_bar = spy_5m_candles[matched_idx]
    prev_bar = spy_5m_candles[matched_idx - 1] if matched_idx > 0 else target_bar
    diff_pt = (target_bar["c"] - prev_bar["c"]) * ratio
    diff_str = f"{diff_pt:+.1f}pt"

    if diff_pt >= 3.5:
        return {"detected": True, "dir": "bull", "diff_pt": diff_pt, "diff_str": diff_str}
    elif diff_pt <= -3.5:
        return {"detected": True, "dir": "bear", "diff_pt": diff_pt, "diff_str": diff_str}
    return {"detected": True, "dir": "flat", "diff_pt": diff_pt, "diff_str": diff_str}


def fetch_global_econ_calendar(countries=("USD",)):
    now_sec = int(time.time())
    url = f"https://nfs.faireconomy.media/ff_calendar_thisweek.json?_={now_sec}"
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Accept": "application/json",
    }
    try:
        r = requests.get(url, headers=req_headers, timeout=5.0)
        if r.status_code != 200:
            return None
        data = r.json()
        parsed = []
        for it in data:
            if it.get("country") not in countries:
                continue
            title = (it.get("title") or "").strip()
            impact = it.get("impact", "")
            t_lower = title.lower()
            if not ((impact in ("High", "Medium")) or any(k in t_lower for k in HIGH_IMPACT_KEYWORDS)):
                continue
            raw_date = it.get("date", "")
            if not raw_date:
                continue
            try:
                dt_obj = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).astimezone(ET)
            except Exception:
                continue

            kr_name = ECON_TITLE_KR.get(title)
            if not kr_name:
                for spk_k, spk_v in FED_SPEAKERS.items():
                    if spk_k in t_lower:
                        kr_name = f"연준 {spk_v['name']} 연설/발언"
                        break
            if not kr_name:
                for spk_k, spk_v in {"lagarde": "ECB 라가르드 총재", "ueda": "일본은행 우에다 총재"}.items():
                    if spk_k in t_lower:
                        kr_name = f"{spk_v} 연설/발언"
                        break
            if not kr_name:
                kr_name = title

            parsed.append({
                "title": kr_name, "title_en": title, "dt": dt_obj, "ts": dt_obj.timestamp(),
                "time": dt_obj.strftime("%H:%M ET"), "impact": impact, "country": it.get("country"),
                "forecast": (it.get("forecast") or "").strip(), "previous": (it.get("previous") or "").strip(),
                "actual": (it.get("actual") or "").strip()
            })
        return parsed
    except Exception:
        return None


def _yahoo_index(sym):
    """Yahoo 지수 전일 대비 등락률 (닛케이·항셍·DAX·FTSE용)."""
    try:
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d",
                         headers=HEADERS, timeout=4)
        meta = ((r.json().get("chart", {}).get("result") or [{}])[0] or {}).get("meta") or {}
        px = num(meta.get("regularMarketPrice"))
        prev = num(meta.get("chartPreviousClose") or meta.get("previousClose"))
        if px is None or prev is None or prev == 0:
            return None
        return {"price": px, "pct": round((px - prev) / prev * 100, 2)}
    except Exception:
        return None


def _eu_asia_events(now_et):
    """전날 15:00 ET ~ 당일 11:30 ET 구간의 유럽·아시아 고영향 이벤트
    (밤사이 일본 지표·유럽 오전 일정·11:30 전 ECB/BoJ 일정)."""
    try:
        evs = cached("econ_events_eu_asia", 900, lambda: fetch_global_econ_calendar(("EUR", "JPY", "CNY", "GBP")))
    except Exception:
        return []
    if not evs:
        return []
    start = (now_et - timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
    end = now_et.replace(hour=11, minute=30, second=0, microsecond=0)
    out = []
    for it in evs:
        dt = it.get("dt")
        if dt and start <= dt <= end:
            out.append({"time": dt.strftime("%H:%M"),
                        "title": it.get("title") or it.get("title_en") or "",
                        "country": it.get("country"), "_ts": it.get("ts") or dt.timestamp()})
    out = sorted(out, key=lambda x: x["_ts"])[:6]
    for e in out:
        e.pop("_ts", None)
    return out


def _build_overnight(now_et, es_price):
    """장전 스트립용 밤사이 요약. 평일 00:00~11:30 ET에만 반환 (이후 None → 프론트 숨김).
    지수는 120초 캐시 + 병렬 조회로 폴링 비용을 묶는다."""
    if now_et.weekday() >= 5 or (now_et.hour * 60 + now_et.minute) >= 690:
        return None
    idx = {}
    specs = [("nikkei", "^N225", "닛케이"), ("hangseng", "^HSI", "항셍"),
             ("dax", "^GDAXI", "DAX"), ("ftse", "^FTSE", "FTSE")]
    try:
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {key: ex.submit(cached, f"yahoo_idx:{sym}", 120, lambda s=sym: _yahoo_index(s))
                    for key, sym, _n in specs}
            for key, _sym, name in specs:
                try:
                    q = futs[key].result(timeout=5)
                except Exception:
                    q = None
                if q:
                    idx[key] = {"name": name, "pct": q["pct"]}
    except Exception:
        pass
    gap = None
    try:
        prev = _yahoo_prev_ref("ES")
        if es_price and prev:
            gap = round((es_price - prev) / prev * 100, 2)
    except Exception:
        pass
    return {"asia": [idx[k] for k in ("nikkei", "hangseng") if k in idx],
            "europe": [idx[k] for k in ("dax", "ftse") if k in idx],
            "es_gap_pct": gap, "events": _eu_asia_events(now_et)}


def get_today_econ_events(now_et, spy_5m_candles, ratio):
    events = cached("econ_events_data", 60, fetch_global_econ_calendar)
    flash_news = fetch_flash_market_news()
    now_ts = now_et.timestamp()
    if not events:
        return {"items": [], "flash_news": flash_news, "source": "N/A", "error": "경제 캘린더 조회 실패"}

    today = now_et.date()
    # 미국 증시 휴장일 (NYSE) — 공휴일 다음날 지표 놓침 방지
    US_HOLIDAYS = {
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
        "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
        "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
        "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
    }

    def _next_trading_day(d):
        nxt = d + timedelta(days=1)
        while nxt.weekday() >= 5 or nxt.isoformat() in US_HOLIDAYS:
            nxt += timedelta(days=1)
        return nxt

    # 다음 거래일 (주말·공휴일 건너뛰기) — 금요일 16:00 이후면 월요일이 아닌 다음 거래일
    tomorrow = _next_trading_day(today)
    days_ahead = (tomorrow - today).days

    is_tomorrow = False
    target_items = []

    # 16:00 ET 이후에는 오늘 밤 잔여 일정을 무시하고 익일(내일) 지표를 1순위로 강제 설정
    if now_et.hour >= 16:
        tomorrow_items = [e for e in events if e["dt"].date() == tomorrow]
        if tomorrow_items:
            target_items = tomorrow_items
            is_tomorrow = True
        else:
            future_events = [e for e in events if e["dt"].date() > today]
            if future_events:
                next_date = min(e["dt"].date() for e in future_events)
                target_items = [e for e in future_events if e["dt"].date() == next_date]
                is_tomorrow = True

    # 장중(16:00 ET 이전)이거나 미래 일정이 전혀 없을 때만 당일 이벤트 노출
    if not target_items:
        today_items = [e for e in events if e["dt"].date() == today]
        active_today_items = [e for e in today_items if (now_ts - e["ts"]) <= 3600]
        target_items = active_today_items if active_today_items else today_items
        is_tomorrow = False

    target_items.sort(key=lambda x: x["ts"])
    out_items = []
    for it in target_items:
        passed = (it["ts"] <= now_ts)
        elapsed_sec = int(now_ts - it["ts"]) if passed else 0
        if not is_tomorrow and passed and elapsed_sec > 3600:
            continue

        has_actual = bool(it["actual"])
        prefix = f"[{it['dt'].strftime('%m/%d')}] " if is_tomorrow else ""
        market_reaction = detect_event_market_reaction(it["ts"], spy_5m_candles, ratio) if passed else None
        eval_res = evaluate_econ_result(it["title_en"], it["actual"], it["forecast"], it["previous"], passed, elapsed_sec, market_reaction)

        out_items.append({
            "title": f"{prefix}{it['title']}", "title_en": it["title_en"], "time": it["time"],
            "ts": it["ts"], "passed": passed, "has_actual": has_actual, "impact": it.get("impact", "High"),
            "actual": it["actual"], "forecast": it["forecast"], "previous": it["previous"],
            "eval_tag": eval_res["tag"], "eval_tone": eval_res["tone"], "eval_sentence": eval_res["sentence"],
        })

    return {"items": out_items, "flash_news": flash_news, "source": "공식 캘린더 + Flash 속보 엔진", "error": None}


def fetch_polymarket_spx_data(spx_price, spy_price=None):
    import json as _json
    import re
    from urllib.parse import quote

    now_et = datetime.now(ET)
    today = now_et.date()

    # 평일 16:00 ET 이후이거나 주말(토/일)이면 다음 거래일(월요일/익일) 일일 마켓 타겟팅
    if today.weekday() == 5:      # 토요일 -> 월요일(+2)
        target_date = today + timedelta(days=2)
    elif today.weekday() == 6:    # 일요일 -> 월요일(+1)
        target_date = today + timedelta(days=1)
    elif now_et.hour >= 16:       # 평일 장 마감 후 -> 다음 영업일
        days_ahead = 3 if today.weekday() == 4 else 1
        target_date = today + timedelta(days=days_ahead)
    else:
        target_date = today

    month_full = target_date.strftime("%B")        # 예: October
    month_short = target_date.strftime("%b")       # 예: Oct
    day_num = str(target_date.day)                 # 예: 19

    # ─────────────────────────────────────────────────────────
    # 1순위: 일일 'closes above $X' 래더 마켓 → 50% 확률(중앙값) 마감가 추정
    #        (Up/Down 확률이 아니라 "마감 시 어느 정도"를 직접 표시)
    # ─────────────────────────────────────────────────────────
    def _ladder_events():
        queries = [
            quote(f"closes above {month_full} {day_num}"),
            quote(f"closes above {month_short} {day_num}"),
            quote("SPY closes above"),
        ]
        for q in queries:
            try:
                r = requests.get(
                    f"https://gamma-api.polymarket.com/public-search?q={q}&events_status=active&limit_per_type=20",
                    headers=HEADERS, timeout=3.0)
                if r.status_code != 200:
                    continue
                data = r.json()
                evs = data.get("events", []) if isinstance(data, dict) else []
                for ev in evs:
                    if ev.get("closed"):
                        continue
                    t = (ev.get("title") or "").lower()
                    if "closes above" not in t or "week of" in t:
                        continue
                    if not (f"{month_full.lower()} {day_num}" in t
                            or f"{month_short.lower()} {day_num}" in t
                            or f"{target_date.month}/{day_num}" in t):
                        continue
                    end_str = str(ev.get("endDate") or "")[:10]
                    try:
                        dd = (datetime.strptime(end_str, "%Y-%m-%d").date() - today).days
                        if dd < 0 or dd > 5:
                            continue
                    except Exception:
                        pass
                    yield ev
            except Exception:
                continue

    def _implied_median_spy(ev):
        """래더 마켓들의 Yes 가격으로 50% 확률(중앙값) 마감가 추정 (SPY 기준)"""
        pts = []
        for m in (ev.get("markets") or []):
            if m.get("closed") or m.get("active") is False:
                continue
            qs = (m.get("question") or m.get("groupItemTitle") or "")
            mt = re.search(r"above\s*\$?\s*([\d,]+(?:\.\d+)?)", qs)
            if not mt:
                continue
            strike = float(mt.group(1).replace(",", ""))
            raw = m.get("outcomePrices")
            try:
                pr = _json.loads(raw) if isinstance(raw, str) else raw
                p = float(pr[0])
            except Exception:
                continue
            if 0.02 <= p <= 0.98:
                pts.append((strike, p))
        if len(pts) < 2:
            return None
        pts.sort()
        for (s_lo, p_lo), (s_hi, p_hi) in zip(pts, pts[1:]):
            if p_lo >= 0.5 >= p_hi and p_lo != p_hi:
                frac = (p_lo - 0.5) / (p_lo - p_hi)
                return s_lo + frac * (s_hi - s_lo)
        return None

    for _ev in _ladder_events():
        med_spy = _implied_median_spy(_ev)
        if med_spy is None:
            continue
        ratio_est = (spx_price / spy_price) if (spx_price and spy_price) else 10.0
        implied_spx = med_spy * ratio_est
        # 검증: 현재가 대비 ±20% 벗어나면 잘못된 마켓 → 스킵
        if spx_price and abs(implied_spx - spx_price) / spx_price > 0.20:
            continue
        date_tag = target_date.strftime("%m/%d")
        diff_str = f" ({implied_spx - spx_price:+.0f}pt)" if spx_price else ""
        vol = sum(float(m.get("volume") or 0) for m in (_ev.get("markets") or []))
        vol_str = f" · 거래량 ${int(vol):,}" if vol > 0 else ""
        return {
            "available": True,
            "title": f"[{date_tag}] SPX 마감 예상가 (Polymarket)",
            "yes_pct": 50,
            "no_pct": 50,
            "summary": f"예상 마감 {implied_spx:,.0f}{diff_str} · 중앙값 50%",
            "source": f"Polymarket SPX{vol_str}",
            "median_spy": med_spy,  # 핸들러가 확정한 비율로 재환산할 수 있게 원본 중앙값 동봉
        }

    # SPY 완전 제외, 순수 S&P 500 / SPX 일일 마켓만 검색 (래더 탐색 실패 시 폴백)
    search_queries = [
        quote(f"S&P 500 {month_full} {day_num}"),
        quote(f"SPX {month_full} {day_num}"),
        quote("S&P 500 Up or Down"),
        quote("S&P 500 close"),
        quote("SPX close"),
    ]

    # 연말/월말/장기 마켓 및 SPY 원천 배제 키워드
    ban_keywords = [
        "spy", "etf", "end of year", "eoy", "end of month", "by end of",
        "in 2026", "in 2027", "by december", "in october", "in november",
        "all time high", "ath", "recession", "fed ", "interest rate", "president"
    ]

    candidates = []

    for q in search_queries:
        try:
            url = f"https://gamma-api.polymarket.com/public-search?q={q}&events_status=active&limit_per_type=20"
            r = requests.get(url, headers=HEADERS, timeout=3.0)
            if r.status_code != 200:
                continue

            data = r.json()
            events = data.get("events", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            if not events:
                continue

            for ev in events:
                if ev.get("closed"):
                    continue

                ev_title = (ev.get("title") or "").strip()
                t_low = ev_title.lower()

                # 오직 S&P 500 / SPX만 허용 (SPY 제외)
                if not any(k in t_low for k in ("s&p", "spx")):
                    continue
                if any(b in t_low for b in ban_keywords):
                    continue

                # 만기일(endDate) 체크: 오늘로부터 5일 이내에 마감되는 단기/일일 마켓만 통과
                end_str = str(ev.get("endDate") or "")[:10]
                if end_str:
                    try:
                        end_dt = datetime.strptime(end_str, "%Y-%m-%d").date()
                        days_diff = (end_dt - today).days
                        if days_diff < 0 or days_diff > 5:
                            continue
                    except Exception:
                        pass

                is_exact_date = (
                    f"{month_full.lower()} {day_num}" in t_low
                    or f"{month_short.lower()} {day_num}" in t_low
                    or f"{target_date.month}/{day_num}" in t_low
                )

                for m in (ev.get("markets") or []):
                    if m.get("closed") or m.get("active") is False:
                        continue

                    q_str = (m.get("question") or m.get("groupItemTitle") or "").strip()
                    q_low = q_str.lower()
                    if any(b in q_low for b in ban_keywords):
                        continue

                    raw_prices = m.get("outcomePrices")
                    if not raw_prices:
                        continue
                    prices = _json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
                    if not prices or len(prices) < 2:
                        continue

                    p0 = float(prices[0])
                    if not (0.02 <= p0 <= 0.98):
                        continue

                    # SPX 지수 범위(4,000 ~ 12,000)의 행사가만 추출 (3자리 SPY 가격 무시)
                    nums = [float(x.replace(",", "")) for x in re.findall(r"\d{1,2},\d{3}(?:\.\d+)?|\d{4}(?:\.\d+)?", q_str)]
                    strike_dist = 9999.0
                    extracted_strike = None
                    if nums:
                        for n in nums:
                            if 4000 <= n <= 12000 and int(n) not in (2025, 2026, 2027):
                                extracted_strike = int(round(n))
                                if spx_price:
                                    strike_dist = abs(n - spx_price)
                                break

                    atm_score = abs(p0 - 0.5)
                    sort_key = (0 if is_exact_date else 1, strike_dist, atm_score)
                    candidates.append((sort_key, ev_title, m, prices, extracted_strike))

            if any(c[0][0] == 0 for c in candidates):
                break
        except Exception:
            continue

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    _, best_ev_title, best_m, prices, extracted_strike = candidates[0]

    raw_outcomes = best_m.get("outcomes")
    outcomes = _json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else (raw_outcomes or ["Yes", "No"])

    yes_pct = int(round(float(prices[0]) * 100))
    no_pct = int(round(float(prices[1]) * 100))

    lbl_yes = str(outcomes[0]) if len(outcomes) > 0 else "Yes"
    lbl_no = str(outcomes[1]) if len(outcomes) > 1 else "No"
    if lbl_yes.lower() == "up":
        lbl_yes, lbl_no = "상승(Up)", "하락(Down)"
    elif lbl_yes.lower() in ("yes", "above"):
        lbl_yes, lbl_no = "상회(Yes)", "하회(No)"

    sub_item = (best_m.get("groupItemTitle") or "").strip()
    date_tag = target_date.strftime("%m/%d")
    if extracted_strike:
        display_title = f"[{date_tag}] SPX {extracted_strike}선 마감 확률"
    elif sub_item and sub_item not in best_ev_title:
        display_title = f"[{date_tag}] {best_ev_title} ({sub_item})"
    else:
        display_title = f"[{date_tag}] {(best_m.get('question') or best_ev_title).strip()}"

    vol = float(best_m.get("volume") or 0)
    vol_str = f" · 거래량 ${int(vol):,}" if vol > 0 else ""

    return {
        "available": True,
        "title": display_title,
        "yes_pct": yes_pct,
        "no_pct": no_pct,
        "summary": f"{lbl_yes} {yes_pct}% · {lbl_no} {no_pct}%",
        "source": f"Polymarket SPX{vol_str}"
    }


def get_polymarket_spx(spx_price, spy_price=None):
    return cached("polymarket_spx_only", 60, lambda: fetch_polymarket_spx_data(spx_price, spy_price)) or {
        "available": False,
        "title": "당일 SPX 일일 폴리마켓 개장 대기",
        "yes_pct": 0,
        "no_pct": 0,
        "summary": "차기 거래일 SPX 마켓 생성 대기 중",
        "source": "Polymarket SPX"
    }


# ─────────────────────────────────────────────────────────────
# 캔들 데이터 / CVD / Volume Profile (전 시간대 1분봉 실시간 정밀 합성)
# ─────────────────────────────────────────────────────────────
TF_SPEC = {
    "1m": (1, 2, None),
    "5m": (1, 2, 5),
    "10m": (1, 2, 10),
    "15m": (1, 2, 15),
    "30m": (1, 2, 30),
    "1h": (1, 5, 60),    # 1시간봉도 5일치 실시간 1분봉으로 합성 (장 시작 즉시 1H 봉 생성 + RSI 기간 확보)
}
TF_LABEL = {"1m": "1m", "5m": "5m", "10m": "10m", "15m": "15m", "30m": "30m", "1h": "1H"}
INSTR = {"spx": "$SPX", "spy": "SPY"}


def normalize_tf(tf):
    key = str(tf or "").strip().lower()
    return key if key in TF_SPEC else "10m"


def schwab_candles(token, symbol, freq, days):
    now_ms = int(time.time() * 1000)
    data = schwab_get(
        token,
        "/pricehistory",
        {
            "symbol": symbol,
            "periodType": "day",
            "period": days,
            "frequencyType": "minute",
            "frequency": freq,
            "endDate": now_ms,
            "needExtendedHoursData": "true",
        },
        timeout=5,
    )
    out = []
    if isinstance(data, dict):
        for cd in data.get("candles") or []:
            if isinstance(cd, dict):
                o, h, l, c, t = (
                    num(cd.get("open")),
                    num(cd.get("high")),
                    num(cd.get("low")),
                    num(cd.get("close")),
                    num(cd.get("datetime")),
                )
                if None not in (o, h, l, c, t):
                    out.append({"t": int(t / 1000), "o": o, "h": h, "l": l, "c": c, "v": num(cd.get("volume")) or 0.0})
    return out


def aggregate_candles(candles, minutes):
    groups = OrderedDict()
    for cd in candles:
        dt = datetime.fromtimestamp(cd["t"], ET)
        total_min = dt.hour * 60 + dt.minute

        # 정규장(09:30 = 570분) 기준으로 시간 슬롯 정렬 (09:30~10:29 -> 09:30 봉으로 생성되어 누락 원천 방지)
        # 단, 16:00 이후 봉은 정규 슬롯에 포함시키지 않음 (1H처럼 큰 봉에서 16:00~ 시간외 거래량이 15:30 봉에 섞이는 것 방지)
        if 570 <= total_min < 960:
            idx = (total_min - 570) // minutes
            slot_min = 570 + idx * minutes
        else:
            slot_min = (total_min // minutes) * minutes

        slot_h, slot_m = divmod(slot_min, 60)
        # DST 해제일(매년 11월 첫 일요일) 01:00~02:00은 두 번 존재 (EDT→EST).
        # 원본 봉(dt)의 DST 오프셋으로 모호시각을 구분해 슬롯 병합 방지.
        _naive = datetime(dt.year, dt.month, dt.day, slot_h, slot_m, 0)
        try:
            slot_ts = int(ET.localize(_naive, is_dst=bool(dt.dst())).timestamp())
        except Exception:
            slot_ts = int(ET.localize(_naive).timestamp())
        key = (dt.date(), slot_ts)

        if key not in groups:
            groups[key] = {
                "t": slot_ts,
                "o": cd["o"],
                "h": cd["h"],
                "l": cd["l"],
                "c": cd["c"],
                "v": cd["v"],
                "buy_v": cd.get("buy_v", 0.0),
                "sell_v": cd.get("sell_v", 0.0),
            }
        else:
            groups[key]["h"] = max(groups[key]["h"], cd["h"])
            groups[key]["l"] = min(groups[key]["l"], cd["l"])
            groups[key]["c"] = cd["c"]
            groups[key]["v"] += cd["v"]
            groups[key]["buy_v"] += cd.get("buy_v", 0.0)
            groups[key]["sell_v"] += cd.get("sell_v", 0.0)
    return list(groups.values())


def _norm_cdf(z):
    """표준정규분포 누적분포함수 (math.erf 기반)"""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def apply_bvc(candles, window=60):
    """Bulk Volume Classification (Easley / Lopez de Prado / O'Hara):
    틱 데이터 없이 1분봉 단위로 매수/매도 체결량을 추정하는 학계 표준 방식.
    V_buy = V * Phi(dP / sigma) — dP는 봉간 종가 변화, sigma는 직전 window개 봉의 표준편차.
    sigma를 구할 수 없는 구간은 종가 위치(CLV) 방식으로 폴백. (여전히 추정치임)"""
    n = len(candles)
    if n == 0:
        return candles

    closes = [c.get("c") for c in candles]
    opens = [c.get("o") for c in candles]
    deltas = []
    for i, cl in enumerate(closes):
        if cl is None:
            deltas.append(None)
        elif i == 0:
            o = opens[0]
            deltas.append(cl - o if o is not None else 0.0)
        else:
            pc = closes[i - 1]
            deltas.append(cl - pc if pc is not None else 0.0)

    for i, c in enumerate(candles):
        v = c.get("v") or 0.0
        if v <= 0:
            c["buy_v"], c["sell_v"] = 0.0, 0.0
            continue

        ratio = None
        d = deltas[i]
        if d is not None:
            win = [x for x in deltas[max(0, i - window + 1):i + 1] if x is not None]
            if len(win) >= 10:
                mean = sum(win) / len(win)
                var = sum((x - mean) ** 2 for x in win) / len(win)
                if var > 0:
                    ratio = _norm_cdf(d / math.sqrt(var))

        if ratio is None:
            # 폴백: 종가 위치(CLV) — 종가가 고가에 가까울수록 매수 우세
            o, h, l, cl = c.get("o"), c.get("h"), c.get("l"), c.get("c")
            if None not in (o, h, l, cl) and (h - l) > 1e-9:
                clv = ((cl - l) - (h - cl)) / (h - l)
                ratio = 0.5 + 0.5 * max(-1.0, min(1.0, clv))
            elif cl is not None and o is not None:
                ratio = 0.6 if cl >= o else 0.4

        if ratio is None:
            ratio = 0.5
        ratio = max(0.05, min(0.95, ratio))
        c["buy_v"] = v * ratio
        c["sell_v"] = v * (1.0 - ratio)

    return candles


def split_bar_volume(c):
    """단일봉 폴백용 BVC 간소형: 종가 위치(CLV) 기반 매수/매도 분할 (추정치)"""
    v, o, h, l, cl = c["v"], c["o"], c["h"], c["l"], c["c"]
    if v <= 0:
        return 0.0, 0.0
    rng = h - l
    if rng <= 1e-9:
        return (v * 0.6, v * 0.4) if cl >= o else (v * 0.4, v * 0.6)
    clv = ((cl - l) - (h - cl)) / rng
    buy_ratio = 0.5 + 0.5 * max(-1.0, min(1.0, clv))
    buy_ratio = max(0.05, min(0.95, buy_ratio))
    return v * buy_ratio, v * (1.0 - buy_ratio)


def get_base_candles(token, ssym, freq, days):
    def load():
        if not token or not ssym:
            return None
        cs = schwab_candles(token, ssym, freq, days)
        if not cs:
            return None
        apply_bvc(cs)  # BVC 매수/매도 분류 (기존 위크-바디 휴리스틱 대체)
        return cs

    return cached(f"base_candles:{ssym}:{freq}:{days}", 5, load)


def get_candles(token, inst, tf):
    key = normalize_tf(tf)

    def load():
        s_freq, s_days, agg = TF_SPEC[key]
        ssym = INSTR.get(inst)
        base = get_base_candles(token, ssym, s_freq, s_days)
        if not base:
            return None
        cs = aggregate_candles(base, agg) if agg else [dict(c) for c in base]
        return {"candles": cs, "source": f"{SRC_SCHWAB} ({ssym} {TF_LABEL[key]})"}

    return cached(f"candles:{inst}:{key}", 4, load)


def es_front_month_local(now=None):
    """ES 근월물 로컬 계산 (API 프로브 불필요 → 콜드스타트에서도 안정).
    만기: 3,6,9,12월 세 번째 금요일. 만기주 목요일부터 다음 월물로 롤오버."""
    if now is None:
        now = datetime.now(ET)
    quarters = [(3, "H"), (6, "M"), (9, "U"), (12, "Z")]
    y = now.year
    cands = []
    for yy in (y, y + 1):
        for mm, code in quarters:
            d1 = datetime(yy, mm, 1)
            first_fri = d1 + timedelta(days=(4 - d1.weekday()) % 7)
            exp = first_fri + timedelta(days=14)
            roll = (exp - timedelta(days=1)).date()  # 만기주 목요일
            cands.append((roll, yy, code))
    cands.sort(key=lambda x: x[0])
    today = now.date()
    for roll, yy, code in cands:
        if today < roll:
            return f"/ES{code}{str(yy)[-2:]}"
    return f"/ESZ{str(y + 1)[-2:]}"


def get_es_candles(token, tf):
    """ES 선물 캔들 (근월물 자동 결정: 로컬 캘린더 우선, 후보 순차 시도, BVC 분류 포함)"""
    key = normalize_tf(tf)

    def load():
        s_freq, s_days, agg = TF_SPEC[key]
        now = datetime.now(ET)
        cands = [es_front_month_local(now)]
        for c in _futures_candidates("/ES", now):
            if c not in cands:
                cands.append(c)
        base, used = None, None
        for ssym in cands:
            b = get_base_candles(token, ssym, s_freq, s_days)
            if b:
                base, used = b, ssym
                break
        if not base:
            return None
        cs = aggregate_candles(base, agg) if agg else [dict(c) for c in base]
        return {"candles": cs, "source": f"{SRC_SCHWAB} (ES {TF_LABEL[key]})", "es_symbol": used}

    return cached(f"candles:es:{key}", 30, load)


def get_rth_session(candles, now_et=None):
    if not candles:
        return [], False, None
    if now_et is None:
        now_et = datetime.now(ET)
    today = now_et.date()
    is_weekday = (now_et.weekday() < 5)
    is_rth = is_weekday and ((now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30)) and now_et.hour < 16)
    is_after = is_weekday and (now_et.hour >= 16)

    sessions = OrderedDict()
    for c in candles:
        dt = datetime.fromtimestamp(c["t"], ET)
        d = dt.date()
        d_open = int(ET.localize(datetime(d.year, d.month, d.day, 9, 30, 0)).timestamp())
        d_close = int(ET.localize(datetime(d.year, d.month, d.day, 16, 0, 0)).timestamp())
        if d_open <= c["t"] < d_close:   # 16:00 시작 봉(시간외)은 제외
            sessions.setdefault(d, []).append(c)

    all_dates = sorted(sessions.keys())
    if is_rth and today in sessions:
        return sessions[today], False, today.strftime("%m/%d")
    if is_after and today in sessions:
        return sessions[today], False, today.strftime("%m/%d")
    priors = [d for d in all_dates if d < today]
    if priors:
        return sessions[priors[-1]], True, priors[-1].strftime("%m/%d")
    if all_dates:
        return sessions[all_dates[-1]], (all_dates[-1] != today), all_dates[-1].strftime("%m/%d")
    return [], False, today.strftime("%m/%d")


def get_overnight_session(candles, now_et=None):
    """야간 세션: 전일 18:00 ET ~ 당일 09:30 ET (ES 24시간 거래용).
    장 시작 전 야간 기관 수급 파악용. sess_date는 'MM/DD 18:00→MM/DD 09:30' 형식."""
    if not candles:
        return [], False, None
    if now_et is None:
        now_et = datetime.now(ET)
    today = now_et.date()
    prev = today - timedelta(days=1)
    start_ts = int(ET.localize(datetime(prev.year, prev.month, prev.day, 18, 0, 0)).timestamp())
    end_ts = int(ET.localize(datetime(today.year, today.month, today.day, 9, 30, 0)).timestamp())
    sess = [c for c in candles if start_ts <= c["t"] < end_ts]
    label = f"{prev.strftime('%m/%d')} 18:00→{today.strftime('%m/%d')} 09:30"
    return sess, False, label


def get_es_session(candles, now_et=None):
    """ES 세션 자동 선택 (주말/야간 대응).
    반환: (bars, mode, sess_date)
    mode: rth_live(평일 정규장) | rth_closed(정규장 마감 직후) | overnight_live(야간 실시간) | prior_rth(주말·휴장 → 최근 정규장)"""
    if not candles:
        return [], "prior_rth", None
    if now_et is None:
        now_et = datetime.now(ET)
    wd = now_et.weekday()
    mins = now_et.hour * 60 + now_et.minute

    # 평일 정규장 09:30~16:00
    if wd < 5 and 570 <= mins < 960:
        bars, _, sess_date = get_rth_session(candles, now_et)
        return bars, "rth_live", sess_date

    # 야간 라이브: 평일 18:00~24:00 / 평일 00:00~09:30 / 일요일 18:00~24:00
    # (금요일 18:00 이후는 주말 휴장이므로 제외)
    overnight_now = (wd < 5 and mins >= 1080) or (wd < 5 and mins < 570) or (wd == 6 and mins >= 1080)
    if overnight_now and not (wd == 4 and mins >= 1080):
        # 야간 세션 시작일: 일요일 저녁·평일 저녁이면 당일 18:00, 심야(00:00~09:30)면 전일 18:00
        d = now_et.date() if (wd == 6 or mins >= 1080) else (now_et - timedelta(days=1)).date()
        start_ts = int(ET.localize(datetime(d.year, d.month, d.day, 18, 0, 0)).timestamp())
        now_ts = int(now_et.timestamp())
        bars = [c for c in candles if start_ts <= c["t"] <= now_ts]
        return bars, "overnight_live", f"{d.strftime('%m/%d')} 18:00"

    # 그 외: 토요일, 일요일 18:00 이전, 평일 16:00~18:00(휴장), 금요일 18:00~ → 최근 정규장
    bars, is_prior, sess_date = get_rth_session(candles, now_et)
    mode = "rth_closed" if (wd < 5 and 960 <= mins < 1080) else "prior_rth"
    return bars, mode, sess_date


def compute_vwap(spy_candles, ratio, now_et=None):
    sess, _, _ = get_rth_session(spy_candles, now_et)
    if not sess or not ratio:
        return None
    cum_v = cum_tp = 0.0
    val = None
    for c in sess:
        if c["v"] <= 0:
            continue
        tp = (c["h"] + c["l"] + c["c"]) / 3.0 * ratio
        cum_v += c["v"]
        cum_tp += tp * c["v"]
        val = cum_tp / cum_v
    return {"val": round(val, 2)} if val else None


def compute_volume_profile(spy_candles, ratio, source, now_et=None):
    sess, is_prior, sess_date = get_rth_session(spy_candles, now_et)
    if not sess or not ratio:
        return None
    bins, total = {}, 0.0
    for c in sess:
        if c["v"] <= 0:
            continue
        lo, hi = min(c["l"], c["h"]) * ratio, max(c["l"], c["h"]) * ratio
        b_lo, b_hi = min(c["o"], c["c"]) * ratio, max(c["o"], c["c"]) * ratio
        lo_b, hi_b = int(round(lo / 5.0)) * 5, int(round(hi / 5.0)) * 5
        rng = list(range(lo_b, hi_b + 5, 5))
        if not rng:
            continue
        weights = [2.5 if b_lo - 2.5 <= b <= b_hi + 2.5 else 1.0 for b in rng]
        w_sum = sum(weights)
        for b, w in zip(rng, weights):
            each = c["v"] * (w / w_sum)
            bins[b] = bins.get(b, 0.0) + each
            total += each

    if not bins or total <= 0:
        return None
    keys = sorted(bins)
    poc = max(bins, key=bins.get)
    target = total * 0.70
    cur, lo_i, hi_i = bins[poc], keys.index(poc), keys.index(poc)
    while cur < target and (lo_i > 0 or hi_i < len(keys) - 1):
        up = bins[keys[hi_i + 1]] if hi_i + 1 < len(keys) else -1.0
        dn = bins[keys[lo_i - 1]] if lo_i > 0 else -1.0
        if up >= dn:
            hi_i += 1
            cur += up
        else:
            lo_i -= 1
            cur += dn

    prefix = f"[전일({sess_date}) 마감 · 09:30 ET 리셋] " if is_prior else ""
    return {
        "val": float(keys[lo_i]), "poc": float(poc), "vah": float(keys[hi_i]),
        "bins": [{"p": float(k), "v": round(v, 1)} for k, v in sorted(bins.items())],
        "source": f"{source} x SPX/SPY 환산 · {prefix}{sess_date} 정규장 · 5pt 구간 POC",
    }


def detect_cvd_divergence(bars):
    """고전적 다이버전스: 가격 고점(저점) 시점의 CVD 값을 비교 (세션 3분할: 초반 vs 후반).
    bars: {h, l, cvd_line} 포함. 반환: None 또는 {"type": "bearish"/"bullish", "text": ...}"""
    n = len(bars)
    if n < 12:
        return None
    third = n // 3
    prev, rec = bars[:third], bars[2 * third:]
    if not prev or not rec:
        return None
    cvd_rng = (max(b["cvd_line"] for b in bars) - min(b["cvd_line"] for b in bars)) or 1.0
    # 약세 다이버전스: 가격은 신고가인데 고점 시점 CVD는 하락 (노이즈 방지: CVD 차가 전체 레인지의 3% 초과)
    ph_prev = max(prev, key=lambda b: b["h"])
    ph_rec = max(rec, key=lambda b: b["h"])
    if ph_rec["h"] > ph_prev["h"] and (ph_prev["cvd_line"] - ph_rec["cvd_line"]) > cvd_rng * 0.03:
        return {"type": "bearish",
                "text": f"약세 다이버전스 (가격 고점↑ {ph_prev['h']:,.1f}→{ph_rec['h']:,.1f}, CVD↓) — 매수 압력 약화"}
    # 강세 다이버전스: 가격은 신저가인데 저점 시점 CVD는 상승
    pl_prev = min(prev, key=lambda b: b["l"])
    pl_rec = min(rec, key=lambda b: b["l"])
    if pl_rec["l"] < pl_prev["l"] and (pl_rec["cvd_line"] - pl_prev["cvd_line"]) > cvd_rng * 0.03:
        return {"type": "bullish",
                "text": f"강세 다이버전스 (가격 저점↓ {pl_prev['l']:,.1f}→{pl_rec['l']:,.1f}, CVD↑) — 매도 압력 약화"}
    return None


def compute_cvd(candles, tf_key, source, symbol="SPY", now_et=None, vol_unit="shares", session="rth"):
    """CVD 계산. session="overnight"이면 전일 18:00~당일 09:30 야간 세션,
    session="auto"이면 현재 시각 기준 세션 자동 선택 (정규장/야간LIVE/휴장).
    vol_unit: "shares" 또는 "contracts"(ES 선물)."""
    if not candles:
        return None
    tf_label = TF_LABEL.get(tf_key, tf_key)
    if now_et is None:
        now_et = datetime.now(ET)
    if session == "auto":
        bars, mode, sess_date = get_es_session(candles, now_et)
        is_prior = (mode == "prior_rth")
    elif session == "overnight":
        bars, is_prior, sess_date = get_overnight_session(candles, now_et)
        mode = "overnight_done"
    else:
        bars, is_prior, sess_date = get_rth_session(candles, now_et)
        mode = "prior_rth" if is_prior else "rth_live"
    if not bars:
        return None

    unit_label = "계약" if vol_unit == "contracts" else "주"
    buy = sell = running = 0.0
    out = []
    for c in bars:
        v = c["v"]
        # 1분봉에서 누적된 매수/매도 볼륨(BVC 추정치)을 그대로 합산
        if "buy_v" in c and "sell_v" in c and (c["buy_v"] + c["sell_v"]) > 0:
            b_v, s_v = c["buy_v"], c["sell_v"]
        else:
            b_v, s_v = split_bar_volume(c)

        delta = b_v - s_v
        buy += b_v
        sell += s_v
        running += delta
        out.append({"t": c["t"], "vol": round(v / 1000.0, 2), "is_bull": delta >= 0,
                    "cvd_line": round(running / 1000.0, 2),
                    "h": c["h"], "l": c["l"], "c": c["c"]})

    total = buy + sell
    if total <= 0:
        return None
    buy_pct = int(round(buy / total * 100))
    sell_pct = 100 - buy_pct
    status, tone = ("Buying Pressure", "bull") if buy_pct >= 53 else (("Selling Pressure", "bear") if buy_pct <= 47 else ("Balanced", "flat"))

    # 다이버전스 + 모멘텀 (최근 6봉 CVD 변화)
    divergence = detect_cvd_divergence(out)
    m_n = min(6, len(out))
    mom_val = out[-1]["cvd_line"] - out[-m_n]["cvd_line"]  # 천 단위
    mom_dir = "up" if mom_val > 0 else ("down" if mom_val < 0 else "flat")
    mom_txt = {"up": "가속↑", "down": "감속↓", "flat": "정체→"}[mom_dir]
    momentum = {"dir": mom_dir, "val": round(mom_val, 2),
                "text": f"CVD 모멘텀 {mom_txt} ({m_n}봉간 {mom_val:+.1f}K {unit_label})"}

    end_ts = bars[-1]["t"]
    if mode == "overnight_live":
        aggregate_range = f"야간 LIVE ({sess_date} → {now_et.strftime('%m/%d %H:%M')} ET) · {len(bars)}개 {tf_label} 봉"
        prefix, sess_label = "", "야간 LIVE"
    elif mode == "overnight_done":
        aggregate_range = f"야간 ({sess_date} ET) · {len(bars)}개 {tf_label} 봉"
        prefix, sess_label = "", "야간"
    elif mode == "rth_closed":
        aggregate_range = f"{sess_date} 정규장 마감 (09:30 ~ 16:00 ET) · {len(bars)}개 {tf_label} 봉"
        prefix, sess_label = "", "정규장"
    else:
        aggregate_range = f"{sess_date} {'전일' if is_prior else ''}정규장 (09:30 ~ {datetime.fromtimestamp(end_ts, ET).strftime('%H:%M:%S ET')}) · {len(bars)}개 {tf_label} 봉"
        prefix = f"[전일({sess_date}) 마감 · 09:30 ET 리셋] " if is_prior else ""
        sess_label = "정규장"

    def fmt_v(v):
        return f"{v/1e6:.2f}M" if v >= 1e6 else (f"{v/1e3:.1f}K" if v >= 1e3 else f"{v:.0f}")

    return {
        "source": f"{source} {'· [전일 마감]' if is_prior else ''}",
        "data_time": datetime.fromtimestamp(end_ts, ET).strftime("%m/%d %H:%M:%S ET"),
        "last_bar_time": datetime.fromtimestamp(end_ts, ET).strftime("%H:%M:%S ET"),
        "is_prior": is_prior, "session_date": sess_date, "session_mode": mode,
        "status": f"{status}{' (전일)' if is_prior else ''}", "tone": tone,
        "aggregate_range": aggregate_range,
        "data_desc": f"{symbol} {prefix}{sess_label} · {source} · 체결 압력 CVD (BVC 추정치) · 단위: {unit_label}",
        "buy_pct": buy_pct, "sell_pct": sell_pct, "buy_vol": fmt_v(buy), "sell_vol": fmt_v(sell),
        "recent_vol": fmt_v(bars[-1]["v"]), "total_vol": fmt_v(total),
        "vol_scale": 1000,  # bars[].vol / cvd_line 단위: 천 단위 → 실제 수량 환산 배율
        "vol_unit": vol_unit, "vol_unit_label": unit_label,
        "divergence": divergence, "momentum": momentum,
        "bars": out, "summary_text": f"CVD Flow: Buy {buy_pct}% / Sell {sell_pct}% in session.",
    }


# ─────────────────────────────────────────────────────────────
# GEX & 방향 분석 & 변동성 쇼크
# ─────────────────────────────────────────────────────────────
def bs_gamma(S, K, T, sigma, r=0.0):
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
        g = pdf / (S * sigma * math.sqrt(T))
        return g if math.isfinite(g) else 0.0
    except Exception:
        return 0.0


def ema_series(values, period):
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi_series(closes, period=14):
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    calc = lambda g, l: 50.0 if l == 0 and g == 0 else (100.0 if l == 0 else 100.0 - (100.0 / (1.0 + g / l)))
    out = [round(calc(avg_g, avg_l), 1)]
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        out.append(round(calc(avg_g, avg_l), 1))
    return out


def parse_schwab_chain(data, exp_date):
    contracts = []
    for side, mkey in (("C", "callExpDateMap"), ("P", "putExpDateMap")):
        for ekey, strikes in (data.get(mkey) or {}).items():
            if ekey.split(":")[0] != exp_date:
                continue
            for skey, arr in (strikes or {}).items():
                for o in arr or []:
                    if not isinstance(o, dict):
                        continue
                    K = num(o.get("strikePrice")) or num(skey)
                    if K is None:
                        continue
                    iv = num(o.get("volatility"))
                    contracts.append({
                        "K": K, "side": side, "oi": num(o.get("openInterest")) or 0.0,
                        "vol": num(o.get("totalVolume")) or num(o.get("volume")) or 0.0,
                        "iv": (iv / 100.0) if iv and 0.01 <= (iv / 100.0) <= 5.0 else None,
                        "gamma": num(o.get("gamma")), "bid": num(o.get("bid")), "ask": num(o.get("ask")), "last": num(o.get("last")),
                    })
    return contracts


def fetch_schwab_chain(token, today_date):
    """SPX/SPXW 옵션 체인 조회.
    주말·공휴일에는 만기가 없으므로, 만기가 존재하는 가장 가까운 거래일로
    앞으로 롤링해 조회한다 (최대 7일)."""
    if not token:
        return None, {"reason": "토큰 없음"}

    def try_date(d):
        t = d.isoformat()
        data = schwab_get(token, "/chains", {"symbol": "$SPX", "contractType": "ALL", "strikeCount": 80, "includeUnderlyingQuote": "false", "fromDate": t, "toDate": t}, timeout=6)
        used_sym = "$SPX"
        exps = set()
        if isinstance(data, dict):
            for mk in ("callExpDateMap", "putExpDateMap"):
                for k in (data.get(mk) or {}).keys():
                    exps.add(k.split(":")[0])
        if t not in exps:
            data_spxw = schwab_get(token, "/chains", {"symbol": "$SPXW", "contractType": "ALL", "strikeCount": 80, "includeUnderlyingQuote": "false", "fromDate": t, "toDate": t}, timeout=6)
            if isinstance(data_spxw, dict):
                data, used_sym = data_spxw, "$SPXW"
                exps = {k.split(":")[0] for mk in ("callExpDateMap", "putExpDateMap") for k in (data.get(mk) or {}).keys()}
        return data, used_sym, t in exps

    d = today_date
    data = used_sym = exp = None
    got_response = False
    for _ in range(7):
        if d.weekday() < 5:
            _data, _sym, ok = try_date(d)
            if isinstance(_data, dict):
                got_response = True
            if ok:
                data, used_sym, exp = _data, _sym, d.isoformat()
                break
        d += timedelta(days=1)
    if not exp:
        return None, {"reason": "만기 없음" if got_response else "체인 응답 없음 (토큰·API 확인)"}

    contracts = parse_schwab_chain(data, exp)
    dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today_date).days
    return ((contracts, exp) if contracts else None), {"used_symbol": used_sym, "is_0dte": dte == 0, "dte_days": dte}


# ─────────────────────────────────────────────────────────────
# 0DTE Credit Spread Optimizer 계산 엔진
# ─────────────────────────────────────────────────────────────
def _bs_delta(S, K, T, sigma, is_call, r=0.04):
    """Black-Scholes 델타. 0DTE에서는 만기가 짧아 델타가 0/1에 수렴 (핀 리스크 반영)."""
    try:
        if not (S and K and T and sigma) or T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return None
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        nd1 = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
        return nd1 if is_call else (nd1 - 1.0)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def compute_spread_optimizer(contracts, spot, call_wall, put_wall, em_pt, width=10.0, T_years=None):
    if not spot:
        return None

    cw = float(call_wall) if call_wall else (spot + 30.0)
    pw = float(put_wall) if put_wall else (spot - 30.0)
    em = float(em_pt) if em_pt else 25.0

    # 스프레드 폭 파라미터 (5pt 단위, 5~50pt). 기본 10pt.
    try:
        width = float(width)
    except (TypeError, ValueError):
        width = 10.0
    width = min(50.0, max(5.0, round(width / 5.0) * 5.0))

    c_bound = max(cw, spot + em)
    p_bound = min(pw, spot - em)

    # 1. 행사가별 실제 매수(Bid)·매도(Ask) 호가 및 유동성 맵 구성
    #    parse_schwab_chain 이 만드는 키: K, side, bid, ask, last, oi, vol
    quote_map = {}
    if contracts:
        for c in contracts:
            try:
                side_raw = str(c.get("side") or c.get("type") or c.get("putCall") or "").upper()
                side = "C" if side_raw.startswith("C") else ("P" if side_raw.startswith("P") else "")
                k = float(c.get("K") or c.get("strike") or 0)
                if not side or k <= 0:
                    continue

                bid = float(c.get("bid") or 0.0)
                ask = float(c.get("ask") or 0.0)
                mid = round((bid + ask) / 2.0, 2) if (bid > 0 and ask > 0) else float(c.get("mid") or c.get("mark") or c.get("last") or 0.0)
                ba_spread = round(max(0.0, ask - bid), 2) if (bid > 0 and ask > 0) else 99.0
                vol = int(c.get("vol") or c.get("volume") or c.get("totalVolume") or 0)
                oi = int(c.get("oi") or c.get("open_interest") or c.get("openInterest") or 0)

                iv_raw = num(c.get("iv"))
                iv = iv_raw if (iv_raw and 0.01 <= iv_raw <= 5.0) else None
                quote_map[(side, round(k, 1))] = {
                    "bid": bid, "ask": ask, "mid": mid,
                    "spread": ba_spread, "liq": vol + oi, "iv": iv
                }
            except Exception:
                continue

    # ATM IV (숏 레그 IV 없을 때 폴백용) — 같은 side에서 스팟에 가장 가까운 행사가
    _atm_iv = {}
    for _side in ("C", "P"):
        _best = None
        for (_s, _k), _q in quote_map.items():
            if _s != _side or not _q.get("iv"):
                continue
            _d = abs(_k - spot)
            if _best is None or _d < _best[0]:
                _best = (_d, _q["iv"])
        if _best:
            _atm_iv[_side] = _best[1]

    def _eval_spread(side, s_k, l_k, bound_val):
        qs = quote_map.get((side, round(s_k, 1)))
        ql = quote_map.get((side, round(l_k, 1)))
        dist_bound = round((s_k - bound_val) if side == "C" else (bound_val - s_k), 1)
        dist_spot = round(abs(s_k - spot), 1)

        if not qs or not ql or (qs["bid"] <= 0 and qs["mid"] <= 0):
            return None

        # 실제 매수·매도 호가 기반 체결가 계산
        # Natural(즉시 체결가) = 매도레그 Bid - 매수레그 Ask
        nat_cr = round(qs["bid"] - ql["ask"], 2) if (qs["bid"] > 0 and ql["ask"] > 0) else None
        mid_cr = round(qs["mid"] - ql["mid"], 2) if (qs["mid"] > 0 and ql["mid"] > 0) else None
        leg_spread_sum = round(qs["spread"] + ql["spread"], 2)

        # 실전 체결 예상 크레딧(Fill Credit): Mid에서 호가 슬리피지(25%) 차감
        if nat_cr is not None and mid_cr is not None:
            fill_cr = round(max(nat_cr, mid_cr - leg_spread_sum * 0.25), 2)
        else:
            fill_cr = mid_cr if (mid_cr and mid_cr > 0) else nat_cr

        if fill_cr is None or fill_cr <= 0.15 or fill_cr >= width * 0.90:
            return None

        # 최대 손실(Max Loss) 및 손익분기점(BEP) 계산
        max_loss_pt = round(width - fill_cr, 2)
        max_loss_usd = int(round(max_loss_pt * 100))
        max_profit_usd = int(round(fill_cr * 100))
        bep = round(s_k + fill_cr, 2) if side == "C" else round(s_k - fill_cr, 2)
        ror_pct = round((fill_cr / max_loss_pt) * 100, 1) if max_loss_pt > 0 else 0.0

        # 호가 기반 실제 체결 가능성(Fill Feasibility) 판정
        slip_ratio = leg_spread_sum / max(fill_cr, 0.01)
        # 호가 공백(LOW_LIQ)은 추천 후보에서 제외 — 체결 불가 스프레드 추천 방지
        if qs["bid"] <= 0.05 or leg_spread_sum > 2.50:
            return None
        if nat_cr is not None and nat_cr >= 0.25 and slip_ratio <= 0.45:
            fill_status = "SWEET_SPOT"
            badge = f"✅ 즉시 체결 양호 · BEP {bep:.1f} · 최대손실 -${max_loss_usd}"
        elif slip_ratio <= 0.85:
            fill_status = "LIMIT_OK"
            badge = f"🟢 지정가 체결 가능 · BEP {bep:.1f} · 최대손실 -${max_loss_usd}"
        else:
            fill_status = "WIDE_SPREAD"
            badge = f"🟡 호가 벌어짐(슬리피지 주의) · BEP {bep:.1f}"

        nat_str = f"${nat_cr:.2f}" if nat_cr is not None and nat_cr > 0 else "불가"
        guide = (
            f"실제호가(매도Bid ${qs['bid']:.2f}/매수Ask ${ql['ask']:.2f}) · "
            f"즉시체결 {nat_str} / 예상체결 ${fill_cr:.2f}(+${max_profit_usd}) · "
            f"최대손실 -${max_loss_usd}(RoR {ror_pct:.1f}%) · 손익분기 {bep:.1f}"
        )

        # 점수: [체결 용이성 + 안전 마진 + 손익비 균형]
        liq_score = 30.0 if fill_status == "SWEET_SPOT" else (20.0 if fill_status == "LIMIT_OK" else 5.0)
        safety_score = min(25.0, max(0.0, dist_bound * 1.5)) + (15.0 if dist_bound >= 0 else -20.0)
        ror_score = max(0.0, 20.0 - abs(ror_pct - 15.0) * 0.6)
        score = liq_score + safety_score + ror_score

        # 숏 레그 델타 (BS) + POP 추정치 — 0DTE 표준 행사가 선정 기준
        # POP ≈ 1 - |Δ| (숏 프리미엄의 만기 OTM 확률 근사, tastytrade 방식)
        _iv = qs.get("iv") or _atm_iv.get(side) or 0.25
        _delta = _bs_delta(spot, s_k, T_years, _iv, side == "C")
        _pop = round(max(5.0, min(95.0, (1.0 - abs(_delta)) * 100.0)), 1) if _delta is not None else None

        return {
            "short": s_k, "long": l_k, "credit": fill_cr,
            "nat_credit": nat_cr, "mid_credit": mid_cr,
            "max_loss": max_loss_pt, "max_loss_usd": max_loss_usd,
            "max_profit_usd": max_profit_usd, "bep": bep, "ror_pct": ror_pct,
            "short_delta": round(_delta, 3) if _delta is not None else None,
            "pop_pct": _pop,
            "short_bid": qs["bid"], "long_ask": ql["ask"], "ba_spread": leg_spread_sum,
            "dist_spot": dist_spot, "dist_bound": dist_bound,
            "status": fill_status, "badge": badge, "guide": guide,
            "boundary": round(bound_val, 1), "_score": score
        }

    # 2. 안전선(c_bound / p_bound) 바깥 행사가 후보군 탐색 (5pt 단위)
    min_short_c = float(int((c_bound + 4.99) // 5) * 5)
    max_short_p = float(int(p_bound // 5) * 5)

    call_candidates = []
    put_candidates = []
    for i in range(8):
        sc = min_short_c + (i * 5.0)
        res_c = _eval_spread("C", sc, sc + width, c_bound)
        if res_c:
            call_candidates.append(res_c)

        sp = max_short_p - (i * 5.0)
        res_p = _eval_spread("P", sp, sp - width, p_bound)
        if res_p:
            put_candidates.append(res_p)

    best_c = max(call_candidates, key=lambda x: x["_score"]) if call_candidates else None
    best_p = max(put_candidates, key=lambda x: x["_score"]) if put_candidates else None

    if not best_c:
        bep_fallback_c = round(min_short_c, 1)
        best_c = {
            "short": min_short_c, "long": min_short_c + width, "credit": None,
            "max_loss": None, "max_loss_usd": None, "bep": bep_fallback_c,
            "status": "WAITING", "badge": f"장중 호가 대기 · 기준선 {min_short_c:.0f}",
            "guide": f"안전선({c_bound:.0f}) 바깥 {width:.0f}pt 폭 · 정규장 개장 후 매수·매도 호가 유입 시 최대손실·BEP 자동 산출",
            "boundary": round(c_bound, 1)
        }
    else:
        best_c.pop("_score", None)

    if not best_p:
        bep_fallback_p = round(max_short_p, 1)
        best_p = {
            "short": max_short_p, "long": max_short_p - width, "credit": None,
            "max_loss": None, "max_loss_usd": None, "bep": bep_fallback_p,
            "status": "WAITING", "badge": f"장중 호가 대기 · 기준선 {max_short_p:.0f}",
            "guide": f"안전선({p_bound:.0f}) 바깥 {width:.0f}pt 폭 · 정규장 개장 후 매수·매도 호가 유입 시 최대손실·BEP 자동 산출",
            "boundary": round(p_bound, 1)
        }
    else:
        best_p.pop("_score", None)

    return {
        "available": True,
        "width": int(width),
        "engine_policy": "실제 매수·매도 호가로 체결 가능성을 검토하고, 최대 손실과 손익분기점을 계산합니다. 목표 크레딧만으로 추천하지 않습니다.",
        "call_spread": best_c,
        "put_spread": best_p,
    }


def analyze_gex(contracts, spot, scale, exp_date, now_et, source, diag=None, width=10.0):
    S = spot / scale
    y, m, d = (int(x) for x in exp_date.split("-"))
    exp_dt = ET.localize(datetime(y, m, d, 16, 0))
    secs = max((exp_dt - now_et).total_seconds(), 1800.0)
    T = secs / SECONDS_PER_YEAR

    use = [c for c in contracts if 0.88 * S <= c["K"] <= 1.12 * S and (c["oi"] > 0 or c.get("vol", 0) > 0)]
    if len(use) < 6:
        return None

    per = {}
    gamma_schwab = gamma_calc = 0
    # 진단용: 콜/풋별 감마 출처 집계 (11:00 콜 GEX 실종 진단용)
    gex_side_diag = {"C": {"schwab": 0, "bs": 0, "none": 0}, "P": {"schwab": 0, "bs": 0, "none": 0}}
    for c in use:
        raw_g = c["gamma"]
        g = raw_g or (bs_gamma(S, c["K"], T, c["iv"]) if c["iv"] else None)
        _gsrc = "schwab" if raw_g else ("bs" if c["iv"] else "none")
        gex_side_diag[c["side"]][_gsrc] += 1
        if g:
            gamma_schwab += 1 if raw_g else 0
            gamma_calc += 0 if raw_g else 1

        e = per.setdefault(c["K"], {"call_gex": 0.0, "put_gex": 0.0, "call_oi": 0.0, "put_oi": 0.0, "call_vol": 0.0, "put_vol": 0.0})
        eff_qty = max(c["oi"], c.get("vol", 0.0))

        if c["side"] == "C":
            e["call_oi"] += c["oi"]
            e["call_vol"] += c.get("vol", 0.0)
        else:
            e["put_oi"] += c["oi"]
            e["put_vol"] += c.get("vol", 0.0)

        if g and eff_qty > 0:
            dg = g * eff_qty * 100.0 * S * S * 0.01
            if c["side"] == "C":
                e["call_gex"] += dg
            else:
                e["put_gex"] -= dg

    if not per:
        return None

    calls_gex = [k for k, e in per.items() if e["call_gex"] > 0]
    puts_gex = [k for k, e in per.items() if e["put_gex"] < 0]
    call_wall = max(calls_gex, key=lambda k: per[k]["call_gex"]) * scale if calls_gex else None
    put_wall = min(puts_gex, key=lambda k: per[k]["put_gex"]) * scale if puts_gex else None
    net_total = sum(e["call_gex"] + e["put_gex"] for e in per.values())

    by_k = {}
    for c in contracts:
        m_val = ((c["bid"] + c["ask"]) / 2.0) if (c.get("bid") and c.get("ask")) else c.get("last")
        if m_val:
            by_k.setdefault(c["K"], {})[c["side"]] = m_val
    both = {k: v for k, v in by_k.items() if "C" in v and "P" in v}
    straddle = (both[min(both, key=lambda x: abs(x - S))]["C"] + both[min(both, key=lambda x: abs(x - S))]["P"]) if both else None
    em_pt = straddle * scale if straddle else None

    by_strike = []
    for K, e in sorted(sorted(per.items(), key=lambda kv: abs(kv[0] - S))[:14], key=lambda kv: kv[0]):
        c_gex_val = round(e["call_gex"] / 1e6, 2)
        p_gex_val = round(abs(e["put_gex"]) / 1e6, 2)
        net_gex_m = round((e["call_gex"] + e["put_gex"]) / 1e6, 2)
        abs_gex_m = round(abs(c_gex_val) + p_gex_val, 1)

        by_strike.append({
            "strike": round(K * scale, 1),
            "call_oi": int(e["call_oi"]),
            "put_oi": int(e["put_oi"]),
            "call_vol": int(e["call_vol"]),
            "put_vol": int(e["put_vol"]),
            "call_gex_m": c_gex_val,
            "put_gex_m": p_gex_val,
            "net_gex_m": net_gex_m,
            "abs_gex_m": abs_gex_m,
        })

    abs_pin_strike = None
    abs_pin_val = 0.0
    if by_strike:
        top_pin = max(by_strike, key=lambda s: s.get("abs_gex_m", 0))
        abs_pin_strike = top_pin["strike"]
        abs_pin_val = top_pin["abs_gex_m"]

    # Max Pain: 옵션 매도자(작성자) 전체 손실이 최소화되는 행사가.
    # 0DTE 만일에는 핀 효과로 종가가 Max Pain 근처로 끌려가는 경향.
    _max_pain = None
    try:
        if per:
            _strikes = sorted(per.keys())
            def _writer_loss(px):
                tot = 0.0
                for k, e in per.items():
                    tot += max(0.0, px - k) * e["call_oi"] + max(0.0, k - px) * e["put_oi"]
                return tot
            _max_pain = min(_strikes, key=_writer_loss)
    except Exception:
        _max_pain = None
    is_0dte_session = bool((now_et.hour < 16 and exp_date == now_et.date().isoformat()) or (now_et.hour >= 16 and exp_date >= now_et.date().isoformat()))

    # --- SPX Gamma Flip (Zero-Gamma 변곡점) 계산 ---
    real_gamma_flip = None
    gamma_flip_note = None
    try:
        valid_strikes = sorted(
            [s for s in by_strike if s.get("strike") is not None],
            key=lambda x: float(x["strike"])
        )
        if spot and len(valid_strikes) >= 4:
            near_strikes = [s for s in valid_strikes if abs(float(s["strike"]) - spot) <= 150]
            if len(near_strikes) >= 4:
                valid_strikes = near_strikes

        if len(valid_strikes) >= 2:
            # 1) 개별 행사가 노이즈 완화를 위한 3-Strike 스무딩 Net GEX 산출
            n_st = len(valid_strikes)
            smoothed_gex = []
            for idx in range(n_st):
                win = valid_strikes[max(0, idx - 1):min(n_st, idx + 2)]
                avg_net = sum(float(x.get("net_gex_m", x.get("net_gex", 0.0))) for x in win) / len(win)
                smoothed_gex.append((float(valid_strikes[idx]["strike"]), avg_net))

            # 2) 부호가 뒤집히는 영교차점(Zero-Crossing) 선형 보간
            crossings = []
            for idx in range(len(smoothed_gex) - 1):
                k1, g1 = smoothed_gex[idx]
                k2, g2 = smoothed_gex[idx + 1]
                if g1 == 0:
                    crossings.append((round(k1, 1), g2 > 0))
                elif (g1 < 0 and g2 > 0) or (g1 > 0 and g2 < 0):
                    flip_pt = k1 + (k2 - k1) * (0.0 - g1) / (g2 - g1)
                    crossings.append((round(flip_pt, 1), g1 < 0 and g2 > 0))

            if crossings:
                # 음(-) -> 양(+) 정방향 변곡점 우선, 현재가(spot)에서 가장 가까운 지점 선택
                pos_crossings = [c[0] for c in crossings if c[1]]
                candidates = pos_crossings if pos_crossings else [c[0] for c in crossings]
                real_gamma_flip = min(candidates, key=lambda x: abs(x - spot)) if spot else candidates[0]
                gamma_flip_note = "Zero-GEX 선형보간 (실시간 체인)"
            else:
                # 3) 전 구간 단일 부호일 때: Call/Put 감마 가중 균형점
                t_call = sum(abs(float(s.get("call_gex_m", s.get("call_gex", 0.0)))) for s in valid_strikes)
                t_put = sum(abs(float(s.get("put_gex_m", s.get("put_gex", 0.0)))) for s in valid_strikes)
                if t_call > 0 and t_put > 0:
                    c_center = sum(float(s["strike"]) * abs(float(s.get("call_gex_m", s.get("call_gex", 0.0)))) for s in valid_strikes) / t_call
                    p_center = sum(float(s["strike"]) * abs(float(s.get("put_gex_m", s.get("put_gex", 0.0)))) for s in valid_strikes) / t_put
                    w_put = t_put / (t_call + t_put)
                    real_gamma_flip = round(c_center * w_put + p_center * (1.0 - w_put), 1)
                    gamma_flip_note = "Call/Put 감마 가중 균형점"
    except Exception:
        real_gamma_flip = None

    if real_gamma_flip is None:
        real_gamma_flip = round((call_wall + put_wall) / 2.0, 1) if (call_wall and put_wall) else round(spot, 1)
        gamma_flip_note = "Wall 중간값 폴백"

    dte_days = (exp_dt.date() - now_et.date()).days
    return {
        "available": True, "source": source, "expiration": exp_date, "is_0dte": is_0dte_session, "dte_days": dte_days, "spot": round(spot, 1),
        "call_wall": round(call_wall, 1) if call_wall else None, "put_wall": round(put_wall, 1) if put_wall else None,
        "gamma_flip": real_gamma_flip, "gamma_flip_note": gamma_flip_note,
        "em_pt": round(em_pt, 1) if em_pt else None, "expected_move": f"±{em_pt:.1f}pt ({em_pt / spot * 100:.2f}%)" if em_pt else None,
        "net_gex": fmt_dollars(net_total), "regime": "positive" if net_total >= 0 else "negative",
        "regime_text": "양(+) 감마 우세 - 딜러 헤지가 변동성 억제" if net_total >= 0 else "음(−) 감마 우세 - 변동성 증폭 구간",
        "strike_count": len(per), "by_strike": by_strike,
        "abs_pin_strike": abs_pin_strike,
        "abs_pin_val": abs_pin_val,
        "max_pain": round(_max_pain, 1) if _max_pain else None,
        "gamma_source_note": (f"감마 {gamma_schwab}개 Schwab 제공값, {gamma_calc}개 BS 실시간 계산값"
            f" | 콜 Schwab {gex_side_diag['C']['schwab']}/BS {gex_side_diag['C']['bs']}/없음 {gex_side_diag['C']['none']}"
            f" · 풋 Schwab {gex_side_diag['P']['schwab']}/BS {gex_side_diag['P']['bs']}/없음 {gex_side_diag['P']['none']}"),
        "oi_skew": {
            "call_oi_at_or_above_spot": int(sum(e["call_oi"] for k, e in per.items() if k >= S)),
            "put_oi_at_or_above_spot": int(sum(e["put_oi"] for k, e in per.items() if k >= S)),
            "call_oi_below_spot": int(sum(e["call_oi"] for k, e in per.items() if k < S)),
            "put_oi_below_spot": int(sum(e["put_oi"] for k, e in per.items() if k < S)),
        },
    }


def get_gex(token, spx_p, ratio, now_et, width=10.0):
    if spx_p is None:
        return {"available": False, "source": "N/A", "reason": "SPX 현재가 없음"}
    try:
        width = float(width)
    except (TypeError, ValueError):
        width = 10.0
    width = min(50.0, max(5.0, round(width / 5.0) * 5.0))
    start = now_et.date() if now_et.hour < 16 else now_et.date() + timedelta(days=1)

    def load():
        r, diag = fetch_schwab_chain(token, start)
        if r:
            return analyze_gex(r[0], spx_p, 1.0, r[1], now_et, f"{SRC_SCHWAB} {diag.get('used_symbol','$SPX')} 체인 (실시간 Volume+OI 결합 GEX)", diag, width)
        return {"available": False, "source": "N/A", "reason": diag.get("reason") or "옵션 체인 수집 불가"}

    return cached(f"gex:w{width:g}", 60, load) or {"available": False, "source": "N/A", "reason": "GEX 조회 실패"}


def detect_market_shock(spx_p, spy_5m_candles, ratio, gex, cvd, vix_active, now_et):
    if not spx_p:
        return {"active": False}
    today = now_et.date()
    is_rth = (now_et.weekday() < 5) and ((now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30)) and now_et.hour < 16)
    if not is_rth:
        return {"active": False}

    today_open_ts = int(ET.localize(datetime(today.year, today.month, today.day, 9, 30, 0)).timestamp())
    today_bars = [c for c in (spy_5m_candles or []) if c["t"] >= today_open_ts]
    recent_bars = today_bars[-6:] if len(today_bars) >= 2 else []

    reasons, shock_type, level = [], "NORMAL", "NORMAL"
    elapsed_text = ""
    is_pre_alert = False

    if len(recent_bars) >= 2 and ratio:
        curr_c = recent_bars[-1]["c"] * ratio
        net_15m = curr_c - (recent_bars[-3]["o"] * ratio if len(recent_bars) >= 3 else recent_bars[0]["o"] * ratio)
        fast_5m = curr_c - (recent_bars[-2]["c"] * ratio)

        if fast_5m <= -10.0 or net_15m <= -16.0:
            shock_type = "DROP"
            level = "CRITICAL" if (fast_5m <= -15.0 or net_15m <= -24.0) else "WARNING"
            val = fast_5m if fast_5m <= -10.0 else net_15m
            reasons.append(f"단기 급락 압력 발생 ({val:.1f}pt 하락)")

        elif fast_5m >= 10.0 or net_15m >= 16.0:
            shock_type = "SURGE"
            level = "CRITICAL" if (fast_5m >= 15.0 or net_15m >= 24.0) else "WARNING"
            val = fast_5m if fast_5m >= 10.0 else net_15m
            reasons.append(f"단기 급등 모멘텀 발생 (+{val:.1f}pt 상승)")

    if gex and gex.get("available") and gex.get("is_0dte"):
        pw, cw = gex.get("put_wall"), gex.get("call_wall")
        by_strike = gex.get("by_strike", [])
        BUFFER = 2.5

        if pw and spx_p < (pw - BUFFER):
            reasons.append(f"Put Wall 지지선({pw:.1f}) 하향 붕괴 이탈 ({spx_p - pw:.1f}pt)")
            shock_type, level = "DROP", "CRITICAL"

        elif cw and spx_p > (cw + BUFFER):
            reasons.append(f"Call Wall 저항선({cw:.1f}) 상향 돌파 이탈 (+{spx_p - cw:.1f}pt)")
            shock_type, level = "SURGE", "CRITICAL"

        elif cw and (cw - 10.0 <= spx_p <= cw + BUFFER):
            cw_row = next((s for s in by_strike if abs(s["strike"] - cw) < 1.0), None)
            if cw_row:
                c_vol, c_oi = cw_row.get("call_vol", 0), cw_row.get("call_oi", 0)
                net_gex_m = cw_row.get("net_gex_m", 0)
                vol_threat = (c_oi > 0 and c_vol >= c_oi * 1.5) or (c_vol >= 8000)
                short_gamma = (net_gex_m < 0)
                cvd_bullish = (cvd and not cvd.get("is_prior") and cvd.get("buy_pct", 0) >= 54)

                if (vol_threat or short_gamma) and cvd_bullish:
                    shock_type, level = "SURGE", "CRITICAL"
                    is_pre_alert = True
                    reasons.append(f"Call Wall({cw:.0f}) 돌파 임박 접근 (현재 {spx_p:.1f}, 이격 {cw - spx_p:.1f}pt)")
                    if vol_threat:
                        reasons.append(f"{cw:.0f} Call 거래량({c_vol:,})이 미결제({c_oi:,}) 대비 폭발 (신규 매수벽 공격)")
                    if short_gamma:
                        reasons.append(f"{cw:.0f} Net GEX 음수({net_gex_m}M$)로 딜러 숏 감마 스퀴즈 가속")
                    reasons.append("⚠️ Bear Call Spread 신규 진입 즉시 보류")

        elif pw and (pw - BUFFER <= spx_p <= pw + 10.0):
            pw_row = next((s for s in by_strike if abs(s["strike"] - pw) < 1.0), None)
            if pw_row:
                p_vol, p_oi = pw_row.get("put_vol", 0), pw_row.get("put_oi", 0)
                vol_threat = (p_oi > 0 and p_vol >= p_oi * 1.5) or (p_vol >= 8000)
                cvd_bearish = (cvd and not cvd.get("is_prior") and cvd.get("sell_pct", 0) >= 54)

                if vol_threat and cvd_bearish:
                    shock_type, level = "DROP", "CRITICAL"
                    is_pre_alert = True
                    reasons.append(f"Put Wall({pw:.0f}) 지지선 붕괴 임박 접근 (현재 {spx_p:.1f}, 이격 {spx_p - pw:.1f}pt)")
                    reasons.append(f"{pw:.0f} Put 거래량({p_vol:,})이 미결제({p_oi:,}) 대비 폭발 (지지선 이탈 위험)")
                    reasons.append("⚠️ Bull Put Spread 신규 진입 즉시 보류")

        if not is_pre_alert:
            if shock_type == "SURGE" and pw and spx_p <= pw + 4.0:
                return {"active": False}
            if shock_type == "DROP" and cw and spx_p >= cw - 4.0:
                return {"active": False}

    if cvd and not cvd.get("is_prior"):
        if cvd.get("sell_pct", 0) >= 65 and shock_type == "DROP":
            reasons.append(f"매도 우위 체결 압력 추정 (Sell {cvd['sell_pct']}%)")
        elif cvd.get("buy_pct", 0) >= 65 and shock_type == "SURGE":
            reasons.append(f"매수 우위 체결 압력 추정 (Buy {cvd['buy_pct']}%)")

    if vix_active and shock_type == "DROP":
        vix_pct = vix_active.get("change_pct")
        if vix_pct and vix_pct >= 6.0:
            reasons.append(f"0DTE 변동성(VIX1D) 스파이크 폭등 (+{vix_pct:.1f}%)")

    is_active = len(reasons) > 0 and (shock_type in ("DROP", "SURGE"))

    if is_pre_alert:
        title = "🚨 [감마 스퀴즈 경보] Call Wall 돌파 임박" if shock_type == "SURGE" else "🚨 [감마 플러시 경보] Put Wall 붕괴 임박"
    else:
        title = (
            "🚨 [변동성 쇼크 · 급락 경보]"
            if shock_type == "DROP" and level == "CRITICAL"
            else (
                "⚠️ [변동성 쇼크 · 하방 주의보]"
                if shock_type == "DROP"
                else ("🚀 [변동성 쇼크 · 급등 경보]" if level == "CRITICAL" else "⚡ [변동성 쇼크 · 상방 모멘텀]")
            )
        )

    return {
        "active": is_active,
        "type": shock_type,
        "level": level,
        "title": title,
        "elapsed_text": elapsed_text or now_et.strftime("%H:%M ET"),
        "details": reasons,
        "timestamp": now_et.strftime("%H:%M:%S ET"),
    }


def analyze_tf(candles):
    closes = [c["c"] for c in candles]
    if len(closes) < 15:
        return None
    e5, e13, e21 = ema_series(closes, 5), ema_series(closes, 13), ema_series(closes, 21)
    p_vs_e5 = 1.0 if closes[-1] > e5[-1] else -1.0
    e5_vs_e13 = 1.0 if e5[-1] > e13[-1] else -1.0
    e13_vs_e21 = 1.0 if e13[-1] > e21[-1] else -1.0
    e5_slope = 1.0 if (len(e5) >= 2 and e5[-1] > e5[-2]) else -1.0

    rs = rsi_series(closes, period=9)
    rsi_val = rs[-1] if rs else 50.0
    rsi_score = 1.0 if rsi_val >= 55 else (-1.0 if rsi_val <= 45 else 0.0)

    score = max(-6.0, min(6.0, p_vs_e5 + e5_vs_e13 + e13_vs_e21 + e5_slope + rsi_score))
    label, tone = (
        ("상승 우세", "bull")
        if score >= 3.0
        else (
            ("상승 편향", "bull")
            if score >= 1.2
            else (("중립", "flat") if score > -1.2 else (("하락 편향", "bear") if score > -3.0 else ("하락 우세", "bear")))
        )
    )
    return {"score": round(score, 1), "status": label, "tone": tone}


def detect_trend_reversal(spy_5m_bars, ratio, vwap_calc, cvd_det, spx_p, now_et, econ_events):
    """장중 추세 전환 감지 (전 구간) — '직전 확립 추세'가 깨졌는지 3신호로 판정.
    세그먼트 방식: 완료된 10분봉을 순서대로 걸으며 추세 구간을 확정하고, 전환이
    확정되면 그 지점부터 새 추세 구간으로 재무장한다 (하루 여러 번 감지 가능).
    신호 (전부 마감 기준): ① VWAP 반대 마감 (10분봉 2연속) ② 구조 방어선 종가 돌파
    (상승 추세: 최근 고점 형성 구간의 최저 저점 / 하락 추세: 그 반대)
    ③ CVD 반전 (최근 30분 흐름이 세그먼트 누적 수급의 50%↑ 반대 + 극값 대비 50% 되돌림).
    세그먼트 이동폭 <10pt면 횡보로 보고 신호를 내지 않는다. 확정 기록은 KV에 하루 래치."""
    out = {"available": False, "state": "pre", "seg_dir": None, "seg_from": None,
           "seg_change": None, "defense": None,
           "signals": {"vwap": None, "orr": None, "cvd": None},
           "sig_count": 0, "sig_total": 0, "new_dir": None, "confirmed_at": None,
           "flips": [], "next_event": None, "new_flip": None, "new_warn": None, "new_invalidation": None, "note": ""}
    if not spy_5m_bars or not ratio or now_et is None:
        return out
    sess, is_prior, sess_date = get_rth_session(spy_5m_bars, now_et)
    if is_prior or not sess:
        return out
    out["available"] = True

    def _mins(t):
        d = datetime.fromtimestamp(t, ET)
        return d.hour * 60 + d.minute

    def _hm(mins):
        return f"{mins // 60:02d}:{mins % 60:02d}"

    # 임박/직후 고영향 이벤트 (10:00·14:00 등 시간대 무관 — 전환 주의 구간 표시용)
    try:
        now_ts0 = now_et.timestamp()
        best = None
        for it in (econ_events or {}).get("items") or []:
            if datetime.fromtimestamp(it["ts"], ET).date() != now_et.date():
                continue
            dm = (it["ts"] - now_ts0) / 60.0
            if -10 <= dm <= 20 and (best is None or abs(dm) < abs(best[0])):
                best = (dm, it)
        if best:
            out["next_event"] = {"title": best[1].get("title") or "경제지표",
                                 "time": datetime.fromtimestamp(best[1]["ts"], ET).strftime("%H:%M"),
                                 "mins": round(best[0])}
    except Exception:
        pass

    S = [{"t": c["t"], "m": _mins(c["t"]), "o": c["o"] * ratio, "h": c["h"] * ratio,
          "l": c["l"] * ratio, "c": c["c"] * ratio, "v": c.get("v") or 0} for c in sess]
    if not S:
        return out

    # 완료된 10분봉 + 봉별 누적 VWAP
    now_ts = now_et.timestamp()
    buckets = {}
    for b in S:
        bk = (b["m"] // 10) * 10
        buckets.setdefault(bk, []).append(b)
    bars10 = []
    cum_v = cum_tp = 0.0
    for bk in sorted(buckets):
        bs = buckets[bk]
        for b in bs:
            if b["v"] > 0:
                cum_v += b["v"]
                cum_tp += (b["h"] + b["l"] + b["c"]) / 3.0 * b["v"]
        end_ts = bs[0]["t"] - (bs[0]["m"] - bk) * 60 + 600
        if end_ts <= now_ts:
            bars10.append({"m": bk, "o": bs[0]["o"], "h": max(x["h"] for x in bs),
                           "l": min(x["l"] for x in bs), "c": bs[-1]["c"],
                           "vwap": (cum_tp / cum_v) if cum_v > 0 else None})
    if not bars10:
        out["state"] = "forming"
        out["note"] = "추세 형성 중"
        return out

    cvd_map = {}
    for b in (cvd_det or {}).get("bars") or []:
        if b.get("cvd_line") is not None:
            cvd_map[_mins(b["t"])] = b["cvd_line"]

    def _fresh_seg(i, d, px, cvd0):
        return {"dir": d, "start_i": i, "start_px": px, "start_cvd": cvd0,
                "from_min": bars10[i]["m"], "ext": px, "ext_cvd": cvd0,
                "defense": None, "vwap_ok": None,
                "hi": px, "lo": px, "min_l_since_hi": None, "max_h_since_lo": None,
                "def_up": None, "def_dn": None}

    def _pillars(i, sg):
        """i번 봉 마감 시점, 세그먼트 sg 기준 3신호 평가. sg는 i 이전 상태여야 한다."""
        d = sg["dir"]
        if not d:
            return {"vwap": None, "orr": None, "cvd": None}
        ds = 1 if d > 0 else -1
        sig = {"vwap": None, "orr": None, "cvd": None}
        # ① VWAP 반대 마감 (극값 봉에서 VWAP을 지킨 추세만 인정 — 반대편 추세는 N/A)
        if sg["vwap_ok"] and i >= 1:
            vw1, vw0 = bars10[i]["vwap"], bars10[i - 1]["vwap"]
            if vw1 and vw0:
                sig["vwap"] = bool((bars10[i]["c"] - vw1) * ds < 0 and (bars10[i - 1]["c"] - vw0) * ds < 0)
        # ② 구조 방어선 종가 돌파
        if sg["defense"] is not None:
            sig["orr"] = bool((bars10[i]["c"] - sg["defense"]) * ds < 0)
        # ③ CVD 반전
        cvd_i = cvd_map.get(bars10[i]["m"])
        cvd_i3 = cvd_map.get(bars10[i - 3]["m"]) if i >= 3 else None
        if cvd_i is not None and cvd_i3 is not None and sg["start_cvd"] is not None and sg["ext_cvd"] is not None:
            gain = sg["ext_cvd"] - sg["start_cvd"]
            if abs(gain) >= 2.0:
                d30 = cvd_i - cvd_i3
                sig["cvd"] = bool(d30 * ds <= -0.5 * abs(gain) and (cvd_i - sg["ext_cvd"]) * ds <= -0.5 * abs(gain))
        return sig

    flips = []
    seg = _fresh_seg(0, 0, bars10[0]["o"], cvd_map.get(bars10[0]["m"]))
    for i, b in enumerate(bars10):
        cvd_i = cvd_map.get(b["m"])
        # 극값·방어선 추적 (양방향 — 방향 확정 전에도 유지)
        if seg["min_l_since_hi"] is None or b["l"] < seg["min_l_since_hi"]:
            seg["min_l_since_hi"] = b["l"]
        if seg["max_h_since_lo"] is None or b["h"] > seg["max_h_since_lo"]:
            seg["max_h_since_lo"] = b["h"]
        if b["h"] > seg["hi"]:
            seg["def_up"] = seg["min_l_since_hi"]
            seg["hi"] = b["h"]
            seg["min_l_since_hi"] = b["l"]
            if seg["dir"] > 0:
                seg["ext"], seg["ext_cvd"] = b["h"], cvd_i
                seg["defense"] = seg["def_up"]
                seg["vwap_ok"] = bool(b["vwap"] and b["c"] > b["vwap"])
        if b["l"] < seg["lo"]:
            seg["def_dn"] = seg["max_h_since_lo"]
            seg["lo"] = b["l"]
            seg["max_h_since_lo"] = b["h"]
            if seg["dir"] < 0:
                seg["ext"], seg["ext_cvd"] = b["l"], cvd_i
                seg["defense"] = seg["def_dn"]
                seg["vwap_ok"] = bool(b["vwap"] and b["c"] < b["vwap"])
        # 방향 확정 (시작가 대비 ±10pt 먼저 도달한 쪽)
        if seg["dir"] == 0:
            up_move = seg["hi"] - seg["start_px"]
            dn_move = seg["start_px"] - seg["lo"]
            if up_move >= 10 or dn_move >= 10:
                seg["dir"] = 1 if up_move >= dn_move else -1
                if seg["dir"] > 0:
                    seg["ext"], seg["defense"] = seg["hi"], seg["def_up"]
                    seg["ext_cvd"] = cvd_map.get(bars10[seg["start_i"]]["m"])
                    for j in range(seg["start_i"], i + 1):
                        if bars10[j]["h"] == seg["hi"]:
                            seg["ext_cvd"] = cvd_map.get(bars10[j]["m"])
                            seg["vwap_ok"] = bool(bars10[j]["vwap"] and bars10[j]["c"] > bars10[j]["vwap"])
                            break
                else:
                    seg["ext"], seg["defense"] = seg["lo"], seg["def_dn"]
                    for j in range(seg["start_i"], i + 1):
                        if bars10[j]["l"] == seg["lo"]:
                            seg["ext_cvd"] = cvd_map.get(bars10[j]["m"])
                            seg["vwap_ok"] = bool(bars10[j]["vwap"] and bars10[j]["c"] < bars10[j]["vwap"])
                            break
            continue
        # 세그먼트 실패 처리: 확립(±10pt) 전에 종가가 시작가에서 반대 방향으로 10pt 이상
        # 밀리면 실패로 보고 반대 방향 세그먼트로 재시작한다. 전환 기록·알림 대상은 아님
        # (확립된 추세의 전환이 아니라, 실패한 반등/눌림의 정리 — 감지기가 죽은
        #  세그먼트에 갇혀 종일 전환 판정을 못 하는 것을 방지)
        if abs(seg["ext"] - seg["start_px"]) < 10 and (b["c"] - seg["start_px"]) * seg["dir"] <= -10:
            nd = -seg["dir"]
            seg = _fresh_seg(i, nd, b["c"], cvd_i)
            seg["hi"] = seg["lo"] = b["c"]
            continue
        # 전환 판정 (확립된 세그먼트, 최소 3봉 경과)
        established = abs(seg["ext"] - seg["start_px"]) >= 10
        if established and i - seg["start_i"] >= 3:
            sig = _pillars(i, seg)
            vals = [v for v in sig.values() if v is not None]
            if len(vals) >= 2 and all(vals):
                nd = -seg["dir"]
                flips.append({"at": _hm(b["m"] + 10), "end_min": b["m"] + 10,
                              "from": "up" if seg["dir"] > 0 else "down",
                              "to": "up" if nd > 0 else "down",
                              "px": round(b["c"], 1)})  # 확정가 (전환 봉 종가) — 무효화 판정 기준
                seg = _fresh_seg(i, nd, b["c"], cvd_i)
                seg["hi"] = seg["lo"] = b["c"]
                continue

    # 현재 세그먼트 표시 정보 + 실시간 신호
    last_i = len(bars10) - 1
    if seg["dir"]:
        out["seg_dir"] = "up" if seg["dir"] > 0 else "down"
        out["seg_from"] = _hm(seg["from_min"])
        out["seg_change"] = round(seg["ext"] - seg["start_px"], 1)
        out["defense"] = round(seg["defense"], 1) if seg["defense"] is not None else None
        sig = _pillars(last_i, seg)
        # ②번 실시간 보정: 현재가도 방어선 밖에 있어야 유지로 인정
        if sig["orr"] and seg["defense"] is not None:
            cur_px = spx_p or bars10[-1]["c"]
            sig["orr"] = bool((cur_px - seg["defense"]) * (1 if seg["dir"] > 0 else -1) < 0)
        out["signals"] = sig
        vals = [v for v in sig.values() if v is not None]
        out["sig_total"] = len(vals)
        out["sig_count"] = sum(1 for v in vals if v)

    # 확정 기록 KV 래치 (인스턴스 간 데이터 편차에도 기록 유지)
    latch_key = f"rev:{sess_date}"
    stored = []
    try:
        raw = kv_get(latch_key)
        if raw:
            stored = json.loads(raw) or []
    except Exception:
        stored = []
    merged = list(stored)
    known = {(f.get("at"), f.get("to")) for f in merged}
    _dirty = False
    for f in flips:
        if (f["at"], f["to"]) not in known:
            merged.append({"at": f["at"], "from": f["from"], "to": f["to"], "px": f.get("px")})
            out["new_flip"] = {"at": f["at"], "from": f["from"], "to": f["to"]}
            _dirty = True
        elif f.get("px") is not None:
            for mf in merged:  # 구 기록에 확정가가 없으면 보강 (무효화 판정용)
                if mf.get("at") == f["at"] and mf.get("to") == f["to"] and mf.get("px") is None:
                    mf["px"] = f["px"]
                    _dirty = True
    merged.sort(key=lambda f: f.get("at") or "")
    if _dirty:
        try:
            kv_set(latch_key, json.dumps(merged), ex_seconds=36 * 3600)
        except Exception:
            pass
    out["flips"] = merged
    last_flip = None
    if merged:
        lf = merged[-1]
        try:
            _hh, _mm = (lf.get("at") or "0:0").split(":")
            _em = int(_hh) * 60 + int(_mm)
        except Exception:
            _em = None
        last_flip = {"at": lf.get("at"), "to": lf.get("to"), "end_min": _em, "px": lf.get("px")}
    now_min = now_et.hour * 60 + now_et.minute
    recent = bool(last_flip and last_flip.get("end_min") is not None and now_min - last_flip["end_min"] <= 20)
    # 확정 무효화: 현재가가 확정가(전환 봉 종가)에서 반대 방향으로 5pt 이상 이탈하면
    # 확정 표시는 즉시 해제하고 실시간 상태로 복귀한다 (기록 자체는 flips에 남음)
    invalidated = False
    if last_flip and last_flip.get("px") is not None:
        _ds = 1 if last_flip.get("to") == "up" else -1
        _cur = spx_p or (bars10[-1]["c"] if bars10 else None)
        if _cur is not None and (_cur - last_flip["px"]) * _ds < -5:
            invalidated = True
        if not invalidated:
            # 무효 래치: 한 번 무효화된 확정은 가격이 되돌아와도 부활하지 않는다
            # (텔레그램은 1회성으로 이미 발송됐는데 웹 배지만 확정으로 되돌아가던 문제)
            try:
                if kv_get(f"rev-inv:{sess_date}:{last_flip['at']}:{last_flip['to']}"):
                    invalidated = True
            except Exception:
                pass

    if last_flip and recent and not invalidated:
        out["state"] = "confirmed"
        out["confirmed_at"] = last_flip["at"]
        out["new_dir"] = last_flip["to"]
        out["note"] = f"{last_flip['at']} 방향 전환 확정"
    elif not seg["dir"] or abs(seg["ext"] - seg["start_px"]) < 10:
        out["state"] = "forming" if now_min < 600 else "flat"
        out["note"] = "추세 형성 중" if out["state"] == "forming" else "뚜렷한 추세 없음 — 감지 대기"
    elif out["sig_count"] >= 2:
        out["state"] = "warn"
        out["note"] = "전환 경보 — 신호 2개 충족"
    elif out["sig_count"] == 1:
        out["state"] = "watch"
        out["note"] = "전환 조짐 — 신호 1개"
    else:
        out["state"] = "hold"
        out["note"] = "추세 유지 중"
    if invalidated and out["state"] in ("flat", "forming", "hold"):
        out["note"] = f"{last_flip['at']} 전환 무효 (확정가 이탈)"
    # 경보 텔레그램 트리거 — 경보(신호 2개 충족) 첫 진입 시 세그먼트당 1회만
    if out["state"] == "warn" and seg["dir"]:
        wkey = f"rev-warn:{sess_date}:{seg['from_min']}:{'up' if seg['dir'] > 0 else 'down'}"
        seen = False
        try:
            seen = bool(kv_get(wkey))
        except Exception:
            seen = False
        if not seen:
            try:
                kv_set(wkey, "1", ex_seconds=36 * 3600)
            except Exception:
                pass
            out["new_warn"] = {
                "seg_from": out["seg_from"], "seg_dir": out["seg_dir"],
                "sig_count": out["sig_count"], "sig_total": out["sig_total"],
                "at": _hm(bars10[-1]["m"] + 10) if bars10 else "",
            }
    # 무효 래치 + 텔레그램 트리거 — 무효화가 처음 감지되면 래치를 남기고(웹 표시용),
    # 텔레그램은 확정 60분 내일 때만 전환당 1회 발송한다
    if invalidated and last_flip:
        ikey = f"rev-inv:{sess_date}:{last_flip['at']}:{last_flip['to']}"
        seen = False
        try:
            seen = bool(kv_get(ikey))
        except Exception:
            seen = False
        if not seen:
            try:
                kv_set(ikey, "1", ex_seconds=36 * 3600)
            except Exception:
                pass
            if last_flip.get("end_min") is not None and now_min - last_flip["end_min"] <= 60:
                out["new_invalidation"] = {"at": last_flip["at"], "to": last_flip["to"],
                                           "px": last_flip["px"],
                                           "cur": round(_cur, 1) if _cur else None}
    return out


def build_direction(tf_results, tf_sources, spx_p, vwap_calc, c1h, cvd_data):
    avail = {k: v for k, v in tf_results.items() if v}
    if not avail:
        return {"available": False, "source": "N/A", "reason": "실시간 봉 수집 불가"}

    weights = {"5m": 0.35, "1m": 0.25, "15m": 0.25, "1h": 0.15}
    score = sum(weights[k] * avail[k]["score"] for k in avail) / sum(weights[k] for k in avail)

    vwap_diff = (spx_p - vwap_calc["val"]) if (spx_p and vwap_calc and vwap_calc.get("val")) else None
    if vwap_diff is not None:
        score += 1.0 if vwap_diff > 1.0 else (-1.5 if vwap_diff < -1.0 else 0)
    if cvd_data:
        score += 1.0 if cvd_data.get("tone") == "bull" else (-1.5 if cvd_data.get("tone") == "bear" else 0)
        div = cvd_data.get("divergence") or {}
        if div.get("type") == "bearish":
            score -= 1.0
        elif div.get("type") == "bullish":
            score += 1.0
        mom = cvd_data.get("momentum") or {}
        if mom.get("dir") == "up":
            score += 0.5
        elif mom.get("dir") == "down":
            score -= 0.5

    score = max(-6.0, min(6.0, score))
    label, tone = (
        ("상승 우세", "bull")
        if score >= 3.0
        else (
            ("상승 편향", "bull")
            if score >= 1.2
            else (("중립", "flat") if score > -1.2 else (("하락 편향", "bear") if score > -3.0 else ("하락 우세", "bear")))
        )
    )
    match_pct = int(round(sum(1 for v in avail.values() if v["tone"] == tone) / len(avail) * 100))

    evidence = []
    if vwap_diff is not None:
        evidence.append(
            {
                "title": "VWAP 위치",
                "signal": "bull" if vwap_diff > 0 else ("bear" if vwap_diff < 0 else "flat"),
                "text": f"현재가가 당일 VWAP {'위' if vwap_diff > 0 else '아래'} ({vwap_diff:+.2f}pt)",
            }
        )
    if cvd_data:
        evidence.append(
            {
                "title": "CVD 볼륨 압력",
                "signal": cvd_data["tone"],
                "text": f"{cvd_data['status']} (Buy {cvd_data['buy_pct']}% / Sell {cvd_data['sell_pct']}%)",
            }
        )
        div = cvd_data.get("divergence") or {}
        if div.get("type"):
            evidence.append(
                {
                    "title": "CVD 다이버전스",
                    "signal": "bear" if div["type"] == "bearish" else "bull",
                    "text": div.get("text", ""),
                }
            )
        mom = cvd_data.get("momentum") or {}
        if mom.get("dir") in ("up", "down"):
            evidence.append(
                {
                    "title": "CVD 모멘텀",
                    "signal": "bull" if mom["dir"] == "up" else "bear",
                    "text": mom.get("text", ""),
                }
            )

    return {
        "available": True,
        "score": round(score, 1),
        "score_text": f"{score:+.1f}",
        "status": label,
        "tone": tone,
        "match_pct": match_pct,
        "summary": f"단기 모멘텀과 체결 압력이 {'상승' if tone=='bull' else ('하락' if tone=='bear' else '중립')} 쪽입니다. {match_pct}% 일치.",
        "tfs": {k: ({**avail[k], "source": tf_sources.get(k)} if k in avail else None) for k in ("1h", "15m", "5m", "1m")},
        "evidence": evidence,
        "source": "Charles Schwab (SPY) · 0DTE EMA(5/13/21)·VWAP·ES CVD 결합",
    }


# ─────────────────────────────────────────────────────────────
# API 엔드포인트
# ─────────────────────────────────────────────────────────────
@app.get("/api/test-alert")
def test_telegram_alert(request: Request):
    if not _admin_ok(request):
        return JSONResponse({"status": "unauthorized"}, status_code=401)
    now_et = datetime.now(ET)
    mock = {
        "active": True,
        "type": "DROP",
        "level": "CRITICAL",
        "title": "🚨 [시스템 테스트] 텔레그램 연동 정상 작동 확인",
        "timestamp": now_et.strftime("%H:%M:%S ET"),
        "elapsed_text": f"{now_et.strftime('%H:%M ET')} 테스트 발송",
        "details": ["환경변수 연동 성공", "실시간 급변동 감지 시 이와 동일하게 자동 전송됩니다."],
    }
    return {"status": "ok", "result": send_telegram_shock_alert(mock, 5750.0, force_test=True)}


def _cron_ok(request: Request):
    """Vercel cron 인증: CRON_SECRET 환경변수와 Authorization 헤더 대조.
    수동 테스트용으로 기존 admin key(?key=)도 허용."""
    cron_secret = os.environ.get("CRON_SECRET")
    if cron_secret and request.headers.get("authorization", "") == f"Bearer {cron_secret}":
        return True
    return _admin_ok(request)


@app.get("/api/check-shock")
def check_shock(request: Request):
    """Vercel cron용 경량 쇼크 체크 — 브라우저가 꺼져 있어도 텔레그램 알람 발송.
    5분 간격 평일 실행 권장 (vercel.json). RTH가 아니면 Schwab API 호출 없이 즉시 종료.
    브라우저 폴링 경로와 동일한 방향별 쿨다운(KV)을 공유하므로 중복 발송 없음."""
    if not _cron_ok(request):
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    now_et = datetime.now(ET)
    is_rth = (now_et.weekday() < 5) and ((now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30)) and now_et.hour < 16)
    if not is_rth:
        return {"status": "skipped", "reason": "RTH 아님", "now_et": now_et.strftime("%m/%d %H:%M ET")}

    token, _ = get_schwab_token()
    if not token:
        return {"status": "error", "reason": "Schwab 토큰 없음"}

    try:
        quotes = get_all_quotes(token) or {}
        q_spx, q_spy = quotes.get("spx"), quotes.get("spy")
        spx_p = q_spx["price"] if q_spx else None
        if not spx_p:
            return {"status": "error", "reason": "SPX 호가 없음"}
        ratio = (spx_p / q_spy["price"]) if (q_spy and q_spy.get("price")) else None

        spy_5m = get_candles(token, "spy", "5m")
        spy_5m_bars = spy_5m.get("candles") if spy_5m else []
        if ratio is None and spy_5m_bars:
            ratio = spx_p / spy_5m_bars[-1]["c"]

        # GEX (월 브레이크 감지용) — 실패해도 가격 기반 감지는 계속 진행
        try:
            gex = get_gex(token, spx_p, ratio, now_et)
        except Exception:
            gex = None

        # CVD (Wall 접근 사전경보용 — 없으면 사전경보가 동작하지 않음)
        try:
            es_c = get_es_candles(token, "10m")
            cvd_cron = compute_cvd(es_c["candles"], "10m", es_c["source"], "ES", now_et, vol_unit="contracts", session="auto") if es_c else None
        except Exception:
            cvd_cron = None

        vix_target = quotes.get("vix1d") or quotes.get("vix")
        shock_alert = detect_market_shock(spx_p, spy_5m_bars, ratio, gex, cvd_cron, vix_target, now_et)
        if shock_alert and shock_alert.get("active"):
            tg = send_telegram_shock_alert(shock_alert, spx_p)
            return {"status": "checked", "alert": shock_alert.get("title"), "telegram": tg,
                    "now_et": now_et.strftime("%m/%d %H:%M ET")}
        return {"status": "checked", "alert": None, "now_et": now_et.strftime("%m/%d %H:%M ET")}
    except Exception as e:
        return {"status": "error", "reason": str(e)[:200]}


@app.get("/api/refresh-token")
def refresh_token_cron(request: Request):
    if not _admin_ok(request):
        return JSONResponse({"status": "unauthorized"}, status_code=401)
    token, msg = get_schwab_token(force_refresh=True)
    return {"status": "ok" if token else "error", "message": msg}


def _get_iv_rank(vix_q, now_et):
    """IV Rank = (현재 VIX - 1년 최저) / (1년 최고 - 1년 최저) * 100.
    히스토리는 JSON blob 1개로 관리해 KV 호출을 1~2회로 제한 (365회 순차 조회 금지).
    KV 없으면 None."""
    try:
        if not KV_AVAILABLE:
            return None
        vix = (vix_q or {}).get("price")
        if not vix or vix <= 0:
            return None
        today = now_et.strftime("%Y-%m-%d")
        hist = []
        try:
            raw = kv_get("ivrank:hist:v1")
            if raw:
                hist = json.loads(raw)
        except Exception:
            hist = []
        if not hist or hist[-1][0] != today:
            hist.append([today, round(vix, 2)])
            hist = hist[-400:]
            kv_set("ivrank:hist:v1", json.dumps(hist), ex_seconds=400 * 86400)
        vals = [v for _, v in hist if isinstance(v, (int, float)) and v > 0]
        if len(vals) < 20:
            return {"rank": None, "note": f"적립 중 ({len(vals)}/20일)"}
        lo, hi = min(vals), max(vals)
        rank = 0.0 if hi <= lo else round((vix - lo) / (hi - lo) * 100.0, 1)
        return {"rank": rank, "vix": round(vix, 2), "lo": round(lo, 2), "hi": round(hi, 2), "days": len(vals)}
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# 대시보드 사용자 인증 (1인 1비밀번호 + 1비밀번호 1기기 바인딩)
#  - Vercel 환경변수 DASHBOARD_USERS = JSON {"james": "pw1", "a": "pw2"}
#  - /api/login → 토큰 발급 (KV, 7일) → 이후 /api/market-data는 Bearer 토큰 필수
#  - 기기 바인딩: 같은 계정의 다른 device_id 로그인은 403 차단
#  - 관리자(/api/admin/unbind): 기기 바인딩 해제 + 해당 사용자 토큰 전부 무효화
# ─────────────────────────────────────────────────────────────
def _dashboard_users():
    """DASHBOARD_USERS 파싱 → (users_dict, error_detail).
    모바일 키보드 입력 대비: BOM·제로폭 문자 제거, 스마트 따옴표→일반,
    후행 쉼표 제거, 작은따옴표 JSON도 허용."""
    raw = os.environ.get("DASHBOARD_USERS", "") or ""
    # ── 진단: 메타정보만 수집 (비밀번호 노출 없음) ──
    diag = ""
    if AUTH_DIAG_MODE:
        codes = " ".join(f"U+{ord(c):04X}" for c in raw[:6])
        codes_tail = " ".join(f"U+{ord(c):04X}" for c in raw[-4:]) if len(raw) > 6 else ""
        diag = f" [진단: 길이={len(raw)}, 앞6코드={codes}, 뒤4코드={codes_tail}]"
    raw = raw.strip().lstrip("﻿").replace(" ", "").replace("​", "").replace("﻿", "")
    raw = raw.replace(""", '"').replace(""", '"').replace("'", "'").replace("'", "'")
    if not raw:
        return {}, "값이 비어있음 (환경변수 추가 후 재배포 필요)" + diag
    raw = re_lib.sub(r",\s*([}\]])", r"\1", raw)
    try:
        d = json.loads(raw)
    except Exception as e:
        try:
            d = json.loads(raw.replace("'", '"'))
        except Exception:
            pos = getattr(e, "pos", None)
            hint = f" (오류 위치: {pos}번째 문자)" if pos is not None else ""
            return {}, f"JSON 형식 오류{hint} (예: {{\"james\": \"pw\"}}){diag} [예외:{type(e).__name__}]"
    if not isinstance(d, dict):
        return {}, "JSON이 객체 형식이 아님" + diag
    if not d:
        return {}, "사용자가 비어있음" + diag
    return d, None


@app.post("/api/login")
async def api_login(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "잘못된 요청"}, status_code=400)
    user = str(body.get("user", "")).strip()
    password = str(body.get("password", ""))
    device_id = str(body.get("device_id", "")).strip()
    force = bool(body.get("force", False))
    users, uerr = _dashboard_users()
    if not users:
        return JSONResponse({"ok": False, "error": f"서버 설정 필요: DASHBOARD_USERS {uerr}"}, status_code=503)
    if not user or not device_id or len(device_id) > 128 or len(user) > 64:
        return JSONResponse({"ok": False, "error": "잘못된 요청"}, status_code=400)
    # 브루트포스 방어: 5회 실패 시 5분 잠금
    try:
        fails = int(kv_get(f"auth:fail:{user}") or 0)
    except Exception:
        fails = 0
    if fails >= 5:
        return JSONResponse({"ok": False, "error": "5회 실패로 5분간 잠김"}, status_code=429)
    expected = users.get(user)
    if not expected or not hmac_lib.compare_digest(str(expected), password):
        try:
            kv_set(f"auth:fail:{user}", str(fails + 1), ex_seconds=300)
        except Exception:
            pass
        return JSONResponse({"ok": False, "error": "아이디 또는 비밀번호가 일치하지 않습니다"}, status_code=401)
    try:
        rev = int(kv_get(f"auth:rev:{user}") or 0)
    except Exception:
        rev = 0
    # 1비밀번호 1기기: 이미 다른 기기에 바인딩되어 있으면 전환 확인 필요
    # force=True면 기존 바인딩 해제 후 새 기기로 전환 (기존 토큰 무효화)
    dev_raw = kv_get(f"auth:dev:{user}")
    if dev_raw:
        try:
            bound = json.loads(dev_raw)
        except Exception:
            bound = {}
        if bound.get("device_id") and bound.get("device_id") != device_id:
            if not force:
                return JSONResponse({"ok": False, "error": "TAKEOVER_REQUIRED",
                                     "message": "다른 기기에서 이미 사용 중입니다. 이 기기로 전환하시겠습니까?"}, status_code=403)
            # 강제 전환: rev 증가로 기존 토큰 무효화
            try:
                rev = int(kv_get(f"auth:rev:{user}") or 0) + 1
                kv_set(f"auth:rev:{user}", str(rev))
            except Exception:
                pass
    token = secrets_lib.token_urlsafe(32)
    kv_set(f"auth:tok:{token}", json.dumps({"user": user, "device_id": device_id, "rev": rev}), ex_seconds=7 * 86400)
    kv_set(f"auth:dev:{user}", json.dumps({"device_id": device_id, "rev": rev}))
    try:
        kv_set(f"auth:fail:{user}", "0", ex_seconds=300)
        kv_set(f"auth:last:{user}", datetime.now(ET).strftime("%Y-%m-%d %H:%M"))
    except Exception:
        pass
    return {"ok": True, "token": token, "user": user}


def _require_auth(request: Request):
    """Bearer 토큰 검증 → 사용자명 반환 (실패 시 None)"""
    if AUTH_DISABLED:
        return "guest"
    try:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        token = auth[7:].strip()
        if not token or len(token) > 128:
            return None
        raw = kv_get(f"auth:tok:{token}")
        if not raw:
            return None
        info = json.loads(raw)
        user = info.get("user")
        if not user:
            return None
        try:
            rev = int(kv_get(f"auth:rev:{user}") or 0)
        except Exception:
            rev = 0
        if info.get("rev", 0) != rev:
            return None  # unbind로 무효화된 토큰
        dev_raw = kv_get(f"auth:dev:{user}")
        if dev_raw:
            try:
                bound = json.loads(dev_raw)
                if bound.get("device_id") != info.get("device_id"):
                    return None
            except Exception:
                return None
        return user
    except Exception:
        return None


@app.post("/api/admin/unbind")
async def api_admin_unbind(request: Request):
    """관리자: 특정 사용자의 기기 바인딩 해제 + 토큰 전부 무효화 (비밀번호 변경 없이 재로그인 가능)"""
    if not _admin_ok(request):
        return JSONResponse({"ok": False}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    user = str(body.get("user", "")).strip()
    if not user:
        return JSONResponse({"ok": False, "error": "user 필요"}, status_code=400)
    kv_cmd("DEL", f"auth:dev:{user}")
    try:
        cur = int(kv_get(f"auth:rev:{user}") or 0)
    except Exception:
        cur = 0
    kv_set(f"auth:rev:{user}", str(cur + 1))
    return {"ok": True, "user": user}


@app.post("/api/logout")
async def api_logout(request: Request):
    """사용자 로그아웃: 기기 바인딩 해제 + 현재 토큰 무효화 (다른 기기에서 로그인 가능)"""
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else ""
    user = None
    if token:
        try:
            raw = kv_get(f"auth:tok:{token}")
            if raw:
                info = json.loads(raw)
                user = info.get("user")
        except Exception:
            pass
    if token:
        kv_cmd("DEL", f"auth:tok:{token}")
    if user:
        kv_cmd("DEL", f"auth:dev:{user}")
    return {"ok": True}


_PRES_BLOB_KEY = "presence:all"
_PRES_LOCAL = {"blob": {}, "fetched_at": 0.0, "wrote": {}}


def _admin_user(users):
    """관리자(접속자 표시를 볼 수 있는 사용자): ADMIN_USER 환경변수가
    우선하고, 없으면 DASHBOARD_USERS의 첫 번째 사용자가 소유자."""
    env_admin = (os.environ.get("ADMIN_USER") or "").strip()
    if env_admin and env_admin in users:
        return env_admin
    return next(iter(users), None)


def _presence_blob(force=False):
    """presence 블롭 조회 (인스턴스 메모리 20초 캐시 — KV 명령 절약)."""
    now = time.time()
    if force or now - _PRES_LOCAL["fetched_at"] > 20:
        blob = {}
        raw = kv_get(_PRES_BLOB_KEY)
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    blob = parsed
            except Exception:
                blob = {}
        _PRES_LOCAL["blob"] = blob
        _PRES_LOCAL["fetched_at"] = now
    return _PRES_LOCAL["blob"]


def _presence_touch(user):
    """접속 하트비트: 사용자의 마지막 접속 시각을 presence 블롭에 기록.
    사용자당 60초에 1회만 KV에 쓰고, 동시 쓰기 경합으로 다른 사용자의
    시각이 최대 수십 초 밀릴 수 있으나 온라인 판정(120초)에는 영향 없음."""
    try:
        if not user or user == "guest":
            return
        now = time.time()
        if now - _PRES_LOCAL["wrote"].get(user, 0) < 60:
            return
        blob = _presence_blob()
        if now - float(blob.get(user) or 0) >= 55:
            blob[user] = int(now)
            kv_set(_PRES_BLOB_KEY, json.dumps(blob))
            _PRES_LOCAL["wrote"][user] = now
            _PRES_LOCAL["fetched_at"] = now
    except Exception:
        pass


def _presence_payload(user):
    """관리자 전용 접속자 목록 (이름·온라인 여부·마지막 접속 경과).
    관리자가 아니면 None → 프론트 칩이 숨겨진다."""
    try:
        users, _e = _dashboard_users()
        if not users or _admin_user(users) != user:
            return None
        now = time.time()
        blob = _presence_blob()
        lst = []
        for name in users:
            ts = blob.get(name)
            ago = int(now - float(ts)) if ts else None
            lst.append({"name": name, "ago_sec": ago,
                        "online": (ago is not None and ago <= 120)})
        return {"admin": True, "users": lst}
    except Exception:
        return None


@app.get("/api/market-data")
def get_market_data(request: Request, background_tasks: BackgroundTasks, rsi_tf: str = "1H", cvd_tf: str = "10m", opt_width: str = "10", part: str = "full"):
    # 대시보드 인증: 토큰 없으면 데이터 차단 (잠금화면 장식 문제 해결)
    auth_user = _require_auth(request)
    if not auth_user:
        return JSONResponse({"status": "unauthorized", "error": "로그인이 필요합니다"}, status_code=401)
    _presence_touch(auth_user)  # 접속 하트비트 (관리자 접속자 표시용)
    t0 = time.time()
    # Vercel Hobby 함수 제한 10초 대비 응답 데드라인 (초과 시 느린 섹션은 폴백으로 대체)
    RESP_BUDGET = 8.5

    def _safe_result(fut, fallback=None):
        try:
            remain = RESP_BUDGET - (time.time() - t0)
            return fut.result(timeout=max(0.5, remain))
        except Exception:
            return fallback

    now_et = datetime.now(ET)
    now_str = now_et.strftime("%m/%d %H:%M:%S ET")

    token, schwab_msg = get_schwab_token()
    quotes = get_all_quotes(token) or {}
    q_spx, q_spy = quotes.get("spx"), quotes.get("spy")
    spx_p = q_spx["price"] if q_spx else None
    ratio_q = (spx_p / q_spy["price"]) if (spx_p and q_spy and q_spy.get("price")) else None

    def slim(q):
        return {"price": q["price"], "change": q["change"], "change_pct": q.get("change_pct"), "source": q["source"]} if q else None

    # 경량 모드 (프론트 시세 폴링 전용): 무거운 캔들·GEX·CVD 조회를 건너뛰고
    # 헤더 시세·금리·IV Rank만 반환한다 — 시세 갱신이 무거운 분석에 막히지 않게 분리
    if part == "quotes":
        used_q = [q["source"] for q in quotes.values() if q]
        schwab_cnt_q = sum(1 for s in used_q if src_kind(s) == "schwab")
        return {
            "status": "success",
            "timestamp": now_str,
            "source_summary": f"Schwab {schwab_cnt_q} · Realtime Hybrid",
            "schwab_status": schwab_msg,
            "presence": _presence_payload(auth_user),
            "spx": q_spx,
            "es": quotes.get("es"),
            "vix1d": slim(quotes.get("vix1d")),
            "vix": slim(quotes.get("vix")),
            "iv_rank": _get_iv_rank(quotes.get("vix"), now_et),
            "mag7": quotes.get("mag7"),
            "wti": quotes.get("wti"),
            "brent": quotes.get("brent"),
            "uso": quotes.get("uso"),
            "yields": {
                "3m": quotes.get("yield-3m"),
                "10y": quotes.get("yield-10y"),
                "30y": quotes.get("yield-30y"),
            },
        }

    r_key, c_key = normalize_tf(rsi_tf), normalize_tf(cvd_tf)
    spy_tf_set = {"1h", "15m", "5m", "1m", c_key}

    ex = ThreadPoolExecutor(max_workers=10)
    try:
        f_spy_all = {k: ex.submit(get_candles, token, "spy", k) for k in spy_tf_set}
        f_es_all = {k: ex.submit(get_es_candles, token, k) for k in spy_tf_set}
        f_spx_r = ex.submit(get_candles, token, "spx", r_key)
        f_gex = ex.submit(get_gex, token, spx_p, ratio_q, now_et, opt_width)
        f_cal = ex.submit(cached, "econ_events_data", 15, fetch_global_econ_calendar)
        f_news = ex.submit(fetch_flash_market_news)

        # 데드라인 기반 수집: 느린 섹션은 폴백으로 대체하고 전체 응답을 보호
        # (미완료 작업은 백그라운드에서 계속되어 캐시를 채움 — 다음 폴링에서 반영)
        spy_all_c = {k: _safe_result(f) for k, f in f_spy_all.items()}
        es_all_c = {k: _safe_result(f) for k, f in f_es_all.items()}
        spx_r = _safe_result(f_spx_r)
        spy_c = spy_all_c.get(c_key)
        es_c = es_all_c.get(c_key)
        gex = _safe_result(f_gex) or {"available": False, "source": "timeout"}
        _ = _safe_result(f_cal)
        _ = _safe_result(f_news)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    spy_5m = spy_all_c.get("5m")
    ratio = ratio_q or ((spx_p / spy_5m["candles"][-1]["c"]) if (spx_p and spy_5m and spy_5m.get("candles")) else None)
    # 장외 비율 왜곡 방지: 장외에는 SPX 종가가 고정된 채 SPY 시세만 ES를 따라 움직여
    # ratio_q가 튀고(예: 10.03→10.13), SPY 환산 레벨(VP·VWAP·전환 방어선)이 통째로 밀린다.
    # → 장외에서는 최근 정규장 세션의 종가 캔들끼리의 비율로 고정한다 (표시되는 세션과 동일 기준).
    _is_rth_now = now_et.weekday() < 5 and (now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30)) and now_et.hour < 16
    if not _is_rth_now and spy_5m and spy_5m.get("candles") and spx_r and spx_r.get("candles"):
        _spy_sess, _, _sd_spy = get_rth_session(spy_5m["candles"], now_et)
        _spx_sess, _, _sd_spx = get_rth_session(spx_r["candles"], now_et)
        if _spy_sess and _spx_sess and _sd_spy == _sd_spx and _spy_sess[-1]["c"]:
            ratio = _spx_sess[-1]["c"] / _spy_sess[-1]["c"]

    spy_5m_bars = spy_5m.get("candles") if spy_5m else []
    econ_events = get_today_econ_events(now_et, spy_5m_bars, ratio)

    # VP/VWAP 환산비: 표시 세션이 종료된 상태(장전·장후·주말)에서는 실시간 비율을 쓰지 않는다.
    # $SPX 호가는 직전 종가에 멈춰 있는데 SPY만 시간외로 움직여 비율이 틀어지기 때문
    # (2026-10-22 06:26 사례: SPY 장전 -0.94% → VP 전체가 당일 고점보다 +75pt 위에 표시됨).
    # 종료된 세션은 SPX 세션 종가(동결된 spx_p) ÷ 세션 마지막 SPY 캔들 종가로 환산한다.
    ratio_vp = ratio
    _sess_bars, _sess_prior, _ = get_rth_session(spy_5m_bars, now_et)
    _rth_now = (now_et.weekday() < 5) and ((now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30)) and now_et.hour < 16)
    if _sess_bars and spx_p and not (_rth_now and not _sess_prior):
        if _sess_bars[-1].get("c"):
            ratio_vp = spx_p / _sess_bars[-1]["c"]
    vwap_calc = compute_vwap(spy_5m_bars, ratio_vp, now_et) if spy_5m else None
    vp = compute_volume_profile(spy_5m_bars, ratio_vp, spy_5m["source"], now_et) if (spy_5m and ratio_vp) else None
    # CVD는 ES 선물 기준 (SPX 선행 수급, 단위: 계약). 세션 자동 선택 (정규장/야간LIVE/휴장).
    # ES 실패 시 SPY로 폴백 (카드가 비지 않도록). 사유를 기록해 UI에 표시.
    def _cvd_es(_sess):
        if not es_c or not es_c.get("candles"):
            return None
        _lt = es_c["candles"][-1].get("t", 0)
        return cached(f"cvd:es:{c_key}:{_sess}:{_lt}", 20, lambda: compute_cvd(es_c["candles"], c_key, es_c["source"], "ES", now_et, vol_unit="contracts", session=_sess))
    cvd = _cvd_es("auto")
    cvd_overnight = _cvd_es("overnight")
    if cvd is None and spy_c:
        es_reason = "ES 캔들 수신 실패" if not es_c else "ES 거래량 없음"
        cvd = compute_cvd(spy_c["candles"], c_key, spy_c["source"], "SPY", now_et)
        if cvd:
            cvd["fallback_note"] = f"SPY 대체 표시 ({es_reason} — ES 복구 시 자동 전환)"

    rsi = None
    if spx_r and spx_r.get("candles"):
        rs = rsi_series([c["c"] for c in spx_r["candles"]])
        if rs:
            cur = rs[-1]
            rsi = {
                "val": cur,
                "status": "과매수" if cur >= 70 else ("과매도" if cur <= 30 else ("상승" if cur >= 55 else ("하락" if cur <= 45 else "중립"))),
                "source": f"{spx_r['source']} · Wilder RSI(14)",
            }

    tf_results, tf_sources = {}, {}
    for k in ("1h", "15m", "5m", "1m"):
        d = spy_all_c.get(k)
        tf_results[k] = analyze_tf(d["candles"]) if (d and d.get("candles")) else None
        tf_sources[k] = d["source"] if d else None

    c1h = spy_all_c["1h"]["candles"] if (spy_all_c.get("1h") and spy_all_c["1h"].get("candles")) else []
    direction = build_direction(tf_results, tf_sources, spx_p, vwap_calc, c1h, cvd)

    # 추세 전환 감지 — CVD 신호는 UI 선택 TF와 무관하게 ES 10m 고정 (UI와 같은 캐시 키 공유)
    cvd_det = cvd
    es_10m = es_all_c.get("10m")
    if es_10m and es_10m.get("candles"):
        _lt10 = es_10m["candles"][-1].get("t", 0)
        _det = cached(f"cvd:es:10m:auto:{_lt10}", 20, lambda: compute_cvd(es_10m["candles"], "10m", es_10m["source"], "ES", now_et, vol_unit="contracts", session="auto"))
        if _det:
            cvd_det = _det
    reversal = detect_trend_reversal(spy_5m_bars, ratio, vwap_calc, cvd_det, spx_p, now_et, econ_events)
    if reversal.get("new_flip"):
        # 전환 확정 텔레그램 — 응답 지연 방지를 위해 백그라운드 발송 (발송 가드는 함수 내부)
        background_tasks.add_task(send_telegram_reversal_alert, reversal["new_flip"], spx_p)
    if reversal.get("new_warn"):
        # 전환 경보 텔레그램 — 확정보다 한 봉 먼저 (발송 가드는 함수 내부)
        background_tasks.add_task(send_telegram_warn_alert, reversal["new_warn"], spx_p)
    if reversal.get("new_invalidation"):
        # 전환 무효 텔레그램 — 확정가가 이탈된 순간 (발송 가드는 함수 내부)
        background_tasks.add_task(send_telegram_invalidation_alert, reversal["new_invalidation"], spx_p)

    vix_target = quotes.get("vix1d") or quotes.get("vix")
    shock_alert = detect_market_shock(spx_p, spy_5m_bars, ratio, gex, cvd, vix_target, now_et)
    if shock_alert and shock_alert.get("active"):
        # 응답 지연 방지: 텔레그램 발송은 응답 전송 후 백그라운드에서 실행
        background_tasks.add_task(send_telegram_shock_alert, shock_alert, spx_p)

    # IV Rank (6) — VIX 일별 종가를 KV에 적립해 1년 랭크 계산 (크레딧 매도 타이밍 잣대)
    iv_rank = _get_iv_rank(quotes.get("vix"), now_et)

    used = [q["source"] for q in quotes.values() if q]
    schwab_cnt = sum(1 for s in used if src_kind(s) == "schwab")

    return {
        "status": "success",
        "timestamp": now_str,
        "source_summary": f"Schwab {schwab_cnt} · Realtime Hybrid",
        "schwab_status": schwab_msg,
        "shock_alert": shock_alert,
        "spx": q_spx,
        "es": quotes.get("es"),
        "vix1d": slim(quotes.get("vix1d")),
        "vix": slim(quotes.get("vix")),
        "iv_rank": iv_rank,
        "mag7": quotes.get("mag7"),
        "econ_events": econ_events,
        "overnight": _build_overnight(now_et, (quotes.get("es") or {}).get("price")),
        "wti": quotes.get("wti"),
        "brent": quotes.get("brent"),
        "uso": quotes.get("uso"),
        "yields": {
            "3m": quotes.get("yield-3m"),
            "10y": quotes.get("yield-10y"),
            "30y": quotes.get("yield-30y"),
        },
        "volume_profile": vp,
        "gex": gex,
        "rsi": rsi,
        "cvd": cvd,
        "cvd_overnight": cvd_overnight,
        "direction": direction,
        "reversal": reversal,
        "presence": _presence_payload(auth_user),
    }


@app.get("/api/callback", response_class=HTMLResponse)
def schwab_callback(request: Request, code: Optional[str] = None):
    if not code:
        return HTMLResponse("<h1>인증 실패</h1>", status_code=400)
    app_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_SECRET")
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI") or str(request.url).split("?")[0]
    try:
        res = requests.post(
            "https://api.schwabapi.com/v1/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
            auth=(app_key, app_secret),
            timeout=8,
        )
    except Exception as e:
        return HTMLResponse(f"<h1>토큰 교환 오류</h1><p>{html_lib.escape(str(e))}</p>", status_code=502)
    if res.status_code != 200:
        return HTMLResponse("<h1>토큰 교환 실패</h1>", status_code=400)
    body = res.json()
    refresh_token = body.get("refresh_token", "")
    access_token = body.get("access_token", "")
    ttl = int(num(body.get("expires_in")) or 1800)
    if KV_AVAILABLE:
        now = time.time()
        kv_set(KV_KEY_REFRESH, refresh_token, ex_seconds=REFRESH_TOKEN_TTL)
        kv_set(KV_KEY_ACCESS, access_token, ex_seconds=ttl)
        kv_set(KV_KEY_ACCESS_EXP, str(now + ttl), ex_seconds=ttl)
    return HTMLResponse("<h1>✅ Schwab 인증 성공</h1><p>토큰이 저장되었습니다. 이 창을 닫아도 됩니다.</p>")
