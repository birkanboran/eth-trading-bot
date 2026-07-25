# Binance ETH/BTC Futures Trading Bot

**Strategy:** Volume Spike Detection on 1-hour candles

## Features

- ✅ **Sync with Binance** - Reads open positions on startup
- ✅ **Proper Rounding** - Decimal-based quantity and price rounding
- ✅ **Real TP/SL Orders** - Take-Profit and Stop-Loss as Binance orders
- ✅ **Critical Error Handling** - Closes position if TP/SL fails
- ✅ **Hedge Mode Support** - Compatible with both one-way and hedge modes
- ✅ **Min Notional/Quantity** - Validates orders before placing
- ✅ **Testnet by Default** - Safe testing with `BINANCE_TESTNET=true`
- ✅ **Dry-Run Mode** - Logs orders without executing (`DRY_RUN=true`)
- ✅ **Live Trading** - Requires explicit `LIVE_TRADING=true`

## Setup

### 1. Create Binance API Key

1. Go to https://www.binance.com/en/account/api-management
2. Create new API key with:
   - ✅ Spot Trading: Enabled
   - ✅ Futures Trading: Enabled
   - ✅ IP Whitelist: No restriction (or add your IP)
3. Copy API Key and Secret

### 2. Create Telegram Bot

1. Message @BotFather on Telegram
2. Create new bot: `/newbot`
3. Copy the token
4. Message your bot and get Chat ID from @userinfobot

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Run Bot

**Testnet (Safe):**
```bash
BINANCE_TESTNET=true DRY_RUN=true python bot.py
```

**Testnet with Real Orders:**
```bash
BINANCE_TESTNET=true LIVE_TRADING=true python bot.py
```

**Live Trading (Real Money):**
```bash
BINANCE_TESTNET=false LIVE_TRADING=true python bot.py
```

## Strategy Details

### Volume Spike Detection
- Monitors 1-hour candle volumes
- Triggers BUY when volume > 2x average (50-period)
- Uses last **closed** candle (not current)

### Position Management
- **Risk:** 1% of balance per trade
- **Position Size:** `(balance * 1%) / ((entry - SL) * leverage)`
- **TP:** Entry + 3%
- **SL:** Entry - 2%
- **Leverage:** 5x

### Order Flow
1. Place BUY market order
2. Set TP (Take-Profit) order
3. Set SL (Stop-Loss) order
4. If TP/SL fails → Close position immediately
5. Clean up on TP/SL hit

## Configuration

Edit `.env`:

```env
LEVERAGE=5              # 1-125x
RISK_PERCENT=1          # 0.1-10%
TP_PERCENT=3            # Take-profit %
SL_PERCENT=2            # Stop-loss %
VOLUME_MULTIPLIER=2     # Volume spike threshold
VOLUME_PERIOD=50        # Candles for average
```

## Monitoring

Bot logs to console with timestamps. Check for:
- ✅ Position sync on startup
- ✅ Volume spike signals
- ✅ Order placement confirmations
- ✅ TP/SL order status
- ❌ Critical errors (TP/SL failures)

## Safety Checks

1. **Quantity Validation** - Checks min/max qty
2. **Notional Validation** - Checks min notional value
3. **Price Rounding** - Uses Decimal for precision
4. **Leverage Check** - Sets leverage before order
5. **TP/SL Critical** - Closes position if either fails

## Troubleshooting

**"Invalid API-key"**
- Check API key in .env
- Verify Futures Trading enabled
- Check IP whitelist

**"Insufficient balance"**
- Ensure Futures wallet has USDT
- Check position size calculation

**"Order rejected"**
- Verify quantity meets LOT_SIZE
- Check notional value meets minimum
- Ensure price is valid

## GitHub Actions

Bot runs every 5 minutes on GitHub Actions:
- Reads Binance positions
- Checks volume signals
- Places orders automatically
- Sends Telegram notifications

Requires GitHub Secrets:
- `BINANCE_API_KEY`
- `BINANCE_SECRET_KEY`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

## Disclaimer

⚠️ **This bot trades with real money. Use at your own risk.**

- Test on testnet first
- Start with small positions
- Monitor regularly
- Understand the strategy
- Never share API keys

## License

MIT
