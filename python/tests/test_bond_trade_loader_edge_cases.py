import tempfile
import unittest
from pathlib import Path

from techtest.loaders import BondTradeLoader


class BondTradeLoaderEdgeCaseTests(unittest.TestCase):
    _HEADER = "Type,TradeDate,Instrument,Counterparty,Notional,Rate,TradeId\n"
    _TRADE = "GovBond,2020-01-01,GB0000000001,Counterparty,100,101.5,BOND001"

    def _load_feed(self, records, header=_HEADER, encoding="utf-8"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "BondTrades.dat"
            with path.open("w", encoding=encoding, newline="") as stream:
                stream.write(header + records)
            return list(BondTradeLoader(str(path)).load_trades())

    def test_quoted_fields_support_commas_quotes_and_newlines(self):
        for value, quoted in (
            ('Example, "Ltd"', '"Example, ""Ltd"""'),
            ("Example\r\nLtd", '"Example\r\nLtd"'),
        ):
            with self.subTest(value=value):
                row = self._TRADE.replace("Counterparty", quoted)
                trades = self._load_feed(row + "\r\n")
                self.assertEqual(trades[0].counterparty, value)
                self.assertEqual(trades[0].trade_id, "BOND001")
                self.assertEqual(trades[0].notional, 100.0)

    def test_bom_and_empty_lines_are_supported(self):
        trades = self._load_feed("\n" + self._TRADE + "\n\n", encoding="utf-8-sig")
        self.assertEqual([trade.trade_id for trade in trades], ["BOND001"])

    def test_header_only_feed_is_empty(self):
        self.assertEqual(self._load_feed(""), [])

    def test_missing_or_changed_headers_are_rejected(self):
        for header in ("", self._HEADER.replace("Notional,Rate", "Rate,Notional"), self._HEADER.rstrip("\n") + ",Extra\n"):
            with self.subTest(header=header), self.assertRaisesRegex(ValueError, r"BondTrades\.dat at line"):
                self._load_feed(self._TRADE + "\n", header=header)

    def test_invalid_records_include_file_and_line_context(self):
        for row in (
            self._TRADE.rsplit(",", 1)[0],
            self._TRADE + ",extra",
            self._TRADE.replace("2020-01-01", "not-a-date"),
            self._TRADE.replace("101.5", "not-a-number"),
            self._TRADE.replace("BOND001", "   "),
        ):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, r"BondTrades\.dat at line 3"):
                self._load_feed(self._TRADE + "\n" + row + "\n")

    def test_unterminated_quotes_are_rejected_with_context(self):
        row = self._TRADE.replace("Counterparty", '"Counterparty')
        with self.assertRaisesRegex(ValueError, r"BondTrades\.dat at line 2"):
            self._load_feed(row)

    def test_non_finite_numbers_are_rejected(self):
        for field in (4, 5):
            for value in ("NaN", "inf", "-inf", "1e999"):
                with self.subTest(field=field, value=value):
                    fields = self._TRADE.split(",")
                    fields[field] = value
                    with self.assertRaisesRegex(ValueError, "finite numbers"):
                        self._load_feed(",".join(fields) + "\n")

    def test_zero_negative_values_and_unknown_types_are_preserved(self):
        row = self._TRADE.replace("GovBond", "Supra").replace(",100,101.5,", ",-100,0,")
        trade = self._load_feed(row + "\n")[0]
        self.assertEqual(trade.trade_type, "Supra")
        self.assertEqual(trade.notional, -100.0)
        self.assertEqual(trade.rate, 0.0)


if __name__ == "__main__":
    unittest.main()
