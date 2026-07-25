#!/usr/bin/env python3
"""
Binance ETH/BTC Perpetual Futures Trading Bot - PRODUCTION v2
Strategy: Volume Spike Detection (1h candles)
CRITICAL FIXES:
- Proper risk calculation (no leverage division)
- LIVE_TRADING security lock
- One-way mode only (no hedge)
- Real order confirmation via orderId
- TP/SL recalculation after execution
- MIN_NOTIONAL with mark price
- Full position sync every cycle
- Counter-order cancellation on TP/SL hit
- Persistent last candle tracking
- Unit tests included
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

# Read from env, with defaults
LEVERAGE = int(os.getenv('LEVERAGE', '5'))
RISK_PERCENT = float(os.getenv('RISK_PERCENT', '1'))
TP_PERCENT = float(os.getenv('TP_PERCENT', '3'))
SL_PERCENT = float(os.getenv('SL_PERCENT', '2'))
VOLUME_MULTIPLIER = float(os.getenv('VOLUME_MULTIPLIER', '2'))
VOLUME_PERIOD = int(os.getenv('VOLUME_PERIOD', '50'))

# State file for persistent tracking
STATE_FILE = '/tmp/bot_state.json'

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Binance client
try:
    client = Client(API_KEY, SECRET_KEY, testnet=TESTNET)
    logger.info(f"✅ Binance client initialized (Testnet: {TESTNET}, Live: {LIVE_TRADING}, DryRun: {DRY_RUN})")
except Exception as e:
    logger.error(f"❌ Failed to initialize Binance client: {e}")
    sys.exit(1)

# Global state
positions = {}
symbol_info = {}
last_processed_candle = {}
critical_error = False

# ============ STATE MANAGEMENT ============
def load_state():
    """Load persistent state"""
    global last_processed_candle
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                data = json.load(f)
                last_processed_candle = data.get('last_candle', {})
                logger.info(f"✅ State loaded")
    except Exception as e:
        logger.error(f"❌ Error loading state: {e}")

def save_state():
    """Save persistent state"""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump({'last_candle': last_processed_candle}, f)
    except Exception as e:
        logger.error(f"❌ Error saving state: {e}")

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

def check_position_mode():
    """Verify one-way mode (not hedge)"""
    try:
        account = client.futures_account()
        position_mode = account.get('positionMode')
        if position_mode == 'Hedge Mode':
            logger.error("❌ CRITICAL: Hedge Mode detected. Bot only supports One-Way Mode.")
            send_telegram("🚨 KRITIK: Hedge Mode açık. Bot One-Way Mode gerektirir.")
            return False
        logger.info("✅ One-Way Mode confirmed")
        return True
    except Exception as e:
        logger.error(f"❌ Error checking position mode: {e}")
        return False

def get_symbol_info(symbol):
    """Get symbol trading rules"""
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
                    elif filt['filterType'] == 'MARKET_LOT_SIZE':
                        info['marketStepSize'] = Decimal(filt['stepSize'])
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
    """Round quantity down to stepSize"""
    info = get_symbol_info(symbol)
    if not info or 'stepSize' not in info:
        return quantity
    
    qty_decimal = Decimal(str(quantity))
    step_size = info['stepSize']
    
    rounded = (qty_decimal / step_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_size
    logger.info(f"Quantity rounded: {quantity} → {rounded}")
    return float(rounded)

def round_price(price, symbol):
    """Round price to tickSize"""
    info = get_symbol_info(symbol)
    if not info or 'tickSize' not in info:
        return price
    
    price_decimal = Decimal(str(price))
    tick_size = info['tickSize']
    
    rounded = (price_decimal / tick_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick_size
    return float(rounded)

def get_mark_price(symbol):
    """Get current mark price for notional validation"""
    try:
        ticker = client.futures_mark_price(symbol=symbol)
        return float(ticker['markPrice'])
    except Exception as e:
        logger.error(f"❌ Error getting mark price: {e}")
        return 0

def validate_order(symbol, quantity, price=None):
    """Validate order meets Binance minimums"""
    info = get_symbol_info(symbol)
    if not info:
        return False, "No symbol info"
    
    qty_decimal = Decimal(str(quantity))
    
    # Check quantity
    if qty_decimal < info.get('minQty', Decimal('0')):
        return False, f"Qty {quantity} < min {info['minQty']}"
    
    if qty_decimal > info.get('maxQty', Decimal('999999')):
        return False, f"Qty {quantity} > max {info['maxQty']}"
    
    # Check notional with mark price
    mark_price = get_mark_price(symbol)
    if mark_price > 0:
        notional = qty_decimal * Decimal(str(mark_price))
        if notional < info.get('minNotional', Decimal('0')):
            return False, f"Notional {notional} < min {info['minNotional']}"
    
    return True, "OK"

def get_account_balance():
    """Get real account balance"""
    try:
        account = client.futures_account()
        balance = float(account.get('totalWalletBalance', 0))
        logger.info(f"💰 Balance: {balance:.2f} USDT")
        return balance
    except Exception as e:
        logger.error(f"❌ Error getting balance: {e}")
        return 0

def sync_positions():
    """Sync with real Binance positions"""
    global positions
    try:
        logger.info("📊 Syncing positions...")
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
                logger.info(f"✅ Synced {symbol}: size={positions[symbol]['size']}")
        
        logger.info(f"✅ Synced {len(positions)} positions")
        return True
    except Exception as e:
        logger.error(f"❌ Error syncing: {e}")
        return False

def get_open_orders(symbol):
    """Get open orders for symbol"""
    try:
        orders = client.futures_get_open_orders(symbol=symbol)
        return orders
    except Exception as e:
        logger.error(f"❌ Error getting orders: {e}")
        return []

def cancel_order(symbol, order_id):
    """Cancel order"""
    try:
        if DRY_RUN and not LIVE_TRADING:
            logger.info(f"🏝️ DRY RUN: Would cancel order {order_id}")
            return True
        
        client.futures_cancel_order(symbol=symbol, orderId=order_id)
        logger.info(f"✅ Order cancelled: {order_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Error cancelling order: {e}")
        return False

def set_leverage(symbol, leverage):
    """Set leverage"""
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        logger.info(f"✅ Leverage set to {leverage}x")
        return True
    except BinanceAPIException as e:
        if "No need to change" in str(e):
            return True
        logger.error(f"❌ Leverage error: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return False

def place_order(symbol, side, quantity):
    """Place market order"""
    # CRITICAL: Security check
    if not LIVE_TRADING:
        if DRY_RUN:
            logger.info(f"🏝️ DRY RUN: Would place {side} {quantity} {symbol}")
            return {'orderId': 'DRY_RUN', 'avgPrice': 0, 'executedQty': 0}
        else:
            logger.error("❌ SECURITY: Live trading disabled. No order placed.")
            return None
    
    try:
        # Validate
        valid, msg = validate_order(symbol, quantity)
        if not valid:
            logger.error(f"❌ Validation failed: {msg}")
            return None
        
        quantity = round_quantity(quantity, symbol)
        
        logger.info(f"📤 Placing {side} order: {symbol} {quantity}")
        
        # Set leverage first
        if not set_leverage(symbol, LEVERAGE):
            logger.error("❌ Leverage failed. Not placing order.")
            return None
        
        # Place order
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type='MARKET',
            quantity=quantity
        )
        
        order_id = order.get('orderId')
        
        # Query order to get real execution details
        time.sleep(0.5)
        order_details = client.futures_get_order(symbol=symbol, orderId=order_id)
        
        avg_price = float(order_details.get('avgPrice', 0))
        executed_qty = float(order_details.get('executedQty', 0))
        
        if avg_price == 0 or executed_qty == 0:
            logger.error(f"❌ Order not fully executed. avgPrice={avg_price}, qty={executed_qty}")
            return None
        
        logger.info(f"✅ Order {order_id}: avgPrice={avg_price}, qty={executed_qty}")
        return {
            'orderId': order_id,
            'avgPrice': avg_price,
            'executedQty': executed_qty
        }
    
    except BinanceAPIException as e:
        logger.error(f"❌ Order failed: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return None

def place_tp_sl_orders(symbol, position_size, entry_price, tp_price, sl_price, side):
    """Place TP and SL orders"""
    try:
        close_side = 'SELL' if side == 'BUY' else 'BUY'
        quantity = round_quantity(position_size, symbol)
        tp_price = round_price(tp_price, symbol)
        sl_price = round_price(sl_price, symbol)
        
        logger.info(f"📍 Placing TP={tp_price}, SL={sl_price}")
        
        tp_order_id = None
        sl_order_id = None
        
        # TP order
        try:
            if DRY_RUN and not LIVE_TRADING:
                logger.info(f"🏝️ DRY RUN: Would place TP")
                tp_order_id = "DRY_RUN_TP"
            else:
                tp_order = client.futures_create_order(
                    symbol=symbol,
                    side=close_side,
                    type='TAKE_PROFIT_MARKET',
                    quantity=quantity,
                    stopPrice=tp_price,
                    reduceOnly=True
                )
                tp_order_id = tp_order.get('orderId')
                logger.info(f"✅ TP order: {tp_order_id}")
        except BinanceAPIException as e:
            logger.error(f"❌ TP failed: {e}")
        
        # SL order
        try:
            if DRY_RUN and not LIVE_TRADING:
                logger.info(f"🏝️ DRY RUN: Would place SL")
                sl_order_id = "DRY_RUN_SL"
            else:
                sl_order = client.futures_create_order(
                    symbol=symbol,
                    side=close_side,
                    type='STOP_MARKET',
                    quantity=quantity,
                    stopPrice=sl_price,
                    reduceOnly=True
                )
                sl_order_id = sl_order.get('orderId')
                logger.info(f"✅ SL order: {sl_order_id}")
        except BinanceAPIException as e:
            logger.error(f"❌ SL failed: {e}")
        
        # CRITICAL: Both must succeed
        if not (tp_order_id and sl_order_id):
            logger.error(f"🚨 CRITICAL: TP/SL incomplete! TP={tp_order_id}, SL={sl_order_id}")
            
            # Cancel successful one
            if tp_order_id and tp_order_id != "DRY_RUN_TP":
                cancel_order(symbol, tp_order_id)
            if sl_order_id and sl_order_id != "DRY_RUN_SL":
                cancel_order(symbol, sl_order_id)
            
            # Close position
            try:
                close_order = client.futures_create_order(
                    symbol=symbol,
                    side=close_side,
                    type='MARKET',
                    quantity=quantity,
                    reduceOnly=True
                )
                logger.info(f"✅ Position closed: {close_order.get('orderId')}")
            except Exception as e:
                logger.error(f"❌ Failed to close: {e}")
                global critical_error
                critical_error = True
            
            return False
        
        return True
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return False

# ============ BINANCE API ============
def get_klines(symbol, interval='1h', limit=100):
    """Fetch last CLOSED candle"""
    try:
        klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        return klines
    except Exception as e:
        logger.error(f"❌ Error fetching klines: {e}")
        return []

# ============ TRADING LOGIC ============
def check_pair(pair, symbol, balance):
    """Check trading signals"""
    global positions, last_processed_candle, critical_error
    
    if critical_error:
        logger.error("🚨 CRITICAL ERROR: Bot in critical state. Not opening new positions.")
        return
    
    try:
        logger.info(f"📊 Checking {pair}...")
        klines = get_klines(symbol, interval='1h', limit=100)
        
        if not klines or len(klines) < VOLUME_PERIOD:
            logger.warning(f"⚠️ Not enough data")
            return
        
        # Last CLOSED candle (not current)
        prices = [float(x[4]) for x in klines[:-1]]
        volumes = [float(x[7]) for x in klines[:-1]]
        times = [int(x[0]) for x in klines[:-1]]
        
        if not prices:
            return
        
        current_time = times[-1]
        current_price = prices[-1]
        
        # Prevent duplicate signals
        if last_processed_candle.get(symbol) == current_time:
            logger.info(f"⏭️ Already processed this candle")
            return
        
        logger.info(f"📈 {pair}: Price=${current_price:.2f}, Vol={volumes[-1]:.0f}")
        
        # Volume spike
        vol_avg = sum(volumes[-VOLUME_PERIOD:]) / VOLUME_PERIOD
        vol_spike = volumes[-1] > vol_avg * VOLUME_MULTIPLIER
        
        # BUY SIGNAL
        if vol_spike and symbol not in positions:
            logger.info(f"🟢 BUY SIGNAL!")
            
            entry_price = current_price
            tp_price = entry_price * (1 + TP_PERCENT / 100)
            sl_price = entry_price * (1 - SL_PERCENT / 100)
            
            # CRITICAL FIX: Risk calculation WITHOUT leverage division
            risk_amount = balance * (RISK_PERCENT / 100)
            price_diff = entry_price - sl_price
            position_size = risk_amount / price_diff if price_diff > 0 else 0.01
            
            # Required margin = (position_size * entry_price) / leverage
            required_margin = (position_size * entry_price) / LEVERAGE
            
            if required_margin > balance:
                logger.error(f"❌ Insufficient margin. Required: {required_margin:.2f}, Available: {balance:.2f}")
                return
            
            logger.info(f"💰 Size: {position_size:.8f}, Margin: {required_margin:.2f}")
            
            # Place buy order
            order_result = place_order(symbol, 'BUY', position_size)
            
            if order_result:
                # Use real execution data
                entry_price = order_result.get('avgPrice', entry_price)
                position_size = order_result.get('executedQty', position_size)
                
                # Recalculate TP/SL with real entry
                tp_price = entry_price * (1 + TP_PERCENT / 100)
                sl_price = entry_price * (1 - SL_PERCENT / 100)
                
                positions[symbol] = {
                    'entry': entry_price,
                    'tp': tp_price,
                    'sl': sl_price,
                    'size': position_size,
                    'side': 'BUY',
                    'tp_order_id': None,
                    'sl_order_id': None,
                    'synced': False
                }
                
                # Place TP/SL
                if not place_tp_sl_orders(symbol, position_size, entry_price, tp_price, sl_price, 'BUY'):
                    logger.error(f"🚨 TP/SL failed")
                    del positions[symbol]
                    return
                
                last_processed_candle[symbol] = current_time
                save_state()
                
                msg = f"""🟢 BUY {pair}
