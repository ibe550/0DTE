import yfinance as yf
import pandas as pd
import numpy as np
import math


def _prepare_indicators(df):
    """OHLCV 데이터프레임에 파생 지표(수급/변동성/모멘텀)를 계산해서 붙인다."""
    df = df.copy()
    df['Returns'] = df['Close'].pct_change()
    df['Vol_MA'] = df['Volume'].rolling(10).mean()
    df['Vol_Spike'] = df['Volume'] > (df['Vol_MA'] * 1.8)
    df['TR'] = np.maximum(df['High'] - df['Low'], abs(df['High'] - df['Close'].shift(1)))
    df['ATR'] = df['TR'].rolling(14).mean()
    df['Volatile_Market'] = df['TR'] > df['ATR']
    return df


def run_probability_analysis(ticker="ES=F", period="1mo", interval="5m", lookahead_bars=6):
    """
    고도화된 퀀트 백테스트 엔진 (상승/하락 확률 양방향 대칭 분석)

    [변경 사항]
    기존 버전은 "상승 + 거래량 급증 + 고변동성" 조건에서만 신호를 잡았기 때문에,
    이미 위로 튄(pump) 캔들 뒤에서만 테스트하는 구조라 통계적으로 되돌림(하락) 쪽으로
    쏠릴 수밖에 없었다(단기 buying-climax 반전 효과). 지금은 상승 스파이크 신호와
    하락 스파이크 신호를 대칭으로 둘 다 계산해서 합산한다 -> 초기 방향에 상관없이
    "거래량 급증 + 고변동성 뒤엔 실제로 어느 쪽이 더 많이 나오는가"를 공정하게 측정한다.

    또한 표본 수가 작을 때 승률/하락률이 통계적으로 불안정하다는 걸 명확히 하기 위해
    신뢰도(confidence_level)와 95% 신뢰구간 오차범위(margin_of_error)를 함께 반환한다.
    """
    df = yf.download(tickers=ticker, period=period, interval=interval, progress=False)
    if df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # --- 파생 지표 계산 (수급, 변동성, 모멘텀) ---
    df['Returns'] = df['Close'].pct_change()
    df['Vol_MA'] = df['Volume'].rolling(10).mean()
    df['Vol_Spike'] = df['Volume'] > (df['Vol_MA'] * 1.8)  # 거래량 급증

    df['TR'] = np.maximum(df['High'] - df['Low'], abs(df['High'] - df['Close'].shift(1)))
    df['ATR'] = df['TR'].rolling(14).mean()
    df['Volatile_Market'] = df['TR'] > df['ATR']  # 변동성 확대 구간

    # N봉 뒤 가격 변화
    df['Future_Return'] = df['Close'].shift(-lookahead_bars) - df['Close']
    df['Target_Win'] = df['Future_Return'] > 0
    df['Target_Loss'] = df['Future_Return'] < 0

    # 데이터 끝부분(마지막 lookahead_bars개 봉)은 미래 값이 없어 Future_Return이 NaN이다.
    # 이 구간은 신호가 잡히더라도 승/패 판정이 불가능하므로 분석 대상에서 제외한다.
    has_future = df['Future_Return'].notna()

    # --- 대칭 신호: 상승 스파이크 / 하락 스파이크 둘 다 포함 ---
    bullish_signal = df['Vol_Spike'] & (df['Returns'] > 0) & df['Volatile_Market'] & has_future
    bearish_signal = df['Vol_Spike'] & (df['Returns'] < 0) & df['Volatile_Market'] & has_future
    combined_signal = bullish_signal | bearish_signal

    total_signals = int(combined_signal.sum())
    bullish_count = int(bullish_signal.sum())
    bearish_count = int(bearish_signal.sum())

    if total_signals == 0:
        return None

    win_signals = int((combined_signal & df['Target_Win']).sum())
    loss_signals = int((combined_signal & df['Target_Loss']).sum())

    win_rate = (win_signals / total_signals) * 100
    loss_rate = (loss_signals / total_signals) * 100

    avg_win = df[combined_signal & df['Target_Win']]['Future_Return'].mean()
    avg_loss = abs(df[combined_signal & df['Target_Loss']]['Future_Return'].mean())

    avg_win_val = avg_win if not np.isnan(avg_win) else 0.0
    avg_loss_val = avg_loss if not np.isnan(avg_loss) else 0.0

    ev = ((win_rate / 100) * avg_win_val) - ((loss_rate / 100) * avg_loss_val)

    # --- 통계적 신뢰도 (표본 수가 작으면 승률/하락률은 노이즈에 가깝다) ---
    p = win_rate / 100.0
    se = math.sqrt(p * (1 - p) / total_signals) if total_signals > 0 else 0.0
    margin_of_error = round(se * 1.96 * 100, 1)  # 95% 신뢰구간, %p 단위

    if total_signals < 30:
        confidence_level = "LOW"
    elif total_signals < 100:
        confidence_level = "MEDIUM"
    else:
        confidence_level = "HIGH"

    date_start = df.index[0].strftime("%m/%d %H:%M") if len(df) else None
    date_end = df.index[-1].strftime("%m/%d %H:%M") if len(df) else None

    # --- 크레딧 스프레드 관점 백테스트 (신규) ---
    # 기존 win_rate/loss_rate는 "N봉 뒤 방향"만 본다. 하지만 실제 크레딧 스프레드는
    # 방향이 맞아도 중간에 숏 스트라이크를 한 번이라도 건드리면(breach) 손실이다.
    # 그래서 신호가 뜬 시점의 ATR을 기준으로 콜/풋 스트라이크를 근사로 잡고,
    # 그 뒤 lookahead_bars 구간 동안 고가/저가가 그 스트라이크를 건드렸는지 확인한다.
    # 주의: 실제 옵션 IV/프리미엄 데이터가 없어 ATR 기반 근사치를 쓴다.
    # 실제 체결 프리미엄과는 차이가 있을 수 있다.
    OFFSET_ATR_MULT = 2.0

    highs = df['High'].values
    lows = df['Low'].values
    closes = df['Close'].values
    atrs = df['ATR'].values
    combined_arr = combined_signal.values
    n = len(df)

    call_breaches = []
    put_breaches = []

    for i in range(n):
        if not combined_arr[i]:
            continue
        if i + lookahead_bars >= n:
            continue
        offset = atrs[i] * OFFSET_ATR_MULT
        if np.isnan(offset) or offset <= 0:
            continue

        call_strike = closes[i] + offset
        put_strike = closes[i] - offset

        window_high = highs[i + 1: i + 1 + lookahead_bars].max()
        window_low = lows[i + 1: i + 1 + lookahead_bars].min()

        call_breaches.append(1 if window_high > call_strike else 0)
        put_breaches.append(1 if window_low < put_strike else 0)

    spread_sample_size = len(call_breaches)
    if spread_sample_size > 0:
        call_spread_win_rate = round((1 - np.mean(call_breaches)) * 100, 1)
        put_spread_win_rate = round((1 - np.mean(put_breaches)) * 100, 1)
    else:
        call_spread_win_rate = None
        put_spread_win_rate = None

    return {
        "total_signals": total_signals,
        "bullish_signals": bullish_count,
        "bearish_signals": bearish_count,
        "win_rate": round(win_rate, 1),
        "loss_rate": round(loss_rate, 1),
        "avg_win": round(avg_win_val, 2),
        "avg_loss": round(avg_loss_val, 2),
        "expected_value": round(ev, 2),
        "confidence_level": confidence_level,
        "margin_of_error": margin_of_error,
        "date_start": date_start,
        "date_end": date_end,
        "call_spread_win_rate": call_spread_win_rate,
        "put_spread_win_rate": put_spread_win_rate,
        "spread_sample_size": spread_sample_size,
        "spread_offset_atr_mult": OFFSET_ATR_MULT,
    }


