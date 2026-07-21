#!/usr/bin/env python3
"""
ETH/USDT 15m MACD Trading Bot - Production Ready
- Telegram entegrasyonu (retry mekanizması ile)
- Hata yönetimi
- Logging
- Monitoring
"""

import asyncio
import ccxt
import pandas as pd
import numpy as np
import ta
from datetime import datetime, timedelta
import json
import os
import sys
import traceback
from telegram import Bot
from telegram.error import TelegramError, NetworkError, TimedOut

# ============================================================================
# KONFIGÜRASYON
# ============================================================================

TELEGRAM_TOKEN = "8993995766:AAGxfrHRnL-9VxBUjOJXA__9BaAVMgD4ndU"
TELEGRAM_CHAT_ID = 851788804

BINANCE_API_KEY = "xHm7n11BEWojfA4p0NovkVTtoKFvVtjlql5pFCDygrotXsQmxH0cxfEB2plsZDGL"
BINANCE_SECRET = "nencSxZ1zYSCP1qF3s7c7nuUGd0IrfXDcwgCx3qrgwDtY88fqzSKb4098v36rlgd"

INITIAL_BALANCE = 100
RISK_PERCENT = 1
LEVERAGE = 2
TIMEFRAME = "15m"
SYMBOL = "ETH/USDT"

LOG_FILE = "/home/ubuntu/bot_signals.log"
ERROR_LOG_FILE = "/home/ubuntu/bot_errors.log"
STATS_FILE = "/home/ubuntu/bot_stats.json"

# Telegram retry ayarları
TELEGRAM_RETRY_ATTEMPTS = 3
TELEGRAM_RETRY_DELAY = 2  # saniye

# ============================================================================
# GLOBAL VARİABLELER
# ============================================================================

positions = []
daily_pnl = 0
weekly_pnl = 0
monthly_pnl = 0
last_signal = None
trade_log = []
telegram_bot = Bot(token=TELEGRAM_TOKEN)

# ============================================================================
# LOGGING FONKSIYONLARI
# ============================================================================

def log_signal(message, level="INFO"):
    """Sinyali dosyaya ve konsola kaydet"""
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_message = f"[{timestamp}] [{level}] {message}"
        
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_message + "\n")
            f.flush()
        
        print(log_message)
    except Exception as e:
        print(f"[ERROR] Log yazma hatası: {e}")

def log_error(message, exception=None):
    """Hata dosyasına kaydet"""
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        error_message = f"[{timestamp}] {message}"
        
        if exception:
            error_message += f"\n  Exception: {str(exception)}\n  Traceback: {traceback.format_exc()}"
        
        with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(error_message + "\n\n")
            f.flush()
        
        print(f"[ERROR] {message}")
        if exception:
            print(f"  {str(exception)}")
    except Exception as e:
        print(f"[CRITICAL] Hata log yazma hatası: {e}")

# ============================================================================
# TELEGRAM FONKSIYONLARI (RETRY İLE)
# ============================================================================

async def send_telegram_with_retry(message, max_retries=TELEGRAM_RETRY_ATTEMPTS):
    """Telegram'a mesaj gönder - retry mekanizması ile"""
    
    for attempt in range(1, max_retries + 1):
        try:
            await telegram_bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=message,
                parse_mode='HTML',
                connect_timeout=10,
                read_timeout=10
            )
            log_signal(f"✓ Telegram gönderildi (Deneme: {attempt}/{max_retries})", level="TELEGRAM")
            return True
            
        except (NetworkError, TimedOut) as e:
            log_error(f"Telegram ağ hatası (Deneme {attempt}/{max_retries})", e)
            
            if attempt < max_retries:
                wait_time = TELEGRAM_RETRY_DELAY * attempt
                log_signal(f"⏳ {wait_time} saniye sonra yeniden deneniyor...", level="TELEGRAM")
                await asyncio.sleep(wait_time)
            else:
                log_error(f"Telegram gönderimi başarısız ({max_retries} deneme tükendi)", e)
                return False
                
        except TelegramError as e:
            log_error(f"Telegram API hatası: {e}", e)
            return False
            
        except Exception as e:
            log_error(f"Telegram gönderimi beklenmeyen hata: {e}", e)
            return False
    
    return False

