#!/usr/bin/env python3
"""Complete Trading Bot - All Signal Details"""

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

class CompleteBot:
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
        self.load_state()
    
    def load_state(self):
        try:
            if os.path.exists('/home/ubuntu/complete_bot_state.json'):
                with open('/home/ubuntu/complete_bot_state.json', 'r') as f:
                    data = json.load(f)
                    self.balance = data.get('balance', 100)
                    self.daily_pnl = data.get('daily_pnl', 0)
                    self.positions = data.get('positions', {})
        except:
            pass
    
    def save_state(self):
        data = {
            'balance': self.balance,
            'daily_pnl': self.daily_pnl,
            'positions': self.positions
        }
        with open('/home/ubuntu/complete_bot_state.json', 'w') as f:
            json.dump(data, f)
    
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
            logger.info("✅ Telegram sent")
        except Exception as e:
            logger.error(f"Telegram error: {e}")
    
    async def process(self, pair):
        symbol = self.pairs[pair]
        df = self.fetch_candles(symbol)
        if df is None or len(df) < 3:
            return
        
        # Swing Low = BUY
        if df['l'].iloc[-1] < df['l'].iloc[-2] and df['l'].iloc[-1] < df['l'].iloc[-3]:
            if pair not in self.positions:
                entry = df['l'].iloc[-1]
                tp = entry * 1.02
                sl = entry * 0.98
                
                # Position size calculation
                risk = self.balance * (self.risk_pct / 100)
                size = risk / (entry - sl)
                notional = size * entry
                
                self.positions[pair] = {
                    'entry': entry,
                    'tp': tp,
                    'sl': sl,
                    'size': size,
                    'notional': notional
                }
                self.save_state()
                
                msg = f"""
🟢 **BUY {pair}/USDT**

📍 Entry: ${entry:.2f}
🎯 TP: ${tp:.2f} (+2%)
🛑 SL: ${sl:.2f} (-2%)

📊 Size: {size:.4f} {pair}
💰 Notional: ${notional:.2f}
⚡ Leverage: {self.leverage}x
⚠️ Risk: {self.risk_pct}%

💵 Balance: ${self.balance:.2f}
📊 Daily PnL: ${self.daily_pnl:.2f}

🕐 {datetime.now(timezone.utc).strftime('%H:%M UTC')}
                """
                await self.send(msg)
                logger.info(f"🟢 BUY {pair} @ ${entry:.2f}")
        
        # Swing High = SELL
        if df['h'].iloc[-1] > df['h'].iloc[-2] and df['h'].iloc[-1] > df['h'].iloc[-3]:
            if pair in self.positions:
                pos = self.positions[pair]
                entry = pos['entry']
                exit_price = df['h'].iloc[-1]
                
                # PnL calculation
                pnl = (exit_price - entry) * pos['size'] * self.leverage
                pnl_pct = (pnl / self.balance) * 100
                
                # Determine close reason
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
                self.save_state()
                
                msg = f"""
🔴 **SELL {pair}/USDT**

📍 Entry: ${entry:.2f}
📍 Exit: ${exit_price:.2f}
🎯 TP: ${pos['tp']:.2f}
🛑 SL: ${pos['sl']:.2f}

💹 PnL: ${pnl:.2f} ({pnl_pct:.2f}%)
{reason}

📊 Size: {pos['size']:.4f} {pair}
⚡ Leverage: {self.leverage}x

💵 Balance: ${old_balance:.2f} → ${self.balance:.2f}
📊 Daily PnL: ${self.daily_pnl:.2f}

🕐 {datetime.now(timezone.utc).strftime('%H:%M UTC')}
                """
                await self.send(msg)
                logger.info(f"🔴 SELL {pair} @ ${exit_price:.2f}, PnL ${pnl:.2f}")
    
    async def run(self):
        logger.info("🚀 Starting Complete Bot...")
        while True:
            try:
                await asyncio.gather(
                    self.process('ETH'),
                    self.process('BTC')
                )
                logger.info(f"Balance: ${self.balance:.2f} | Daily PnL: ${self.daily_pnl:.2f}")
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await asyncio.sleep(60)

async def main():
    bot = CompleteBot()
    await bot.run()

if __name__ == '__main__':
    asyncio.run(main())
