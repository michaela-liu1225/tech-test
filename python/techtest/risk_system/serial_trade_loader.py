from __future__ import annotations

import os
from typing import Iterable, Iterator

from techtest.loaders import TRADE_DATA_DIR, BondTradeLoader, FxTradeLoader
from techtest.models import Trade


class SerialTradeLoader:
    def load_trades(self) -> Iterator[Iterable[Trade]]:
        """Yield each source's trade iterator only when requested."""
        for loader in self._get_trade_loaders():
            yield loader.load_trades()

    def _get_trade_loaders(self) -> Iterable[BondTradeLoader | FxTradeLoader]:
        return [
            BondTradeLoader(os.path.join(TRADE_DATA_DIR, "BondTrades.dat")),
            FxTradeLoader(os.path.join(TRADE_DATA_DIR, "FxTrades.dat")),
        ]
