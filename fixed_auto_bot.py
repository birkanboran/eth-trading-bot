#!/usr/bin/env python3
import ccxt, json, os
from telegram import Bot
from datetime import datetime, timedelta, timezone
import time

bot = Bot(token='8993995766:AAGxfrHRnL-9VxBUjOJXA__9BaAVMgD4ndU')
chat_id = '851788804'

exchange = ccxt.bybit({
    'apiKey': 'CPSkGJlpunApHRWmIu',
    'secret': 'wrfqLrR74nZRsT02p6F4fAHwlqtvJvWFnDDA',
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

state_file = '/home/ubuntu/bot_state.json'

def load_state():
    try:
        if os.path.exists(state_file):
            with open(state_file) as f:
                return json.load(f)
    except:
        pass
    return {'balance': 95.99, 'daily_pnl': 0, 'positions': {}}

def save_state(state):
    with open(state_file, 'w') as f:
        json.dump(state, f)

def get_time():
    tz = timezone(timedelta(hours=3))
    return datetime.now(tz).strftime('%H:%M')

def send_telegram(msg):
    try:
        bot.send_message(chat_id=chat_id, text=msg)
    except:
        pass

def check_pair(pair, symbol):
    state = load_state()
    balance = state['balance']
    daily_pnl = state['daily_pnl']
    positions = state['positions']
    
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=100)
        if not ohlcv or len(ohlcv) < 50:
            return
        
        prices = [x[4] for x in ohlcv]
        volumes = [x[5] for x in ohlcv]
        times = [x[0] for x in ohlcv]
        
        current_time = times[-1]
        vol_avg = sum(volumes[-50:]) / 50
        vol_spike = volumes[-1] > vol_avg * 2
        current_price = prices[-1]
        
        # BUY
        if vol_spike and pair not in positions:
            try:
                entry = current_price
                tp = entry * 1.03
                sl = entry * 0.98
                size = 0.1
                leverage = 5
                
                exchange.set_leverage(leverage, symbol)
                order = exchange.create_market_buy_order(symbol, size)
                
                positions[pair] = {
                    'entry': entry, 'tp': tp, 'sl': sl, 'size': size,
                    'leverage': leverage, 'buy_time': current_time, 'order_id': order['id']
                }
                save_state({'balance': balance, 'daily_pnl': daily_pnl, 'positions': positions})
                
                msg = f"""🟢 BUY {pair}

Giriş: ${entry:.2f}
Hedef: ${tp:.2f}
Zaraf: ${sl:.2f}
Boyut: {size:.4f}
Kaldıraç: {leverage}x
Bakiye: ${balance:.2f}"""
                
                send_telegram(msg)
                print(f"✅ BUY {pair}")
                
            except Exception as e:
                print(f"❌ BUY: {e}")
                send_telegram(f"❌ BUY Error: {str(e)[:80]}")
        
        # SELL
        if pair in positions:
            pos = positions[pair]
            entry = pos['entry']
            tp = pos['tp']
            sl = pos['sl']
            size = pos['size']
            leverage = pos['leverage']
            buy_time = pos['buy_time']
            
            if current_time == buy_time:
                return
            
            if current_price >= tp or current_price <= sl:
                try:
                    order = exchange.create_market_sell_order(symbol, size)
                    
                    pnl = (current_price - entry) * size * leverage
                    old_balance = balance
                    balance += pnl
                    daily_pnl += pnl
                    del positions[pair]
                    save_state({'balance': balance, 'daily_pnl': daily_pnl, 'positions': positions})
                    
                    reason = "✅ HEDEF" if current_price >= tp else "❌ ZARAF"
                    
                    msg = f"""🔴 SELL {pair}

Giriş: ${entry:.2f}
Çıkış: ${current_price:.2f}
{reason}
Kar: ${pnl:.2f}
Bakiye: ${old_balance:.2f} → ${balance:.2f}"""
                    
                    send_telegram(msg)
                    print(f"✅ SELL {pair}")
                    
                except Exception as e:
                    print(f"❌ SELL: {e}")
                    send_telegram(f"❌ SELL Error: {str(e)[:80]}")
    
    except Exception as e:
        print(f"Error {pair}: {e}")

def main():
    while True:
        try:
            check_pair('ETH', 'ETH/USDT:USDT')
            time.sleep(2)
            check_pair('BTC', 'BTC/USDT:USDT')
            time.sleep(298)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(300)

if __name__ == '__main__':
    main()
