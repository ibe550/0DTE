"""
신호 기록·추적 모듈.

목적: "데이터 기반"이라고 주장하려면 매일의 신호(BULLISH/BEARISH/WAIT)와
그 결과가 실제로 어떻게 됐는지를 쌓아서, 시스템 스스로 "내가 얼마나 맞추고
있나"를 검증할 수 있어야 한다. 이 모듈이 그 역할을 한다.

저장소: SQLite 파일 (signal_log.db, 앱과 같은 디렉토리).
주의: Streamlit Cloud는 재배포되거나 앱이 장시간 미사용으로 슬립 후 재시작되면
파일 시스템이 초기화될 수 있어 완전한 영구 보존은 보장되지 않는다.
정말 장기 보존이 필요하면 Google Sheets나 외부 DB 연동으로 바꿔야 한다.
"""

import os
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import pytz
import yfinance as yf

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signal_log.db")
EST_TZ = pytz.timezone("US/Eastern")

# 같은 서버에서 너무 자주 resolve를 돌리면(재실행마다) yfinance 호출이 쌓여
# rate limit 위험이 커진다. 최소 이 간격(초)마다만 실제로 조회한다.
MIN_RESOLVE_INTERVAL_SEC = 180
MAX_RESOLVE_PER_RUN = 5  # 한 번에 확인할 최대 미해결 신호 수


def _get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at TEXT NOT NULL,
            spot_price REAL,
            direction TEXT,
            confidence REAL,
            win_rate REAL,
            loss_rate REAL,
            call_strike REAL,
            put_strike REAL,
            timeframe_label TEXT,
            timeframe_minutes INTEGER,
            target_check_at TEXT,
            resolved INTEGER DEFAULT 0,
            actual_price_at_check REAL,
            actual_direction TEXT,
            call_breached INTEGER,
            put_breached INTEGER,
            correct INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    return conn


