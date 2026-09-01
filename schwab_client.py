"""
Schwab API 클라이언트 - 실시간 시세 + 옵션 체인 + GEX(감마 노출도) 계산.

인증 흐름:
- Streamlit Secrets에 저장된 SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SCHWAB_REFRESH_TOKEN을 이용해
  access_token(30분 유효)을 자동으로 발급/갱신한다.
- refresh_token 자체는 Schwab 정책상 7일 후 만료되며 자동 연장이 안 된다.
  7일마다 로컬에서 schwab_auth_setup.py를 다시 실행해서 Secrets를 갱신해야 한다.
- refresh_token이 만료되면 이 모듈의 함수들은 에러 메시지를 반환한다 (앱을 죽이지 않음).
"""

import base64
import requests
import streamlit as st

TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
CHAINS_URL = "https://api.schwabapi.com/marketdata/v1/chains"
QUOTES_URL = "https://api.schwabapi.com/marketdata/v1/quotes"


def _get_credentials():
    app_key = st.secrets.get("SCHWAB_APP_KEY", "")
    app_secret = st.secrets.get("SCHWAB_APP_SECRET", "")
    refresh_token = st.secrets.get("SCHWAB_REFRESH_TOKEN", "")
    return app_key, app_secret, refresh_token


def is_configured():
    app_key, app_secret, refresh_token = _get_credentials()
    return bool(app_key and app_secret and refresh_token)


@st.cache_data(ttl=1500)  # access_token은 30분(1800초) 유효 -> 25분마다 미리 갱신
def _get_access_token():
    """refresh_token으로 access_token 발급. 반환: (access_token_or_None, error_or_None)"""
    app_key, app_secret, refresh_token = _get_credentials()
    if not (app_key and app_secret and refresh_token):
        return None, "Schwab API 키가 secrets에 설정되지 않았습니다 (SCHWAB_APP_KEY/SCHWAB_APP_SECRET/SCHWAB_REFRESH_TOKEN)."

    basic_auth = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
    try:
        resp = requests.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {basic_auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            timeout=10,
        )
    except Exception as e:
        return None, f"Schwab 토큰 갱신 요청 실패: {e}"

    if resp.status_code == 401:
        return None, "Schwab refresh_token이 만료됐습니다 (7일 주기) - schwab_auth_setup.py를 로컬에서 다시 실행해 갱신하세요."
    if resp.status_code != 200:
        return None, f"Schwab 토큰 갱신 실패 ({resp.status_code}): {resp.text[:150]}"

    return resp.json().get("access_token"), None


def fetch_quotes(symbols):
    """
    실시간 시세 조회. symbols: 리스트, 예: ["$SPX", "$VIX", "SPY"]
    반환: ({symbol: (price, chg, pct)}, error_or_None)
    """
    access_token, err = _get_access_token()
    if access_token is None:
        return {}, err

    try:
        resp = requests.get(
            QUOTES_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"symbols": ",".join(symbols)},
            timeout=10,
        )
    except Exception as e:
        return {}, f"Schwab 시세 조회 요청 실패: {e}"

    if resp.status_code != 200:
        return {}, f"Schwab 시세 조회 실패 ({resp.status_code}): {resp.text[:150]}"

    data = resp.json()
    results = {}
    for sym in symbols:
        entry = data.get(sym, {})
        quote = entry.get("quote", {})
        price = quote.get("lastPrice") or quote.get("mark")
        chg = quote.get("netChange")
        pct = quote.get("netPercentChange")
        if price is not None:
            results[sym] = (float(price), float(chg or 0), float(pct or 0))
        else:
            results[sym] = (None, None, None)

    return results, None


def fetch_option_chain(symbol="$SPX", contract_type="ALL", strike_count=40, expiration_date=None):
    """
    옵션 체인 조회. 반환: (chain_dict_or_None, error_or_None)

    expiration_date: "YYYY-MM-DD" 문자열. 지정하면 그 날짜 만기만 요청해서
    (fromDate=toDate=해당일) 불필요한 다른 만기(예: 몇 년 뒤 LEAPS)까지
    받아오는 걸 방지한다. None이면 모든 만기를 다 받아온다(비효율적이고
    다른 만기 데이터가 섞여 계산이 왜곡될 위험이 있음).
    """
    access_token, err = _get_access_token()
    if access_token is None:
        return None, err

    params = {
        "symbol": symbol,
        "contractType": contract_type,
        "strikeCount": strike_count,
        "includeUnderlyingQuote": "true",
        "strategy": "SINGLE",
        "range": "ALL",
    }
    if expiration_date:
        params["fromDate"] = expiration_date
        params["toDate"] = expiration_date

    try:
        resp = requests.get(
            CHAINS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            timeout=15,
        )
    except Exception as e:
        return None, f"Schwab 옵션체인 요청 실패: {e}"

    if resp.status_code != 200:
        return None, f"Schwab 옵션체인 조회 실패 ({resp.status_code}): {resp.text[:150]}"

    return resp.json(), None


