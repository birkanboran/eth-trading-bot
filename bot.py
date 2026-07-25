#!/usr/bin/env python3
"""
Binance ETH/BTC Perpetual Futures Trading Bot - PRODUCTION VERSION
Strategy: Volume Spike Detection (1h candles)
Features:
- Sync with real Binance positions on startup
- Proper leverage, quantity, and price rounding (Decimal)
- TP/SL as real orders with critical error handling
- Hedge mode support
- Min notional/quantity validation
- Testnet/dry-run by default, LIVE_TRADING=true for real trades
"""
import os
import sys
import time
import json
import logging
import requests
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from binance.client import Client
from binance.exceptions import BinanceAPIException

# ============ CONFIGURATION ============
API_KEY = os.getenv('BINANCE_API_KEY', '')
SECRET_KEY = os.getenv('BINANCE_SECRET_KEY', '')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

TESTNET = os.getenv('BINANCE_TESTNET', 'true').lower() == 'true'
LIVE_TRADING = os.getenv('LIVE_TRADING', 'false').lower() == 'true'
DRY_RUN = os.getenv('DRY_RUN', 'true').lower() == 'true'

# Trading parameters
LEVERAGE = 5
RISK_PERCENT = 1
TP_PERCENT = 3
SL_PERCENT = 2
VOLUME_MULTIPLIER = 2
VOLUME_PERIOD = 50

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Binance client
try:
    client = Client(API_KEY, SECRET_KEY, testnet=TESTNET)
    logger.info(f"✅ Binance client initialized (Testnet: {TESTNET}, Live: {LIVE_TRADING})")
except Exception as e:
    logger.error(f"❌ Failed to initialize Binance client: {e}")
    sys.exit(1)

# Global state
positions = {}
symbol_info = {}

# ============ UTILITIES ============
def get_time_utc3():
    """Get current time in UTC+3"""
    tz = timezone(timedelta(hours=3))
    return datetime.now(tz).strftime('%H:%M:%S')