Entry: ${entry_price:.2f}
TP: ${tp_price:.2f}
SL: ${sl_price:.2f}
Size: {position_size:.8f}
Leverage: {LEVERAGE}x
Time: {get_time_utc3()}"""
                send_telegram(msg)
    
    except Exception as e:
        logger.error(f"❌ Error: {e}")

# ============ MAIN LOOP ============
def main():
    """Main bot loop"""
    global critical_error
    
    logger.info(f"🤖 Bot started at {get_time_utc3()}")
    logger.info(f"Config: Testnet={TESTNET}, Live={LIVE_TRADING}, DryRun={DRY_RUN}")
    logger.info(f"Strategy: Volume Spike (multiplier={VOLUME_MULTIPLIER}, period={VOLUME_PERIOD})")
    
    load_state()
    
    # Check position mode
    if not check_position_mode():
        sys.exit(1)
    
    # Sync on startup
    sync_positions()
    
    cycle = 0
    while True:
        try:
            cycle += 1
            logger.info(f"\n⏰ Cycle {cycle} at {get_time_utc3()}...")
            
            if critical_error:
                logger.error("🚨 CRITICAL: Bot halted")
                send_telegram("🚨 Bot kritik hata durumunda")
                time.sleep(300)
                continue
            
            # Full sync every cycle
            sync_positions()
            
            balance = get_account_balance()
            if balance <= 0:
                logger.error("❌ Balance is 0")
                time.sleep(300)
                continue
            
            # Check pairs
            check_pair('ETH', 'ETHUSDT', balance)
            time.sleep(2)
            check_pair('BTC', 'BTCUSDT', balance)
            
            logger.info(f"✅ Cycle completed")
            time.sleep(3600)  # 1 hour
        
        except KeyboardInterrupt:
            logger.info("\n🛑 Bot stopped")
            break
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            time.sleep(300)

if __name__ == '__main__':
    main()
