#!/usr/bin/env python3
"""
Bybit ETH/BTC Perpetual Futures Trading Bot - FIXED VERSION
Strategy: Volume Spike Detection + Swing High/Low
Real trading enabled with error handling
"""
import ccxt
import asyncio
import json
import os
import sys
from telegram import Bot
from datetime import datetime, timedelta, timezone

# ============ CONFIGURATION ============
API_KEY = "mUTJK74gQTJ6Tp67z6"
SECRET_KEY = "k3ulpN87Kjm7iiGqvZAYKF5V4TQDDGdLot3K"
TELEGRAM_TOKEN = '8993995766:AAGxfrHRnL-9VxBUjOJXA__9BaAVMgD4ndU'
CHAT_ID = '851788804'

# Trading parameters
LEVERAGE = 5
RISK_PERCENT = 1
TP_PERCENT = 3
SL_PERCENT = 2
VOLUME_MULTIPLIER = 2
VOLUME_PERIOD = 50

# State file
STATE_FILE = '/tmp/bot_state.json'

# ============ INITIALIZATION ============
bot = Bot(token=TELEGRAM_TOKEN)

exchange = ccxt.bybit({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',
        'fetchBalance': 'v5',
    }
})

# Global state
balance = 95.99
daily_pnl = 0
positions = {}
last_signal_candle = {}

# ============ STATE MANAGEMENT ============
def load_state():
    """Load bot state from JSON file"""
    global balance, daily_pnl, positions, last_signal_candle
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                data = json.load(f)
                balance = data.get('balance', 95.99)
                daily_pnl = data.get('daily_pnl', 0)
                positions = data.get('positions', {})
                last_signal_candle = data.get('last_signal_candle', {})
    except Exception as e:
        print(f"Error loading state: {e}")

def save_state():
    """Save bot state to JSON file"""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump({
                'balance': balance,
                'daily_pnl': daily_pnl,
                'positions': positions,
                'last_signal_candle': last_signal_candle
            }, f, indent=2)
    except Exception as e:
        print(f"Error saving state: {e}")

# ============ UTILITIES ============
def get_time_utc3():
    """Get current time in UTC+3 (Turkey)"""
    tz = timezone(timedelta(hours=3))
    return datetime.now(tz).strftime('%H:%M')

async def send_telegram(msg):
    """Send message to Telegram"""
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg)
        print(f"✅ Telegram sent")
    except Exception as e:
        print(f"❌ Telegram error: {e}")

# ============ TRADING LOGIC ============
async def place_market_buy(symbol, size):
    """Place market BUY order on Bybit"""
    try:
        print(f"📤 Placing BUY order: {symbol} {size}")
        print(f"DEBUG: Symbol={symbol}, Size={size}, Type=market")
        order = exchange.create_market_buy_order(symbol, size)
        print(f"DEBUG: Order response = {order}")
        print(f"✅ BUY order placed: {order.get('id', 'unknown')}")
        return order
    except Exception as e:
        print(f"❌ Buy order error: {e}")
        print(f"DEBUG: Full error = {type(e).__name__}: {str(e)}")
        return None

async def place_market_sell(symbol, size):
    """Place market SELL order on Bybit"""
    try:
        print(f"📤 Placing SELL order: {symbol} {size}")
        print(f"DEBUG: Symbol={symbol}, Size={size}, Type=market")
        order = exchange.create_market_sell_order(symbol, size)
        print(f"DEBUG: Order response = {order}")
        print(f"✅ SELL order placed: {order.get('id', 'unknown')}")
        return order
    except Exception as e:
        print(f"❌ Sell order error: {e}")
        print(f"DEBUG: Full error = {type(e).__name__}: {str(e)}")
        return None