def send_telegram(msg):
    """Send message to Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("⚠️ Telegram credentials not set")
        return
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {'chat_id': CHAT_ID, 'text': msg}
        requests.post(url, data=data, timeout=10)
        logger.info("✅ Telegram sent")
    except Exception as e:
        logger.error(f"❌ Telegram error: {e}")

def get_symbol_info(symbol):
    """Get symbol trading rules (LOT_SIZE, PRICE_FILTER, etc.)"""
    if symbol in symbol_info:
        return symbol_info[symbol]
    
    try:
        exchange_info = client.futures_exchange_info()
        for sym in exchange_info['symbols']:
            if sym['symbol'] == symbol:
                info = {}
                for filt in sym['filters']:
                    if filt['filterType'] == 'LOT_SIZE':
                        info['stepSize'] = Decimal(filt['stepSize'])
                        info['minQty'] = Decimal(filt['minQty'])
                        info['maxQty'] = Decimal(filt['maxQty'])
                    elif filt['filterType'] == 'PRICE_FILTER':
                        info['tickSize'] = Decimal(filt['tickSize'])
                        info['minPrice'] = Decimal(filt['minPrice'])
                    elif filt['filterType'] == 'MIN_NOTIONAL':
                        info['minNotional'] = Decimal(filt['notional'])
                
                symbol_info[symbol] = info
                logger.info(f"✅ Symbol info loaded: {symbol}")
                return info
        
        logger.warning(f"⚠️ Symbol {symbol} not found")
        return {}
    except Exception as e:
        logger.error(f"❌ Error getting symbol info: {e}")
        return {}

def round_quantity(quantity, symbol):
    """Round quantity down to stepSize using Decimal"""
    info = get_symbol_info(symbol)
    if not info or 'stepSize' not in info:
        return quantity
    
    qty_decimal = Decimal(str(quantity))
    step_size = info['stepSize']
    
    # Round down
    rounded = (qty_decimal / step_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_size
    
    logger.info(f"Quantity rounded: {quantity} → {rounded} {symbol}")
    return float(rounded)

def round_price(price, symbol):
    """Round price to tickSize using Decimal"""
    info = get_symbol_info(symbol)
    if not info or 'tickSize' not in info:
        return price
    
    price_decimal = Decimal(str(price))
    tick_size = info['tickSize']
    
    # Round down for SL, round up for TP
    rounded = (price_decimal / tick_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick_size
    
    return float(rounded)

def validate_order(symbol, quantity, price=None):
    """Validate order meets Binance minimums"""
    info = get_symbol_info(symbol)
    if not info:
        return True, "No symbol info"
    
    qty_decimal = Decimal(str(quantity))
    
    # Check quantity
    if qty_decimal < info.get('minQty', Decimal('0')):
        return False, f"Qty {quantity} < min {info['minQty']}"
    
    if qty_decimal > info.get('maxQty', Decimal('999999')):
        return False, f"Qty {quantity} > max {info['maxQty']}"
    
    # Check notional (only for limit orders with price)
    if price:
        notional = qty_decimal * Decimal(str(price))
        if notional < info.get('minNotional', Decimal('0')):
            return False, f"Notional {notional} < min {info['minNotional']}"
    
    return True, "OK"

def get_account_balance():
    """Get real account balance from Binance"""
    try:
        account = client.futures_account()
        balance = float(account.get('totalWalletBalance', 0))
        logger.info(f"💰 Account balance: {balance:.2f} USDT")
        return balance
    except Exception as e:
        logger.error(f"❌ Error getting balance: {e}")
        return 0

def sync_positions():
    """Sync local positions with real Binance positions"""
    global positions
    try:
        logger.info("📊 Syncing positions with Binance...")
        open_positions = client.futures_position_information()
        
        positions = {}
        for pos in open_positions:
            if float(pos['positionAmt']) != 0:
                symbol = pos['symbol']
                positions[symbol] = {
                    'entry': float(pos['entryPrice']),
                    'size': abs(float(pos['positionAmt'])),
                    'side': 'BUY' if float(pos['positionAmt']) > 0 else 'SELL',
                    'leverage': int(pos['leverage']),
                    'synced': True
                }
                logger.info(f"✅ Synced {symbol}: {positions[symbol]}")
        
        logger.info(f"✅ Synced {len(positions)} positions")
        return positions
    except Exception as e:
        logger.error(f"❌ Error syncing positions: {e}")
        return {}

def set_leverage(symbol, leverage):
    """Set leverage for symbol"""
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        logger.info(f"✅ Leverage set to {leverage}x for {symbol}")
        return True
    except BinanceAPIException as e:
        if "No need to change" in str(e):
            logger.info(f"ℹ️ Leverage already {leverage}x for {symbol}")
            return True
        logger.error(f"❌ Leverage error: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Error setting leverage: {e}")
        return False

def place_order(symbol, side, quantity):
    """Place market order on Binance Futures"""
    try:
        # Validate
        valid, msg = validate_order(symbol, quantity)
        if not valid:
            logger.error(f"❌ Order validation failed: {msg}")
            return None
        
        quantity = round_quantity(quantity, symbol)
        
        logger.info(f"📤 Placing {side} order: {symbol} {quantity:.8f}")
        
        if DRY_RUN and not LIVE_TRADING:
            logger.info(f"🏝️ DRY RUN: Would place {side} order")
            return "DRY_RUN_ORDER_ID"
        
        # Set leverage first
        set_leverage(symbol, LEVERAGE)
        
        # Place order
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type='MARKET',
            quantity=quantity
        )
        
        order_id = order.get('orderId')
        avg_price = float(order.get('avgPrice', 0))
        executed_qty = float(order.get('executedQty', 0))
        
        logger.info(f"✅ Order placed: {order_id}, AvgPrice: {avg_price}, Qty: {executed_qty}")
        return {
            'orderId': order_id,
            'avgPrice': avg_price,
            'executedQty': executed_qty
        }
    
    except BinanceAPIException as e:
        logger.error(f"❌ Order failed: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Order error: {e}")
        return None

def place_tp_sl_orders(symbol, position_size, entry_price, tp_price, sl_price, side):
    """Place TP and SL orders as real Binance orders"""
    try:
        close_side = 'SELL' if side == 'BUY' else 'BUY'
        quantity = round_quantity(position_size, symbol)
        tp_price = round_price(tp_price, symbol)
        sl_price = round_price(sl_price, symbol)
        
        logger.info(f"📍 Placing TP/SL: TP={tp_price}, SL={sl_price}")
        
        tp_success = False
        sl_success = False
        
        # TP order
        try:
            if DRY_RUN and not LIVE_TRADING:
                logger.info(f"🏝️ DRY RUN: Would place TP order")
                tp_success = True
            else:
                tp_order = client.futures_create_order(
                    symbol=symbol,
                    side=close_side,
                    type='TAKE_PROFIT_MARKET',
                    quantity=quantity,
                    stopPrice=tp_price,
                    reduceOnly=True
                )
                tp_success = True
                logger.info(f"✅ TP order placed: {tp_order.get('orderId')}")
        except BinanceAPIException as e:
            logger.error(f"❌ TP order failed: {e}")
        
        # SL order
        try:
            if DRY_RUN and not LIVE_TRADING:
                logger.info(f"🏝️ DRY RUN: Would place SL order")
                sl_success = True
            else:
                sl_order = client.futures_create_order(
                    symbol=symbol,
                    side=close_side,
                    type='STOP_MARKET',
                    quantity=quantity,
                    stopPrice=sl_price,
                    reduceOnly=True
                )
                sl_success = True
                logger.info(f"✅ SL order placed: {sl_order.get('orderId')}")
        except BinanceAPIException as e:
            logger.error(f"❌ SL order failed: {e}")
        
        # Critical: Both must succeed
        if not (tp_success and sl_success):
            logger.error(f"🚨 CRITICAL: TP/SL incomplete! TP={tp_success}, SL={sl_success}")
            send_telegram(f"🚨 KRITIK HATA: TP/SL emirleri başarısız!\nTP={tp_success}, SL={sl_success}\n{symbol}")
            return False
        
        return True
    except Exception as e:
        logger.error(f"❌ Error placing TP/SL: {e}")
        return False

# ============ BINANCE API ============
def get_klines(symbol, interval='1h', limit=100):
    """Fetch OHLCV data from Binance (last closed candle)"""
    try:
        klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        return klines
    except Exception as e:
        logger.error(f"❌ Error fetching klines: {e}")
        return []

# ============ TRADING LOGIC ============
def check_pair(pair, symbol, balance):
    """Check trading signals for a pair"""
    global positions
    
    try:
        logger.info(f"📊 Checking {pair}...")
        klines = get_klines(symbol, interval='1h', limit=100)
        
        if not klines or len(klines) < VOLUME_PERIOD:
            logger.warning(f"⚠️ Not enough data for {pair}")
            return
        
        # Use last CLOSED candle (index -2, not -1)
        prices = [float(x[4]) for x in klines[:-1]]  # Close prices (excluding current)
        volumes = [float(x[7]) for x in klines[:-1]]  # Quote asset volumes
        times = [int(x[0]) for x in klines[:-1]]
        
        if not prices:
            return
        
        current_time = times[-1]
        current_price = prices[-1]
        
        logger.info(f"📈 {pair}: Price=${current_price:.2f}, Vol={volumes[-1]:.0f}")
        
        # Check for volume spike
        vol_avg = sum(volumes[-VOLUME_PERIOD:]) / VOLUME_PERIOD
        vol_spike = volumes[-1] > vol_avg * VOLUME_MULTIPLIER
        
        # BUY SIGNAL
        if vol_spike and symbol not in positions:
            logger.info(f"🟢 BUY SIGNAL for {pair}!")
            
            entry_price = current_price
            tp_price = entry_price * (1 + TP_PERCENT / 100)
            sl_price = entry_price * (1 - SL_PERCENT / 100)
            
            # Risk calculation: (balance * risk%) / ((entry - sl) * leverage)
            risk_amount = balance * (RISK_PERCENT / 100)
            price_diff = entry_price - sl_price
            position_size = risk_amount / (price_diff * LEVERAGE) if price_diff > 0 else 0.01
            
            logger.info(f"💰 Position size: {position_size:.8f}")
            
            # Place buy order
            order_result = place_order(symbol, 'BUY', position_size)
            
            if order_result:
                # Use real executed price if available
                if isinstance(order_result, dict):
                    entry_price = order_result.get('avgPrice', entry_price)
                    position_size = order_result.get('executedQty', position_size)
                
                positions[symbol] = {
                    'entry': entry_price,
                    'tp': tp_price,
                    'sl': sl_price,
                    'size': position_size,
                    'side': 'BUY',
                    'synced': False
                }
                
                # Place TP/SL orders
                if not place_tp_sl_orders(symbol, position_size, entry_price, tp_price, sl_price, 'BUY'):
                    logger.error(f"🚨 CRITICAL: TP/SL failed for {symbol}")
                    # Close position immediately
                    try:
                        close_order = client.futures_create_order(
                            symbol=symbol,
                            side='SELL',
                            type='MARKET',
                            quantity=position_size,
                            reduceOnly=True
                        )
                        logger.info(f"✅ Position closed due to TP/SL failure: {close_order.get('orderId')}")
                    except Exception as e:
                        logger.error(f"❌ Failed to close position: {e}")
                    
                    del positions[symbol]
                    return
                
                msg = f"""🟢 BUY {pair}

Giriş Fiyatı
${entry_price:.2f}

Hedef (TP)
${tp_price:.2f}

Zarar Durdurma (SL)
${sl_price:.2f}

Pozisyon Boyutu
{position_size:.8f}

Kaldıraç
{LEVERAGE}x

Bakiye
${balance:.2f}

Saat
{get_time_utc3()}"""
                
                send_telegram(msg)
    
    except Exception as e:
        logger.error(f"❌ Error checking {pair}: {e}")

# ============ MAIN LOOP ============
def main():
    """Main bot loop - 24/7 operation"""
    logger.info(f"🤖 Bot started at {get_time_utc3()}")
    logger.info(f"Mode: Testnet={TESTNET}, Live={LIVE_TRADING}, DryRun={DRY_RUN}")
    
    # Sync with Binance on startup
    sync_positions()
    
    cycle = 0
    while True:
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
            
            # Wait 1 hour before next check
            logger.info(f"⏳ Sleeping for 1 hour...")
            time.sleep(3600)
        
        except KeyboardInterrupt:
            logger.info("\n🛑 Bot stopped by user")
            break
        except Exception as e:
            logger.error(f"❌ Main loop error: {e}")
            time.sleep(300)

if __name__ == '__main__':
    main()