def run_walk_forward_analysis(ticker="ES=F", period="3mo", interval="5m",
                                lookahead_bars=6, n_windows=4):
    """
    워크포워드 / 아웃오브샘플 검증.

    기존 run_probability_analysis()는 선택한 기간 전체를 통째로 한 번만 계산한다.
    그러면 결과가 "여러 상황에서 반복되는 진짜 패턴"인지, 아니면 "그 기간에만
    우연히 나온 결과(과최적화)"인지 구분할 수 없다.

    이 함수는 전체 기간을 n_windows개의 연속된 구간으로 나눠서 구간마다 따로
    승률/스프레드 승률을 계산한다. 파라미터(거래량 1.8배, ATR 14기간 등)는
    구간마다 다시 맞추지 않고 동일하게 고정한다 -> 그래야 "이 고정된 규칙이
    시간이 지나도 계속 통하는가"를 제대로 검증할 수 있다.

    구간별 결과가 들쭉날쭉하면(방향이 왔다갔다하거나 승률 표준편차가 크면)
    지금까지의 백테스트 결과가 우연일 가능성이 높다는 뜻이다.
    """
    df = yf.download(tickers=ticker, period=period, interval=interval, progress=False)
    if df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = _prepare_indicators(df)
    df['Future_Return'] = df['Close'].shift(-lookahead_bars) - df['Close']
    df['Target_Win'] = df['Future_Return'] > 0
    df['Target_Loss'] = df['Future_Return'] < 0
    has_future = df['Future_Return'].notna()

    bullish_signal = df['Vol_Spike'] & (df['Returns'] > 0) & df['Volatile_Market'] & has_future
    bearish_signal = df['Vol_Spike'] & (df['Returns'] < 0) & df['Volatile_Market'] & has_future
    combined_signal = (bullish_signal | bearish_signal).values

    n = len(df)
    window_size = n // n_windows
    if window_size < 50:
        return None  # 데이터가 너무 적어 구간을 나누면 무의미함

    OFFSET_ATR_MULT = 2.0
    highs = df['High'].values
    lows = df['Low'].values
    closes = df['Close'].values
    atrs = df['ATR'].values
    win_arr = df['Target_Win'].values
    loss_arr = df['Target_Loss'].values

    windows_result = []

    for w in range(n_windows):
        start = w * window_size
        end = n if w == n_windows - 1 else (w + 1) * window_size

        total_signals = 0
        win_signals = 0
        loss_signals = 0
        call_breaches = []
        put_breaches = []

        for i in range(start, end):
            if not combined_signal[i]:
                continue
            total_signals += 1
            if win_arr[i]:
                win_signals += 1
            elif loss_arr[i]:
                loss_signals += 1

            # 미래 구간이 전체 데이터 범위를 안 벗어나면 스프레드 브리치도 계산
            # (윈도우 경계를 넘어 다음 구간 데이터를 살짝 참조할 수 있는데,
            # 이건 "그 시점에 실제로 일어난 일"이라 백테스트 상 문제 없음)
            if i + lookahead_bars < n:
                offset = atrs[i] * OFFSET_ATR_MULT
                if not np.isnan(offset) and offset > 0:
                    call_strike = closes[i] + offset
                    put_strike = closes[i] - offset
                    wh = highs[i + 1:i + 1 + lookahead_bars].max()
                    wl = lows[i + 1:i + 1 + lookahead_bars].min()
                    call_breaches.append(1 if wh > call_strike else 0)
                    put_breaches.append(1 if wl < put_strike else 0)

        win_rate = round(win_signals / total_signals * 100, 1) if total_signals > 0 else None
        loss_rate = round(loss_signals / total_signals * 100, 1) if total_signals > 0 else None
        call_wr = round((1 - np.mean(call_breaches)) * 100, 1) if call_breaches else None
        put_wr = round((1 - np.mean(put_breaches)) * 100, 1) if put_breaches else None

        windows_result.append({
            "window": w + 1,
            "date_start": df.index[start].strftime("%m/%d"),
            "date_end": df.index[end - 1].strftime("%m/%d"),
            "total_signals": total_signals,
            "win_rate": win_rate,
            "loss_rate": loss_rate,
            "call_spread_win_rate": call_wr,
            "put_spread_win_rate": put_wr,
        })

    # --- 구간 간 안정성(consistency) 평가 ---
    valid_win_rates = [wr["win_rate"] for wr in windows_result if wr["win_rate"] is not None]

    if len(valid_win_rates) >= 2:
        stability_std = round(float(np.std(valid_win_rates)), 1)
        directions = [1 if wr > 50 else (-1 if wr < 50 else 0) for wr in valid_win_rates]
        consistent_direction = (len(set(directions)) == 1) and (0 not in directions)
    else:
        stability_std = None
        consistent_direction = None

    return {
        "windows": windows_result,
        "n_windows": n_windows,
        "lookahead_bars": lookahead_bars,
        "stability_std": stability_std,
        "consistent_direction": consistent_direction,
    }
