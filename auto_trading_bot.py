#!/usr/bin/env python3
import ccxt, asyncio, json, os, time
from telegram import Bot
from datetime import datetime, timedelta, timezone

bot = Bot(token='8993995766:AAGxfrHRnL-9VxBUjOJXA__9BaAVMgD4ndU')
chat_id = '851788804'

exchange = ccxt.bybit({
    'apiKey': 'CPSkGJlpunApHRWmIu',
    'secret': 'wrfqLrR74nZRsT02p6F4fAHwlqtvJvWFnDDA',
    'enableRateLimit': True,
    'options': {'defaultType': 'swap', 'fetchPositions': True}
})

state_file = '/home/ubuntu/bot_state.json'
balance = 95.99
daily_pnl = 0
positions = {}

def load_state():
    global balance, daily_pnl, positions
    try:
        if os.path.exists(state_file):
            with open(state_file) as f:
                data = json.load(f)
                balance = data.get('balance', 95.99)
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

def place_buy_order(symbol, size, leverage):
    try:
        exchange.set_leverage(leverage, symbol)
        order = exchange.create_market_buy_order(symbol, size)
        return order
    except Exception as e:
        print(f"Buy error: {e}")
        return None

def place_sell_order(symbol, size):
    try:
        order = exchange.create_market_sell_order(symbol, size)
        return order
    except Exception as e:
        print(f"Sell error: {e}")
        return None

async def check_pair(pair, symbol):
    global balance, daily_pnl, positions
    
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
        
        # BUY
        if vol_spike and pair not in positions:
            entry = prices[-1]
            tp = entry * 1.03
            sl = entry * 0.98
            size = 0.1
            leverage = 5
            
            order = place_buy_order(symbol, size, leverage)
            
            if order:
                positions[pair] = {
                    'entry': entry,
                    'tp': tp,
                    'sl': sl,
                    'size': size,
                    'leverage': leverage,
                    'buy_time': current_time,
                    'order_id': order.get('id')
                }
                save_state()
                
                msg = f"""🟢 BUY {pair}

Giriş Fiyatı
${entry:.2f}

Hedef (TP)
${tp:.2f}

Zarar Durdurma (SL)
${sl:.2f}

Pozisyon Boyutu
{size:.4f} {pair}

Kaldıraç
{leverage}x

Bakiye
${balance:.2f}

Saat
{get_time()}"""
                
                await send(msg)
        
        # SELL
        if pair in positions:
            pos = positions[pair]
            current = prices[-1]
            entry = pos['entry']
            tp = pos['tp']
            sl = pos['sl']
            size = pos['size']
            leverage = pos['leverage']
            buy_time = pos['buy_time']
            
            if current_time == buy_time:
                return
            
            if current >= tp or current <= sl:
                order = place_sell_order(symbol, size)
                
                if order:
                    pnl = (current - entry) * size * leverage
                    old_balance = balance
                    balance += pnl
                    daily_pnl += pnl
                    del positions[pair]
                    save_state()
                    
                    reason = "✅ HEDEF TUTTU" if current >= tp else "❌ ZARAR DURDURMA"
                    
                    msg = f"""🔴 SELL {pair}

Giriş Fiyatı
${entry:.2f}

Çıkış Fiyatı
${current:.2f}

Hedef (TP)
${tp:.2f}

Zaraf Durdurma (SL)
${sl:.2f}

Pozisyon Boyutu
{size:.4f} {pair}

Sonuç
{reason}

Kar/Zarar
${pnl:.2f}

Bakiye Değişimi
${old_balance:.2f} → ${balance:.2f}

Günlük Kar
${daily_pnl:.2f}

Saat
{get_time()}"""
                    
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
        except Exception as e:
            print(f"Main error: {e}")
            await asyncio.sleep(300)

if __name__ == '__main__':
    asyncio.run(main())
