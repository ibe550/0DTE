import pandas as pd
import numpy as np
from datetime import datetime
import pytz

# Alpaca SDK Imports
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest
from alpaca.data.enums import OptionsFeed

class AlpacaOptionEngine:
    def __init__(self, api_key: str, secret_key: str):
        """
        Alpaca Option Historical / Real-time Data Client 초기화
        """
        self.client = OptionHistoricalDataClient(api_key, secret_key)
        self.est_tz = pytz.timezone('US/Eastern')

    def get_0dte_chain_analytics(self, symbol: str = "SPY", current_price: float = 0.0):
        """
        오늘 만기(0DTE) 옵션 체인을 조회하여 실시간 Delta, IV, GEX, 주요 Strike 추출
        """
        if current_price <= 0:
            return None

        today_str = datetime.now(self.est_tz).strftime('%Y-%m-%d')

        try:
            # 1. 0DTE 옵션 체인 요청 (현재가 기준 ±2% 범위 행수가격)
            req = OptionChainRequest(
                underlying_symbol=symbol,
                expiration_date=today_str,
                feed=OptionsFeed.INDICATIVE # 또는 OPRA (구독 플랜에 맞게 설정)
            )
            
            chain = self.client.get_option_chain(req)
            
            if not chain:
                return None

            data = []
            for option_symbol, snapshot in chain.items():
                greeks = snapshot.greeks
                quote = snapshot.latest_quote
                
                # Delta 및 IV 파싱 (Greeks 정보 존재 여부 확인)
                delta = greeks.delta if greeks and greeks.delta is not None else 0.0
                gamma = greeks.gamma if greeks and greeks.gamma is not None else 0.0
                iv = snapshot.implied_volatility if snapshot.implied_volatility else 0.0
                
                bid = quote.bid_price if quote else 0.0
                ask = quote.ask_price if quote else 0.0
                mid_price = (bid + ask) / 2.0 if (bid and ask) else 0.0

                # Option Symbol 내 Strike 및 Call/Put 구분 파싱 (Standard OCC Format)
                # 예: SPY260826C00560000 -> Type: C, Strike: 560.0
                opt_type = 'C' if 'C' in option_symbol[9:] else 'P'
                try:
                    strike_str = option_symbol[-8:]
                    strike = float(strike_str) / 1000.0
                except Exception:
                    continue

                # Gamma Exposure (GEX) 대략적 추정
                # GEX = Gamma * OpenInterest (또나 Volume) * 100 * SpotPrice^2
                gex = gamma * 100 * (current_price ** 2) * (1 if opt_type == 'C' else -1)

                data.append({
                    'symbol': option_symbol,
                    'type': opt_type,
                    'strike': strike,
                    'delta': delta,
                    'gamma': gamma,
                    'iv': iv,
                    'mid_price': mid_price,
                    'gex': gex
                })

            df = pd.DataFrame(data)
            if df.empty:
                return None

            # 2. 델타 기반 매매 기준점 산출 (Target Delta: ±0.15 Delta ~ ±0.20 Delta)
            calls = df[df['type'] == 'C'].sort_values(by='strike')
            puts = df[df['type'] == 'P'].sort_values(by='strike')

            # 0.15 Delta Strike 찾기 (Put Credit Spread / Call Credit Spread 매도 추천용)
            call_15d = calls.iloc[(calls['delta'] - 0.15).abs().argsort()[:1]]
            put_15d = puts.iloc[(puts['delta'] + 0.15).abs().argsort()[:1]]

            # Max Gamma Strike (주가 끌어당김/저항 벽 역할을 하는 Gamma Wall)
            max_gex_strike = df.groupby('strike')['gex'].sum().abs().idxmax()
            avg_iv = df['iv'].mean() * 100

            return {
                'avg_iv': round(avg_iv, 2),
                'max_gex_strike': max_gex_strike,
                'call_15d_strike': float(call_15d['strike'].values[0]) if not call_15d.empty else current_price * 1.01,
                'call_15d_delta': float(call_15d['delta'].values[0]) if not call_15d.empty else 0.15,
                'put_15d_strike': float(put_15d['strike'].values[0]) if not put_15d.empty else current_price * 0.99,
                'put_15d_delta': float(put_15d['delta'].values[0]) if not put_15d.empty else -0.15,
                'df_chain': df
            }

        except Exception as e:
            # 장이 열리지 않았거나 API 호출 실패 시 예외 처리
            return None
