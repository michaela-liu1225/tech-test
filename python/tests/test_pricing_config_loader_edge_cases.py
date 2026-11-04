import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from techtest.risk_system import (
    PRICING_CONFIG_DIR,
    PricingConfigLoader,
    PricingEngineConfig,
    PricingEngineConfigItem,
)


class PricingConfigLoaderEdgeCaseTests(unittest.TestCase):
    def _load_xml(self, content: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "PricingEngines.xml"
            path.write_text(content, encoding="utf-8")
            loader = PricingConfigLoader()
            loader.config_file = str(path)
            return loader.load_config()

    def test_all_mappings_keep_file_order_and_allow_shared_engine_classes(self):
        loader = PricingConfigLoader()
        loader.config_file = os.path.join(PRICING_CONFIG_DIR, "PricingEngines.xml")
        config = loader.load_config()
        expected = [
            PricingEngineConfigItem("GovBond", "techtest.pricers", "GovBondPricingEngine"),
            PricingEngineConfigItem("CorpBond", "techtest.pricers", "CorpBondPricingEngine"),
            PricingEngineConfigItem("FxSpot", "techtest.pricers", "FxPricingEngine"),
            PricingEngineConfigItem("FxFwd", "techtest.pricers", "FxPricingEngine"),
        ]
        self.assertIsInstance(config, PricingEngineConfig)
        self.assertEqual(list(config), expected)
        self.assertEqual(list(config), expected)  # The result can be iterated again.

    def test_bom_comments_and_reordered_attributes_are_supported(self):
        config = self._load_xml(
            '\ufeff<?xml version="1.0" encoding="utf-8"?>\n'
            '<PricingEngines><!-- FX configuration -->\n'
            '  <Engine class=" FxPricingEngine " tradeType=" FxSpot "\n'
            '          module=" techtest.pricers " />\n'
            '</PricingEngines>'
        )
        self.assertEqual(config, [
            PricingEngineConfigItem("FxSpot", "techtest.pricers", "FxPricingEngine"),
        ])

    def test_loading_does_not_require_the_engine_module_to_exist(self):
        config = self._load_xml(
            '<PricingEngines><Engine tradeType="CustomTrade" '
            'module="not_installed_pricing_module" class="CustomEngine" /></PricingEngines>'
        )
        self.assertEqual(config, [
            PricingEngineConfigItem("CustomTrade", "not_installed_pricing_module", "CustomEngine"),
        ])

    def test_required_attributes_must_not_be_missing_or_blank(self):
        for name in ("tradeType", "module", "class"):
            for value in (None, "", "   "):
                with self.subTest(attribute=name, value=value):
                    attributes = {
                        "tradeType": "FxSpot", "module": "techtest.pricers", "class": "FxPricingEngine",
                    }
                    if value is None:
                        del attributes[name]
                    else:
                        attributes[name] = value
                    root = ET.Element("PricingEngines")
                    ET.SubElement(root, "Engine", attributes)
                    with self.assertRaisesRegex(ValueError, f"Engine 1.*{name!r}"):
                        self._load_xml(ET.tostring(root, encoding="unicode"))

    def test_duplicate_trade_types_are_rejected(self):
        for second_class in ("GovBondPricingEngine", "OtherEngine"):
            with self.subTest(second_class=second_class):
                with self.assertRaisesRegex(ValueError, "duplicate tradeType 'GovBond'"):
                    self._load_xml(
                        '<PricingEngines>'
                        '<Engine tradeType="GovBond" module="techtest.pricers" class="GovBondPricingEngine" />'
                        f'<Engine tradeType="GovBond" module="techtest.pricers" class="{second_class}" />'
                        '</PricingEngines>'
                    )

    def test_wrong_root_and_unexpected_entries_are_rejected(self):
        for content, message in (
            ("<WrongRoot />", "expected a PricingEngines root"),
            ("<PricingEngines><Engin /></PricingEngines>", "unexpected element 'Engin'"),
        ):
            with self.subTest(content=content):
                with self.assertRaisesRegex(ValueError, message):
                    self._load_xml(content)

    def test_empty_configuration_returns_an_empty_list(self):
        self.assertEqual(self._load_xml("<PricingEngines />"), [])

    def test_config_file_must_be_set(self):
        for path in (None, ""):
            with self.subTest(path=path):
                loader = PricingConfigLoader()
                loader.config_file = path
                with self.assertRaisesRegex(ValueError, "configuration file must be provided"):
                    loader.load_config()

    def test_missing_file_error_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            loader = PricingConfigLoader()
            loader.config_file = str(Path(directory) / "missing.xml")
            with self.assertRaises(FileNotFoundError):
                loader.load_config()

    def test_malformed_xml_error_is_not_hidden(self):
        with self.assertRaises(ET.ParseError):
            self._load_xml("<PricingEngines><Engine></PricingEngines>")


if __name__ == "__main__":
    unittest.main()
