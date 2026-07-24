#!/usr/bin/env python3
import ccxt, pandas as pd, asyncio, json, os
from telegram import Bot
from datetime import datetime, timedelta, timezone

class SmartMoneyBot:
    def __init__(self):
        self.exchange = ccxt.bybit({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
        self.bot = Bot(token='8993995766:AAGxfrHRnL-9VxBUjOJXA__9BaAVMgD4ndU')
        self.chat_id = '851788804'
        self.pairs = {'ETH': 'ETH/USDT:USDT', 'BTC': 'BTC/USDT:USDT'}
        self.leverage = 3
        self.risk_pct = 0.5
        self.balance = 100
        self.daily_pnl = 0
        self.positions = {}
        self.load_state()
    
    def load_state(self):
        try:
            if os.path.exists('/home/ubuntu/smart_money_state.json'):
                with open('/home/ubuntu/smart_money_state.json', 'r') as f:
                    data = json.load(f)
                    self.balance = data.get('balance', 100)
                    self.daily_pnl = data.get('daily_pnl', 0)
                    self.positions = data.get('positions', {})
        except:
            pass
    
    def save_state(self):
        with open('/home/ubuntu/smart_money_state.json', 'w') as f:
            json.dump({'balance': self.balance, 'daily_pnl': self.daily_pnl, 'positions': self.positions}, f)
    
    def get_candles(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, '1h', limit=200)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            return df
        except:
            return None
    
    def detect_smart_money(self, df):
        if len(df) < 50:
            return None
        vol_avg = df['v'].tail(50).mean()
        vol_spike = df['v'].iloc[-1] > vol_avg * 2
        recent_atr = (df['h'] - df['l']).tail(20).mean()
        consolidation = recent_atr < (df['h'] - df['l']).tail(50).mean() * 0.7
        resistance = df['h'].tail(50).max()
        breakout = df['c'].iloc[-1] > resistance * 0.99
        if vol_spike and consolidation and breakout:
            return df['c'].iloc[-1]
        return None
    
    def detect_exit(self, df, entry_price):
        if len(df) < 5:
            return None
        current_price = df['c'].iloc[-1]
        if current_price >= entry_price * 1.03:
            return current_price
        if current_price <= entry_price * 0.98:
            return current_price
        vol_avg = df['v'].tail(20).mean()
        if df['v'].iloc[-1] < vol_avg * 0.5 and current_price < entry_price:
            return current_price
        return None
    
    async def send(self, msg):
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=msg)
        except:
            pass
    
    def get_time(self):
        tz = timezone(timedelta(hours=3))
        return datetime.now(tz).strftime('%H:%M')
    
    async def process_pair(self, pair):
        symbol = self.pairs[pair]
        df = self.get_candles(symbol)
        if df is None or len(df) < 50:
            return
        
        entry = self.detect_smart_money(df)
        if entry and pair not in self.positions:
            tp = entry * 1.03
            sl = entry * 0.98
            risk = self.balance * (self.risk_pct / 100)
            size = risk / (entry - sl)
            
            self.positions[pair] = {
                'entry': entry,
                'tp': tp,
                'sl': sl,
                'size': size
            }
            self.save_state()
            
            msg = f"""🟢 BUY {pair}
Entry: ${entry:.2f}
TP: ${tp:.2f} | SL: ${sl:.2f}
Size: {size:.4f} {pair}
Leverage: {self.leverage}x
Balance: ${self.balance:.2f}
Saat: {self.get_time()}"""
            
            await self.send(msg)
        
        if pair in self.positions:
            exit_price = self.detect_exit(df, self.positions[pair]['entry'])
            if exit_price:
                pos = self.positions[pair]
                entry = pos['entry']
                tp = pos['tp']
                sl = pos['sl']
                size = pos['size']
                
                pnl = (exit_price - entry) * size * self.leverage
                pnl_pct = (pnl / self.balance) * 100
                
                old_balance = self.balance
                self.balance += pnl
                self.daily_pnl += pnl
                
                del self.positions[pair]
                self.save_state()
                
                reason = 'TP ✅' if exit_price >= tp else 'SL ❌'
                
                msg = f"""🔴 SELL {pair}
Entry: ${entry:.2f}
Exit: ${exit_price:.2f}
TP: ${tp:.2f} | SL: ${sl:.2f}
Size: {size:.4f} {pair}

💹 PnL: ${pnl:.2f} ({pnl_pct:.2f}%)
{reason}

Balance: ${old_balance:.2f} → ${self.balance:.2f}
Daily PnL: ${self.daily_pnl:.2f}
Saat: {self.get_time()}"""
                
                await self.send(msg)
    
    async def run(self):
        while True:
            try:
                await asyncio.gather(self.process_pair('ETH'), self.process_pair('BTC'))
                await asyncio.sleep(300)
            except:
                await asyncio.sleep(300)

asyncio.run(SmartMoneyBot().run())
