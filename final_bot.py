#!/usr/bin/env python3
import ccxt, asyncio, json, os
from telegram import Bot
from datetime import datetime, timedelta, timezone

bot = Bot(token='8993995766:AAGxfrHRnL-9VxBUjOJXA__9BaAVMgD4ndU')
chat_id = '851788804'
exchange = ccxt.bybit({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

state_file = '/home/ubuntu/bot_state.json'
balance = 100
daily_pnl = 0
positions = {}

def load_state():
    global balance, daily_pnl, positions
    try:
        if os.path.exists(state_file):
            with open(state_file) as f:
                data = json.load(f)
                balance = data.get('balance', 100)
                daily_pnl = data.get('daily_pnl', 0)
                positions = data.get('positions', {})
    except:
        pass

def save_state():
    with open(state_file, 'w') as f:
        json.dump({'balance': balance, 'daily_pnl': daily_pnl, 'positions': positions}, f)

def get_time():
    tz = timezone(timedelta(hours=3))
    return datetime.now(tz).strftime('%H:%M')

async def send(msg):
    try:
        await bot.send_message(chat_id=chat_id, text=msg)
    except:
        pass

async def check_pair(pair, symbol):
    global balance, daily_pnl, positions
    
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=100)
        if not ohlcv or len(ohlcv) < 50:
            return
        
        prices = [x[4] for x in ohlcv]
        volumes = [x[5] for x in ohlcv]
        
        vol_avg = sum(volumes[-50:]) / 50
        vol_spike = volumes[-1] > vol_avg * 2
        
        # BUY SIGNAL
        if vol_spike and pair not in positions:
            entry = prices[-1]
            tp = entry * 1.03
            sl = entry * 0.98
            size = 0.1
            leverage = 5
            
            positions[pair] = {
                'entry': entry,
                'tp': tp,
                'sl': sl,
                'size': size,
                'leverage': leverage
            }
            save_state()
            
            msg = f"""🟢 BUY {pair}

Giriş: ${entry:.2f}
Hedef: ${tp:.2f}
Zarar: ${sl:.2f}
Miktar: {size:.4f} {pair}
Kaldıraç: {leverage}x
Bakiye: ${balance:.2f}
Saat: {get_time()}"""
            
            await send(msg)
        
        # SELL SIGNAL - ONLY at TP or SL
        if pair in positions:
            pos = positions[pair]
            current = prices[-1]
            entry = pos['entry']
            tp = pos['tp']
            sl = pos['sl']
            size = pos['size']
            leverage = pos['leverage']
            
            # ONLY close if TP or SL is hit
            if current >= tp:
                # TP HIT
                pnl = (current - entry) * size * leverage
                old_balance = balance
                balance += pnl
                daily_pnl += pnl
                del positions[pair]
                save_state()
                
                msg = f"""🔴 SELL {pair}

Giriş: ${entry:.2f}
Çıkış: ${current:.2f}
Hedef: ${tp:.2f}
Zarar: ${sl:.2f}
Miktar: {size:.4f} {pair}

✅ HEDEF TUTTU
Kar: ${pnl:.2f}

Bakiye: ${old_balance:.2f} → ${balance:.2f}
Günlük Kar: ${daily_pnl:.2f}
Saat: {get_time()}"""
                
                await send(msg)
            
            elif current <= sl:
                # SL HIT
                pnl = (current - entry) * size * leverage
                old_balance = balance
                balance += pnl
                daily_pnl += pnl
                del positions[pair]
                save_state()
                
                msg = f"""🔴 SELL {pair}

Giriş: ${entry:.2f}
Çıkış: ${current:.2f}
Hedef: ${tp:.2f}
Zarar: ${sl:.2f}
Miktar: {size:.4f} {pair}

❌ ZARAR DURDURMA
Zarar: ${pnl:.2f}

Bakiye: ${old_balance:.2f} → ${balance:.2f}
Günlük Kar: ${daily_pnl:.2f}
Saat: {get_time()}"""
                
                await send(msg)
    
    except Exception as e:
        print(f"Error {pair}: {e}")

async def main():
    load_state()
    while True:
        try:
            await asyncio.gather(
                check_pair('ETH', 'ETH/USDT:USDT'),
                check_pair('BTC', 'BTC/USDT:USDT')
            )
            await asyncio.sleep(300)
        except:
            await asyncio.sleep(300)

asyncio.run(main())
