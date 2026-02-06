import unittest

from . import scan


class ParseCacheKeyTest(unittest.TestCase):
    def setUp(self) -> None:
        with scan._parse_cache_lock:
            scan._parse_cache.clear()

    def test_cache_key_includes_suffix(self) -> None:
        scan._store_cached_parse("ts", "hash", ".ts", 1, [{"spec": "a"}])

        cached_ts = scan._get_cached_parse("ts", "hash", ".ts")
        cached_vue = scan._get_cached_parse("ts", "hash", ".vue")

        self.assertIsNotNone(cached_ts)
        self.assertIsNone(cached_vue)


if __name__ == "__main__":
    unittest.main()
