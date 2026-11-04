from __future__ import annotations

from datetime import datetime
from typing import Iterator

from techtest.models import BondTrade


class BondTradeLoader:
    _SEPARATOR = ","

    def __init__(self, data_file: str) -> None:
        self.data_file = data_file

    def load_trades(self) -> Iterator[BondTrade]:
        """Yield one trade at a time while the feed is open."""
        # utf-8-sig skips the byte order mark at the start of the file.
        with open(self.data_file, encoding="utf-8-sig") as stream:
            next(stream, None)  # Skip the header line.
            for line in stream:
                yield self._create_trade_from_line(line.rstrip("\r\n"))

    def _create_trade_from_line(self, line: str) -> BondTrade:
        items = line.split(self._SEPARATOR)
        trade = BondTrade(items[6], trade_type=items[0])
        trade.trade_date = datetime.fromisoformat(items[1])
        trade.instrument = items[2]
        trade.counterparty = items[3]
        trade.notional = float(items[4])
        trade.rate = float(items[5])

        return trade
