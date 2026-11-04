# Risk system tech test (Python)

The exercises are in [candidate-instructions.md](./candidate-instructions.md).

## Requirements

Python 3.9 or later. Only the Python standard library is used: there is nothing to install.

## Running the tests

From this folder:

```sh
python3 -m unittest discover -s tests -t .
```

The original tests are unchanged; extra tests cover invalid input and edge cases.
Concurrency tests coordinate workers explicitly, so they check overlapping work
and completion without depending on machine speed.

## Running the application

From this folder:

```sh
python3 -m techtest.console_app
```

The application uses `ParallelPricer`. Prices are simulated and vary between runs.

## Decisions by task

### Task 1: Load government and corporate bonds

**Problem:** Bonds share the same fields, but their types select different pricing engines.

- **Keep one `BondTrade` model and preserve the feed's type.** This avoids duplicate
  models and prevents corporate or unsupported bonds from being priced as government bonds.
  Use `Type`, not the ID prefix: `GOV007` is a `Supra` trade.
- **Use `csv.reader` and validate columns, field counts and values.** Handle quoted
  fields correctly and locate bad records with file/line errors. Accept common UTF-8
  exports (including the optional BOM encoding marker) and skip blank records.
- **Reject invalid dates, `NaN` and infinity; keep zero, negatives and valid dates.**
  This catches unusable input without inventing business rules.

### Task 2: Load FX trades

**Problem:** FX uses a different file layout and stores the currency pair in two columns.

- **Use `csv.reader(delimiter="¬")` with Task 1's validation policy.** Handle quoted
  fields without manual splitting. Different delimiters or columns need explicit
  parser/schema changes and tests.
- **Combine `Ccy1 + Ccy2` and preserve source types, IDs and dates.** Even the sample's
  past value date and year `2112` remain unchanged: no business rule was supplied
  to correct dates or reclassify spot/forward trades.
- **Validate the `FxTrades` header/date and require `END`.** This catches a missing
  trailer; reading stops at the first `END`. Bond feeds have no equivalent completeness check.
- **Leave the trailer number unchecked.** Four sample trades end with `END¬5`;
  its meaning is undocumented, so treating it as a trade count would reject valid input.

### Task 3: Read pricing configuration

**Problem:** The system needs a reliable mapping from trade types to engine classes.

- **Parse XML with standard-library `ElementTree` into a reusable list.** Configuration
  is small and can be fully checked before pricing. Unlike large, single-pass trade
  feeds (Task 7), it can stay in memory and be read repeatedly without reopening the file.
- **Reject unexpected structure, missing attributes and duplicate trade types.**
  Fail early with a useful error, avoiding ambiguous engine selection.

### Task 4: Load and select pricing engines

**Problem:** Direct imports would make the core system depend on each concrete engine.

- **Use `importlib` and the existing `PricingEngine` interface.** An engine can be added
  with code and an XML entry, leaving routing unchanged. Configuration must be trusted:
  it selects executable Python classes.
- **Build and validate the complete engine mapping before replacing the old one.**
  Failed imports cannot leave a partly updated mapping; errors retain their original cause.
- **Report an error for an unsupported type, including `Supra`, and continue.**
  No Supra engine or XML mapping is supplied. Preserve its type and record the missing
  engine; substituting a government engine or zero price would misrepresent the result.
  To support Supra later, define its pricing rule, provide a suitable engine, add its
  XML entry and tests. Routing stays unchanged; extend models/loaders only if new fields are needed.

### Task 5: Iterate over results

**Problem:** Prices and errors are stored separately, but callers need one record per trade.

- **Yield priced trades with any warning, then error-only trades.** Both pieces of
  information survive, each ID appears once, and no extra list or set is needed.
- **Assume IDs are unique across feeds; reject a second price or error for an ID.**
  This prevents overwriting stored values. A price plus a warning is allowed;
  these checks do not validate global uniqueness of input trade IDs.

### Task 6: Print results

**Problem:** Output must handle a price, an error, or both without hiding valid values.

- **Reuse Task 5's iterator and join the present fields with ` : `.** One formatting
  path covers all three required formats without repeating merge logic.
- **Treat only `None` as absent; keep numeric values unchanged.** Zero prices and
  warnings remain visible, and no unspecified rounding rule is introduced.

### Task 7: Stream trade input

**Problem:** Loading every trade before pricing makes input memory grow with file size.

- **Use generators throughout the loading pipeline.** Open files and parse records
  only when requested, so pricing can start before the whole feed is loaded.
- **Keep streams single-use, without caching or a separate validation pass.** This
  avoids storing or reading the whole feed twice. Call `load_trades()` again to reread;
  errors appear when reached, possibly after earlier trades have been priced.
- **Keep results in memory, as permitted by the exercise.** This limits input buffering;
  total memory still grows with the number of stored results.

### Task 8: Price trades concurrently

**Problem:** Serial pricing waits for each trade, but unrestricted parallel work can exhaust memory.

- **Reuse engine loading/selection and add a thread pool.** Rules stay in one place,
  while the supplied `sleep`-based waits overlap. For CPU-heavy pure Python under the
  GIL, consider processes with result transfer.
- **Default to `min(32, (os.cpu_count() or 1) + 4)` workers, with an override.** Extra
  workers overlap waits; the cap limits the default. This is a starting point: use
  `ParallelPricer(max_workers=4)` to tune for CPU quotas, memory and engine threads.
- **Keep at most `max_workers` submitted tasks pending.** Wait for capacity before
  reading more trades, so queued work cannot undo Task 7's memory savings.
- **Lock result updates, including duplicate checks, but leave pricing outside the lock.**
  Calculations overlap while stored results remain protected. Read them after `price()`
  returns; do not reuse the pricer or receiver across simultaneous batches.
- **Share engine instances that support concurrent calls.** This avoids unnecessary
  copies. A stateful engine needs its own protection or an instance per worker;
  the result lock does not protect engine state.
- **Record unsupported types and engine-reported errors per trade; raise malformed-feed,
  configuration and unexpected
  engine/receiver failures.** This separates missing pricing coverage from a broken batch.
  Wait for submitted work and close consumed iterators where supported. Normal return
  means all results are available; after a failure, treat results as partial and use
  fresh iterators and a fresh receiver for a full retry.
  Output order is not guaranteed; automatic retries, timeouts and recovery after a restart are out of scope.
