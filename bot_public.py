#!/usr/bin/env python3
import ccxt, pandas as pd, asyncio, requests
from telegram import Bot

# Use public API (no auth needed)
exchange = ccxt.bybit({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
bot = Bot(token='8993995766:AAGxfrHRnL-9VxBUjOJXA__9BaAVMgD4ndU')
state = {'ETH': None, 'BTC': None}

async def send(msg):
    try:
        await bot.send_message(chat_id='851788804', text=msg)
        print(f"✅ Sent")
    except Exception as e:
        print(f"❌ {e}")

def get_df(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '15m', limit=50)
        return pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
    except Exception as e:
        print(f"Fetch error: {e}")
        return None

async def trade(pair, symbol):
    global state
    df = get_df(symbol)
    if df is None or len(df) < 3:
        return
    
    buy = df['l'].iloc[-1] < df['l'].iloc[-2] and df['l'].iloc[-1] < df['l'].iloc[-3]
    sell = df['h'].iloc[-1] > df['h'].iloc[-2] and df['h'].iloc[-1] > df['h'].iloc[-3]
    
    if buy and state[pair] is None:
        entry = df['l'].iloc[-1]
        await send(f"🟢 BUY {pair}\n${entry:.2f}")
        state[pair] = entry
        print(f"🟢 BUY {pair}")
    
    elif sell and state[pair]:
        exit = df['h'].iloc[-1]
        await send(f"🔴 SELL {pair}\n${exit:.2f}")
        state[pair] = None
        print(f"🔴 SELL {pair}")

async def main():
    print("🚀 Bot started (public API)")
    while True:
        try:
            await trade('ETH', 'ETH/USDT:USDT')
            await trade('BTC', 'BTC/USDT:USDT')
            print(".", end="", flush=True)
            await asyncio.sleep(60)
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(60)

asyncio.run(main())
