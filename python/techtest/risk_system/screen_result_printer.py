from __future__ import annotations

from techtest.models import ScalarResults


class ScreenResultPrinter:
    def print_results(self, results: ScalarResults) -> None:
        """Print each trade ID followed by its non-None result and error."""
        for result in results:
            fields = [result.trade_id]
            if result.result is not None:
                fields.append(str(result.result))
            if result.error is not None:
                fields.append(result.error)
            print(" : ".join(fields))