# ============================================================================
# BINANCE FONKSIYONLARI
# ============================================================================

def get_exchange():
    """Binance bağlantısı oluştur"""
    try:
        exchange = ccxt.binance({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_SECRET,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
                'testnet': False,
                # Mainnet URLs
            'urls': {
                    'api': {
                        'future': 'https://testnet.binancefuture.com/fapi',
                        'fapiPublic': 'https://testnet.binancefuture.com/fapi/v1',
                        'fapiPrivate': 'https://testnet.binancefuture.com/fapi/v1',
                    }
                }
            }
        })
        log_signal("✓ Binance bağlantısı kuruldu", level="BINANCE")
        return exchange
    except Exception as e:
        log_error("Binance bağlantı hatası", e)
        return None

def get_eth_data(exchange):
    """ETH/USDT verisi al"""
    try:
        candles = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=100)
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        log_error("Veri alma hatası", e)
        return None

def calculate_macd_signal(df):
    """MACD sinyali hesapla"""
    try:
        if len(df) < 26:
            return None
        
        df['close'] = pd.to_numeric(df['close'])
        macd = ta.trend.MACD(df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        
        last_macd = df['macd'].iloc[-1]
        last_signal = df['macd_signal'].iloc[-1]
        prev_macd = df['macd'].iloc[-2]
        prev_signal = df['macd_signal'].iloc[-2]
        
        if prev_macd <= prev_signal and last_macd > last_signal:
            return "BUY"
        
        if prev_macd >= prev_signal and last_macd < last_signal:
            return "SELL"
        
        return None
    except Exception as e:
        log_error("MACD hesaplama hatası", e)
        return None

def calculate_position_size(current_price):
    """Pozisyon boyutu hesapla"""
    try:
        risk_amount = INITIAL_BALANCE * (RISK_PERCENT / 100)
        stop_loss_percent = 0.5
        stop_loss_amount = current_price * (stop_loss_percent / 100)
        
        position_size = risk_amount / stop_loss_amount
        position_size_usdt = position_size * current_price * LEVERAGE
        
        return {
            'size': position_size,
            'usdt': position_size_usdt,
            'risk': risk_amount,
            'sl_percent': stop_loss_percent
        }
    except Exception as e:
        log_error("Pozisyon boyutu hesaplama hatası", e)
        return None

# ============================================================================
# TICARET FONKSİYONLARI
# ============================================================================

async def execute_buy_order(price, position_info):
    """AL emri ver"""
    global positions, trade_log
    
    try:
        tp_price = price * 1.01
        sl_price = price * (1 - position_info['sl_percent']/100)
        
        position = {
            'id': len(positions) + 1,
            'type': 'BUY',
            'entry_price': price,
            'tp_price': tp_price,
            'sl_price': sl_price,
            'size': position_info['size'],
            'entry_time': datetime.now(),
            'status': 'OPEN',
            'pnl': 0,
            'closed_by': None
        }
        
        positions.append(position)
        trade_log.append(position)
        
        message = f"""🟢 <b>AL SİNYALİ</b>
━━━━━━━━━━━━━━━━━━
<b>Zaman:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
<b>Fiyat:</b> ${price:.2f}
<b>TP:</b> ${tp_price:.2f} (+1%)
<b>SL:</b> ${sl_price:.2f} (-0.5%)
<b>Boyut:</b> {position_info['size']:.4f} ETH
<b>Kaldıraç:</b> {LEVERAGE}x
<b>Risk:</b> ${position_info['risk']:.2f}
<b>ID:</b> #{position['id']}"""
        
        log_signal(f"🟢 AL - Fiyat: ${price:.2f} - ID: #{position['id']}", level="SIGNAL")
        await send_telegram_with_retry(message)
        save_stats()
        
    except Exception as e:
        log_error("AL emri hatası", e)

async def execute_sell_order(price, position_info):
    """SAT emri ver"""
    global positions, trade_log
    
    try:
        tp_price = price * 0.99
        sl_price = price * (1 + position_info['sl_percent']/100)
        
        position = {
            'id': len(positions) + 1,
            'type': 'SELL',
            'entry_price': price,
            'tp_price': tp_price,
            'sl_price': sl_price,
            'size': position_info['size'],
            'entry_time': datetime.now(),
            'status': 'OPEN',
            'pnl': 0,
            'closed_by': None
        }
        
        positions.append(position)
        trade_log.append(position)
        
        message = f"""🔴 <b>SAT SİNYALİ</b>
━━━━━━━━━━━━━━━━━━
<b>Zaman:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
<b>Fiyat:</b> ${price:.2f}
<b>TP:</b> ${tp_price:.2f} (-1%)
<b>SL:</b> ${sl_price:.2f} (+0.5%)
<b>Boyut:</b> {position_info['size']:.4f} ETH
<b>Kaldıraç:</b> {LEVERAGE}x
<b>Risk:</b> ${position_info['risk']:.2f}
<b>ID:</b> #{position['id']}"""
        
        log_signal(f"🔴 SAT - Fiyat: ${price:.2f} - ID: #{position['id']}", level="SIGNAL")
        await send_telegram_with_retry(message)
        save_stats()
        
    except Exception as e:
        log_error("SAT emri hatası", e)

def check_positions(current_price):
    """Açık pozisyonları kontrol et"""
    global positions, daily_pnl, weekly_pnl, monthly_pnl
    
    try:
        for pos in positions:
            if pos['status'] != 'OPEN':
                continue
            
            pnl = 0
            closed_by = None
            
            if pos['type'] == 'BUY':
                if current_price >= pos['tp_price']:
                    pnl = (pos['tp_price'] - pos['entry_price']) * pos['size']
                    closed_by = 'TP'
                elif current_price <= pos['sl_price']:
                    pnl = (pos['sl_price'] - pos['entry_price']) * pos['size']
                    closed_by = 'SL'
            
            elif pos['type'] == 'SELL':
                if current_price <= pos['tp_price']:
                    pnl = (pos['entry_price'] - pos['tp_price']) * pos['size']
                    closed_by = 'TP'
                elif current_price >= pos['sl_price']:
                    pnl = (pos['entry_price'] - pos['sl_price']) * pos['size']
                    closed_by = 'SL'
            
            if closed_by:
                pos['status'] = 'CLOSED'
                pos['pnl'] = pnl
                pos['closed_by'] = closed_by
                pos['close_time'] = datetime.now()
                
                daily_pnl += pnl
                weekly_pnl += pnl
                monthly_pnl += pnl
                
                pnl_percent = (pnl / (pos['entry_price'] * pos['size'])) * 100
                pnl_emoji = "✅" if pnl > 0 else "❌"
                
                log_signal(f"{pnl_emoji} POZİSYON KAPANDI - ID: #{pos['id']} - {closed_by} - PnL: ${pnl:.2f}", level="POSITION")
                save_stats()
    
    except Exception as e:
        log_error("Pozisyon kontrol hatası", e)

def save_stats():
    """İstatistikleri kaydet"""
    try:
        stats = {
            'timestamp': datetime.now().isoformat(),
            'daily_pnl': daily_pnl,
            'weekly_pnl': weekly_pnl,
            'monthly_pnl': monthly_pnl,
            'total_trades': len(trade_log),
            'open_positions': len([p for p in positions if p['status'] == 'OPEN']),
            'closed_positions': len([p for p in positions if p['status'] == 'CLOSED']),
        }
        with open(STATS_FILE, 'w') as f:
            json.dump(stats, f, indent=2)
    except Exception as e:
        log_error("Stats kaydetme hatası", e)

async def send_daily_report():
    """Günlük rapor gönder"""
    global daily_pnl, trade_log
    
    try:
        closed_trades = [t for t in trade_log if t['status'] == 'CLOSED']
        wins = len([t for t in closed_trades if t['pnl'] > 0])
        losses = len([t for t in closed_trades if t['pnl'] < 0])
        
        win_rate = (wins/(wins+losses)*100) if (wins+losses) > 0 else 0
        
        message = f"""📊 <b>GÜNLÜK RAPOR</b>
━━━━━━━━━━━━━━━━━━
<b>Tarih:</b> {datetime.now().strftime('%Y-%m-%d')}
<b>İşlem:</b> {len(closed_trades)}
<b>Kazanan:</b> {wins} ✅
<b>Kaybeden:</b> {losses} ❌
<b>Başarı:</b> {win_rate:.1f}%
<b>Günlük PnL:</b> ${daily_pnl:.2f}
<b>Haftalık PnL:</b> ${weekly_pnl:.2f}
<b>Aylık PnL:</b> ${monthly_pnl:.2f}"""
        
        log_signal("📊 GÜNLÜK RAPOR GÖNDERILIYOR", level="REPORT")
        await send_telegram_with_retry(message)
    
    except Exception as e:
        log_error("Günlük rapor hatası", e)

# ============================================================================
# ANA DÖNGÜ
# ============================================================================

async def main_loop():
    """Ana döngü"""
    global last_signal
    
    exchange = get_exchange()
    if not exchange:
        log_error("Binance bağlantısı kurulamadı - Bot durduruluyor")
        return
    
    startup_msg = f"""🤖 <b>BOT BAŞLATILDI</b>
━━━━━━━━━━━━━━━━━━
<b>Strateji:</b> 15m MACD
<b>Sembol:</b> {SYMBOL}
<b>Sermaye:</b> ${INITIAL_BALANCE}
<b>Risk:</b> {RISK_PERCENT}%
<b>Kaldıraç:</b> {LEVERAGE}x
<b>TP:</b> +1% | <b>SL:</b> -0.5%

7/24 sinyalleri gönderilecek..."""
    
    log_signal("🤖 BOT BAŞLATILDI", level="STARTUP")
    await send_telegram_with_retry(startup_msg)
    
    loop_count = 0
    error_count = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            loop_count += 1
            error_count = 0  # Başarılı döngü - hata sayacını sıfırla
            
            # Veri al
            df = get_eth_data(exchange)
            if df is None:
                await asyncio.sleep(60)
                continue
            
            current_price = float(df['close'].iloc[-1])
            
            # MACD sinyali hesapla
            signal = calculate_macd_signal(df)
            
            # Pozisyonları kontrol et
            check_positions(current_price)
            
            # Yeni sinyal varsa
            if signal and signal != last_signal:
                position_info = calculate_position_size(current_price)
                
                if position_info:
                    if signal == "BUY":
                        await execute_buy_order(current_price, position_info)
                    elif signal == "SELL":
                        await execute_sell_order(current_price, position_info)
                    
                    last_signal = signal
            
            # Her saat başında rapor gönder
            if datetime.now().minute == 0 and loop_count % 4 == 0:
                await send_daily_report()
            
            # 15 dakika bekle
            await asyncio.sleep(900)
        
        except Exception as e:
            error_count += 1
            log_error(f"Ana döngü hatası (Hata #{error_count}/{max_consecutive_errors})", e)
            
            if error_count >= max_consecutive_errors:
                log_error(f"Çok fazla hata ({max_consecutive_errors}) - Bot durduruluyor")
                break
            
            await asyncio.sleep(60)

# ============================================================================
# BAŞLANGIC
# ============================================================================

if __name__ == "__main__":
    try:
        log_signal("=" * 80, level="STARTUP")
        log_signal("ETH/USDT 15m MACD Trading Bot - Production Ready", level="STARTUP")
        log_signal(f"Başlangıç: {datetime.now()}", level="STARTUP")
        log_signal("=" * 80, level="STARTUP")
        
        asyncio.run(main_loop())
    
    except KeyboardInterrupt:
        log_signal("🛑 BOT DURDURULDU (Kullanıcı)", level="SHUTDOWN")
    
    except Exception as e:
        log_error("KRITIK HATA - Bot kapanıyor", e)
        sys.exit(1)

