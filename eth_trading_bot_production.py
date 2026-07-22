#!/usr/bin/env python3
"""
ETH/USDT Trading Bot - PRODUCTION VERSION
State Machine: IDLE -> LONG -> IDLE
Working SELL signals, no duplicates
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

import ccxt
import pandas as pd
from telegram import Bot
from telegram.error import TelegramError

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s UTC] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('/home/ubuntu/bot_prod.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TradingBotProduction:
    def __init__(self):
        # API
        self.exchange = ccxt.bybit({
            'apiKey': os.getenv('BYBIT_API_KEY', 'CPSkGJlpunApHRWmIu'),
            'secret': os.getenv('BYBIT_SECRET_KEY', 'wrfqLrR74nZRsT02p6F4fAHwlqtvJvWFnDDA'),
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        
        self.telegram = Bot(token=os.getenv('TELEGRAM_TOKEN', '8993995766:AAGxfrHRnL-9VxBUjOJXA__9BaAVMgD4ndU'))
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID', '851788804')
        
        # Params
        self.symbol = 'ETH/USDT:USDT'
        self.timeframe = '15m'
        self.leverage = 5
        self.risk_pct = 1
        
        # State
        self.state = 'IDLE'
        self.position = None
        self.last_candle_time = None
        self.balance = 100
        self.trades = []
        self.daily_pnl = 0
        
        self.load_state()
        logger.info("✅ Bot Production initialized")
    
    def get_utc(self):
        return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    def load_state(self):
        try:
            if os.path.exists('/home/ubuntu/bot_prod_state.json'):
                with open('/home/ubuntu/bot_prod_state.json', 'r') as f:
                    data = json.load(f)
                    self.state = data.get('state', 'IDLE')
                    self.position = data.get('position')
                    self.balance = data.get('balance', 100)
                    logger.info(f"✅ Loaded state: {self.state}")
        except Exception as e:
            logger.warning(f"⚠️ State load error: {e}, starting fresh")
            self.state = 'IDLE'
    
    def save_state(self):
        data = {
            'state': self.state,
            'position': self.position,
            'balance': self.balance,
            'timestamp': self.get_utc()
        }
        with open('/home/ubuntu/bot_prod_state.json', 'w') as f:
            json.dump(data, f, indent=2)
    
    def fetch_candles(self, limit=50) -> Optional[pd.DataFrame]:
        try:
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['time', 'o', 'h', 'l', 'c', 'v'])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return None
    
    def find_swing_low(self, df) -> Optional[Tuple[int, float]]:
        """Swing low = dip"""
        if len(df) < 5:
            return None
        
        i = len(df) - 1
        current = df['l'].iloc[i]
        
        # Check if current is lower than previous 2
        if i >= 2:
            prev_min = df['l'].iloc[max(0, i-2):i].min()
            if current < prev_min:
                return i, current
        
        return None
    
    def find_swing_high(self, df) -> Optional[Tuple[int, float]]:
        """Swing high = peak"""
        if len(df) < 5:
            return None
        
        i = len(df) - 1
        current = df['h'].iloc[i]
        
        # Check if current is higher than previous 2
        if i >= 2:
            prev_max = df['h'].iloc[max(0, i-2):i].max()
            if current > prev_max:
                return i, current
        
        return None
    
    def send_msg(self, msg: str):
        try:
            self.telegram.send_message(chat_id=self.chat_id, text=msg)
            logger.info("✅ Telegram sent")
        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
    
    def on_buy(self, entry: float, df):
        if self.state != 'IDLE':
            logger.warning(f"⚠️ Not IDLE, ignoring BUY")
            return
        
        tp = entry * 1.02
        sl = entry * 0.98
        
        risk = self.balance * (self.risk_pct / 100)
        size = risk / (entry - sl)
        notional = size * entry
        
        self.position = {
            'entry': entry,
            'tp': tp,
            'sl': sl,
            'size': size,
            'notional': notional,
            'entry_time': self.get_utc()
        }
        self.state = 'LONG'
        self.save_state()
        
        msg = f"""
🟢 **BUY SIGNAL - ETH/USDT**

📍 Entry: ${entry:.2f}
🎯 TP: ${tp:.2f} (+2%)
🛑 SL: ${sl:.2f} (-2%)

📊 Size: {size:.4f} ETH
💰 Notional: ${notional:.2f}
⚡ Leverage: {self.leverage}x
⚠️ Risk: {self.risk_pct}%

💵 Balance: ${self.balance:.2f}

🕐 {self.position['entry_time']}
        """
        self.send_msg(msg)
        logger.info(f"🟢 BUY @ ${entry:.2f}")
    
    def on_sell(self, exit_price: float, df):
        if self.state != 'LONG' or not self.position:
            logger.warning(f"⚠️ No position, ignoring SELL")
            return
        
        entry = self.position['entry']
        pnl = (exit_price - entry) * self.position['size'] * self.leverage
        pnl_pct = (pnl / self.balance) * 100
        
        if exit_price >= self.position['tp']:
            reason = 'TP ✅'
        elif exit_price <= self.position['sl']:
            reason = 'SL ❌'
        else:
            reason = 'MARKET'
        
        old_bal = self.balance
        self.balance += pnl
        self.daily_pnl += pnl
        
        self.trades.append({
            'entry': entry,
            'exit': exit_price,
            'pnl': pnl,
            'reason': reason,
            'time': self.get_utc()
        })
        
        self.position = None
        self.state = 'IDLE'
        self.save_state()
        
        msg = f"""
🔴 **SELL SIGNAL - ETH/USDT**

📍 Entry: ${entry:.2f}
📍 Exit: ${exit_price:.2f}
🎯 TP: ${self.position['tp']:.2f}
🛑 SL: ${self.position['sl']:.2f}

💹 PnL: ${pnl:.2f} ({pnl_pct:.2f}%)
{reason}

📊 Size: {self.position['size']:.4f} ETH
⚡ Leverage: {self.leverage}x

💵 Balance: ${old_bal:.2f} → ${self.balance:.2f}
📈 Trades: {len(self.trades)}
📊 Daily PnL: ${self.daily_pnl:.2f}

🕐 {self.get_utc()}
        """
        self.send_msg(msg)
        logger.info(f"🔴 SELL @ ${exit_price:.2f}, PnL ${pnl:.2f}")
    
    def run(self):
        logger.info("🚀 Starting bot...")
        
        while True:
            try:
                df = self.fetch_candles(limit=50)
                if df is None or len(df) < 5:
                    logger.warning("⚠️ Insufficient data")
                    time.sleep(60)
                    continue
                
                current_time = df['time'].iloc[-1]
                
                # Skip same candle
                if self.last_candle_time and self.last_candle_time == current_time:
                    time.sleep(30)
                    continue
                
                self.last_candle_time = current_time
                
                # STATE MACHINE
                if self.state == 'IDLE':
                    swing = self.find_swing_low(df)
                    if swing:
                        idx, price = swing
                        logger.info(f"📍 Swing low @ ${price:.2f}")
                        self.on_buy(price, df)
                
                elif self.state == 'LONG':
                    swing = self.find_swing_high(df)
                    if swing:
                        idx, price = swing
                        logger.info(f"📍 Swing high @ ${price:.2f}")
                        self.on_sell(price, df)
                
                price = df['c'].iloc[-1]
                logger.info(f"Price: ${price:.2f} | State: {self.state} | Balance: ${self.balance:.2f}")
                
                time.sleep(60)
                
            except Exception as e:
                logger.error(f"❌ Error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(60)

if __name__ == '__main__':
    bot = TradingBotProduction()
    bot.run()
