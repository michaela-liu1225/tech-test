import io
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from threading import Barrier, Event, Lock, get_ident
from unittest.mock import Mock, patch

from techtest.models import BondTrade, PricingEngine, ResultReceiver, ScalarResults
from techtest.risk_system import ParallelPricer, SerialPricer, SerialTradeLoader


class CallbackPricingEngine(PricingEngine):
    def __init__(self, callback):
        self._callback = callback

    def price(self, trade, result_receiver):
        self._callback(trade, result_receiver)


class GuardedResultReceiver(ResultReceiver):
    """Detect concurrent calls to a receiver that requires serialized access."""

    def __init__(self):
        self.calls = []
        self._entry = Lock()

    def _record(self, kind, trade_id, value):
        if not self._entry.acquire(blocking=False):
            raise AssertionError("Concurrent result receiver access")
        try:
            time.sleep(0.01)
            self.calls.append((kind, trade_id, value))
        finally:
            self._entry.release()

    def add_result(self, trade_id, result):
        self._record("result", trade_id, result)

    def add_error(self, trade_id, error):
        self._record("error", trade_id, error)


class ParallelPricerTests(unittest.TestCase):
    def _configured_pricer(self, callback, max_workers=2):
        pricer = ParallelPricer(max_workers=max_workers)
        pricer._pricers = {"GovBond": CallbackPricingEngine(callback)}
        patcher = patch.object(pricer, "_load_pricers")
        patcher.start()
        self.addCleanup(patcher.stop)
        return pricer

    def test_worker_count_must_be_a_positive_integer(self):
        for value in (0, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ParallelPricer(max_workers=value)
        for value in (True, False, 1.5, "4"):
            with self.subTest(value=value), self.assertRaises(TypeError):
                ParallelPricer(max_workers=value)

    def test_automatic_worker_limit_uses_cpu_count_with_a_fallback_and_cap(self):
        for cpu_count, expected in ((1, 5), (12, 16), (128, 32), (None, 5)):
            with self.subTest(cpu_count=cpu_count), \
                    patch("techtest.risk_system.parallel_pricer.os.cpu_count", return_value=cpu_count), \
                    patch("techtest.risk_system.parallel_pricer.ThreadPoolExecutor", wraps=ThreadPoolExecutor) as pool:
                pricer = self._configured_pricer(lambda trade, receiver: None, max_workers=None)
                pricer.price([], ScalarResults())
                pool.assert_called_once_with(max_workers=expected)

    def test_explicit_worker_limit_does_not_depend_on_cpu_detection(self):
        with patch("techtest.risk_system.parallel_pricer.os.cpu_count") as cpu_count, \
                patch("techtest.risk_system.parallel_pricer.ThreadPoolExecutor", wraps=ThreadPoolExecutor) as pool:
            pricer = self._configured_pricer(lambda trade, receiver: receiver.add_result(trade.trade_id, 42.0), 3)
            results = ScalarResults()
            pricer.price([[BondTrade("Trade")]], results)
            cpu_count.assert_not_called()
            pool.assert_called_once_with(max_workers=3)
            self.assertEqual(results["Trade"].result, 42.0)

    def test_pricing_overlaps_within_the_worker_limit(self):
        barrier = Barrier(2, timeout=5)
        state_lock = Lock()
        active = 0
        peak = 0
        worker_threads = set()

        def price(trade, receiver):
            nonlocal active, peak
            with state_lock:
                active += 1
                peak = max(peak, active)
                worker_threads.add(get_ident())
            try:
                barrier.wait()
                receiver.add_result(trade.trade_id, 42.0)
            finally:
                with state_lock:
                    active -= 1

        results = ScalarResults()
        self._configured_pricer(price).price([[BondTrade(str(i)) for i in range(4)]], results)
        self.assertEqual(peak, 2)
        self.assertEqual(active, 0)
        self.assertEqual(len(worker_threads), 2)
        self.assertNotIn(get_ident(), worker_threads)
        self.assertEqual({result.trade_id for result in results}, {"0", "1", "2", "3"})

    def test_price_waits_for_the_last_job_before_returning(self):
        started = Event()
        release = Event()

        def price(trade, receiver):
            started.set()
            if not release.wait(5):
                raise RuntimeError("Test release was not received")
            receiver.add_result(trade.trade_id, 42.0)

        pricer = self._configured_pricer(price)
        results = ScalarResults()
        with ThreadPoolExecutor(max_workers=1) as caller:
            call = caller.submit(pricer.price, [[BondTrade("Trade")]], results)
            try:
                self.assertTrue(started.wait(5))
                self.assertFalse(call.done())
            finally:
                release.set()
            call.result(timeout=5)
        self.assertEqual(results["Trade"].result, 42.0)

    def test_submission_limit_preserves_streaming_on_the_calling_thread(self):
        state_lock = Lock()
        produced = 0
        completed = 0
        peak = 0
        caller_thread = get_ident()

        def trades():
            nonlocal produced, peak
            for index in range(40):
                self.assertEqual(get_ident(), caller_thread)
                with state_lock:
                    self.assertLess(produced - completed, 2, "Input was consumed beyond the pending limit")
                    produced += 1
                    peak = max(peak, produced - completed)
                yield BondTrade(str(index))

        def price(trade, receiver):
            nonlocal completed
            time.sleep(0.005)
            receiver.add_result(trade.trade_id, 42.0)
            with state_lock:
                completed += 1

        results = ScalarResults()
        self._configured_pricer(price).price([trades()], results)
        self.assertEqual(produced, 40)
        self.assertEqual(completed, 40)
        self.assertLessEqual(peak, 2)
        self.assertEqual(len(list(results)), 40)

    def test_a_completed_job_allows_more_work_while_an_earlier_job_is_running(self):
        release_first = Event()
        third_started = Event()

        def price(trade, receiver):
            if trade.trade_id == "First":
                if not release_first.wait(5):
                    raise RuntimeError("A completed slot was not reused")
            elif trade.trade_id == "Third":
                third_started.set()
                release_first.set()
            receiver.add_result(trade.trade_id, 42.0)

        results = ScalarResults()
        self._configured_pricer(price).price(
            [[BondTrade("First"), BondTrade("Second"), BondTrade("Third")]], results
        )
        self.assertTrue(third_started.is_set())
        self.assertEqual(len(list(results)), 3)

    def test_receiver_writes_are_serialized_and_preserve_values(self):
        barrier = Barrier(2, timeout=5)

        def price(trade, receiver):
            barrier.wait()
            receiver.add_result(trade.trade_id, 0.0)
            receiver.add_error(trade.trade_id, None if trade.trade_id == "First" else "Model warning")

        receiver = GuardedResultReceiver()
        self._configured_pricer(price).price([[BondTrade("First"), BondTrade("Second")]], receiver)
        self.assertCountEqual(receiver.calls, [
            ("result", "First", 0.0), ("error", "First", None),
            ("result", "Second", 0.0), ("error", "Second", "Model warning"),
        ])

    def test_worker_failure_joins_running_jobs_and_closes_inputs(self):
        failure = RuntimeError("Unexpected pricing failure")
        started = Event()
        release = Event()
        finished = Event()
        closed = []

        def price(trade, receiver):
            if trade.trade_id == "Failed":
                raise failure
            started.set()
            if not release.wait(5):
                raise RuntimeError("Test release was not received")
            receiver.add_result(trade.trade_id, 42.0)
            finished.set()

        def trades():
            try:
                yield BondTrade("Failed")
                yield BondTrade("Running")
                raise AssertionError("Input was consumed after the failed window")
            finally:
                closed.append("trades")

        source = trades()

        def containers():
            try:
                yield source
                raise AssertionError("Another source was requested after failure")
            finally:
                closed.append("containers")

        streams = containers()
        results = ScalarResults()
        pricer = self._configured_pricer(price)
        with ThreadPoolExecutor(max_workers=1) as caller:
            call = caller.submit(pricer.price, streams, results)
            try:
                self.assertTrue(started.wait(5))
                self.assertFalse(call.done())
            finally:
                release.set()
            with self.assertRaises(RuntimeError) as raised:
                call.result(timeout=5)
        self.assertIs(raised.exception, failure)
        self.assertTrue(finished.is_set())
        self.assertEqual(closed, ["trades", "containers"])
        self.assertEqual(results["Running"].result, 42.0)

    def test_input_failure_waits_for_already_submitted_work(self):
        failure = ValueError("Malformed input record")
        started = Event()
        release = Event()

        def price(trade, receiver):
            started.set()
            if not release.wait(5):
                raise RuntimeError("Test release was not received")
            receiver.add_result(trade.trade_id, 42.0)

        def trades():
            yield BondTrade("Valid")
            raise failure

        results = ScalarResults()
        pricer = self._configured_pricer(price)
        with ThreadPoolExecutor(max_workers=1) as caller:
            call = caller.submit(pricer.price, [trades()], results)
            try:
                self.assertTrue(started.wait(5))
                self.assertFalse(call.done())
            finally:
                release.set()
            with self.assertRaises(ValueError) as raised:
                call.result(timeout=5)
        self.assertIs(raised.exception, failure)
        self.assertEqual(results["Valid"].result, 42.0)

    def test_duplicate_results_are_rejected(self):
        barrier = Barrier(2, timeout=5)

        def price(trade, receiver):
            barrier.wait()
            receiver.add_result(trade.trade_id, 42.0)

        with self.assertRaisesRegex(ValueError, "already been added"):
            self._configured_pricer(price).price([[BondTrade("Same"), BondTrade("Same")]], ScalarResults())

    def test_receiver_failures_are_not_swallowed(self):
        failure = ValueError("Result storage failed")
        receiver = Mock(spec=ResultReceiver)
        receiver.add_result.side_effect = failure
        pricer = self._configured_pricer(lambda trade, target: target.add_result(trade.trade_id, 42.0))
        with self.assertRaises(ValueError) as raised:
            pricer.price([[BondTrade("Trade")]], receiver)
        self.assertIs(raised.exception, failure)

    def test_empty_inputs_and_repeated_calls_with_one_worker(self):
        pricer = self._configured_pricer(lambda trade, receiver: receiver.add_result(trade.trade_id, 42.0), 1)
        results = ScalarResults()
        pricer.price([], results)
        pricer.price([[]], results)
        self.assertEqual(list(results), [])
        for trade_id in ("First", "Second"):
            pricer.price([[BondTrade(trade_id)]], results)
        self.assertEqual([result.trade_id for result in results], ["First", "Second"])

    def test_configuration_failure_does_not_consume_inputs(self):
        consumed = []

        def containers():
            consumed.append(True)
            yield [BondTrade("Trade")]

        pricer = ParallelPricer()
        with patch.object(pricer, "_load_pricers", side_effect=RuntimeError("Invalid configuration")):
            with self.assertRaisesRegex(RuntimeError, "Invalid configuration"):
                pricer.price(containers(), ScalarResults())
        self.assertEqual(consumed, [])

    def test_missing_receiver_is_rejected_before_loading(self):
        pricer = ParallelPricer()
        with patch.object(pricer, "_load_pricers") as load_pricers:
            with self.assertRaisesRegex(ValueError, "result_receiver"):
                pricer.price([], None)
            load_pricers.assert_not_called()

    def test_supplied_feeds_match_serial_results(self):
        serial_results = ScalarResults()
        parallel_results = ScalarResults()
        with patch("techtest.pricers.base_pricing_engine.time.sleep"), \
                patch("techtest.pricers.base_pricing_engine.BasePricingEngine._calculate_result", return_value=42.0), \
                redirect_stdout(io.StringIO()):
            SerialPricer().price(SerialTradeLoader().load_trades(), serial_results)
            ParallelPricer().price(SerialTradeLoader().load_trades(), parallel_results)

        self.assertEqual(len(list(parallel_results)), 14)
        self.assertEqual(
            {result.trade_id: result for result in parallel_results},
            {result.trade_id: result for result in serial_results},
        )


if __name__ == "__main__":
    unittest.main()
