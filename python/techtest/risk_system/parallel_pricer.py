from __future__ import annotations

import os
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import closing, nullcontext
from threading import Lock
from typing import ContextManager, Iterable, Iterator, TypeVar

from techtest.models import ResultReceiver, Trade
from techtest.risk_system.serial_pricer import SerialPricer

T = TypeVar("T")


def _closing_iterator(items: Iterable[T]) -> ContextManager[Iterator[T]]:
    """Close consumed generators on early exit while accepting ordinary iterables."""
    iterator = iter(items)
    if callable(getattr(iterator, "close", None)):
        return closing(iterator)
    return nullcontext(iterator)


class _LockedResultReceiver(ResultReceiver):
    """Protect receiver updates without serializing pricing calculations."""

    def __init__(self, receiver: ResultReceiver) -> None:
        self._receiver = receiver
        self._lock = Lock()

    def add_result(self, trade_id: str, result: float) -> None:
        with self._lock:
            self._receiver.add_result(trade_id, result)

    def add_error(self, trade_id: str, error: str | None) -> None:
        with self._lock:
            self._receiver.add_error(trade_id, error)


class ParallelPricer(SerialPricer):
    """Price trades concurrently using engines that support concurrent calls."""

    def __init__(self, max_workers: int | None = None) -> None:
        if max_workers is None:
            # Use Python 3.9's thread-pool heuristic as a configurable starting point.
            max_workers = min(32, (os.cpu_count() or 1) + 4)
        if isinstance(max_workers, bool) or not isinstance(max_workers, int):
            raise TypeError("max_workers must be an integer")
        if max_workers < 1:
            raise ValueError("max_workers must be greater than zero")
        super().__init__()
        self._max_workers = max_workers

    def price(self, trade_containers: Iterable[Iterable[Trade]], result_receiver: ResultReceiver) -> None:
        """Return after all submitted work finishes, propagating unexpected failures."""
        if result_receiver is None:
            raise ValueError("result_receiver must not be None")
        self._load_pricers()
        receiver = _LockedResultReceiver(result_receiver)
        pending: set[Future[None]] = set()

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor, \
                _closing_iterator(trade_containers) as containers:
            for trade_container in containers:
                with _closing_iterator(trade_container) as trades:
                    for trade in trades:
                        pending.add(executor.submit(self._price_trade, trade, receiver))
                        # Bound queued work as well as the number of running threads.
                        if len(pending) >= self._max_workers:
                            completed, pending = wait(pending, return_when=FIRST_COMPLETED)
                            for future in completed:
                                future.result()

            for future in pending:
                future.result()
