# Binance ETH/BTC Futures Trading Bot - Production v2

**Strategy:** Volume Spike Detection on 1-hour candles

## Critical Security Features

✅ **LIVE_TRADING Lock** - No real orders without `LIVE_TRADING=true`
✅ **DRY_RUN Mode** - Logs orders without executing
✅ **One-Way Mode Only** - Rejects hedge mode on startup
✅ **Position Sync** - Reads real Binance positions every cycle
✅ **Decimal Rounding** - Prevents precision errors
✅ **TP/SL Critical** - Closes position if either fails
✅ **Margin Validation** - Checks required margin before order
✅ **Candle Deduplication** - Prevents duplicate signals

## Features

- **Risk Calculation:** `position_size = (balance * risk%) / (entry - SL)`
- **Margin Check:** `required_margin = (size * entry) / leverage`
- **Order Confirmation:** Queries orderId for real avgPrice and executedQty
- **TP/SL Recalculation:** Uses real execution price
- **Min Notional:** Validated with mark price
- **Persistent State:** Tracks last processed candle to prevent duplicates
- **Full Sync:** Every cycle reads Binance positions and open orders

## Setup

### 1. Binance API Key

https://www.binance.com/en/account/api-management

Requirements:
- Spot Trading: Enabled
- Futures Trading: Enabled
- IP Whitelist: No restriction
- Withdraw: DISABLED

### 2. Telegram Bot

Message @BotFather on Telegram:
- /newbot → Copy token
- Message your bot
- Get Chat ID from @userinfobot

### 3. Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 4. Install

```bash
pip install -r requirements.txt
```

### 5. Run

**Testnet (Safe):**
```bash
BINANCE_TESTNET=true DRY_RUN=true python bot.py
```

**Live Trading:**
```bash
BINANCE_TESTNET=false LIVE_TRADING=true python bot.py
```

## Configuration

Edit .env:

```
LEVERAGE=5              # 1-125x
RISK_PERCENT=1          # % of balance per trade
TP_PERCENT=3            # Take-profit %
SL_PERCENT=2            # Stop-loss %
VOLUME_MULTIPLIER=2     # Spike threshold
VOLUME_PERIOD=50        # Candles for average
```

## Strategy

### Volume Spike Detection
- Monitors 1-hour candle volumes
- Triggers when: volume > avg(last 50) * 2
- Uses last CLOSED candle (not current)

### Position Management
- Risk: 1% of balance per trade
- Position Size: (balance * 1%) / (entry - SL)
- TP: Entry + 3%
- SL: Entry - 2%
- Leverage: 5x

### Order Flow
1. Validate position mode (one-way only)
2. Sync with Binance
3. Check volume spike
4. Calculate position size
5. Validate margin
6. Place BUY market order
7. Query orderId for real execution data
8. Recalculate TP/SL with real entry
9. Place TP (TAKE_PROFIT_MARKET) order
10. Place SL (STOP_MARKET) order
11. If either TP/SL fails → Cancel successful one → Close position
12. Save candle time to prevent duplicates

## Safety Checks

Position Mode: One-way only (rejects hedge mode)
Leverage: Validates set_leverage() success
Margin: Checks required < available
Quantity: Validates min/max qty
Notional: Validates with mark price
Order Execution: Confirms avgPrice and qty > 0
TP/SL: Both must succeed or position closes
Critical Error: Halts bot if close fails

## Monitoring

Bot logs:
- Position sync status
- Volume spike signals
- Order confirmations
- TP/SL placement
- Critical errors

## Testing

```bash
python test_bot.py -v
```

Tests:
- Risk calculation
- Quantity rounding (Decimal)
- Price rounding (tickSize)
- TP/SL calculation
- Security locks

## GitHub Actions

Runs every 5 minutes via cron:
```
schedule:
  - cron: '*/5 * * * *'
```

Requires GitHub Secrets:
- BINANCE_API_KEY
- BINANCE_SECRET_KEY
- TELEGRAM_TOKEN
- TELEGRAM_CHAT_ID

## Troubleshooting

**"Hedge Mode detected"**
- Bot only supports one-way mode
- Change Binance to one-way mode

**"Insufficient margin"**
- Increase balance or reduce risk %
- Check leverage setting

**"Order rejected"**
- Verify quantity meets LOT_SIZE
- Check notional value
- Ensure price is valid

**"TP/SL failed"**
- Bot closes position immediately
- Check Telegram for alert
- Verify Binance balance

## Disclaimer

⚠️ This bot trades with real money. Use at your own risk.

- Test on testnet first
- Start with small positions
- Monitor regularly
- Understand the strategy
- Never share API keys
- Keep LIVE_TRADING=false until confident

## License

MIT