async def check_pair(pair, symbol):
    """Check trading signals for a pair"""
    global balance, daily_pnl, positions, last_signal_candle
    
    try:
        # Fetch OHLCV data
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=100)
        if not ohlcv or len(ohlcv) < VOLUME_PERIOD:
            print(f"⚠️ Not enough data for {pair}")
            return
        
        prices = [x[4] for x in ohlcv]  # Close prices
        volumes = [x[5] for x in ohlcv]  # Volumes
        times = [x[0] for x in ohlcv]    # Timestamps
        
        current_time = times[-1]
        current_price = prices[-1]
        
        print(f"📊 {pair}: Price=${current_price:.2f}, Volume={volumes[-1]:.0f}")
        
        # Check if we have an open position
        has_position = pair in positions
        print(f"📍 {pair}: Has position = {has_position}")
        
        # Calculate volume spike
        vol_avg = sum(volumes[-VOLUME_PERIOD:]) / VOLUME_PERIOD
        vol_spike = volumes[-1] > vol_avg * VOLUME_MULTIPLIER
        
        # Check last 3 candles for volume spike
        recent_vol_spike = any(volumes[-i] > vol_avg * VOLUME_MULTIPLIER for i in range(1, 4))
        
        print(f"📈 {pair}: Vol={volumes[-1]:.0f}, Avg={vol_avg:.0f}, Spike={vol_spike}")
        print(f"📊 {pair}: Recent spike={recent_vol_spike}")
        
        # ========== ONLY HANDLE OPEN POSITIONS (SELL LOGIC) ==========
        if has_position:
            pos = positions[pair]
            entry = pos['entry']
            tp = pos['tp']
            sl = pos['sl']
            size = pos['size']
            buy_time = pos['buy_time']
            
            # Prevent same-candle BUY/SELL
            if current_time == buy_time:
                print(f"⏭️ {pair}: Skipping SELL (same candle)")
                return
            
            # TP HIT
            if current_price >= tp:
                print(f"🟢 TP HIT for {pair}!")
                sell_order = await place_market_sell(symbol, size)
                
                if sell_order:
                    pnl = (current_price - entry) * size * LEVERAGE
                    old_balance = balance
                    balance += pnl
                    daily_pnl += pnl
                    
                    del positions[pair]
                    if pair in last_signal_candle:
                        del last_signal_candle[pair]
                    save_state()
                    
                    msg = f"""🔴 SELL {pair}

Giriş Fiyatı
${entry:.2f}

Çıkış Fiyatı
${current_price:.2f}

Hedef (TP)
${tp:.2f}

Zarar Durdurma (SL)
${sl:.2f}

Pozisyon Boyutu
{size:.6f} {pair}

Sonuç
✅ HEDEF TUTTU

Kar/Zarar
${pnl:.2f}

Bakiye Değişimi
${old_balance:.2f} → ${balance:.2f}

Günlük Kar
${daily_pnl:.2f}

Saat
{get_time_utc3()}"""
                    
                    await send_telegram(msg)
            
            # SL HIT
            elif current_price <= sl:
                print(f"🔴 SL HIT for {pair}!")
                sell_order = await place_market_sell(symbol, size)
                
                if sell_order:
                    pnl = (current_price - entry) * size * LEVERAGE
                    old_balance = balance
                    balance += pnl
                    daily_pnl += pnl
                    
                    del positions[pair]
                    if pair in last_signal_candle:
                        del last_signal_candle[pair]
                    save_state()
                    
                    msg = f"""🔴 SELL {pair}

Giriş Fiyatı
${entry:.2f}

Çıkış Fiyatı
${current_price:.2f}

Hedef (TP)
${tp:.2f}

Zarar Durdurma (SL)
${sl:.2f}

Pozisyon Boyutu
{size:.6f} {pair}

Sonuç
❌ ZARAR DURDURMA

Kar/Zarar
${pnl:.2f}

Bakiye Değişimi
${old_balance:.2f} → ${balance:.2f}

Günlük Kar
${daily_pnl:.2f}

Saat
{get_time_utc3()}"""
                    
                    await send_telegram(msg)
            return
        
        # ========== NO POSITION - CHECK FOR BUY SIGNAL ==========
        # Prevent duplicate BUY signals from same candle
        if pair in last_signal_candle and last_signal_candle[pair] == current_time:
            print(f"⏭️ {pair}: Skipping BUY (same candle)")
            return
        
        # BUY SIGNAL: Volume spike detected
        if vol_spike or recent_vol_spike:
            print(f"🟢 BUY SIGNAL for {pair}!")
            
            entry_price = current_price
            tp_price = entry_price * (1 + TP_PERCENT / 100)
            sl_price = entry_price * (1 - SL_PERCENT / 100)
            
            # Calculate position size based on risk
            risk_amount = balance * (RISK_PERCENT / 100)
            price_diff = entry_price - sl_price
            position_size = risk_amount / (price_diff * LEVERAGE) if price_diff > 0 else 0.01
            
            print(f"💰 Position size: {position_size:.6f}")
            
            # Place buy order
            buy_order = await place_market_buy(symbol, position_size)
            
            if buy_order:
                positions[pair] = {
                    'entry': entry_price,
                    'tp': tp_price,
                    'sl': sl_price,
                    'size': position_size,
                    'leverage': LEVERAGE,
                    'buy_time': current_time,
                    'order_id': buy_order.get('id', 'unknown')
                }
                last_signal_candle[pair] = current_time
                save_state()
                
                # Send BUY signal to Telegram
                msg = f"""🟢 BUY {pair}

Giriş Fiyatı
${entry_price:.2f}

Hedef (TP)
${tp_price:.2f}

Zarar Durdurma (SL)
${sl_price:.2f}

Pozisyon Boyutu
{position_size:.6f} {pair}

Kaldıraç
{LEVERAGE}x

Bakiye
${balance:.2f}

Saat
{get_time_utc3()}"""
                
                await send_telegram(msg)
    
    except Exception as e:
        print(f"❌ Error checking {pair}: {e}")

# ============ MAIN LOOP ============
async def main():
    """Main bot loop"""
    load_state()
    print(f"🤖 Bot started. Initial balance: ${balance:.2f}")
    
    while True:
        try:
            print(f"\n⏰ Checking at {get_time_utc3()}...")
            
            # Check both pairs in parallel
            await asyncio.gather(
                check_pair('ETH', 'ETH/USDT:USDT'),
                check_pair('BTC', 'BTC/USDT:USDT')
            )
            
            print(f"✅ Check completed. Sleeping 300s...")
            # Wait 5 minutes before next check
            await asyncio.sleep(300)
        
        except Exception as e:
            print(f"❌ Main loop error: {e}")
            await asyncio.sleep(300)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped")
        sys.exit(0)
