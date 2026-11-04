import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from techtest.loaders import TRADE_DATA_DIR, FxTradeLoader
from techtest.models import FxTrade


class FxTradeLoaderEdgeCaseTests(unittest.TestCase):
    _HEADER = (
        "FxTrades¬2012-10-15\n"
        "Type¬TradeDate¬Ccy1¬Ccy2¬Amount¬Rate¬ValueDate¬Counterparty¬TradeId\n"
    )
    _TRADE = "FxSpot¬2012-10-08¬EUR¬USD¬145000000¬0.97562¬2012-10-11¬CSI,AG¬SPOT001"

    def _load_feed(self, records: str, encoding: str = "utf-8"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "FxTrades.dat"
            path.write_text(self._HEADER + records, encoding=encoding)
            return list(FxTradeLoader(str(path)).load_trades())

    def test_all_trade_ids_are_preserved(self):
        trades = list(FxTradeLoader(os.path.join(TRADE_DATA_DIR, "FxTrades.dat")).load_trades())
        self.assertEqual(
            [trade.trade_id for trade in trades],
            ["SPOT001", "SPOT002", "FWD001", "FWD002"],
        )

    def test_unusual_dates_do_not_change_feed_types(self):
        trades = list(FxTradeLoader(os.path.join(TRADE_DATA_DIR, "FxTrades.dat")).load_trades())
        self.assertEqual(trades[1].trade_type, FxTrade.FX_SPOT_TRADE_TYPE)
        self.assertEqual(trades[1].instrument, "EURGBP")
        self.assertEqual(trades[1].value_date, datetime(2012, 7, 11))
        self.assertEqual(trades[2].trade_type, FxTrade.FX_FORWARD_TRADE_TYPE)
        self.assertEqual(trades[2].instrument, "USDCHF")
        self.assertEqual(trades[2].value_date, datetime(2112, 10, 15))

    def test_bom_and_empty_lines_are_supported(self):
        trades = self._load_feed("\n" + self._TRADE + "\n\nEND¬5\n", encoding="utf-8-sig")
        self.assertEqual([trade.trade_id for trade in trades], ["SPOT001"])

    def test_end_marker_stops_loading(self):
        trades = self._load_feed(self._TRADE + "\nEND¬5\nthis is not a trade\n")
        self.assertEqual([trade.trade_id for trade in trades], ["SPOT001"])

    def test_quoted_counterparty_can_contain_the_separator(self):
        row = self._TRADE.replace("CSI,AG", '"CSI¬AG"')
        trades = self._load_feed(row + "\nEND¬5\n")
        self.assertEqual(trades[0].counterparty, "CSI¬AG")
        self.assertEqual(trades[0].trade_id, "SPOT001")

    def test_unknown_trade_type_is_preserved(self):
        row = self._TRADE.replace("FxSpot", "UnknownFxType")
        trades = self._load_feed(row + "\nEND¬5\n")
        self.assertEqual(trades[0].trade_type, "UnknownFxType")

    def test_invalid_records_raise_with_file_and_line_context(self):
        invalid_rows = [
            self._TRADE.rsplit("¬", 1)[0],
            self._TRADE.replace("2012-10-08", "2012-99-08"),
            self._TRADE.replace("0.97562", "not-a-number"),
            self._TRADE.replace("SPOT001", ""),
        ]
        for row in invalid_rows:
            with self.subTest(row=row):
                with self.assertRaisesRegex(ValueError, r"FxTrades\.dat at line 3"):
                    self._load_feed(row + "\nEND¬5\n")

    def test_trade_id_must_not_be_missing_or_blank(self):
        for trade_id in (None, "", "   "):
            with self.subTest(trade_id=trade_id):
                with self.assertRaises(ValueError):
                    FxTrade(trade_id, FxTrade.FX_SPOT_TRADE_TYPE)


if __name__ == "__main__":
    unittest.main()
