# --- [실시간 시장 데이터 및 백업 라우터] ---

@app.get("/api/market")
def get_market_data():
    try:
        # 1. Upstash Redis 금고에서 토큰 꺼내기
        kv_headers = {"Authorization": f"Bearer {KV_TOKEN}"}
        token_res = requests.get(f"{KV_URL}/get/schwab_token", headers=kv_headers)
        
        if token_res.status_code != 200 or not token_res.json().get('result'):
            raise Exception("토큰 없음")
            
        token_data = json.loads(token_res.json()['result'])
        access_token = token_data['access_token']
        
        # 2. 찰스스왑 API로 실시간 데이터 가져오기
        schwab_headers = {"Authorization": f"Bearer {access_token}"}
        quote_res = requests.get("https://api.schwabapi.com/marketdata/v1/quotes?symbols=$SPX", headers=schwab_headers)
        
        if quote_res.status_code == 200:
            current_price = quote_res.json()['$SPX']['quote']['lastPrice']
            return {
                "status": "success", 
                "source": "Charles Schwab", 
                "spx_price": current_price
            }
        else:
            raise Exception("찰스스왑 응답 에러")
            
    except Exception as e:
        # --- [2순위 백업: 야후 파이낸스 가격 & 0DTE 옵션 체인] ---
        try:
            spx = yf.Ticker("^SPX")
            
            # 1. SPX 현재 가격 가져오기
            hist = spx.history(period="5d")
            current_price = hist['Close'].iloc[-1]
            
            # 2. 가장 가까운 만기일(0DTE)의 옵션 체인 가져오기
            expirations = spx.options
            if expirations:
                nearest_expiry = expirations[0]  # 0DTE
                opt_chain = spx.option_chain(nearest_expiry)
                
                # 콜/풋 총 거래량 등 기초 지표 계산 가능
                total_call_volume = int(opt_chain.calls['volume'].fillna(0).sum())
                total_put_volume = int(opt_chain.puts['volume'].fillna(0).sum())
            else:
                total_call_volume = 0
                total_put_volume = 0

            return {
                "status": "success", 
                "source": "Yahoo Finance (Backup)", 
                "spx_price": round(current_price, 2),
                "options_data": {
                    "expiry": nearest_expiry if expirations else "N/A",
                    "total_call_volume": total_call_volume,
                    "total_put_volume": total_put_volume
                }
            }
        except Exception as backup_error:
            return {"status": "fail", "error": f"백업 서버도 실패했습니다: {str(backup_error)}"}