def log_signal(spot_price, direction, confidence, win_rate, loss_rate,
                call_strike, put_strike, timeframe_label, timeframe_minutes):
    """
    새 신호를 기록한다. direction: 'BULLISH' / 'BEARISH' / 'WAIT'
    timeframe_minutes 뒤를 '결과 확인 시점'으로 잡는다.
    """
    conn = _get_conn()
    now_et = datetime.now(EST_TZ)
    target_check_at = now_et + timedelta(minutes=timeframe_minutes)

    conn.execute("""
        INSERT INTO signals
        (logged_at, spot_price, direction, confidence, win_rate, loss_rate,
         call_strike, put_strike, timeframe_label, timeframe_minutes, target_check_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now_et.isoformat(), spot_price, direction, confidence, win_rate, loss_rate,
        call_strike, put_strike, timeframe_label, timeframe_minutes, target_check_at.isoformat()
    ))
    conn.commit()
    conn.close()


def _get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def _set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def resolve_pending_signals():
    """
    확인 시점이 지난 미해결 신호들의 실제 결과를 조회해서 채운다.
    너무 잦은 호출을 막기 위해 MIN_RESOLVE_INTERVAL_SEC 안에 다시 불리면 스킵한다.
    """
    conn = _get_conn()
    now_et = datetime.now(EST_TZ)

    last_run_str = _get_meta(conn, "last_resolve_at")
    if last_run_str:
        last_run = datetime.fromisoformat(last_run_str)
        if (now_et - last_run).total_seconds() < MIN_RESOLVE_INTERVAL_SEC:
            conn.close()
            return 0

    _set_meta(conn, "last_resolve_at", now_et.isoformat())
    conn.commit()

    pending = pd.read_sql(
        "SELECT * FROM signals WHERE resolved=0 ORDER BY logged_at ASC LIMIT ?",
        conn, params=(MAX_RESOLVE_PER_RUN * 3,)
    )
    if pending.empty:
        conn.close()
        return 0

    resolved_count = 0
    checked = 0

    for _, row in pending.iterrows():
        if checked >= MAX_RESOLVE_PER_RUN:
            break

        target_time = datetime.fromisoformat(row['target_check_at'])
        if target_time.tzinfo is None:
            target_time = EST_TZ.localize(target_time)
        if target_time > now_et:
            continue  # 아직 확인 시점 안 됨

        logged_time = datetime.fromisoformat(row['logged_at'])
        if logged_time.tzinfo is None:
            logged_time = EST_TZ.localize(logged_time)

        checked += 1

        try:
            hist = yf.download(
                tickers='ES=F',
                start=logged_time - timedelta(minutes=10),
                end=target_time + timedelta(minutes=15),
                interval='5m',
                progress=False,
            )
        except Exception:
            continue

        if hist is None or hist.empty:
            continue

        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)

        if hist.index.tz is None:
            hist.index = hist.index.tz_localize('UTC').tz_convert(EST_TZ)
        else:
            hist.index = hist.index.tz_convert(EST_TZ)

        window = hist[(hist.index >= logged_time) & (hist.index <= target_time + timedelta(minutes=5))]
        if window.empty:
            continue

        actual_price = float(window['Close'].iloc[-1])
        window_high = float(window['High'].max())
        window_low = float(window['Low'].min())

        spot = row['spot_price']
        if actual_price > spot:
            actual_direction = "UP"
        elif actual_price < spot:
            actual_direction = "DOWN"
        else:
            actual_direction = "FLAT"

        call_strike = row['call_strike']
        put_strike = row['put_strike']
        call_breached = int(window_high > call_strike) if pd.notna(call_strike) else None
        put_breached = int(window_low < put_strike) if pd.notna(put_strike) else None

        predicted = row['direction']
        if predicted == "BULLISH":
            correct = int(actual_direction == "UP")
        elif predicted == "BEARISH":
            correct = int(actual_direction == "DOWN")
        else:
            correct = None  # WAIT(관망)는 맞다/틀리다 판정 대상 아님

        conn.execute("""
            UPDATE signals SET resolved=1, actual_price_at_check=?, actual_direction=?,
            call_breached=?, put_breached=?, correct=? WHERE id=?
        """, (actual_price, actual_direction, call_breached, put_breached, correct, int(row['id'])))
        resolved_count += 1

    conn.commit()
    conn.close()
    return resolved_count


def get_signal_history(limit=100):
    conn = _get_conn()
    df = pd.read_sql(
        "SELECT * FROM signals ORDER BY logged_at DESC LIMIT ?", conn, params=(limit,)
    )
    conn.close()
    return df


def get_accuracy_stats():
    """
    자기 검증용 통계. 신뢰구간 표시가 있는 신호(confidence)만 대상으로
    구간별(낮음/보통/높음) 실제 적중률을 비교해서, 신뢰도 표시가 실제로
    의미가 있는지(캘리브레이션)까지 확인할 수 있게 한다.
    """
    conn = _get_conn()
    df = pd.read_sql(
        "SELECT * FROM signals WHERE resolved=1 AND correct IS NOT NULL", conn
    )
    conn.close()

    if df.empty:
        return None

    overall_accuracy = round(df['correct'].mean() * 100, 1)
    total_resolved = len(df)

    bins = [0, 40, 70, 101]
    labels = ["낮음(<40%)", "보통(40-70%)", "높음(70%+)"]
    df['conf_tier'] = pd.cut(df['confidence'].fillna(0), bins=bins, labels=labels, right=False)
    by_confidence = df.groupby('conf_tier', observed=True)['correct'].agg(['mean', 'count'])
    by_confidence['mean'] = (by_confidence['mean'] * 100).round(1)

    df['logged_date'] = pd.to_datetime(df['logged_at']).dt.date
    daily = df.groupby('logged_date')['correct'].agg(['mean', 'count'])
    daily['mean'] = (daily['mean'] * 100).round(1)

    return {
        "overall_accuracy": overall_accuracy,
        "total_resolved": total_resolved,
        "by_confidence": by_confidence,
        "daily_accuracy": daily,
    }
