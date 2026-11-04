from __future__ import annotations

import xml.etree.ElementTree as ET

from techtest.risk_system.pricing_engine_config import PricingEngineConfig
from techtest.risk_system.pricing_engine_config_item import PricingEngineConfigItem


class PricingConfigLoader:
    def __init__(self) -> None:
        self.config_file: str | None = None

    def load_config(self) -> PricingEngineConfig:
        if not self.config_file:
            raise ValueError("A pricing configuration file must be provided")

        root = ET.parse(self.config_file).getroot()
        if root.tag != "PricingEngines":
            raise ValueError(f"{self.config_file}: expected a PricingEngines root element")

        config = PricingEngineConfig()
        trade_types = set()
        for index, engine in enumerate(root, start=1):
            if engine.tag != "Engine":
                raise ValueError(f"{self.config_file}: unexpected element {engine.tag!r}")

            attributes = {}
            for name in ("tradeType", "module", "class"):
                value = engine.get(name, "").strip()
                if not value:
                    raise ValueError(
                        f"{self.config_file}: Engine {index} requires a non-empty {name!r} attribute"
                    )
                attributes[name] = value

            trade_type = attributes["tradeType"]
            if trade_type in trade_types:
                raise ValueError(f"{self.config_file}: duplicate tradeType {trade_type!r}")
            trade_types.add(trade_type)
            config.append(PricingEngineConfigItem(
                trade_type=trade_type,
                module=attributes["module"],
                class_name=attributes["class"],
            ))

        return config
