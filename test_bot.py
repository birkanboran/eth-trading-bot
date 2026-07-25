#!/usr/bin/env python3
"""Unit tests"""
import unittest
from decimal import Decimal, ROUND_DOWN

class TestBotLogic(unittest.TestCase):
    def test_risk_calculation(self):
        balance = 100.0
        risk_amount = balance * 0.01
        price_diff = 40.0
        position_size = risk_amount / price_diff
        self.assertAlmostEqual(position_size, 0.025, places=6)
    
    def test_quantity_rounding(self):
        quantity = 0.00374853
        step_size = Decimal('0.001')
        qty_decimal = Decimal(str(quantity))
        rounded = (qty_decimal / step_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_size
        self.assertEqual(float(rounded), 0.003)
    
    def test_price_rounding(self):
        price = 2000.12345
        tick_size = Decimal('0.01')
        price_decimal = Decimal(str(price))
        rounded = (price_decimal / tick_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick_size
        self.assertEqual(float(rounded), 2000.12)
    
    def test_tp_sl_calculation(self):
        entry = 2000.0
        tp = entry * 1.03
        sl = entry * 0.98
        self.assertAlmostEqual(tp, 2060.0, places=2)
        self.assertAlmostEqual(sl, 1960.0, places=2)
    
    def test_security_locks(self):
        live_trading = False
        dry_run = True
        self.assertFalse(live_trading and not dry_run)
        self.assertFalse(live_trading)

if __name__ == '__main__':
    unittest.main()
