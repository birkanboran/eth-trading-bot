#!/usr/bin/env python3
"""
ETH/USDT Perpetual Trading Bot - Swing High/Low Strategy
5x leverage, 1% risk per trade, Bybit API, Telegram signals
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import traceback

import ccxt
import pandas as pd
import numpy as np
import requests
from telegram import Bot
from telegram.error import TelegramError

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('/home/ubuntu/bot_swing_5x.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SwingTradingBot:
    def __init__(self):
        self.bybit_api_key = os.getenv('BYBIT_API_KEY', 'CPSkGJlpunApHRWmIu')
        self.bybit_secret = os.getenv('BYBIT_SECRET_KEY', 'wrfqLrR74nZRsT02p6F4fAHwlqtvJvWFnDDA')
        self.telegram_token = os.getenv('TELEGRAM_TOKEN', '8993995766:AAGxfrHRnL-9VxBUjOJXA__9BaAVMgD4ndU')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '851788804')
        
        self.exchange = ccxt.bybit({
            'apiKey': self.bybit_api_key,
            'secret': self.bybit_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        
        self.telegram_bot = Bot(token=self.telegram_token)
        self.symbol = 'ETH/USDT:USDT'
        self.timeframe = '15m'
        self.leverage = 5
        self.risk_percent = 1
        self.initial_capital = 100
        
        # State tracking
        self.last_signal = None
        self.active_position = None
        self.balance = self.initial_capital
        self.daily_pnl = 0
        self.weekly_pnl = 0
        self.monthly_pnl = 0
        self.trade_count = 0
        
        self.stats_file = '/home/ubuntu/bot_swing_5x_stats.json'
        self.trades_file = '/home/ubuntu/bot_swing_5x_trades.json'
        self.load_stats()
        
        logger.info("Bot initialized - Swing High/Low Strategy (5x leverage)")
    
    def load_stats(self):
        """Load trading statistics"""
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, 'r') as f:
                    stats = json.load(f)
                    self.balance = stats.get('balance', self.initial_capital)
                    self.daily_pnl = stats.get('daily_pnl', 0)
                    self.weekly_pnl = stats.get('weekly_pnl', 0)
                    self.monthly_pnl = stats.get('monthly_pnl', 0)
                    self.trade_count = stats.get('trade_count', 0)
            except:
                pass
    
    def save_stats(self):
        """Save trading statistics"""
        stats = {
            'balance': self.balance,
            'daily_pnl': self.daily_pnl,
            'weekly_pnl': self.weekly_pnl,
            'monthly_pnl': self.monthly_pnl,
            'trade_count': self.trade_count,
            'timestamp': datetime.now().isoformat()
        }
        with open(self.stats_file, 'w') as f:
            json.dump(stats, f, indent=2)
    
    def save_trade(self, trade_data):
        """Save trade to file"""
        trades = []
        if os.path.exists(self.trades_file):
            try:
                with open(self.trades_file, 'r') as f:
                    trades = json.load(f)
            except:
                pass
        
        trades.append(trade_data)
        with open(self.trades_file, 'w') as f:
            json.dump(trades, f, indent=2)
    
    def fetch_ohlcv(self, limit: int = 100) -> pd.DataFrame:
        """Fetch OHLCV data from Bybit"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"Error fetching OHLCV: {e}")
            return None
    
    def find_swing_points(self, df: pd.DataFrame, window: int = 2) -> Tuple[List[int], List[int]]:
        """Find swing lows (BUY) and swing highs (SELL)"""
        swing_lows = []
        swing_highs = []
        
        for i in range(window, len(df) - window):
            if df['low'].iloc[i] == df['low'].iloc[i-window:i+window+1].min():
                swing_lows.append(i)
            
            if df['high'].iloc[i] == df['high'].iloc[i-window:i+window+1].max():
                swing_highs.append(i)
        
        return swing_lows, swing_highs
    
    def calculate_position_size(self, entry_price: float, sl_price: float) -> float:
        """Calculate position size based on risk management"""
        risk_amount = self.balance * (self.risk_percent / 100)
        price_diff = abs(entry_price - sl_price)
        
        if price_diff == 0:
            return 0
        
        position_size = risk_amount / price_diff
        return position_size
    
    def generate_signal(self, df: pd.DataFrame) -> Optional[Dict]:
        """Generate trading signal at swing points"""
        if len(df) < 10:
            return None
        
        swing_lows, swing_highs = self.find_swing_points(df, window=2)
        
        if not swing_lows and not swing_highs:
            return None
        
        all_swings = sorted([(i, 'LOW' if i in swing_lows else 'HIGH') 
                            for i in swing_lows + swing_highs])
        
        if not all_swings:
            return None
        
        last_swing_idx, swing_type = all_swings[-1]
        
        # BUY Signal: Swing Low
        if swing_type == 'LOW' and self.last_signal != 'BUY':
            entry_price = df['low'].iloc[last_swing_idx]
            
            # Calculate SL (2% below entry)
            sl_price = entry_price * 0.98
            
            # Calculate TP (2% above entry)
            tp_price = entry_price * 1.02
            
            # Calculate position size
            position_size = self.calculate_position_size(entry_price, sl_price)
            
            # Calculate notional value
            notional = position_size * entry_price
            
            return {
                'signal': 'BUY',
                'entry_price': entry_price,
                'tp_price': tp_price,
                'sl_price': sl_price,
                'position_size': position_size,
                'notional': notional,
                'leverage': self.leverage,
                'risk_percent': self.risk_percent,
                'timestamp': datetime.now().isoformat()
            }
        
        # SELL Signal: Swing High
        elif swing_type == 'HIGH' and self.last_signal != 'SELL' and self.active_position:
            exit_price = df['high'].iloc[last_swing_idx]
            
            # Calculate PnL
            entry = self.active_position['entry_price']
            pnl = (exit_price - entry) * self.active_position['position_size'] * self.leverage
            pnl_percent = (pnl / self.balance) * 100
            
            # Determine if closed by TP or SL
            if exit_price >= self.active_position['tp_price']:
                close_reason = 'TP'
            elif exit_price <= self.active_position['sl_price']:
                close_reason = 'SL'
            else:
                close_reason = 'MARKET'
            
            # Update balance and stats
            self.balance += pnl
            self.daily_pnl += pnl
            self.weekly_pnl += pnl
            self.monthly_pnl += pnl
            self.trade_count += 1
            
            return {
                'signal': 'SELL',
                'entry_price': entry,
                'exit_price': exit_price,
                'tp_price': self.active_position['tp_price'],
                'sl_price': self.active_position['sl_price'],
                'position_size': self.active_position['position_size'],
                'leverage': self.leverage,
                'pnl': round(pnl, 2),
                'pnl_percent': round(pnl_percent, 2),
                'close_reason': close_reason,
                'balance': round(self.balance, 2),
                'timestamp': datetime.now().isoformat()
            }
        
        return None
    
    def send_buy_signal(self, signal_data: Dict):
        """Send BUY signal to Telegram"""
        try:
            message = f"""
🟢 **BUY SIGNAL - ETH/USDT**

📍 Entry: ${signal_data['entry_price']:.2f}
🎯 TP: ${signal_data['tp_price']:.2f}
🛑 SL: ${signal_data['sl_price']:.2f}

📊 Position Size: {signal_data['position_size']:.4f} ETH
💰 Notional: ${signal_data['notional']:.2f}
⚡ Leverage: {signal_data['leverage']}x
⚠️ Risk: {signal_data['risk_percent']}%

💵 Current Balance: ${self.balance:.2f}

🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """
            self.telegram_bot.send_message(chat_id=self.telegram_chat_id, text=message)
            logger.info(f"BUY signal sent: Entry ${signal_data['entry_price']:.2f}")
            
            self.active_position = signal_data
            self.last_signal = 'BUY'
            self.save_stats()
            
        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
    
    def send_sell_signal(self, signal_data: Dict):
        """Send SELL signal to Telegram"""
        try:
            close_emoji = '✅' if signal_data['close_reason'] == 'TP' else '❌'
            
            message = f"""
🔴 **SELL SIGNAL - ETH/USDT**

📍 Entry: ${signal_data['entry_price']:.2f}
📍 Exit: ${signal_data['exit_price']:.2f}
🎯 TP: ${signal_data['tp_price']:.2f}
🛑 SL: ${signal_data['sl_price']:.2f}

💹 PnL: ${signal_data['pnl']} ({signal_data['pnl_percent']}%)
{close_emoji} Closed by: {signal_data['close_reason']}

📊 Position Size: {signal_data['position_size']:.4f} ETH
⚡ Leverage: {signal_data['leverage']}x

💵 Balance: ${signal_data['balance']}
📈 Total Trades: {self.trade_count}
📊 Daily PnL: ${self.daily_pnl:.2f}

🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """
            self.telegram_bot.send_message(chat_id=self.telegram_chat_id, text=message)
            logger.info(f"SELL signal sent: Exit ${signal_data['exit_price']:.2f}, PnL ${signal_data['pnl']}")
            
            self.save_trade(signal_data)
            self.active_position = None
            self.last_signal = 'SELL'
            self.save_stats()
            
        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
    
    def run(self):
        """Main bot loop"""
        logger.info("Starting bot loop...")
        
        while True:
            try:
                # Fetch latest data
                df = self.fetch_ohlcv(limit=100)
                if df is None or len(df) < 10:
                    logger.warning("Insufficient data, retrying...")
                    time.sleep(60)
                    continue
                
                # Generate signal
                signal = self.generate_signal(df)
                
                if signal:
                    if signal['signal'] == 'BUY':
                        self.send_buy_signal(signal)
                    elif signal['signal'] == 'SELL':
                        self.send_sell_signal(signal)
                
                # Log current state
                current = df.iloc[-1]
                logger.info(f"Price: ${current['close']:.2f} | Balance: ${self.balance:.2f}")
                
                # Wait for next candle
                time.sleep(60)
                
            except Exception as e:
                logger.error(f"Error in bot loop: {e}")
                logger.error(traceback.format_exc())
                time.sleep(60)

if __name__ == '__main__':
    bot = SwingTradingBot()
    bot.run()