def calculate_gex_from_chain(chain_data, spot_price):
    """
    옵션 체인에서 스트라이크별 감마 익스포저(GEX)를 계산한다.
    관례: 콜 GEX는 +(딜러 매도 콜 관점에서 헤지 매수 압력), 풋 GEX는 -로 표시.
    GEX(strike) = OI * gamma * 100 * spot^2 * 0.01  (업계에서 흔히 쓰는 근사 공식)

    반환: dict 또는 None (체인이 비어있을 때)
    {
        'by_strike': [{'strike', 'call_gex', 'put_gex', 'net_gex'}, ...],
        'call_wall': strike,       # 콜 감마가 가장 큰 스트라이크 (저항대 근사)
        'put_wall': strike,        # 풋 감마(음수)가 가장 큰 스트라이크 (지지대 근사)
        'gamma_flip': strike_or_None,  # 누적 net_gex 부호가 바뀌는 지점
        'net_gex_total': float,
        'net_delta_total': float,  # 전체 델타 익스포저 합 (콜 - 풋)
    }
    """
    if not chain_data:
        return None

    strike_gex = {}
    net_delta_total = 0.0

    for exp_map_key in ("callExpDateMap", "putExpDateMap"):
        exp_map = chain_data.get(exp_map_key, {})
        is_call = exp_map_key == "callExpDateMap"
        for _exp_date, strikes in exp_map.items():
            for strike_str, contracts in strikes.items():
                for c in contracts:
                    # 안전망: API 요청에서 fromDate/toDate로 오늘 만기만 걸러도,
                    # 혹시 다른 만기가 섞여 오면(예: 요청 파라미터 무시됨) 여기서 한 번 더 걸러낸다.
                    # 0DTE가 아닌 계약(며칠~몇 년 뒤 만기, 특히 LEAPS)이 섞이면
                    # 그 계약들의 대량 미결제약정이 전체 계산을 왜곡시킨다.
                    if c.get("daysToExpiration") not in (0, None):
                        continue

                    try:
                        strike = float(c.get("strikePrice", strike_str))
                    except (TypeError, ValueError):
                        continue
                    gamma = c.get("gamma") or 0
                    delta = c.get("delta") or 0
                    oi = c.get("openInterest") or 0

                    gex = oi * gamma * 100 * (spot_price ** 2) * 0.01
                    delta_exposure = oi * delta * 100

                    if strike not in strike_gex:
                        strike_gex[strike] = {"call_gex": 0.0, "put_gex": 0.0}

                    if is_call:
                        strike_gex[strike]["call_gex"] += gex
                        net_delta_total += delta_exposure
                    else:
                        strike_gex[strike]["put_gex"] -= gex
                        net_delta_total += delta_exposure  # 풋 델타는 원래 음수라 그대로 더함

    if not strike_gex:
        return None

    by_strike = []
    for strike in sorted(strike_gex.keys()):
        call_gex = strike_gex[strike]["call_gex"]
        put_gex = strike_gex[strike]["put_gex"]
        by_strike.append({
            "strike": strike,
            "call_gex": call_gex,
            "put_gex": put_gex,
            "net_gex": call_gex + put_gex,
        })

    call_wall = max(by_strike, key=lambda x: x["call_gex"])["strike"]
    put_wall = min(by_strike, key=lambda x: x["put_gex"])["strike"]
    net_gex_total = sum(x["net_gex"] for x in by_strike)

    gamma_flip = None
    cumulative = 0.0
    for row in by_strike:
        prev_cumulative = cumulative
        cumulative += row["net_gex"]
        if prev_cumulative != 0 and (
            (prev_cumulative < 0 <= cumulative) or (prev_cumulative > 0 >= cumulative)
        ):
            gamma_flip = row["strike"]
            break

    return {
        "by_strike": by_strike,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "gamma_flip": gamma_flip,
        "net_gex_total": net_gex_total,
        "net_delta_total": net_delta_total,
    }
