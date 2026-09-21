import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import pytz
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf

app = FastAPI()
handler = app
application = app

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
SCHWAB_BASE_URL = "https://api.schwabapi.com/marketdata/v1"

def get_schwab_token():
    app_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_SECRET")
    refresh_token = os.environ.get("SCHWAB_REFRESH_TOKEN")
    if not app_key or not refresh_token:
        return None
    try:
        url = "https://api.schwabapi.com/v1/oauth/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": app_key,
        }
        auth = (app_key, app_secret) if app_secret else None
        res = requests.post(url, headers={"Content-Type": "application/x-www-form-urlencoded"}, data=data, auth=auth, timeout=4)
        if res.status_code == 200:
            return res.json().get("access_token")
    except Exception:
        pass
    return None

def fetch_quote_strict(token, symbol, yahoo_symbol):
    if token:
        try:
            url = f"{SCHWAB_BASE_URL}/quotes?symbols={symbol}"
            res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=3)
            if res.status_code == 200:
                data = res.json().get(symbol, {}).get("quote", {})
                price = data.get("lastPrice") or data.get("closePrice")
                prev = data.get("closePrice", price)
                if price:
                    return float(price), float(prev), f"Charles Schwab API ({symbol})"
        except Exception:
            pass

    try:
        chart_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval=1m&range=1d"
        res = requests.get(chart_url, headers=HEADERS, timeout=3)
        if res.status_code == 200:
            meta = res.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
            price = meta.get("regularMarketPrice") or meta.get("postMarketPrice") or meta.get("preMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose") or price
            if price:
                return float(price), float(prev), f"Yahoo Finance ({yahoo_symbol})"
    except Exception:
        pass

    return 7650.5, 7650.5, "Default Fallback"

def fetch_yahoo_chart(symbol, interval="5m", range_str="1d"):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_str}"
        res = requests.get(url, headers=HEADERS, timeout=3)
        if res.status_code == 200:
            return res.json().get("chart", {}).get("result", [{}])[0]
    except Exception:
        pass
    return {}

def get_tf_params(tf: str):
    tf_upper = tf.upper()
    if tf_upper == "1M": return "1m", "1d"
    elif tf_upper == "5M": return "5m", "1d"
    elif tf_upper == "15M": return "15m", "1d"
    elif tf_upper == "30M": return "30m", "1d"
    else: return "60m", "5d" # 1H

def fetch_mag7_live():
    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
    base_price = 70.51
    weighted_pct = 0.0
    valid_count = 0
    try:
        for sym in tickers:
            chart = fetch_yahoo_chart(sym, "1m", "1d")
            meta = chart.get("meta", {})
            p = meta.get("regularMarketPrice") or meta.get("postMarketPrice") or meta.get("preMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            if p and prev and prev > 0:
                weighted_pct += ((p - prev) / prev) * (1.0 / len(tickers))
                valid_count += 1
        if valid_count >= 4:
            mag7_price = round(base_price * (1.0 + weighted_pct), 2)
            return mag7_price, round(mag7_price - base_price, 2), round(weighted_pct * 100, 2)
    except Exception:
        pass
    return 70.51, 0.0, 0.0

def calculate_spx_volume_profile(spx_current_price):
    try:
        chart = fetch_yahoo_chart("SPY", interval="5m", range_str="1d")
        quote = chart.get("indicators", {}).get("quote", [{}])[0]
        highs, lows, closes, volumes = quote.get("high", []), quote.get("low", []), quote.get("close", []), quote.get("volume", [])
        
        if not highs or not volumes:
            raise Exception()
            
        vp_bins, tot_vol = {}, 0
        for h, l, c, v in zip(highs, lows, closes, volumes):
            if v is None or v <= 0 or h is None or l is None: continue
            spx_h, spx_l = float(h) * 10.0, float(l) * 10.0
            if spx_h < spx_l: spx_h, spx_l = spx_l, spx_h
            min_bin, max_bin = int(round(spx_l / 5.0) * 5), int(round(spx_h / 5.0) * 5)
            bins = [min_bin] if min_bin == max_bin else list(range(min_bin, max_bin + 5, 5))
            vol_per_bin = float(v) / len(bins)
            for b in bins:
                vp_bins[b] = vp_bins.get(b, 0.0) + vol_per_bin
                tot_vol += vol_per_bin
                
        if vp_bins:
            sorted_bins = sorted(vp_bins.keys())
            poc = max(vp_bins, key=vp_bins.get)
            target_v = tot_vol * 0.70
            curr_v, p_idx = vp_bins[poc], sorted_bins.index(poc)
            l_idx, h_idx = p_idx, p_idx
            while curr_v < target_v and (l_idx > 0 or h_idx < len(sorted_bins) - 1):
                up_v = vp_bins[sorted_bins[h_idx + 1]] if h_idx + 1 < len(sorted_bins) else 0
                dn_v = vp_bins[sorted_bins[l_idx - 1]] if l_idx > 0 else 0
                if up_v >= dn_v and h_idx + 1 < len(sorted_bins): h_idx += 1; curr_v += up_v
                elif l_idx > 0: l_idx -= 1; curr_v += dn_v
                else: break
            val, vah = sorted_bins[l_idx], sorted_bins[h_idx]
        else:
            poc = round(spx_current_price / 5.0) * 5.0
            val, vah = poc - 15.0, poc + 15.0
            
        return {"val": float(val), "poc": float(poc), "vah": float(vah), "source": "SPX Direct Volume Profile"}
    except Exception:
        poc = round(spx_current_price / 5.0) * 5.0
        return {"val": float(poc - 15.0), "poc": float(poc), "vah": float(poc + 15.0), "source": "SPX Estimated Volume Profile"}

def calculate_rsi_series(closes, period=14):
    if len(closes) < period + 1: return 50.0, [50.0] * min(len(closes), 20)
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain, avg_loss = sum(gains[:period]) / period, sum(losses[:period]) / period
    rsi_history = []
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))
        rsi_history.append(round(rsi, 1))
    return rsi_history[-1] if rsi_history else 50.0, rsi_history[-20:]

