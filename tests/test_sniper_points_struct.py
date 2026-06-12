# -*- coding: utf-8 -*-

import unittest

from src.schemas.sniper_points_struct import (
    finalize_dashboard_sniper_points_struct,
    get_sniper_points_struct,
    validate_dashboard_sniper_points_struct,
    validate_sniper_points_struct,
)


def _valid_applicable_struct():
    return {
        "schema_version": 1,
        "applicable": True,
        "not_applicable_reason": None,
        "ideal_buy": {
            "low": 1.67,
            "high": 1.68,
            "basis": "MA5",
            "condition": "缩量回踩企稳",
        },
        "secondary_buy": {
            "low": 1.60,
            "high": 1.62,
            "basis": "MA10",
            "condition": "MA5失守后回踩获得支撑",
        },
        "stop_loss": {
            "price": 1.54,
            "trigger": "intraday_below",
            "basis": "MA20",
        },
        "take_profit": {
            "targets": [1.85, 2.00],
            "basis": "前高/整数关口",
        },
    }


class TestSniperPointsStructValidation(unittest.TestCase):
    def test_valid_applicable_struct_passes(self):
        ok, errors = validate_sniper_points_struct(
            _valid_applicable_struct(),
            current_price=1.70,
        )
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_valid_not_applicable_struct_passes(self):
        struct = {
            "schema_version": 1,
            "applicable": False,
            "not_applicable_reason": "空头排列，严禁买入",
            "ideal_buy": None,
            "secondary_buy": None,
            "stop_loss": {
                "price": 18.20,
                "trigger": "close_below",
                "basis": "持仓者参考位",
            },
            "take_profit": None,
        }
        ok, errors = validate_sniper_points_struct(struct, current_price=20.0)
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_stop_loss_must_be_below_ideal_buy(self):
        struct = _valid_applicable_struct()
        struct["stop_loss"]["price"] = 1.68
        ok, errors = validate_sniper_points_struct(struct, current_price=1.70)
        self.assertFalse(ok)
        self.assertTrue(any("stop_loss.price" in item for item in errors))

    def test_take_profit_targets_must_exceed_ideal_buy_high(self):
        struct = _valid_applicable_struct()
        struct["take_profit"]["targets"] = [1.60]
        ok, errors = validate_sniper_points_struct(struct, current_price=1.70)
        self.assertFalse(ok)
        self.assertTrue(any("take_profit.targets" in item for item in errors))

    def test_prices_must_be_within_current_price_band(self):
        struct = _valid_applicable_struct()
        ok, errors = validate_sniper_points_struct(struct, current_price=10.0)
        self.assertFalse(ok)
        self.assertTrue(any("0.3x~3x" in item for item in errors))

    def test_applicable_false_requires_null_buy_zones(self):
        struct = _valid_applicable_struct()
        struct["applicable"] = False
        struct["not_applicable_reason"] = "暂无买点"
        ok, errors = validate_sniper_points_struct(struct, current_price=1.70)
        self.assertFalse(ok)
        self.assertTrue(any("ideal_buy must be null" in item for item in errors))

    def test_targets_must_be_sorted(self):
        struct = _valid_applicable_struct()
        struct["take_profit"]["targets"] = [2.00, 1.85]
        ok, errors = validate_sniper_points_struct(struct, current_price=1.70)
        self.assertFalse(ok)
        self.assertTrue(any("sorted ascending" in item for item in errors))

    def test_finalize_strips_invalid_struct(self):
        dashboard = {
            "data_perspective": {
                "price_position": {"current_price": 1.70},
            },
            "battle_plan": {
                "sniper_points": {"ideal_buy": "1.67-1.68"},
                "sniper_points_struct": _valid_applicable_struct(),
            },
        }
        dashboard["battle_plan"]["sniper_points_struct"]["stop_loss"]["price"] = 1.70
        valid, errors = finalize_dashboard_sniper_points_struct(
            dashboard,
            strip_on_failure=True,
        )
        self.assertFalse(valid)
        self.assertTrue(errors)
        self.assertIsNone(get_sniper_points_struct(dashboard))

    def test_validate_dashboard_absent_struct_is_ok(self):
        dashboard = {"battle_plan": {"sniper_points": {"ideal_buy": "1.67"}}}
        ok, errors = validate_dashboard_sniper_points_struct(dashboard)
        self.assertTrue(ok)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
