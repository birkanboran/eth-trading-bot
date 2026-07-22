#!/usr/bin/env python3
"""
ETH/USDT Trading Bot - FINAL VERSION
- Working BUY/SELL signals
- PnL tracking for open positions
- State machine (IDLE -> LONG -> IDLE)
"""

import os
import json
import time
import asyncio
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
        logging.FileHandler('/home/ubuntu/bot_final.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TradingBotFinal:
    def __init__(self):
        self.exchange = ccxt.bybit({
            'apiKey': os.getenv('BYBIT_API_KEY', 'CPSkGJlpunApHRWmIu'),
            'secret': os.getenv('BYBIT_SECRET_KEY', 'wrfqLrR74nZRsT02p6F4fAHwlqtvJvWFnDDA'),
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        
        self.telegram = Bot(token=os.getenv('TELEGRAM_TOKEN', '8993995766:AAGxfrHRnL-9VxBUjOJXA__9BaAVMgD4ndU'))
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID', '851788804')
        
        self.symbol = 'ETH/USDT:USDT'
        self.timeframe = '15m'
        self.leverage = 5
        self.risk_pct = 1
        
        self.state = 'IDLE'
        self.position = None
        self.balance = 100
        self.daily_pnl = 0
        self.last_candle_time = None
        
        self.load_state()
        logger.info("✅ Bot Final initialized")
    
    def get_utc(self):
        return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    def load_state(self):
        try:
            if os.path.exists('/home/ubuntu/bot_final_state.json'):
                with open('/home/ubuntu/bot_final_state.json', 'r') as f:
                    data = json.load(f)
                    self.state = data.get('state', 'IDLE')
                    self.position = data.get('position')
                    self.balance = data.get('balance', 100)
                    self.daily_pnl = data.get('daily_pnl', 0)
                    logger.info(f"✅ Loaded: state={self.state}, balance=${self.balance:.2f}")
        except Exception as e:
            logger.warning(f"⚠️ State load error: {e}")
    
    def save_state(self):
        data = {
            'state': self.state,
            'position': self.position,
            'balance': self.balance,
            'daily_pnl': self.daily_pnl,
            'timestamp': self.get_utc()
        }
        with open('/home/ubuntu/bot_final_state.json', 'w') as f:
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
    
    async def send_msg(self, msg: str):
        try:
            await self.telegram.send_message(chat_id=self.chat_id, text=msg)
            logger.info("✅ Telegram sent")
        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
    
    def find_swing_low(self, df) -> Optional[Tuple[int, float]]:
        """Find swing low (dip) - BUY signal"""
        if len(df) < 5:
            return None
        
        i = len(df) - 1
        current = df['l'].iloc[i]
        
        # Current low is lower than previous 2 candles
        if i >= 2:
            prev_lows = df['l'].iloc[max(0, i-2):i]
            if len(prev_lows) > 0 and current < prev_lows.min():
                return i, current
        
        return None
    
    def find_swing_high(self, df) -> Optional[Tuple[int, float]]:
        """Find swing high (peak) - SELL signal"""
        if len(df) < 5:
            return None
        
        i = len(df) - 1
        current = df['h'].iloc[i]
        
        # Current high is higher than previous 2 candles
        if i >= 2:
            prev_highs = df['h'].iloc[max(0, i-2):i]
            if len(prev_highs) > 0 and current > prev_highs.max():
                return i, current
        
        return None
    
    async def on_buy(self, entry: float, df):
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
            'entry_time': self.get_utc(),
            'entry_price_current': entry
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
        await self.send_msg(msg)
        logger.info(f"🟢 BUY @ ${entry:.2f}")
    
    async def on_sell(self, exit_price: float, df):
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
📊 Daily PnL: ${self.daily_pnl:.2f}

🕐 {self.get_utc()}
        """
        await self.send_msg(msg)
        logger.info(f"🔴 SELL @ ${exit_price:.2f}, PnL ${pnl:.2f}")
    
    async def send_pnl_update(self, current_price: float):
        """Send PnL update for open position"""
        if self.state != 'LONG' or not self.position:
            return
        
        entry = self.position['entry']
        unrealized_pnl = (current_price - entry) * self.position['size'] * self.leverage
        unrealized_pct = (unrealized_pnl / self.balance) * 100
        
        msg = f"""
📊 **POSITION UPDATE - ETH/USDT**

📍 Entry: ${entry:.2f}
📍 Current: ${current_price:.2f}
🎯 TP: ${self.position['tp']:.2f}
🛑 SL: ${self.position['sl']:.2f}

💹 Unrealized PnL: ${unrealized_pnl:.2f} ({unrealized_pct:.2f}%)
📊 Size: {self.position['size']:.4f} ETH
⚡ Leverage: {self.leverage}x

💵 Balance: ${self.balance:.2f}
📊 Daily PnL: ${self.daily_pnl:.2f}

🕐 {self.get_utc()}
        """
        await self.send_msg(msg)
    
    async def run(self):
        logger.info("🚀 Starting bot...")
        
        update_counter = 0
        
        while True:
            try:
                df = self.fetch_candles(limit=50)
                if df is None or len(df) < 5:
                    logger.warning("⚠️ Insufficient data")
                    await asyncio.sleep(60)
                    continue
                
                current_time = df['time'].iloc[-1]
                
                if self.last_candle_time and self.last_candle_time == current_time:
                    await asyncio.sleep(30)
                    continue
                
                self.last_candle_time = current_time
                
                # STATE MACHINE
                if self.state == 'IDLE':
                    swing = self.find_swing_low(df)
                    if swing:
                        idx, price = swing
                        logger.info(f"📍 Swing low @ ${price:.2f}")
                        await self.on_buy(price, df)
                
                elif self.state == 'LONG':
                    swing = self.find_swing_high(df)
                    if swing:
                        idx, price = swing
                        logger.info(f"📍 Swing high @ ${price:.2f}")
                        await self.on_sell(price, df)
                    else:
                        # Send PnL update every 5 iterations
                        update_counter += 1
                        if update_counter >= 5:
                            current_price = df['c'].iloc[-1]
                            await self.send_pnl_update(current_price)
                            update_counter = 0
                
                price = df['c'].iloc[-1]
                logger.info(f"Price: ${price:.2f} | State: {self.state} | Balance: ${self.balance:.2f}")
                
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"❌ Error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await asyncio.sleep(60)

async def main():
    bot = TradingBotFinal()
    await bot.run()

if __name__ == '__main__':
    asyncio.run(main())
