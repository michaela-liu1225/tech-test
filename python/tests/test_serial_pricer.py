import io
import subprocess
import sys
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from techtest.models import BondTrade, PricingEngine, ScalarResults
from techtest.risk_system import PricingConfigLoader, PricingEngineConfigItem, SerialPricer, SerialTradeLoader


class StubPricingEngine(PricingEngine):
    def price(self, trade, result_receiver):
        result_receiver.add_result(trade.trade_id, 42.0)


class BrokenPricingEngine(StubPricingEngine):
    def __init__(self):
        raise ValueError("Engine initialization failed")


class SerialPricerTests(unittest.TestCase):
    def test_supplied_configuration_loads_all_engines(self):
        pricer = SerialPricer()
        pricer._load_pricers()

        expected = {
            "GovBond": "GovBondPricingEngine",
            "CorpBond": "CorpBondPricingEngine",
            "FxSpot": "FxPricingEngine",
            "FxFwd": "FxPricingEngine",
        }
        self.assertEqual(set(pricer._pricers), set(expected))
        for trade_type, class_name in expected.items():
            engine = pricer._pricers[trade_type]
            self.assertIsInstance(engine, PricingEngine)
            self.assertEqual(type(engine).__name__, class_name)
            self.assertTrue(engine.is_trade_type_supported(trade_type))
        self.assertIsNot(pricer._pricers["FxSpot"], pricer._pricers["FxFwd"])

    def test_configured_custom_engine_can_price_a_trade(self):
        config = [PricingEngineConfigItem("CustomTrade", __name__, "StubPricingEngine")]
        results = ScalarResults()
        trade = BondTrade("CUSTOM001", trade_type="CustomTrade")

        with patch.object(PricingConfigLoader, "load_config", return_value=config):
            SerialPricer().price([[trade]], results)

        self.assertEqual(results["CUSTOM001"].result, 42.0)
        self.assertIsNone(results["CUSTOM001"].error)

    def test_invalid_engines_report_the_entry_and_preserve_the_cause(self):
        cases = [
            ("not_installed_pricing_engine_test_module", "Engine", ModuleNotFoundError),
            (__name__, "MissingEngine", AttributeError),
            ("builtins", "str", TypeError),
            ("math", "pi", TypeError),
            ("techtest.models", "PricingEngine", TypeError),
            (__name__, "BrokenPricingEngine", ValueError),
        ]
        for module, class_name, cause_type in cases:
            with self.subTest(module=module, class_name=class_name):
                config = [PricingEngineConfigItem("CustomTrade", module, class_name)]
                with patch.object(PricingConfigLoader, "load_config", return_value=config):
                    with self.assertRaises(RuntimeError) as raised:
                        SerialPricer()._load_pricers()
                self.assertIn(f"{module}.{class_name}", str(raised.exception))
                self.assertIn("CustomTrade", str(raised.exception))
                self.assertIsInstance(raised.exception.__cause__, cause_type)

    def test_failed_loading_does_not_publish_partial_engines_or_price_trades(self):
        pricer = SerialPricer()
        pricer._load_pricers()
        previous_engines = pricer._pricers
        results = ScalarResults()
        config = [
            PricingEngineConfigItem("CustomTrade", __name__, "StubPricingEngine"),
            PricingEngineConfigItem("BrokenTrade", __name__, "BrokenPricingEngine"),
        ]
        trade = BondTrade("CUSTOM001", trade_type="CustomTrade")

        with patch.object(PricingConfigLoader, "load_config", return_value=config):
            with self.assertRaises(RuntimeError):
                pricer.price([[trade]], results)

        self.assertIs(pricer._pricers, previous_engines)
        self.assertNotIn("CustomTrade", pricer._pricers)
        self.assertNotIn("CUSTOM001", results)

    def test_reloading_removes_old_mappings_including_when_config_is_empty(self):
        first = PricingEngineConfigItem("FirstTrade", __name__, "StubPricingEngine")
        second = PricingEngineConfigItem("SecondTrade", __name__, "StubPricingEngine")
        pricer = SerialPricer()

        with patch.object(PricingConfigLoader, "load_config", side_effect=[[first, second], [second], []]):
            pricer._load_pricers()
            self.assertEqual(set(pricer._pricers), {"FirstTrade", "SecondTrade"})
            pricer._load_pricers()
            self.assertEqual(set(pricer._pricers), {"SecondTrade"})
            pricer._load_pricers()
            self.assertEqual(pricer._pricers, {})

    def test_importing_risk_system_does_not_import_concrete_pricers(self):
        # A fresh interpreter avoids modules already imported by other tests.
        script = textwrap.dedent("""
            import importlib.abc
            import sys

            class RejectPricers(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == "techtest.pricers" or fullname.startswith("techtest.pricers."):
                        raise AssertionError("Unexpected import-time dependency: " + fullname)
                    return None

            sys.meta_path.insert(0, RejectPricers())
            import techtest.risk_system
            if any(name == "techtest.pricers" or name.startswith("techtest.pricers.") for name in sys.modules):
                raise AssertionError("Concrete pricers were imported")
        """)
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_all_feed_trades_receive_results_or_expected_errors(self):
        containers = [list(container) for container in SerialTradeLoader().load_trades()]
        trades = [trade for container in containers for trade in container]
        results = ScalarResults()
        with patch("techtest.pricers.base_pricing_engine.time.sleep"), \
                patch("techtest.pricers.base_pricing_engine.BasePricingEngine._calculate_result", return_value=42.0), \
                redirect_stdout(io.StringIO()):
            SerialPricer().price(containers, results)

        expected_errors = {
            "GOV006": "Undefined error in pricing",
            "GOV007": "No Pricing Engines available for this trade type",
            "FWD001": "Unable to calibrate model to value date",
        }
        self.assertEqual(len(trades), 14)
        for trade in trades:
            with self.subTest(trade_id=trade.trade_id):
                result = results[trade.trade_id]
                expected_value = None if trade.trade_id in {"GOV006", "GOV007"} else 42.0
                self.assertEqual(result.result, expected_value)
                self.assertEqual(result.error, expected_errors.get(trade.trade_id))


if __name__ == "__main__":
    unittest.main()
