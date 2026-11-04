import io
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from techtest.loaders import BondTradeLoader, FxTradeLoader
from techtest.models import PricingEngine, ScalarResults
from techtest.risk_system import SerialPricer, SerialTradeLoader


class StreamingTradeLoadingTests(unittest.TestCase):
    _CASES = (
        (
            BondTradeLoader,
            "Type,TradeDate,Instrument,Counterparty,Notional,Rate,TradeId\n"
            "GovBond,2020-01-01,GB0000000001,Counterparty,100,101.5,BOND001\n"
            "CorpBond,2020-01-01,GB0000000002,Counterparty,200,102.5,BOND002\n",
            ["BOND001", "BOND002"],
            1,
        ),
        (
            FxTradeLoader,
            "FxTrades¬2020-01-01\n"
            "Type¬TradeDate¬Ccy1¬Ccy2¬Amount¬Rate¬ValueDate¬Counterparty¬TradeId\n"
            "FxSpot¬2020-01-01¬EUR¬USD¬100¬1.2¬2020-01-03¬Counterparty¬FX001\n"
            "FxFwd¬2020-01-01¬USD¬JPY¬200¬110.5¬2020-04-01¬Counterparty¬FX002\n"
            "END¬3\n",
            ["FX001", "FX002"],
            2,
        ),
    )

    def test_files_are_opened_and_read_only_as_trades_are_requested(self):
        for loader_class, feed, trade_ids, header_count in self._CASES:
            with self.subTest(loader=loader_class.__name__):
                stream = io.StringIO(feed)
                with patch("builtins.open", return_value=stream) as open_feed, \
                        closing(loader_class("feed.dat").load_trades()) as trades:
                    open_feed.assert_not_called()
                    self.assertEqual(next(trades).trade_id, trade_ids[0])
                    first_record_end = len("".join(feed.splitlines(keepends=True)[:header_count + 1]))
                    self.assertEqual(stream.tell(), first_record_end)
                    self.assertFalse(stream.closed)

                    self.assertEqual(next(trades).trade_id, trade_ids[1])
                    with self.assertRaises(StopIteration):
                        next(trades)
                    self.assertTrue(stream.closed)

    def test_explicitly_closing_an_unfinished_iterator_closes_the_file(self):
        for loader_class, feed, _, _ in self._CASES:
            with self.subTest(loader=loader_class.__name__):
                stream = io.StringIO(feed)
                with patch("builtins.open", return_value=stream):
                    with closing(loader_class("feed.dat").load_trades()) as trades:
                        next(trades)
                        self.assertFalse(stream.closed)
                    self.assertTrue(stream.closed)

    def test_later_parse_errors_are_deferred_and_close_the_file(self):
        for loader_class, feed, trade_ids, header_count in self._CASES:
            with self.subTest(loader=loader_class.__name__):
                lines = feed.splitlines(keepends=True)
                lines[header_count + 1] = lines[header_count + 1].replace("2020-01-01", "not-a-date", 1)
                stream = io.StringIO("".join(lines))
                with patch("builtins.open", return_value=stream), \
                        closing(loader_class("feed.dat").load_trades()) as trades:
                    self.assertEqual(next(trades).trade_id, trade_ids[0])
                    with self.assertRaises(ValueError):
                        next(trades)
                    self.assertTrue(stream.closed)

    def test_missing_file_errors_are_deferred_until_iteration(self):
        for loader_class, _, _, _ in self._CASES:
            with self.subTest(loader=loader_class.__name__):
                with patch("builtins.open", side_effect=FileNotFoundError("Missing feed")) as open_feed, \
                        closing(loader_class("missing.dat").load_trades()) as trades:
                    open_feed.assert_not_called()
                    with self.assertRaises(FileNotFoundError):
                        next(trades)

    def test_an_exhausted_iterator_can_be_replaced_by_a_fresh_load(self):
        for loader_class, feed, trade_ids, _ in self._CASES:
            with self.subTest(loader=loader_class.__name__):
                with patch("builtins.open", side_effect=lambda *args, **kwargs: io.StringIO(feed)) as open_feed:
                    loader = loader_class("feed.dat")
                    trades = loader.load_trades()
                    self.assertEqual([trade.trade_id for trade in trades], trade_ids)
                    self.assertEqual(list(trades), [])
                    self.assertEqual([trade.trade_id for trade in loader.load_trades()], trade_ids)
                    self.assertEqual(open_feed.call_count, 2)

    def test_trade_sources_are_requested_lazily(self):
        first_loader = Mock(spec=BondTradeLoader)
        second_loader = Mock(spec=FxTradeLoader)
        first_loader.load_trades.return_value = iter(())
        second_loader.load_trades.return_value = iter(())
        loader = SerialTradeLoader()

        with patch.object(loader, "_get_trade_loaders", return_value=[first_loader, second_loader]), \
                closing(loader.load_trades()) as streams:
            first_loader.load_trades.assert_not_called()
            second_loader.load_trades.assert_not_called()
            self.assertIs(next(streams), first_loader.load_trades.return_value)
            first_loader.load_trades.assert_called_once_with()
            second_loader.load_trades.assert_not_called()
            self.assertIs(next(streams), second_loader.load_trades.return_value)
            second_loader.load_trades.assert_called_once_with()
            with self.assertRaises(StopIteration):
                next(streams)

    def test_each_trade_is_priced_before_the_next_record_is_parsed(self):
        events = []

        def track_parser(parse):
            def parse_and_record(record):
                trade = parse(record)
                events.append(("load", trade.trade_id))
                return trade
            return parse_and_record

        def price_and_record(trade, receiver):
            events.append(("price", trade.trade_id))
            receiver.add_result(trade.trade_id, 42.0)

        with tempfile.TemporaryDirectory() as directory:
            sources = []
            for loader_class, feed, _, _ in self._CASES:
                path = Path(directory) / (loader_class.__name__ + ".dat")
                path.write_text(feed, encoding="utf-8-sig")
                sources.append(loader_class(str(path)))

            loader = SerialTradeLoader()
            pricer = SerialPricer()
            engine = Mock(spec=PricingEngine)
            engine.price.side_effect = price_and_record
            pricer._pricers = {trade_type: engine for trade_type in ("GovBond", "CorpBond", "FxSpot", "FxFwd")}
            results = ScalarResults()
            with patch.object(loader, "_get_trade_loaders", return_value=sources), \
                    patch.object(pricer, "_load_pricers"), \
                    patch.object(sources[0], "_create_trade_from_fields", side_effect=track_parser(sources[0]._create_trade_from_fields)), \
                    patch.object(sources[1], "_create_trade_from_fields", side_effect=track_parser(sources[1]._create_trade_from_fields)):
                pricer.price(loader.load_trades(), results)

        trade_ids = ["BOND001", "BOND002", "FX001", "FX002"]
        self.assertEqual(events, [(action, trade_id) for trade_id in trade_ids for action in ("load", "price")])
        self.assertEqual(
            [(result.trade_id, result.result, result.error) for result in results],
            [(trade_id, 42.0, None) for trade_id in trade_ids],
        )


if __name__ == "__main__":
    unittest.main()
