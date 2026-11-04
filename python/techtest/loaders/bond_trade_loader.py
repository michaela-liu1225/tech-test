from __future__ import annotations

import csv
from datetime import datetime
from math import isfinite
from typing import Iterator

from techtest.models import BondTrade


class BondTradeLoader:
    _SEPARATOR = ","
    _HEADER = ["Type", "TradeDate", "Instrument", "Counterparty", "Notional", "Rate", "TradeId"]

    def __init__(self, data_file: str) -> None:
        self.data_file = data_file

    def load_trades(self) -> Iterator[BondTrade]:
        """Yield one trade at a time while the feed is open."""
        # utf-8-sig skips the byte order mark at the start of the file.
        with open(self.data_file, encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, delimiter=self._SEPARATOR, strict=True)
            try:
                if next(reader, None) != self._HEADER:
                    raise ValueError("Missing or unexpected bond column header")
                for items in reader:
                    if not items:
                        continue
                    yield self._create_trade_from_fields(items)
            except (csv.Error, ValueError) as exc:
                raise ValueError(
                    f"Invalid bond feed in {self.data_file} at line {max(reader.line_num, 1)}: {exc}"
                ) from exc

    def _create_trade_from_fields(self, items: list[str]) -> BondTrade:
        trade_type, trade_date, instrument, counterparty, notional, rate, trade_id = items
        trade = BondTrade(trade_id, trade_type=trade_type)
        trade.trade_date = datetime.fromisoformat(trade_date)
        trade.instrument = instrument
        trade.counterparty = counterparty
        trade.notional = float(notional)
        trade.rate = float(rate)
        if not isfinite(trade.notional) or not isfinite(trade.rate):
            raise ValueError("Notional and rate must be finite numbers")

        return trade
