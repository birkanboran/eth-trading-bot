#!/usr/bin/env python3
"""
ETH + BTC Perpetual Trading Bot
- Trades both ETH/USDT and BTC/USDT simultaneously
- Separate state machines for each pair
- Combined balance tracking
"""

import os
import json
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
        logging.FileHandler('/home/ubuntu/bot_dual.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class DualTradingBot:
    def __init__(self):
        self.exchange = ccxt.bybit({
            'apiKey': os.getenv('BYBIT_API_KEY', 'CPSkGJlpunApHRWmIu'),
            'secret': os.getenv('BYBIT_SECRET_KEY', 'wrfqLrR74nZRsT02p6F4fAHwlqtvJvWFnDDA'),
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        
        self.telegram = Bot(token=os.getenv('TELEGRAM_TOKEN', '8993995766:AAGxfrHRnL-9VxBUjOJXA__9BaAVMgD4ndU'))
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID', '851788804')
        
        # Pairs
        self.pairs = {
            'ETH': {'symbol': 'ETH/USDT:USDT', 'state': 'IDLE', 'position': None, 'last_candle': None},
            'BTC': {'symbol': 'BTC/USDT:USDT', 'state': 'IDLE', 'position': None, 'last_candle': None}
        }
        
        # Global params
        self.leverage = 5
        self.risk_pct = 1
        self.balance = 100
        self.daily_pnl = 0
        self.timeframe = '15m'
        
        self.load_state()
        logger.info("✅ Dual Bot (ETH + BTC) initialized")
    
    def get_utc(self):
        return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    def load_state(self):
        try:
            if os.path.exists('/home/ubuntu/bot_dual_state.json'):
                with open('/home/ubuntu/bot_dual_state.json', 'r') as f:
                    data = json.load(f)
                    self.balance = data.get('balance', 100)
                    self.daily_pnl = data.get('daily_pnl', 0)
                    self.pairs = data.get('pairs', self.pairs)
                    logger.info(f"✅ Loaded: balance=${self.balance:.2f}")
        except Exception as e:
            logger.warning(f"⚠️ State load error: {e}")
    
    def save_state(self):
        data = {
            'balance': self.balance,
            'daily_pnl': self.daily_pnl,
            'pairs': self.pairs,
            'timestamp': self.get_utc()
        }
        with open('/home/ubuntu/bot_dual_state.json', 'w') as f:
            json.dump(data, f, indent=2)
    
    def fetch_candles(self, symbol: str, limit=50) -> Optional[pd.DataFrame]:
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, self.timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['time', 'o', 'h', 'l', 'c', 'v'])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"Fetch error ({symbol}): {e}")
            return None
    
    async def send_msg(self, msg: str):
        try:
            await self.telegram.send_message(chat_id=self.chat_id, text=msg)
            logger.info("✅ Telegram sent")
        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
    
    def find_swing_low(self, df) -> Optional[Tuple[int, float]]:
        if len(df) < 5:
            return None
        i = len(df) - 1
        current = df['l'].iloc[i]
        if i >= 2:
            prev_lows = df['l'].iloc[max(0, i-2):i]
            if len(prev_lows) > 0 and current < prev_lows.min():
                return i, current
        return None
    
    def find_swing_high(self, df) -> Optional[Tuple[int, float]]:
        if len(df) < 5:
            return None
        i = len(df) - 1
        current = df['h'].iloc[i]
        if i >= 2:
            prev_highs = df['h'].iloc[max(0, i-2):i]
            if len(prev_highs) > 0 and current > prev_highs.max():
                return i, current
        return None
    
    async def on_buy(self, pair: str, entry: float):
        if self.pairs[pair]['state'] != 'IDLE':
            logger.warning(f"⚠️ {pair} not IDLE, ignoring BUY")
            return
        
        tp = entry * 1.02
        sl = entry * 0.98
        
        risk = self.balance * (self.risk_pct / 100)
        size = risk / (entry - sl)
        notional = size * entry
        
        self.pairs[pair]['position'] = {
            'entry': entry,
            'tp': tp,
            'sl': sl,
            'size': size,
            'notional': notional,
            'entry_time': self.get_utc()
        }
        self.pairs[pair]['state'] = 'LONG'
        self.save_state()
        
        msg = f"""
🟢 **BUY SIGNAL - {pair}/USDT**

📍 Entry: ${entry:.2f}
🎯 TP: ${tp:.2f} (+2%)
🛑 SL: ${sl:.2f} (-2%)

📊 Size: {size:.4f} {pair}
💰 Notional: ${notional:.2f}
⚡ Leverage: {self.leverage}x
⚠️ Risk: {self.risk_pct}%

💵 Balance: ${self.balance:.2f}

🕐 {self.pairs[pair]['position']['entry_time']}
        """
        await self.send_msg(msg)
        logger.info(f"🟢 {pair} BUY @ ${entry:.2f}")
    
    async def on_sell(self, pair: str, exit_price: float):
        if self.pairs[pair]['state'] != 'LONG' or not self.pairs[pair]['position']:
            logger.warning(f"⚠️ {pair} no position, ignoring SELL")
            return
        
        pos = self.pairs[pair]['position']
        entry = pos['entry']
        pnl = (exit_price - entry) * pos['size'] * self.leverage
        pnl_pct = (pnl / self.balance) * 100
        
        if exit_price >= pos['tp']:
            reason = 'TP ✅'
        elif exit_price <= pos['sl']:
            reason = 'SL ❌'
        else:
            reason = 'MARKET'
        
        old_bal = self.balance
        self.balance += pnl
        self.daily_pnl += pnl
        
        self.pairs[pair]['position'] = None
        self.pairs[pair]['state'] = 'IDLE'
        self.save_state()
        
        msg = f"""
🔴 **SELL SIGNAL - {pair}/USDT**

📍 Entry: ${entry:.2f}
📍 Exit: ${exit_price:.2f}
🎯 TP: ${pos['tp']:.2f}
🛑 SL: ${pos['sl']:.2f}

💹 PnL: ${pnl:.2f} ({pnl_pct:.2f}%)
{reason}

📊 Size: {pos['size']:.4f} {pair}
⚡ Leverage: {self.leverage}x

💵 Balance: ${old_bal:.2f} → ${self.balance:.2f}
📊 Daily PnL: ${self.daily_pnl:.2f}

🕐 {self.get_utc()}
        """
        await self.send_msg(msg)
        logger.info(f"🔴 {pair} SELL @ ${exit_price:.2f}, PnL ${pnl:.2f}")
    
    async def process_pair(self, pair: str):
        """Process single pair"""
        symbol = self.pairs[pair]['symbol']
        
        df = self.fetch_candles(symbol, limit=50)
        if df is None or len(df) < 5:
            return
        
        current_time = df['time'].iloc[-1]
        
        # Skip same candle
        if self.pairs[pair]['last_candle'] and self.pairs[pair]['last_candle'] == current_time:
            return
        
        self.pairs[pair]['last_candle'] = current_time
        
        # STATE MACHINE
        if self.pairs[pair]['state'] == 'IDLE':
            swing = self.find_swing_low(df)
            if swing:
                idx, price = swing
                logger.info(f"📍 {pair} Swing low @ ${price:.2f}")
                await self.on_buy(pair, price)
        
        elif self.pairs[pair]['state'] == 'LONG':
            swing = self.find_swing_high(df)
            if swing:
                idx, price = swing
                logger.info(f"📍 {pair} Swing high @ ${price:.2f}")
                await self.on_sell(pair, price)
        
        price = df['c'].iloc[-1]
        logger.info(f"{pair}: ${price:.2f} | State: {self.pairs[pair]['state']}")
    
    async def run(self):
        logger.info("🚀 Starting Dual Bot (ETH + BTC)...")
        
        while True:
            try:
                # Process both pairs in parallel
                await asyncio.gather(
                    self.process_pair('ETH'),
                    self.process_pair('BTC')
                )
                
                logger.info(f"Balance: ${self.balance:.2f} | Daily PnL: ${self.daily_pnl:.2f}")
                
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"❌ Error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await asyncio.sleep(60)

async def main():
    bot = DualTradingBot()
    await bot.run()

if __name__ == '__main__':
    asyncio.run(main())
