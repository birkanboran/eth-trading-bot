#!/usr/bin/env python3
"""
Binance ETH/BTC Perpetual Futures Trading Bot - FIXED VERSION
Strategy: Volume Spike Detection
- Proper leverage handling
- Real balance reading
- TP/SL as real orders
- Proper quantity rounding
- 24/7 operation
"""
import requests
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from binance.client import Client
from binance.exceptions import BinanceAPIException
import logging

# ============ CONFIGURATION ============
# Use environment variables for security
API_KEY = os.getenv('BINANCE_API_KEY', '')
SECRET_KEY = os.getenv('BINANCE_SECRET_KEY', '')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
TESTNET = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'

# Trading parameters
LEVERAGE = 5
RISK_PERCENT = 1
TP_PERCENT = 3
SL_PERCENT = 2
VOLUME_MULTIPLIER = 2
VOLUME_PERIOD = 50

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Binance client
try:
    client = Client(API_KEY, SECRET_KEY, testnet=TESTNET)
    logger.info(f"✅ Binance client initialized (Testnet: {TESTNET})")
except Exception as e:
    logger.error(f"❌ Failed to initialize Binance client: {e}")
    sys.exit(1)

# Global state
positions = {}
last_signal_candle = {}

# ============ UTILITIES ============
def get_time_utc3():
    """Get current time in UTC+3"""
    tz = timezone(timedelta(hours=3))
    return datetime.now(tz).strftime('%H:%M')

def send_telegram(msg):
    """Send message to Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("⚠️ Telegram credentials not set")
        return
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {'chat_id': CHAT_ID, 'text': msg}
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            logger.info("✅ Telegram sent")
        else:
            logger.warning(f"⚠️ Telegram error: {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Telegram error: {e}")

def get_account_balance():
    """Get real account balance from Binance"""
    try:
        account = client.futures_account()
        balance = float(account.get('totalWalletBalance', 0))
        logger.info(f"💰 Account balance: {balance:.2f} USDT")
        return balance
    except BinanceAPIException as e:
        logger.error(f"❌ Balance error: {e}")
        return 0
    except Exception as e:
        logger.error(f"❌ Error getting balance: {e}")
        return 0

def round_quantity(quantity, symbol):
    """Round quantity to symbol's precision"""
    try:
        exchange_info = client.futures_exchange_info()
        for sym in exchange_info['symbols']:
            if sym['symbol'] == symbol:
                # Find quantity precision
                for filt in sym['filters']:
                    if filt['filterType'] == 'LOT_SIZE':
                        step_size = float(filt['stepSize'])
                        # Round down to step size
                        precision = len(str(step_size).rstrip('0').split('.')[-1])
                        rounded = round(quantity, precision)
                        logger.info(f"Quantity rounded: {quantity} → {rounded} {symbol}")
                        return rounded
        return quantity
    except Exception as e:
        logger.error(f"❌ Error rounding quantity: {e}")
        return quantity

def set_leverage(symbol, leverage):
    """Set leverage for symbol"""
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        logger.info(f"✅ Leverage set to {leverage}x for {symbol}")
        return True
    except BinanceAPIException as e:
        logger.error(f"❌ Leverage error: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Error setting leverage: {e}")
        return False

def place_order(symbol, side, quantity, order_type='MARKET'):
    """Place market order on Binance Futures"""
    try:
        # Round quantity first
        quantity = round_quantity(quantity, symbol)
        
        logger.info(f"📤 Placing {side} order: {symbol} {quantity:.8f}")
        
        # Set leverage first
        set_leverage(symbol, LEVERAGE)
        
        # Place order
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity
        )
        
        order_id = order.get('orderId')
        logger.info(f"✅ {side} order placed: {order_id}")
        return order_id
    
    except BinanceAPIException as e:
        logger.error(f"❌ Order failed: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Order error: {e}")
        return None

def place_tp_sl_orders(symbol, position_size, entry_price, tp_price, sl_price, side):
    """Place TP and SL orders as real Binance orders"""
    try:
        # Close side is opposite of entry side
        close_side = 'SELL' if side == 'BUY' else 'BUY'
        quantity = round_quantity(position_size, symbol)
        
        # TP order (limit order at TP price)
        try:
            tp_order = client.futures_create_order(
                symbol=symbol,
                side=close_side,
                type='TAKE_PROFIT_MARKET',
                quantity=quantity,
                stopPrice=tp_price,
                reduceOnly=True
            )
            logger.info(f"✅ TP order placed: {tp_order.get('orderId')}")
        except Exception as e:
            logger.warning(f"⚠️ TP order failed: {e}")
        
        # SL order (stop loss)
        try:
            sl_order = client.futures_create_order(
                symbol=symbol,
                side=close_side,
                type='STOP_MARKET',
                quantity=quantity,
                stopPrice=sl_price,
                reduceOnly=True
            )
            logger.info(f"✅ SL order placed: {sl_order.get('orderId')}")
        except Exception as e:
            logger.warning(f"⚠️ SL order failed: {e}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Error placing TP/SL: {e}")
        return False

