from __future__ import annotations

import importlib
import os
from typing import Iterable

from techtest.models import PricingEngine, ResultReceiver, Trade
from techtest.risk_system.pricing_config_loader import PricingConfigLoader


class SerialPricer:
    def __init__(self) -> None:
        self._pricers: dict[str, PricingEngine] = {}

    def price(self, trade_containers: Iterable[Iterable[Trade]], result_receiver: ResultReceiver) -> None:
        self._load_pricers()

        for trade_container in trade_containers:
            for trade in trade_container:
                if trade.trade_type not in self._pricers:
                    result_receiver.add_error(trade.trade_id, "No Pricing Engines available for this trade type")
                    continue

                pricer = self._pricers[trade.trade_type]
                pricer.price(trade, result_receiver)

    def _load_pricers(self) -> None:
        pricing_config_loader = PricingConfigLoader()
        pricing_config_loader.config_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "pricing_config", "PricingEngines.xml")
        pricer_config = pricing_config_loader.load_config()

        pricers: dict[str, PricingEngine] = {}
        for config_item in pricer_config:
            try:
                module = importlib.import_module(config_item.module)
                engine_class = getattr(module, config_item.class_name)
                if not isinstance(engine_class, type) or not issubclass(engine_class, PricingEngine):
                    raise TypeError("Configured class must be a PricingEngine subclass")
                pricers[config_item.trade_type] = engine_class()
            except Exception as exc:
                # Include the configuration entry while retaining the original cause.
                raise RuntimeError(
                    f"Could not load pricing engine {config_item.module}.{config_item.class_name} "
                    f"for trade type {config_item.trade_type!r}: {exc}"
                ) from exc

        # Replace the mapping only after every configured engine has loaded.
        self._pricers = pricers
