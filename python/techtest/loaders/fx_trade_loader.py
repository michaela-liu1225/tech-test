from __future__ import annotations

import csv
from datetime import datetime
from typing import Iterator

from techtest.models import FxTrade


class FxTradeLoader:
    _SEPARATOR = "¬"

    def __init__(self, data_file: str) -> None:
        self.data_file = data_file

    def load_trades(self) -> Iterator[FxTrade]:
        """Yield one trade at a time while the feed is open."""
        with open(self.data_file, encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, delimiter=self._SEPARATOR)
            next(reader, None)  # Skip the feed name and date.
            next(reader, None)  # Skip the column names.
            for items in reader:
                if not items:
                    continue
                if items[0] == "END":
                    # The trailer number is undocumented; the supplied feed has
                    # four trades but ends with END¬5. Only use the end marker.
                    break
                try:
                    trade = self._create_trade_from_fields(items)
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid FX trade in {self.data_file} at line {reader.line_num}: {exc}"
                    ) from exc
                yield trade

    def _create_trade_from_fields(self, items: list[str]) -> FxTrade:
        trade_type, trade_date, ccy1, ccy2, amount, rate, value_date, counterparty, trade_id = items
        trade = FxTrade(trade_id, trade_type)
        trade.trade_date = datetime.fromisoformat(trade_date)
        trade.instrument = ccy1 + ccy2
        trade.notional = float(amount)
        trade.rate = float(rate)
        trade.value_date = datetime.fromisoformat(value_date)
        trade.counterparty = counterparty

        return trade
