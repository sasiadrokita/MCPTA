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

    def set_trailing_stop(self, symbol, side, callback_rate=1.0):
        """
        Sets Trailing Stop for an active position (Bybit V5).
        callback_rate: percentage value (e.g. 1.0 = 1%)
        """
        try:
            # Recalculate symbol and fetch ticker for price distance
            ticker = self.exchange.fetch_ticker(symbol)
            price = ticker['last']
            # Bybit V5 requires price distance for Trailing Stop
            ts_dist = str(round(price * (callback_rate / 100), 2))
            
            # Form request for Bybit V5 Position API
            # side: 'Buy' for Long position, 'Sell' for Short position
            params = {
                'category': 'linear',
                'symbol': symbol.replace('/', '').split(':')[0], # format BTCUSDT
                'trailingStop': ts_dist,
                'positionIdx': 0, # 0 for unhedged
            }
            
            response = self.exchange.private_post_v5_position_trading_stop(params)
            print(f"[BYBIT] Trailing Stop {callback_rate}% ({ts_dist}) set for {symbol}")
            return response
        except Exception as e:
            print(f"[BYBIT] Trailing Stop setup error: {e}")
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
                        'tps': [tp_val] if tp_val > 0 else []
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
            # In Bybit V5 Unified it's best to check fetchClosedPnl or fetchMyTrades
            # CCXT unifies this as fetchClosedPnl in newer versions
            if hasattr(self.exchange, 'fetch_closed_pnl'):
                return self.exchange.fetch_closed_pnl(symbol, limit=limit)
            
            # Fallback to fetch_my_trades
            trades = self.exchange.fetch_my_trades(symbol, limit=20)
            if trades:
                # Search for the last transaction with realizedPnl
                closed_trades = [t for t in reversed(trades) if t.get('info', {}).get('closedPnl')]
                if closed_trades:
                    last_trade = closed_trades[0]
                    return [{
                        'symbol': last_trade['symbol'],
                        'realizedPnl': float(last_trade['info'].get('closedPnl', 0)),
                        'timestamp': last_trade['timestamp']
                    }]
            return []
        except Exception as e:
            print(f"[BYBIT] PnL fetch error: {e}")
            return []
