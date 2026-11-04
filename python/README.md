# Risk system tech test (Python)

The exercises are in [candidate-instructions.md](./candidate-instructions.md).

## Requirements

Python 3.9 or later. Only the Python standard library is used: there is nothing to install.

## Running the tests

From this folder:

```
python3 -m unittest discover -s tests -t .
```

The suite includes the original tests and additional regression tests for the
completed exercises. Concurrency tests use synchronization primitives to check
overlapping work and completion, rather than asserting a machine-specific speedup.

## Running the application

From this folder:

```
python3 -m techtest.console_app
```

The application uses `ParallelPricer`. By default, the worker limit is
`min(32, (os.cpu_count() or 1) + 4)`, matching the Python 3.9 thread-pool heuristic.
For example, 12 reported logical CPUs give a limit of 16 workers. This is a
starting point for the supplied waiting-based workload, not a measured optimum.
Use `ParallelPricer(max_workers=4)` to set an explicit limit. CPU counts may not
reflect scheduler or container quotas; tune the limit for the workload, memory
budget and any threads used inside the pricing engine. The supplied engines
return simulated prices, so numeric results vary between runs.

## Implementation decisions

- Both loaders use strict CSV parsing with their feed's delimiter, UTF-8 with an
  optional BOM, and support for quoted delimiters, escaped quotes and newlines.
  Blank records are skipped. The column names and order must match the supplied
  schemas; each trade must have exactly the expected number of fields. Format
  errors include the file and physical line at which parsing failed.
- The FX feed must start with `FxTrades` and an ISO-formatted feed date and end
  with an `END` marker. Missing `END` is treated as an incomplete feed, even if
  earlier records were valid. Reading stops at the first `END`, as before.
  Its trailing number is not interpreted or checked: the sample contains four
  trades but ends with `END` and `5`, and the number's meaning is undocumented.
  Bond feeds have no trailer and cannot detect truncation at a record boundary.
- Amounts/notionals and rates must be finite numbers; `NaN`, infinity and
  overflowing numeric inputs are rejected. Zero and negative values are
  preserved. Product types and unusual but valid dates are also preserved;
  business validation requires rules not supplied by this exercise.
- Configuration rejects missing engine attributes and duplicate trade types.
  Engines are imported dynamically through the existing interface and loaded
  completely before replacing the registry. Configuration is assumed trusted.
  Unsupported types, including the supplied Supra trade, produce an error.
- Results retain both a price and any accompanying warning, with one record per
  trade ID. Zero is a valid price; only `None` means absent. Trade IDs are assumed
  unique across input sources. Output follows the requested three formats.
- Bond and FX feeds are single-use iterators: records are parsed as the pricer
  requests them. Call `load_trades()` again to reread a feed. Input errors are
  raised when encountered, after earlier trades may already have been priced.
- `ParallelPricer` reuses `SerialPricer`'s engine loading and single-trade routing.
  It keeps at most `max_workers` submitted futures pending and waits for a
  completion before reading more trades. This preserves bounded trade buffering;
  stored results still grow with the number of trades, as allowed by exercise 7.
- A lock protects calls to the result receiver, including its duplicate checks.
  Pricing itself runs outside that lock. The caller should read the results after
  `price()` returns and should not concurrently reuse the same pricer or receiver.
- Engine instances are shared between workers and must support concurrent calls.
  The supplied engines read their configuration and use the thread-safe
  `Random.random()` implementation. A future engine with mutable calculation
  state would need synchronization or a separate instance per worker.
- Threads suit the supplied `sleep`-based simulated work. Pure Python CPU-bound
  calculations on CPython with the GIL would generally need a different approach,
  such as worker processes with explicit result transfer.
- Normal return means all trades have finished. Unexpected engine, receiver or
  input failures propagate to the caller; already submitted work is joined and
  results may be partial. Such results must not be treated as a completed batch;
  a full retry should use fresh input iterators and a fresh receiver. Durable
  checkpoints, automatic retries and timeouts are outside this exercise's scope.
  Consumed iterators are closed when supported, including when processing stops
  due to an error. Result order is not guaranteed to match input order.

Relevant standard-library documentation: [csv](https://docs.python.org/3.9/library/csv.html),
[concurrent.futures](https://docs.python.org/3.9/library/concurrent.futures.html),
[threading](https://docs.python.org/3.9/library/threading.html), and
[random](https://docs.python.org/3.9/library/random.html).
