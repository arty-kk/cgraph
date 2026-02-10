import ipaddress
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import settings  # noqa: E402
from app.infra import rate_limit  # noqa: E402


class TestRateLimitTrustedProxy(unittest.TestCase):
    def setUp(self) -> None:
        self.original_trusted_proxy_cidrs = settings.trusted_proxy_cidrs
        rate_limit._parse_trusted_proxy_networks.cache_clear()

    def tearDown(self) -> None:
        settings.trusted_proxy_cidrs = self.original_trusted_proxy_cidrs
        rate_limit._parse_trusted_proxy_networks.cache_clear()

    def test_client_is_trusted_proxy_valid_and_invalid_cidrs(self) -> None:
        settings.trusted_proxy_cidrs = "10.0.0.0/8, invalid-cidr, 192.168.1.0/24"

        self.assertTrue(rate_limit._client_is_trusted_proxy("10.10.1.1"))
        self.assertTrue(rate_limit._client_is_trusted_proxy("192.168.1.77"))
        self.assertFalse(rate_limit._client_is_trusted_proxy("172.16.0.1"))
        self.assertFalse(rate_limit._client_is_trusted_proxy("not-an-ip"))

    def test_parsing_not_repeated_for_same_config_value(self) -> None:
        settings.trusted_proxy_cidrs = "10.0.0.0/8,192.168.1.0/24"
        original_ip_network = ipaddress.ip_network

        with patch("app.infra.rate_limit.ipaddress.ip_network", wraps=original_ip_network) as spy:
            self.assertTrue(rate_limit._client_is_trusted_proxy("10.1.2.3"))
            self.assertTrue(rate_limit._client_is_trusted_proxy("192.168.1.5"))

        self.assertEqual(spy.call_count, 2)

    def test_cache_key_changes_when_config_value_changes(self) -> None:
        original_ip_network = ipaddress.ip_network

        with patch("app.infra.rate_limit.ipaddress.ip_network", wraps=original_ip_network) as spy:
            settings.trusted_proxy_cidrs = "10.0.0.0/8"
            self.assertTrue(rate_limit._client_is_trusted_proxy("10.1.2.3"))

            settings.trusted_proxy_cidrs = "192.168.1.0/24"
            self.assertTrue(rate_limit._client_is_trusted_proxy("192.168.1.5"))

        self.assertEqual(spy.call_count, 2)

    def test_invalid_cidr_warning_logged_once_for_same_config_value(self) -> None:
        settings.trusted_proxy_cidrs = "invalid-cidr"

        with patch("app.infra.rate_limit.logger.warning") as warning_spy:
            self.assertFalse(rate_limit._client_is_trusted_proxy("10.1.2.3"))
            self.assertFalse(rate_limit._client_is_trusted_proxy("10.2.3.4"))

        self.assertEqual(warning_spy.call_count, 1)

    def test_invalid_cidr_warning_relogged_after_config_change(self) -> None:
        with patch("app.infra.rate_limit.logger.warning") as warning_spy:
            settings.trusted_proxy_cidrs = "invalid-cidr-1"
            self.assertFalse(rate_limit._client_is_trusted_proxy("10.1.2.3"))

            settings.trusted_proxy_cidrs = "invalid-cidr-2"
            self.assertFalse(rate_limit._client_is_trusted_proxy("10.1.2.4"))

        self.assertEqual(warning_spy.call_count, 2)


if __name__ == "__main__":
    unittest.main()