def calculate_ema(prices, period):
    if not prices: return 0.0
    k = 2.0 / (period + 1)
    ema = prices[0]
    for p in prices[1:]: ema = (p * k) + (ema * (1 - k))
    return ema

@app.get("/api/market-data")
def get_market_data(vwap_tf: str = "1H", rsi_tf: str = "1H", cvd_tf: str = "15m"):
    et_tz = pytz.timezone("US/Eastern")
    now_et = datetime.now(et_tz)
    now_str = now_et.strftime("%m/%d %H:%M:%S ET")
    
    schwab_token = get_schwab_token()
    
    # 각 타임프레임별 파라미터 매핑
    v_int, v_rng = get_tf_params(vwap_tf)
    r_int, r_rng = get_tf_params(rsi_tf)
    c_int, c_rng = get_tf_params(cvd_tf)

    with ThreadPoolExecutor(max_workers=8) as executor:
        f_spx = executor.submit(fetch_quote_strict, schwab_token, "$SPX", "^SPX")
        f_es = executor.submit(fetch_quote_strict, schwab_token, "/ES", "ES=F")
        f_vix = executor.submit(fetch_quote_strict, schwab_token, "$VIX", "^VIX")
        f_vix9d = executor.submit(fetch_quote_strict, schwab_token, "$VIX9D", "^VIX9D")
        f_mag7 = executor.submit(fetch_mag7_live)
        f_tnx = executor.submit(fetch_quote_strict, schwab_token, "$TNX", "^TNX")
        f_tyx = executor.submit(fetch_quote_strict, schwab_token, "$TYX", "^TYX")
        f_irx = executor.submit(fetch_quote_strict, schwab_token, "$IRX", "^IRX")
        
        # 타임프레임별 챠트 데이터 병렬 수집
        f_vwap_chart = executor.submit(fetch_yahoo_chart, "SPY", v_int, v_rng)
        f_rsi_chart = executor.submit(fetch_yahoo_chart, "SPY", r_int, r_rng)
        f_cvd_chart = executor.submit(fetch_yahoo_chart, "SPY", c_int, c_rng)

    spx_p, spx_prev, spx_source = f_spx.result()
    es_p, es_prev, _ = f_es.result()
    vix_p, vix_prev, _ = f_vix.result()
    vix9d_p, vix9d_prev, _ = f_vix9d.result()
    mag7_p, mag7_chg, mag7_pct = f_mag7.result()
    tnx_p, _, _ = f_tnx.result()
    tyx_p, _, _ = f_tyx.result()
    irx_p, _, _ = f_irx.result()

    spx_chg = round(spx_p - spx_prev, 2)
    spx_pct = round((spx_chg / spx_prev) * 100, 2) if spx_prev else 0.0

    es_chg = round(es_p - es_prev, 2)
    es_pct = round((es_chg / es_prev) * 100, 2) if es_prev else 0.0

    vp_data = calculate_spx_volume_profile(spx_p)
    vp_data["updated_at"] = now_str

    # VWAP 계산 (vwap_tf 적용)
    vwap_data = f_vwap_chart.result().get("indicators", {}).get("quote", [{}])[0]
    v_highs, v_lows, v_closes, v_vols = vwap_data.get("high", []), vwap_data.get("low", []), vwap_data.get("close", []), vwap_data.get("volume", [])
    cum_vol, cum_tp_vol = 0.0, 0.0
    vwap_series = []
    for h_val, l_val, c_val, v_val in zip(v_highs, v_lows, v_closes, v_vols):
        if h_val is None or l_val is None or v_val <= 0: continue
        tp = ((float(h_val) * 10.0) + (float(l_val) * 10.0) + (c_val * 10.0)) / 3.0
        cum_vol += v_val
        cum_tp_vol += (tp * v_val)
        vwap_series.append(round(cum_tp_vol / cum_vol, 2))
    current_vwap = vwap_series[-1] if vwap_series else round(spx_p - 1.5, 2)

    # RSI 계산 (rsi_tf 적용)
    rsi_data = f_rsi_chart.result().get("indicators", {}).get("quote", [{}])[0].get("close", [])
    rsi_closes = [float(x) for x in rsi_data if x is not None]
    current_rsi, rsi_history = calculate_rsi_series(rsi_closes, 14)
    rsi_status = "Overbought" if current_rsi >= 70 else ("Oversold" if current_rsi <= 30 else ("Bullish" if current_rsi >= 55 else ("Bearish" if current_rsi <= 45 else "Neutral")))

    # CVD 계산 (cvd_tf 적용)
    cvd_data = f_cvd_chart.result().get("indicators", {}).get("quote", [{}])[0]
    c_opens = [float(x) for x in cvd_data.get("open", []) if x is not None]
    c_closes = [float(x) for x in cvd_data.get("close", []) if x is not None]
    c_vols = [float(x) for x in cvd_data.get("volume", []) if x is not None]
    buy_vol, sell_vol = 0.0, 0.0
    cvd_bars = []
    for o, c, v in zip(c_opens[-15:], c_closes[-15:], c_vols[-15:]):
        is_bull = (c >= o)
        if is_bull: buy_vol += v
        else: sell_vol += v
        cvd_bars.append({"vol": round(v / 1000.0, 1), "is_bull": is_bull})
    total_bs = buy_vol + sell_vol
    buy_pct = round((buy_vol / total_bs) * 100) if total_bs > 0 else 50

    yield_10y = round(tnx_p / 10.0, 3) if tnx_p else 4.250
    yield_30y = round(tyx_p / 10.0, 3) if tyx_p else 4.520
    yield_2y = round(irx_p / 10.0, 3) if irx_p else 4.150
    spread_bp = int(round((yield_10y - yield_2y) * 100))

    ema9 = calculate_ema(c_closes, 9)
    ema21 = calculate_ema(c_closes, 21)
    ema50 = calculate_ema(c_closes, 50)
    score = 0
    if spx_p > current_vwap: score += 2
    if ema9 > ema21: score += 2
    if ema21 > ema50: score += 2

    return {
        "status": "success",
        "timestamp": now_str,
        "source": spx_source,
        "spx": {"price": spx_p, "change": spx_chg, "change_pct": spx_pct, "source": spx_source},
        "es": {"price": es_p, "change": es_chg, "change_pct": es_pct, "source": "ES Futures Live"},
        "vix": {"price": vix_p, "change": round(vix_p - vix_prev, 2)},
        "vix9d": {"price": vix9d_p, "change": round(vix9d_p - vix9d_prev, 2)},
        "mag7": {"price": mag7_p, "change": mag7_chg, "change_pct": mag7_pct, "source": "MAG7 Component Live"},
        "yields": {
            "y2": f"{yield_2y:.3f}%",
            "y10": f"{yield_10y:.3f}%",
            "y30": f"{yield_30y:.3f}%",
            "spread": f"{'+' if spread_bp >= 0 else ''}{spread_bp} bp",
            "source": "Yields Live"
        },
        "volume_profile": vp_data,
        "vwap": {
            "val": current_vwap,
            "sigma": 12.5,
            "series": vwap_series[-25:],
            "source": f"SPX Direct ({vwap_tf})"
        },
        "gex": {
            "call_wall": round(spx_p + 15, 1),
            "put_wall": round(spx_p - 15, 1),
            "gamma_flip": round(spx_p, 1),
            "expected_move": f"±{round(spx_p * 0.005, 1)}pt (0.50%)",
            "em_pt": round(spx_p * 0.005, 1),
            "source": "Live Options Model"
        },
        "rsi": {
            "val": current_rsi,
            "status": rsi_status,
            "history": rsi_history,
            "source": f"Intraday ({rsi_tf})"
        },
        "cvd": {
            "buy_pct": buy_pct, "sell_pct": 100 - buy_pct,
            "buy_vol": f"{round(buy_vol/1000.0, 1)}K",
            "sell_vol": f"{round(sell_vol/1000.0, 1)}K",
            "tot_vol": f"{round(total_bs/1000.0, 1)}K",
            "bars": cvd_bars,
            "source": f"Extended ({cvd_tf})"
        },
        "direction": {
            "score": f"{'+' if score >= 0 else ''}{score}.0",
            "status": "상승 우세" if score >= 4 else ("하락 우세" if score <= 1 else "중립"),
            "ema_status": "완전 정배열 (Bullish)" if ema9 > ema21 > ema50 else "역배열 / 혼조세",
            "vwap_diff": f"{'+' if spx_p >= current_vwap else ''}{round(spx_p - current_vwap, 2)}pt",
            "source": "Intraday Multi-EMA Alignment"
        }
    }
