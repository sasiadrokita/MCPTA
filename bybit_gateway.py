import ccxt
import os
import time
from dotenv import load_dotenv

load_dotenv(override=True)

class BybitGateway:
    def __init__(self):
        self.api_key = os.getenv('BYBIT_API_KEY')
        self.api_secret = os.getenv('BYBIT_API_SECRET')
        
        # CCXT Initialization with Unified Account mode (Bybit V5)
        self.exchange = ccxt.bybit({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
                'recvWindow': 10000,
                'adjustForTimeDifference': True
            }
        })
        
        try:
            self.exchange.load_time_difference()
        except Exception as e:
            print(f"[BYBIT] Time sync warning: {e}")

    def get_balance(self):
        """Fetches USDT + USDC balance and calculates total operational capital."""
        try:
            balance = self.exchange.fetch_balance()
            usdt_free = balance.get('USDT', {}).get('free', 0)
            usdc_free = balance.get('USDC', {}).get('free', 0)
            usdt_total = balance.get('USDT', {}).get('total', 0)
            usdc_total = balance.get('USDC', {}).get('total', 0)
            
            # In Unified Account we calculate the sum of stable currencies as a foundation
            total_wallet = float(usdt_total) + float(usdc_total)
            total_available = float(usdt_free) + float(usdc_free)
            
            return {
                'wallet': total_wallet, 
                'available': total_available,
                'USDT': float(usdt_free),
                'USDC': float(usdc_free)
            }
        except Exception as e:
            print(f"[BYBIT] Balance fetch error: {e}")
            return {'wallet': 0, 'available': 0, 'USDT': 0, 'USDC': 0}

    def place_market_order(self, symbol, side, qty, tp_price=None, sl_price=None, reduce_only=False):
        """
        Places a Market order with optional TP/SL.
        Symbol will be forced to LINEAR format (e.g. BTC/USDT:USDT).
        """
        try:
            # Ensure symbol is in Linear format for Bybit V5
            base_sym = symbol.replace('/', '').replace(':USDT', '').replace('USDT', '')
            linear_symbol = f"{base_sym}/USDT:USDT"
            
            params = {'category': 'linear'}
            if reduce_only: params['reduceOnly'] = True
            if tp_price: params['takeProfit'] = str(tp_price)
            if sl_price: params['stopLoss'] = str(sl_price)
            
            # [v22.8.2] Native TP/SL supported by Bybit V5
            order = self.exchange.create_order(
                symbol=linear_symbol,
                type='market',
                side=side.lower(),
                amount=qty,
                params=params
            )
            print(f"[BYBIT] Order {side} {qty} {symbol} sent. ID: {order['id']}")
            return order
        except Exception as e:
            print(f"[BYBIT] Order placement error: {e}")
            return None



    def get_positions(self):
        """v24.0: Fetches active positions and maps them to Dashboard format."""
        try:
            positions = self.exchange.fetch_positions(params={'category': 'linear'})
            active = []
            for p in positions:
                contracts = float(p.get('contracts', 0) or 0)
                if contracts != 0:
                    # SL/TP are in raw Bybit data (p['info']), not in unified CCXT fields
                    raw = p.get('info', {})
                    sl_val = float(raw.get('stopLoss', 0) or 0)
                    tp_val = float(raw.get('takeProfit', 0) or 0)
                    ts_val = float(raw.get('trailingStop', 0) or 0)
                    
                    # createdTime is in ms, default to current time if missing
                    created_time_ms = float(raw.get('createdTime', p.get('timestamp') or (time.time() * 1000)))
                    
                    # symbol_raw = Bybit format (ETHUSDT) for engine
                    raw_sym = raw.get('symbol', p['symbol'].replace('/', '').split(':')[0])
                    active.append({
                        'symbol': p['symbol'],
                        'symbol_raw': raw_sym,
                        'qty': abs(contracts),
                        'contracts': abs(contracts),
                        'side': p.get('side', '').upper(),
                        'entry_price': float(p.get('entryPrice', 0) or 0),
                        'mark_price': float(p.get('markPrice', 0) or 0),
                        'unrealized_pnl': float(p.get('unrealizedPnl', 0) or 0),
                        'leverage': float(p.get('leverage', 1) or 1),
                        'liquidation_price': float(p.get('liquidationPrice', 0) or 0),
                        'sl': sl_val,
                        'tps': [tp_val] if tp_val > 0 else [],
                        'ts_dist': ts_val,
                        'entry_time': created_time_ms / 1000.0  # Convert to seconds
                    })
            return active
        except Exception as e:
            print(f"[BYBIT] Positions fetch error: {e}")
            return []

    def get_position(self, symbol):
        """Fetches active position data."""
        try:
            base_sym = symbol.replace('/', '').replace(':USDT', '').replace('USDT', '')
            linear_symbol = f"{base_sym}/USDT:USDT"
            positions = self.exchange.fetch_positions([linear_symbol], params={'category': 'linear'})
            if positions:
                pos = positions[0]
                return {
                    'active': float(pos['contracts']) > 0,
                    'side': pos['side'],
                    'qty': float(pos['contracts']),
                    'entry_price': float(pos['entryPrice']),
                    'leverage': float(pos['leverage']),
                    'unrealized_pnl': float(pos['unrealizedPnl'])
                }
            return None
        except Exception as e:
            print(f"[BYBIT] Position fetch error: {e}")
            return None

    def close_position(self, symbol):
        """Closes entire position at market price."""
        pos = self.get_position(symbol)
        if pos and pos['active']:
            exit_side = 'sell' if pos['side'] == 'long' else 'buy'
            return self.place_market_order(symbol, exit_side, pos['qty'])
        return None

    def set_leverage(self, symbol, leverage):
        """Sets leverage for a given symbol on Bybit."""
        try:
            base_sym = symbol.replace('/', '').replace(':USDT', '').replace('USDT', '')
            linear_symbol = f"{base_sym}/USDT:USDT"
            return self.exchange.set_leverage(int(leverage), linear_symbol, params={'category': 'linear'})
        except Exception as e:
            print(f"[BYBIT] Leverage setup error: {e}")
            return None

    def cancel_all_orders(self, symbol):
        """Cancels all active orders for a given symbol."""
        try:
            return self.exchange.cancel_all_orders(symbol)
        except Exception as e:
            print(f"[BYBIT] Order cancellation error: {e}")
            return None

    def get_closed_pnl(self, symbol, limit=1):
        """Fetches PnL from recently closed transactions."""
        try:
            # We normalize the symbol to raw format (e.g. BTCUSDT) for Bybit V5 private API
            raw_symbol = symbol.replace('/', '').replace(':USDT', '').replace('USDT', '') + 'USDT'
            
            # Direct Bybit V5 private API call
            res = self.exchange.private_get_v5_position_closed_pnl({
                'category': 'linear',
                'symbol': raw_symbol,
                'limit': limit
            })
            
            pnl_list = []
            if res and str(res.get('retCode')) == '0' and 'result' in res and 'list' in res['result']:
                for item in res['result']['list']:
                    pnl_list.append({
                        'symbol': item.get('symbol'),
                        'side': item.get('side'),
                        'realizedPnl': float(item.get('closedPnl', 0.0)),
                        'closedPnl': float(item.get('closedPnl', 0.0)),
                        'pnl': float(item.get('closedPnl', 0.0)),
                        'exit_price': float(item.get('avgExitPrice', 0.0)),
                        'avgExitPrice': float(item.get('avgExitPrice', 0.0)),
                        'avgEntryPrice': float(item.get('avgEntryPrice', 0.0)),
                        'timestamp': int(item.get('updatedTime', 0)),
                        'updatedTime': int(item.get('updatedTime', 0))
                    })
                return pnl_list
            
            # Fallback to fetch_closed_pnl (if CCXT supports it in the future)
            if hasattr(self.exchange, 'fetch_closed_pnl'):
                # normalize to ccxt format
                base_sym = symbol.replace('/', '').replace(':USDT', '').replace('USDT', '')
                linear_symbol = f"{base_sym}/USDT:USDT"
                ccxt_pnl = self.exchange.fetch_closed_pnl(linear_symbol, limit=limit)
                if ccxt_pnl:
                    pnl_list = []
                    for item in ccxt_pnl:
                        pnl_val = float(item.get('pnl', item.get('realizedPnl', 0.0)))
                        pnl_list.append({
                            'symbol': item.get('symbol'),
                            'side': item.get('side', ''),
                            'realizedPnl': pnl_val,
                            'closedPnl': pnl_val,
                            'pnl': pnl_val,
                            'exit_price': float(item.get('exitPrice', item.get('price', 0.0))),
                            'avgExitPrice': float(item.get('exitPrice', item.get('price', 0.0))),
                            'avgEntryPrice': float(item.get('entryPrice', 0.0)),
                            'timestamp': item.get('timestamp', 0),
                            'updatedTime': item.get('timestamp', 0)
                        })
                    return pnl_list
            
            # Fallback to fetch_my_trades
            base_sym = symbol.replace('/', '').replace(':USDT', '').replace('USDT', '')
            linear_symbol = f"{base_sym}/USDT:USDT"
            trades = self.exchange.fetch_my_trades(linear_symbol, limit=20)
            if trades:
                closed_trades = [t for t in reversed(trades) if t.get('info', {}).get('closedPnl')]
                if closed_trades:
                    pnl_list = []
                    for last_trade in closed_trades[:limit]:
                        raw = last_trade.get('info', {})
                        pnl_val = float(raw.get('closedPnl', 0.0))
                        pnl_list.append({
                            'symbol': last_trade['symbol'],
                            'side': last_trade.get('side', raw.get('side', '')),
                            'realizedPnl': pnl_val,
                            'closedPnl': pnl_val,
                            'pnl': pnl_val,
                            'exit_price': float(raw.get('execPrice', 0.0)),
                            'avgExitPrice': float(raw.get('execPrice', 0.0)),
                            'avgEntryPrice': float(raw.get('avgEntryPrice', 0.0)),
                            'timestamp': last_trade['timestamp'],
                            'updatedTime': last_trade['timestamp']
                        })
                    return pnl_list
            return []
        except Exception as e:
            print(f"[BYBIT] PnL fetch error: {e}")
            return []

    def get_orderflow_metrics(self, symbol):
        """
        V24.0: Retrieves Funding Rate and approximate CVD (last 500 trades) for AI Context.
        """
        try:
            # Fix CCXT format: e.g. BTCUSDT -> BTC/USDT:USDT
            raw_sym = symbol.replace('/', '').split(':')[0].replace('USDT', '')
            linear_sym = f"{raw_sym}/USDT:USDT"
            
            funding_rate = 0.0
            try:
                fr_data = self.exchange.fetch_funding_rate(linear_sym)
                funding_rate = float(fr_data.get('fundingRate', 0.0))
            except Exception as e:
                print(f"[BYBIT] Funding Rate fetch error for {symbol}: {e}")

            cvd = 0.0
            try:
                trades = self.exchange.fetch_trades(linear_sym, limit=500)
                if trades:
                    buy_vol = sum(t.get('amount', 0) for t in trades if t.get('side') == 'buy')
                    sell_vol = sum(t.get('amount', 0) for t in trades if t.get('side') == 'sell')
                    cvd = buy_vol - sell_vol
            except Exception as e:
                print(f"[BYBIT] CVD fetch error for {symbol}: {e}")

            return {
                "funding_rate": funding_rate,
                "cvd": cvd
            }
        except Exception as e:
            print(f"[BYBIT] Orderflow metrics error: {e}")
            return {"funding_rate": 0.0, "cvd": 0.0}

    def set_trailing_stop(self, symbol, trailing_dist, active_price=None):
        """
        V24.0: Sets a Trailing Stop for an open position using Bybit V5 API.
        """
        try:
            raw_sym = symbol.replace('/', '').split(':')[0]
            params = {
                'category': 'linear',
                'symbol': raw_sym,
                'trailingStop': str(trailing_dist)
            }
            if active_price:
                params['activePrice'] = str(active_price)
                
            res = self.exchange.privatePostV5PositionTradingStop(params)
            return res
        except Exception as e:
            print(f"[BYBIT] Trailing Stop error for {symbol}: {e}")
            return None
