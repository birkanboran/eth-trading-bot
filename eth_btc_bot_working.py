#!/usr/bin/env python3
"""Working Trading Bot - Improved Swing Detection"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone

import ccxt
import pandas as pd
from telegram import Bot

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger(__name__)

class WorkingBot:
    def __init__(self):
        self.exchange = ccxt.bybit({
            'apiKey': os.getenv('BYBIT_API_KEY', 'CPSkGJlpunApHRWmIu'),
            'secret': os.getenv('BYBIT_SECRET_KEY', 'wrfqLrR74nZRsT02p6F4fAHwlqtvJvWFnDDA'),
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        
        self.telegram = Bot(token=os.getenv('TELEGRAM_TOKEN', '8993995766:AAGxfrHRnL-9VxBUjOJXA__9BaAVMgD4ndU'))
        self.chat_id = '851788804'
        
        self.pairs = {'ETH': 'ETH/USDT:USDT', 'BTC': 'BTC/USDT:USDT'}
        self.leverage = 5
        self.risk_pct = 1
        self.balance = 100
        self.daily_pnl = 0
        self.positions = {}
        self.last_signals = {}
        self.load_state()
        logger.info("✅ Bot started")
    
    def load_state(self):
        try:
            if os.path.exists('/home/ubuntu/working_bot_state.json'):
                with open('/home/ubuntu/working_bot_state.json', 'r') as f:
                    data = json.load(f)
                    self.balance = data.get('balance', 100)
                    self.daily_pnl = data.get('daily_pnl', 0)
                    self.positions = data.get('positions', {})
        except:
            pass
    
    def save_state(self):
        data = {'balance': self.balance, 'daily_pnl': self.daily_pnl, 'positions': self.positions}
        with open('/home/ubuntu/working_bot_state.json', 'w') as f:
            json.dump(data, f)
    
    def fetch_candles(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, '15m', limit=100)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            return df
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return None
    
    async def send(self, msg):
        try:
            await self.telegram.send_message(chat_id=self.chat_id, text=msg)
        except Exception as e:
            logger.error(f"Send error: {e}")
    
    def find_swing_low(self, df):
        """Find swing low with improved detection"""
        if len(df) < 5:
            return None
        
        # Check last 5 candles for lowest low
        recent = df.tail(5)
        lowest_idx = recent['l'].idxmin()
        lowest_price = df.loc[lowest_idx, 'l']
        
        # Check if it's lower than surrounding candles
        if lowest_idx > 0 and lowest_idx < len(df) - 1:
            if df.loc[lowest_idx, 'l'] < df.loc[lowest_idx-1, 'l'] and df.loc[lowest_idx, 'l'] < df.loc[lowest_idx+1, 'l']:
                return lowest_price
        
        return None
    
    def find_swing_high(self, df):
        """Find swing high with improved detection"""
        if len(df) < 5:
            return None
        
        # Check last 5 candles for highest high
        recent = df.tail(5)
        highest_idx = recent['h'].idxmax()
        highest_price = df.loc[highest_idx, 'h']
        
        # Check if it's higher than surrounding candles
        if highest_idx > 0 and highest_idx < len(df) - 1:
            if df.loc[highest_idx, 'h'] > df.loc[highest_idx-1, 'h'] and df.loc[highest_idx, 'h'] > df.loc[highest_idx+1, 'h']:
                return highest_price
        
        return None
    
    async def process(self, pair):
        symbol = self.pairs[pair]
        df = self.fetch_candles(symbol)
        if df is None or len(df) < 5:
            return
        
        current_price = df['c'].iloc[-1]
        
        # BUY Signal
        swing_low = self.find_swing_low(df)
        if swing_low and pair not in self.positions:
            if pair not in self.last_signals or self.last_signals[pair] != 'BUY':
                entry = swing_low
                tp = entry * 1.02
                sl = entry * 0.98
                
                risk = self.balance * (self.risk_pct / 100)
                size = risk / (entry - sl)
                notional = size * entry
                
                self.positions[pair] = {'entry': entry, 'tp': tp, 'sl': sl, 'size': size, 'notional': notional}
                self.last_signals[pair] = 'BUY'
                self.save_state()
                
                msg = f"""🟢 BUY {pair}
Entry: ${entry:.2f}
TP: ${tp:.2f} | SL: ${sl:.2f}
Size: {size:.4f} {pair}
Leverage: {self.leverage}x
Balance: ${self.balance:.2f}"""
                await self.send(msg)
                logger.info(f"🟢 BUY {pair} @ ${entry:.2f}")
        
        # SELL Signal
        swing_high = self.find_swing_high(df)
        if swing_high and pair in self.positions:
            if pair not in self.last_signals or self.last_signals[pair] != 'SELL':
                pos = self.positions[pair]
                entry = pos['entry']
                exit_price = swing_high
                
                pnl = (exit_price - entry) * pos['size'] * self.leverage
                pnl_pct = (pnl / self.balance) * 100
                
                if exit_price >= pos['tp']:
                    reason = 'TP ✅'
                elif exit_price <= pos['sl']:
                    reason = 'SL ❌'
                else:
                    reason = 'MARKET'
                
                old_balance = self.balance
                self.balance += pnl
                self.daily_pnl += pnl
                
                del self.positions[pair]
                self.last_signals[pair] = 'SELL'
                self.save_state()
                
                msg = f"""🔴 SELL {pair}
Entry: ${entry:.2f} | Exit: ${exit_price:.2f}
PnL: ${pnl:.2f} ({pnl_pct:.2f}%)
{reason}
Balance: ${old_balance:.2f} → ${self.balance:.2f}
Daily PnL: ${self.daily_pnl:.2f}"""
                await self.send(msg)
                logger.info(f"🔴 SELL {pair} @ ${exit_price:.2f}, PnL ${pnl:.2f}")
    
    async def run(self):
        logger.info("🚀 Running bot...")
        while True:
            try:
                await asyncio.gather(self.process('ETH'), self.process('BTC'))
                logger.info(f"ETH: {self.positions.get('ETH', 'IDLE')} | BTC: {self.positions.get('BTC', 'IDLE')} | Balance: ${self.balance:.2f}")
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error: {e}")
                await asyncio.sleep(60)

async def main():
    bot = WorkingBot()
    await bot.run()

if __name__ == '__main__':
    asyncio.run(main())
