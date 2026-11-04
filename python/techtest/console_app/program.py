from __future__ import annotations

from techtest.models import ScalarResults
from techtest.risk_system import ScreenResultPrinter, SerialPricer, SerialTradeLoader


def main() -> None:
    trade_loader = SerialTradeLoader()

    trade_streams = trade_loader.load_trades()
    results = ScalarResults()
    pricer = SerialPricer()
    pricer.price(trade_streams, results)

    screen_printer = ScreenResultPrinter()
    screen_printer.print_results(results)


if __name__ == "__main__":
    main()
