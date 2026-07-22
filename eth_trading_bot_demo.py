#!/usr/bin/env python3
"""
ETH/USDT Trading Bot - Demo Version (Backtesting)
Simulates real trading with complete signal details
"""

import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class DemoTradingBot:
    def __init__(self):
        self.symbol = 'ETH/USDT'
        self.timeframe = '15m'
        self.leverage = 5
        self.risk_percent = 1
        self.initial_capital = 100
        self.balance = self.initial_capital
        
        self.daily_pnl = 0
        self.weekly_pnl = 0
        self.monthly_pnl = 0
        self.trade_count = 0
        
        self.trades = []
        self.load_data()
    
    def load_data(self):
        """Load historical data"""
        self.df = pd.read_csv('/home/ubuntu/eth_bybit_1month.csv')
        self.df['timestamp'] = pd.to_datetime(self.df['timestamp'])
        self.df = self.df.sort_values('timestamp').reset_index(drop=True)
        print(f"✅ Data loaded: {len(self.df)} candles")
    
    def find_swing_points(self, df, window=2):
        """Find swing lows and highs"""
        swing_lows = []
        swing_highs = []
        
        for i in range(window, len(df) - window):
            if df['low'].iloc[i] == df['low'].iloc[i-window:i+window+1].min():
                swing_lows.append(i)
            
            if df['high'].iloc[i] == df['high'].iloc[i-window:i+window+1].max():
                swing_highs.append(i)
        
        return swing_lows, swing_highs
    
    def calculate_position_size(self, entry_price, sl_price):
        """Calculate position size based on risk"""
        risk_amount = self.balance * (self.risk_percent / 100)
        price_diff = abs(entry_price - sl_price)
        
        if price_diff == 0:
            return 0
        
        position_size = risk_amount / price_diff
        return position_size
    
    def backtest(self):
        """Run backtest and generate signals"""
        swing_lows, swing_highs = self.find_swing_points(self.df, window=2)
        
        all_swings = sorted([(i, 'LOW' if i in swing_lows else 'HIGH') 
                            for i in swing_lows + swing_highs])
        
        signals = []
        last_signal = None
        active_position = None
        
        for idx, swing_type in all_swings:
            row = self.df.iloc[idx]
            
            # BUY Signal
            if swing_type == 'LOW' and last_signal != 'BUY':
                entry_price = row['low']
                sl_price = entry_price * 0.98
                tp_price = entry_price * 1.02
                position_size = self.calculate_position_size(entry_price, sl_price)
                notional = position_size * entry_price
                
                signal = {
                    'signal': 'BUY',
                    'timestamp': row['timestamp'].isoformat(),
                    'entry_price': round(entry_price, 2),
                    'tp_price': round(tp_price, 2),
                    'sl_price': round(sl_price, 2),
                    'position_size': round(position_size, 4),
                    'notional': round(notional, 2),
                    'leverage': self.leverage,
                    'risk_percent': self.risk_percent,
                    'balance': round(self.balance, 2)
                }
                signals.append(signal)
                active_position = signal
                last_signal = 'BUY'
            
            # SELL Signal
            elif swing_type == 'HIGH' and last_signal != 'SELL' and active_position:
                exit_price = row['high']
                entry = active_position['entry_price']
                pnl = (exit_price - entry) * active_position['position_size'] * self.leverage
                pnl_percent = (pnl / self.balance) * 100
                
                # Determine close reason
                if exit_price >= active_position['tp_price']:
                    close_reason = 'TP'
                elif exit_price <= active_position['sl_price']:
                    close_reason = 'SL'
                else:
                    close_reason = 'MARKET'
                
                # Update balance
                self.balance += pnl
                self.daily_pnl += pnl
                self.weekly_pnl += pnl
                self.monthly_pnl += pnl
                self.trade_count += 1
                
                signal = {
                    'signal': 'SELL',
                    'timestamp': row['timestamp'].isoformat(),
                    'entry_price': round(entry, 2),
                    'exit_price': round(exit_price, 2),
                    'tp_price': round(active_position['tp_price'], 2),
                    'sl_price': round(active_position['sl_price'], 2),
                    'position_size': round(active_position['position_size'], 4),
                    'leverage': self.leverage,
                    'pnl': round(pnl, 2),
                    'pnl_percent': round(pnl_percent, 2),
                    'close_reason': close_reason,
                    'balance': round(self.balance, 2),
                    'total_trades': self.trade_count,
                    'daily_pnl': round(self.daily_pnl, 2)
                }
                signals.append(signal)
                self.trades.append(signal)
                active_position = None
                last_signal = 'SELL'
        
        return signals
    
    def print_results(self, signals):
        """Print trading results"""
        print("\n" + "="*100)
        print("ETH/USDT TRADING BOT - DEMO BACKTEST RESULTS")
        print("="*100)
        
        print(f"\n📊 Summary:")
        print(f"  Initial Balance: ${self.initial_capital}")
        print(f"  Final Balance: ${self.balance:.2f}")
        print(f"  Total PnL: ${self.balance - self.initial_capital:.2f}")
        print(f"  Return: {((self.balance - self.initial_capital) / self.initial_capital * 100):.2f}%")
        print(f"  Total Trades: {self.trade_count}")
        
        wins = len([t for t in self.trades if t['pnl'] > 0])
        losses = len([t for t in self.trades if t['pnl'] < 0])
        print(f"  Wins: {wins}, Losses: {losses}")
        
        if self.trades:
            print(f"  Win Rate: {(wins / len(self.trades) * 100):.1f}%")
        
        print(f"\n📈 Recent Signals (Last 5):")
        for signal in signals[-5:]:
            if signal['signal'] == 'BUY':
                print(f"\n  🟢 BUY @ ${signal['entry_price']}")
                print(f"     TP: ${signal['tp_price']} | SL: ${signal['sl_price']}")
                print(f"     Size: {signal['position_size']:.4f} ETH | Leverage: {signal['leverage']}x")
            else:
                print(f"\n  🔴 SELL @ ${signal['exit_price']}")
                print(f"     Entry: ${signal['entry_price']} | Exit: ${signal['exit_price']}")
                print(f"     PnL: ${signal['pnl']} ({signal['pnl_percent']}%) - {signal['close_reason']}")
                print(f"     Balance: ${signal['balance']}")
        
        print("\n" + "="*100)
    
    def save_signals(self, signals):
        """Save signals to file"""
        with open('/home/ubuntu/bot_demo_signals.json', 'w') as f:
            json.dump(signals, f, indent=2)
        print(f"\n✅ Signals saved: bot_demo_signals.json ({len(signals)} signals)")

if __name__ == '__main__':
    bot = DemoTradingBot()
    signals = bot.backtest()
    bot.print_results(signals)
    bot.save_signals(signals)
