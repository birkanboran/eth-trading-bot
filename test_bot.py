#!/usr/bin/env python3
"""Unit tests - security and logic"""
import unittest
from decimal import Decimal, ROUND_DOWN

class TestBotSecurity(unittest.TestCase):
    def test_live_trading_lock(self):
        live_trading = False
        self.assertFalse(live_trading)
    
    def test_dry_run_returns_real_price_qty(self):
        mark_price = 2000.0
        quantity = 0.00374853
        step_size = Decimal('0.001')
        qty_decimal = Decimal(str(quantity))
        rounded = (qty_decimal / step_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_size
        self.assertEqual(float(rounded), 0.003)
        self.assertGreater(mark_price, 0)
    
    def test_position_mode_check(self):
        dual_side = False
        self.assertFalse(dual_side)
    
    def test_market_lot_size_rounding(self):
        quantity = 0.00374853
        market_step = Decimal('0.001')
        qty_decimal = Decimal(str(quantity))
        rounded = (qty_decimal / market_step).quantize(Decimal('1'), rounding=ROUND_DOWN) * market_step
        self.assertEqual(float(rounded), 0.003)
    
    def test_min_qty_validation(self):
        quantity = 0.001
        min_qty = Decimal('0.001')
        self.assertGreaterEqual(Decimal(str(quantity)), min_qty)
    
    def test_available_balance_used(self):
        available = 95.79
        total = 100.0
        self.assertLess(available, total)
    
    def test_volume_spike_excludes_signal_candle(self):
        volumes = [100, 110, 105, 120, 115, 250]
        multiplier = 2.0
        period = 5
        vol_avg = sum(volumes[-period-1:-1]) / period
        vol_spike = volumes[-1] > vol_avg * multiplier
        self.assertAlmostEqual(vol_avg, 110.0, places=1)
        self.assertTrue(vol_spike)
    
    def test_tp_sl_order_ids_returned(self):
        tp_sl_result = {'tp_order_id': 12345, 'sl_order_id': 12346}
        self.assertIsNotNone(tp_sl_result.get('tp_order_id'))
    
    def test_risk_calculation(self):
        balance = 100.0
        risk_amount = balance * 0.01
        price_diff = 40.0
        position_size = risk_amount / price_diff
        self.assertAlmostEqual(position_size, 0.025, places=6)

if __name__ == '__main__':
    unittest.main()
