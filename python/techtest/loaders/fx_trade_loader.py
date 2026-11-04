from __future__ import annotations

import csv
from datetime import datetime
from math import isfinite
from typing import Iterator

from techtest.models import FxTrade


class FxTradeLoader:
    _SEPARATOR = "¬"
    _HEADER = ["Type", "TradeDate", "Ccy1", "Ccy2", "Amount", "Rate", "ValueDate", "Counterparty", "TradeId"]

    def __init__(self, data_file: str) -> None:
        self.data_file = data_file

    def load_trades(self) -> Iterator[FxTrade]:
        """Yield one trade at a time while the feed is open."""
        with open(self.data_file, encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, delimiter=self._SEPARATOR, strict=True)
            try:
                feed_header = next(reader, [])
                if len(feed_header) != 2 or feed_header[0] != "FxTrades":
                    raise ValueError("Missing or unexpected FX feed header")
                datetime.fromisoformat(feed_header[1])
                if next(reader, None) != self._HEADER:
                    raise ValueError("Missing or unexpected FX column header")
                for items in reader:
                    if not items:
                        continue
                    if items[0] == "END":
                        # The trailer number is undocumented; the supplied feed has
                        # four trades but ends with END¬5. Only use the end marker.
                        return
                    yield self._create_trade_from_fields(items)
                raise ValueError("Missing END marker; the FX feed may be incomplete")
            except (csv.Error, ValueError) as exc:
                raise ValueError(
                    f"Invalid FX feed in {self.data_file} at line {max(reader.line_num, 1)}: {exc}"
                ) from exc

    def _create_trade_from_fields(self, items: list[str]) -> FxTrade:
        trade_type, trade_date, ccy1, ccy2, amount, rate, value_date, counterparty, trade_id = items
        trade = FxTrade(trade_id, trade_type)
        trade.trade_date = datetime.fromisoformat(trade_date)
        trade.instrument = ccy1 + ccy2
        trade.notional = float(amount)
        trade.rate = float(rate)
        if not isfinite(trade.notional) or not isfinite(trade.rate):
            raise ValueError("Amount and rate must be finite numbers")
        trade.value_date = datetime.fromisoformat(value_date)
        trade.counterparty = counterparty

        return trade
