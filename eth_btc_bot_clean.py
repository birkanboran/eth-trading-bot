#!/usr/bin/env python3
"""Clean ETH + BTC Bot - Simple Signal Format"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone

import ccxt
import pandas as pd
from telegram import Bot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CleanBot:
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
        self.positions = {}
        self.load_state()
    
    def load_state(self):
        try:
            if os.path.exists('/home/ubuntu/clean_bot_state.json'):
                with open('/home/ubuntu/clean_bot_state.json', 'r') as f:
                    self.positions = json.load(f)
        except:
            pass
    
    def save_state(self):
        with open('/home/ubuntu/clean_bot_state.json', 'w') as f:
            json.dump(self.positions, f)
    
    def fetch_candles(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, '15m', limit=50)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            return df
        except:
            return None
    
    async def send(self, msg):
        try:
            await self.telegram.send_message(chat_id=self.chat_id, text=msg)
        except:
            pass
    
    async def process(self, pair):
        symbol = self.pairs[pair]
        df = self.fetch_candles(symbol)
        if df is None or len(df) < 3:
            return
        
        # Swing Low = BUY
        if df['l'].iloc[-1] < df['l'].iloc[-2] and df['l'].iloc[-1] < df['l'].iloc[-3]:
            if pair not in self.positions:
                price = df['l'].iloc[-1]
                self.positions[pair] = {'entry': price, 'type': 'LONG'}
                self.save_state()
                
                msg = f"🟢 BUY {pair}\nPrice: ${price:.2f}"
                await self.send(msg)
                logger.info(f"BUY {pair} @ ${price:.2f}")
        
        # Swing High = SELL
        if df['h'].iloc[-1] > df['h'].iloc[-2] and df['h'].iloc[-1] > df['h'].iloc[-3]:
            if pair in self.positions:
                entry = self.positions[pair]['entry']
                exit_price = df['h'].iloc[-1]
                pnl = exit_price - entry
                pnl_pct = (pnl / entry) * 100
                
                del self.positions[pair]
                self.save_state()
                
                msg = f"🔴 SELL {pair}\nEntry: ${entry:.2f}\nExit: ${exit_price:.2f}\nPnL: ${pnl:.2f} ({pnl_pct:.1f}%)"
                await self.send(msg)
                logger.info(f"SELL {pair} @ ${exit_price:.2f}, PnL ${pnl:.2f}")
    
    async def run(self):
        logger.info("Starting Clean Bot...")
        while True:
            try:
                await asyncio.gather(
                    self.process('ETH'),
                    self.process('BTC')
                )
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error: {e}")
                await asyncio.sleep(60)

async def main():
    bot = CleanBot()
    await bot.run()

if __name__ == '__main__':
    asyncio.run(main())
