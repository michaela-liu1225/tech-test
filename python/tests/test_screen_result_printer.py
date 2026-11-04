import io
import runpy
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from techtest.models import ScalarResults
from techtest.risk_system import ScreenResultPrinter


class ScreenResultPrinterTests(unittest.TestCase):
    def _print_results(self, results):
        output = io.StringIO()
        with redirect_stdout(output):
            ScreenResultPrinter().print_results(results)
        return output.getvalue()

    def test_prints_all_three_formats_with_one_line_per_trade(self):
        results = ScalarResults()
        results.add_result("WithWarning", 42.125)
        results.add_error("WithWarning", "Model warning")
        results.add_result("Successful", 10.0)
        results.add_error("Failed", "Pricing failed")

        self.assertEqual(
            self._print_results(results),
            "WithWarning : 42.125 : Model warning\n"
            "Successful : 10.0\n"
            "Failed : Pricing failed\n",
        )

    def test_zero_and_negative_results_are_preserved(self):
        cases = [
            (0.0, None, "Trade : 0.0\n"),
            (0.0, "Model warning", "Trade : 0.0 : Model warning\n"),
            (-12.345, None, "Trade : -12.345\n"),
        ]
        for value, error, expected in cases:
            with self.subTest(value=value, error=error):
                results = ScalarResults()
                results.add_result("Trade", value)
                results.add_error("Trade", error)
                self.assertEqual(self._print_results(results), expected)

    def test_empty_results_print_nothing(self):
        self.assertEqual(self._print_results(ScalarResults()), "")

    def test_missing_result_and_error_print_only_the_trade_id(self):
        results = ScalarResults()
        results.add_error("Trade", None)
        self.assertEqual(self._print_results(results), "Trade\n")

    def test_empty_error_message_is_preserved(self):
        results = ScalarResults()
        results.add_result("Trade", 42.0)
        results.add_error("Trade", "")
        self.assertEqual(self._print_results(results), "Trade : 42.0 : \n")

    def test_console_app_prints_all_feed_trades(self):
        output = io.StringIO()
        with patch("techtest.pricers.base_pricing_engine.time.sleep"), \
                patch("techtest.pricers.base_pricing_engine.BasePricingEngine._calculate_result", return_value=42.0), \
                redirect_stdout(output):
            runpy.run_module("techtest.console_app", run_name="__main__")

        expected_lines = [
            f"{trade_id} : 42.0"
            for trade_id in (
                "GOV001", "GOV002", "GOV003", "GOV004", "GOV005",
                "CORP001", "CORP002", "CORP003", "SPOT001", "SPOT002", "FWD002",
            )
        ]
        expected_lines.extend([
            "FWD001 : 42.0 : Unable to calibrate model to value date",
            "GOV006 : Undefined error in pricing",
            "GOV007 : No Pricing Engines available for this trade type",
        ])
        result_lines = [line for line in output.getvalue().splitlines() if " : " in line]
        self.assertCountEqual(result_lines, expected_lines)


if __name__ == "__main__":
    unittest.main()
