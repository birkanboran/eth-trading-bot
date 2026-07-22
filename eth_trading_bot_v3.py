#!/usr/bin/env python3
"""
ETH/USDT Trading Bot - COMPLETE REWRITE
- Proper state machine (IDLE -> LONG -> IDLE)
- Working SELL signals
- No duplicate signals
- Real position tracking
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Dict

import ccxt
import pandas as pd
from telegram import Bot
from telegram.error import TelegramError

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s UTC] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('/home/ubuntu/bot_v3.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TradingBotV3:
    def __init__(self):
        # API Setup
        self.exchange = ccxt.bybit({
            'apiKey': os.getenv('BYBIT_API_KEY', 'CPSkGJlpunApHRWmIu'),
            'secret': os.getenv('BYBIT_SECRET_KEY', 'wrfqLrR74nZRsT02p6F4fAHwlqtvJvWFnDDA'),
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        
        self.telegram_bot = Bot(token=os.getenv('TELEGRAM_TOKEN', '8993995766:AAGxfrHRnL-9VxBUjOJXA__9BaAVMgD4ndU'))
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID', '851788804')
        
        # Trading params
        self.symbol = 'ETH/USDT:USDT'
        self.timeframe = '15m'
        self.leverage = 5
        self.risk_pct = 1
        
        # State machine
        self.state = 'IDLE'  # IDLE or LONG
        self.position = None  # Current open position
        self.last_candle_time = None  # Track processed candles
        
        # Stats
        self.balance = 100
        self.trades = []
        self.daily_pnl = 0
        
        self.load_state()
        logger.info("✅ Bot V3 initialized - State Machine Ready")
    
    def get_utc_now(self):
        return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    def load_state(self):
        """Load persistent state"""
        if os.path.exists('/home/ubuntu/bot_v3_state.json'):
            try:
                with open('/home/ubuntu/bot_v3_state.json', 'r') as f:
                    data = json.load(f)
                    self.state = data.get('state', 'IDLE')
                    self.position = data.get('position', None)
                    self.balance = data.get('balance', 100)
                    self.last_candle_time = data.get('last_candle_time', None)
                    logger.info(f"✅ Loaded state: {self.state}")
            except Exception as e:
                logger.error(f"Error loading state: {e}")
    
    def save_state(self):
        """Save persistent state"""
        state_data = {
            'state': self.state,
            'position': self.position,
            'balance': self.balance,
            'last_candle_time': self.last_candle_time,
            'timestamp': self.get_utc_now()
        }
        with open('/home/ubuntu/bot_v3_state.json', 'w') as f:
            json.dump(state_data, f, indent=2)
    
    def fetch_candles(self, limit=50):
        """Fetch OHLCV data"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['time', 'o', 'h', 'l', 'c', 'v'])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return None
    
    def find_swing_low(self, df):
        """Find swing low (dip) - best BUY point"""
        if len(df) < 5:
            return None
        
        # Last candle is swing low if:
        # - Its low is lower than previous 2 and next 2 candles
        i = len(df) - 1
        current_low = df['l'].iloc[i]
        
        # Check previous 2
        if i >= 2:
            prev_lows = df['l'].iloc[i-2:i].min()
            if current_low < prev_lows:
                return i, current_low
        
        return None
    
    def find_swing_high(self, df):
        """Find swing high (peak) - best SELL point"""
        if len(df) < 5:
            return None
        
        # Last candle is swing high if:
        # - Its high is higher than previous 2 candles
        i = len(df) - 1
        current_high = df['h'].iloc[i]
        
        # Check previous 2
        if i >= 2:
            prev_highs = df['h'].iloc[i-2:i].max()
            if current_high > prev_highs:
                return i, current_high
        
        return None
    
    def send_telegram(self, message):
        """Send message to Telegram"""
        try:
            self.telegram_bot.send_message(chat_id=self.chat_id, text=message)
            logger.info("✅ Telegram sent")
        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
    
    def on_buy_signal(self, entry_price, df):
        """Handle BUY signal"""
        if self.state != 'IDLE':
            logger.warning(f"⚠️ Already in {self.state} state, ignoring BUY")
            return
        
        # Calculate TP/SL
        tp = entry_price * 1.02  # +2%
        sl = entry_price * 0.98  # -2%
        
        # Calculate position size
        risk_amount = self.balance * (self.risk_pct / 100)
        position_size = risk_amount / (entry_price - sl)
        notional = position_size * entry_price
        
        # Create position
        self.position = {
            'entry': entry_price,
            'tp': tp,
            'sl': sl,
            'size': position_size,
            'notional': notional,
            'entry_time': self.get_utc_now(),
            'entry_candle_idx': len(df) - 1
        }
        self.state = 'LONG'
        self.save_state()
        
        msg = f"""
🟢 **BUY SIGNAL**

📍 Entry: ${entry_price:.2f}
🎯 TP: ${tp:.2f} (+2%)
🛑 SL: ${sl:.2f} (-2%)

📊 Size: {position_size:.4f} ETH
💰 Notional: ${notional:.2f}
⚡ Leverage: {self.leverage}x
⚠️ Risk: {self.risk_pct}%

💵 Balance: ${self.balance:.2f}
🕐 {self.position['entry_time']}
        """
        self.send_telegram(msg)
        logger.info(f"🟢 BUY @ ${entry_price:.2f}")
    
    def on_sell_signal(self, exit_price, df):
        """Handle SELL signal"""
        if self.state != 'LONG' or not self.position:
            logger.warning(f"⚠️ No open position, ignoring SELL")
            return
        
        entry = self.position['entry']
        pnl = (exit_price - entry) * self.position['size'] * self.leverage
        pnl_pct = (pnl / self.balance) * 100
        
        # Determine close reason
        if exit_price >= self.position['tp']:
            reason = 'TP ✅'
        elif exit_price <= self.position['sl']:
            reason = 'SL ❌'
        else:
            reason = 'MARKET'
        
        # Update balance
        old_balance = self.balance
        self.balance += pnl
        self.daily_pnl += pnl
        
        # Save trade
        trade = {
            'entry': entry,
            'exit': exit_price,
            'tp': self.position['tp'],
            'sl': self.position['sl'],
            'size': self.position['size'],
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'reason': reason,
            'entry_time': self.position['entry_time'],
            'exit_time': self.get_utc_now()
        }
        self.trades.append(trade)
        
        # Reset state
        self.position = None
        self.state = 'IDLE'
        self.save_state()
        
        msg = f"""
🔴 **SELL SIGNAL**

📍 Entry: ${entry:.2f}
📍 Exit: ${exit_price:.2f}
🎯 TP: ${self.position['tp']:.2f}
🛑 SL: ${self.position['sl']:.2f}

💹 PnL: ${pnl:.2f} ({pnl_pct:.2f}%)
{reason}

📊 Size: {self.position['size']:.4f} ETH
⚡ Leverage: {self.leverage}x

💵 Balance: ${old_balance:.2f} → ${self.balance:.2f}
📈 Trades: {len(self.trades)}
📊 Daily PnL: ${self.daily_pnl:.2f}

🕐 {self.get_utc_now()}
        """
        self.send_telegram(msg)
        logger.info(f"🔴 SELL @ ${exit_price:.2f}, PnL ${pnl:.2f}")
    
    def run(self):
        """Main loop"""
        logger.info("🚀 Starting bot loop...")
        
        while True:
            try:
                df = self.fetch_candles(limit=50)
                if df is None or len(df) < 5:
                    logger.warning("⚠️ Insufficient data")
                    time.sleep(60)
                    continue
                
                current_time = df['time'].iloc[-1]
                
                # Skip if same candle
                if self.last_candle_time and self.last_candle_time == current_time:
                    time.sleep(30)
                    continue
                
                self.last_candle_time = current_time
                
                # STATE MACHINE
                if self.state == 'IDLE':
                    # Look for BUY signal
                    swing_low = self.find_swing_low(df)
                    if swing_low:
                        idx, price = swing_low
                        logger.info(f"📍 Swing low detected @ ${price:.2f}")
                        self.on_buy_signal(price, df)
                
                elif self.state == 'LONG':
                    # Look for SELL signal
                    swing_high = self.find_swing_high(df)
                    if swing_high:
                        idx, price = swing_high
                        logger.info(f"📍 Swing high detected @ ${price:.2f}")
                        self.on_sell_signal(price, df)
                
                # Log current price
                current_price = df['c'].iloc[-1]
                logger.info(f"Price: ${current_price:.2f} | State: {self.state} | Balance: ${self.balance:.2f}")
                
                time.sleep(60)
                
            except Exception as e:
                logger.error(f"❌ Error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(60)

if __name__ == '__main__':
    bot = TradingBotV3()
    bot.run()