def close_position(symbol, position_size, side):
    """Close position with reduceOnly flag"""
    try:
        close_side = 'SELL' if side == 'BUY' else 'BUY'
        quantity = round_quantity(position_size, symbol)
        
        order = client.futures_create_order(
            symbol=symbol,
            side=close_side,
            type='MARKET',
            quantity=quantity,
            reduceOnly=True
        )
        
        logger.info(f"✅ Position closed: {order.get('orderId')}")
        return order.get('orderId')
    except BinanceAPIException as e:
        logger.error(f"❌ Close position error: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Error closing position: {e}")
        return None

# ============ BINANCE API ============
def get_klines(symbol, interval='1h', limit=100):
    """Fetch OHLCV data from Binance"""
    try:
        klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        return klines
    except BinanceAPIException as e:
        logger.error(f"❌ Error fetching klines: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ Error fetching klines: {e}")
        return []

# ============ TRADING LOGIC ============
def check_pair(pair, symbol, balance):
    """Check trading signals for a pair"""
    global positions, last_signal_candle
    
    try:
        logger.info(f"📊 Checking {pair}...")
        klines = get_klines(symbol, interval='1h', limit=100)
        
        if not klines or len(klines) < VOLUME_PERIOD:
            logger.warning(f"⚠️ Not enough data for {pair}")
            return
        
        # Parse klines
        prices = [float(x[4]) for x in klines]
        volumes = [float(x[7]) for x in klines]
        times = [int(x[0]) for x in klines]
        
        current_time = times[-1]
        current_price = prices[-1]
        
        logger.info(f"📈 {pair}: Price=${current_price:.2f}, Vol={volumes[-1]:.0f}")
        
        # Check for volume spike
        vol_avg = sum(volumes[-VOLUME_PERIOD:]) / VOLUME_PERIOD
        vol_spike = volumes[-1] > vol_avg * VOLUME_MULTIPLIER
        recent_vol_spike = any(volumes[-i] > vol_avg * VOLUME_MULTIPLIER for i in range(1, 4))
        
        # BUY SIGNAL
        if (vol_spike or recent_vol_spike) and pair not in positions:
            if pair in last_signal_candle and last_signal_candle[pair] == current_time:
                logger.info(f"⏭️ {pair}: Skipping BUY (same candle)")
                return
            
            logger.info(f"🟢 BUY SIGNAL for {pair}!")
            
            entry_price = current_price
            tp_price = entry_price * (1 + TP_PERCENT / 100)
            sl_price = entry_price * (1 - SL_PERCENT / 100)
            
            # Calculate position size
            risk_amount = balance * (RISK_PERCENT / 100)
            price_diff = entry_price - sl_price
            position_size = risk_amount / (price_diff * LEVERAGE) if price_diff > 0 else 0.01
            
            logger.info(f"💰 Position size: {position_size:.8f}")
            
            # Place buy order
            buy_order = place_order(symbol, 'BUY', position_size)
            
            if buy_order:
                positions[pair] = {
                    'entry': entry_price,
                    'tp': tp_price,
                    'sl': sl_price,
                    'size': position_size,
                    'side': 'BUY',
                    'buy_time': current_time,
                    'order_id': buy_order
                }
                last_signal_candle[pair] = current_time
                
                # Place TP/SL orders
                place_tp_sl_orders(symbol, position_size, entry_price, tp_price, sl_price, 'BUY')
                
                msg = f"""🟢 BUY {pair}

Giriş Fiyatı
${entry_price:.2f}

Hedef (TP)
${tp_price:.2f}

Zarar Durdurma (SL)
${sl_price:.2f}

Pozisyon Boyutu
{position_size:.8f} {pair}

Kaldıraç
{LEVERAGE}x

Bakiye
${balance:.2f}

Saat
{get_time_utc3()}"""
                
                send_telegram(msg)
    
    except Exception as e:
        logger.error(f"❌ Error checking {pair}: {type(e).__name__}: {e}")

# ============ MAIN LOOP ============
def main():
    """Main bot loop - 24/7 operation"""
    logger.info(f"🤖 Bot started at {get_time_utc3()}")
    
    cycle = 0
    while True:  # 24/7 loop
        try:
            cycle += 1
            logger.info(f"\n⏰ Cycle {cycle} at {get_time_utc3()}...")
            
            # Get real balance
            balance = get_account_balance()
            if balance <= 0:
                logger.error("❌ Balance is 0 or negative")
                time.sleep(300)
                continue
            
            # Check both pairs
            check_pair('ETH', 'ETHUSDT', balance)
            time.sleep(2)
            check_pair('BTC', 'BTCUSDT', balance)
            
            logger.info(f"✅ Cycle completed")
            
            # Wait 1 hour before next check (or adjust as needed)
            logger.info(f"⏳ Sleeping for 1 hour...")
            time.sleep(3600)
        
        except KeyboardInterrupt:
            logger.info("\n🛑 Bot stopped by user")
            break
        except Exception as e:
            logger.error(f"❌ Main loop error: {type(e).__name__}: {e}")
            time.sleep(300)

if __name__ == '__main__':
    main()
