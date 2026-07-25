#!/usr/bin/env python3
"""
Binance ETH/BTC Perpetual Futures Trading Bot
Strategy: Volume Spike Detection
Using python-binance library for reliable order placement
"""
import requests
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from binance.client import Client
from binance.exceptions import BinanceAPIException

# ============ CONFIGURATION ============
API_KEY = "H7iuFE4Qh5C0exsnSbwZ20JMzjqGEKkV0pXyVhWYGODB66AhZUs67FIQc2GjIu8P"
SECRET_KEY = "hXmbpkUHgSFBld6P2KGyltkkwWNJcM5re1fCM4TAlv1DaOYGH4ovKJ35OYUOVtPr"
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

# Initialize Binance client
client = Client(API_KEY, SECRET_KEY)

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
                print(f"✅ State loaded: balance=${balance:.2f}, pnl=${daily_pnl:.2f}")
    except Exception as e:
        print(f"❌ Error loading state: {e}")

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
        print(f"❌ Error saving state: {e}")

# ============ UTILITIES ============
def get_time_utc3():
    """Get current time in UTC+3"""
    tz = timezone(timedelta(hours=3))
    return datetime.now(tz).strftime('%H:%M')

def send_telegram(msg):
    """Send message to Telegram (blocking)"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {'chat_id': CHAT_ID, 'text': msg}
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            print(f"✅ Telegram sent")
        else:
            print(f"⚠️ Telegram error: {response.status_code}")
    except Exception as e:
        print(f"❌ Telegram error: {e}")

# ============ BINANCE API ============
def get_klines(symbol, interval='1h', limit=100):
    """Fetch OHLCV data from Binance"""
    try:
        klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        return klines
    except BinanceAPIException as e:
        print(f"❌ Error fetching klines: {e}")
        return []
    except Exception as e:
        print(f"❌ Error fetching klines: {e}")
        return []

def place_order(symbol, side, quantity):
    """Place market order on Binance Futures"""
    try:
        print(f"📤 Placing {side} order: {symbol} {quantity:.6f}")
        
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type='MARKET',
            quantity=quantity,
            leverage=LEVERAGE
        )
        
        order_id = order.get('orderId')
        print(f"✅ {side} order placed: {order_id}")
        return order_id
    
    except BinanceAPIException as e:
        print(f"❌ Order failed: {e}")
        return None
    except Exception as e:
        print(f"❌ Order error: {e}")
        return None

# ============ TRADING LOGIC ============
def check_pair(pair, symbol):
    """Check trading signals for a pair"""
    global balance, daily_pnl, positions, last_signal_candle
    
    try:
        # Fetch OHLCV data
        print(f"📊 Fetching {pair} data...")
        klines = get_klines(symbol, interval='1h', limit=100)
        
        if not klines or len(klines) < VOLUME_PERIOD:
            print(f"⚠️ Not enough data for {pair}")
            return
        
        # Parse klines: [time, open, high, low, close, volume, ...]
        prices = [float(x[4]) for x in klines]
        volumes = [float(x[7]) for x in klines]  # Quote asset volume
        times = [int(x[0]) for x in klines]
        
        current_time = times[-1]
        current_price = prices[-1]
        
        print(f"📈 {pair}: Price=${current_price:.2f}, Vol={volumes[-1]:.0f}")
        
        # Check if we have an open position
        has_position = pair in positions
        
        # Calculate volume spike
        vol_avg = sum(volumes[-VOLUME_PERIOD:]) / VOLUME_PERIOD
        vol_spike = volumes[-1] > vol_avg * VOLUME_MULTIPLIER
        recent_vol_spike = any(volumes[-i] > vol_avg * VOLUME_MULTIPLIER for i in range(1, 4))
        
        print(f"📊 {pair}: Vol spike={vol_spike or recent_vol_spike}")
        
        # ========== HANDLE OPEN POSITIONS (SELL LOGIC) ==========
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
                sell_order = place_order(symbol, 'SELL', size)
                
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
                    
                    send_telegram(msg)
            
            # SL HIT
            elif current_price <= sl:
                print(f"🔴 SL HIT for {pair}!")
                sell_order = place_order(symbol, 'SELL', size)
                
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
                    
                    send_telegram(msg)
            return
        
        # ========== NO POSITION - CHECK FOR BUY SIGNAL ==========
        if pair in last_signal_candle and last_signal_candle[pair] == current_time:
            print(f"⏭️ {pair}: Skipping BUY (same candle)")
            return
        
        # BUY SIGNAL
        if vol_spike or recent_vol_spike:
            print(f"🟢 BUY SIGNAL for {pair}!")
            
            entry_price = current_price
            tp_price = entry_price * (1 + TP_PERCENT / 100)
            sl_price = entry_price * (1 - SL_PERCENT / 100)
            
            # Calculate position size
            risk_amount = balance * (RISK_PERCENT / 100)
            price_diff = entry_price - sl_price
            position_size = risk_amount / (price_diff * LEVERAGE) if price_diff > 0 else 0.01
            
            print(f"💰 Position size: {position_size:.6f}")
            
            # Place buy order
            buy_order = place_order(symbol, 'BUY', position_size)
            
            if buy_order:
                positions[pair] = {
                    'entry': entry_price,
                    'tp': tp_price,
                    'sl': sl_price,
                    'size': position_size,
                    'leverage': LEVERAGE,
                    'buy_time': current_time,
                    'order_id': buy_order
                }
                last_signal_candle[pair] = current_time
                save_state()
                
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
                
                send_telegram(msg)
    
    except Exception as e:
        print(f"❌ Error checking {pair}: {type(e).__name__}: {e}")

# ============ MAIN LOOP ============
def main():
    """Main bot loop"""
    load_state()
    print(f"🤖 Bot started. Balance: ${balance:.2f}")
    print(f"⏰ Running for 5 minutes...")
    
    start_time = time.time()
    timeout = 300  # 5 minutes
    
    while time.time() - start_time < timeout:
        try:
            print(f"\n⏰ Check at {get_time_utc3()}...")
            
            # Check both pairs
            check_pair('ETH', 'ETHUSDT')
            time.sleep(2)
            check_pair('BTC', 'BTCUSDT')
            
            print(f"✅ Check completed")
            
            # Wait before next check
            elapsed = time.time() - start_time
            remaining = timeout - elapsed
            if remaining > 0:
                print(f"⏳ Sleeping... ({remaining:.0f}s remaining)")
                time.sleep(min(60, remaining))
        
        except Exception as e:
            print(f"❌ Main loop error: {type(e).__name__}: {e}")
            time.sleep(10)
    
    print(f"\n✅ Bot completed. Final balance: ${balance:.2f}, Daily PnL: ${daily_pnl:.2f}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped")
        sys.exit(0)
