import asyncio
import importlib
import json
import sys
import time
import types
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def install_astrbot_stubs():
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    event_module = types.ModuleType("astrbot.api.event")
    star_module = types.ModuleType("astrbot.api.star")

    class DummyAstrBotConfig(dict):
        pass

    class DummyLogger:
        def exception(self, *_args, **_kwargs):
            return None

        def info(self, *_args, **_kwargs):
            return None

    class DummyStar:
        def __init__(self, context):
            self.context = context

    class DummyContext:
        pass

    class DummyAstrMessageEvent:
        def plain_result(self, text):
            return text

    def command(_name):
        def decorator(func):
            return func

        return decorator

    def register(*_args, **_kwargs):
        def decorator(cls):
            return cls

        return decorator

    event_module.filter = types.SimpleNamespace(command=command)
    event_module.AstrMessageEvent = DummyAstrMessageEvent
    star_module.Context = DummyContext
    star_module.Star = DummyStar
    star_module.register = register
    api_module.AstrBotConfig = DummyAstrBotConfig
    api_module.logger = DummyLogger()

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module
    sys.modules["astrbot.api.event"] = event_module
    sys.modules["astrbot.api.star"] = star_module


class FakeResponse:
    def __init__(self, payload=None, raw_bytes=None):
        self._payload = payload
        self._raw_bytes = raw_bytes

    def read(self, size=-1):
        data = self._raw_bytes
        if data is None:
            data = json.dumps(self._payload).encode("utf-8")
        if size is None or size < 0:
            return data
        return data[:size]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class AuthHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_astrbot_stubs()
        cls.main = importlib.import_module("main")

    def setUp(self):
        self.config = self.main.AstrBotConfig()
        self.plugin = self.main.KepCsServerStatusPlugin(
            context=None,
            config=self.config,
        )

    def test_build_api_headers_supports_both_header_styles(self):
        self.config[self.plugin.API_KEY_CONFIG_KEY] = "test-api-key"
        headers = self.plugin._build_api_headers()

        self.assertEqual(headers["X-API-Key"], "test-api-key")
        self.assertEqual(headers["Authorization"], "Bearer test-api-key")
        self.assertNotIn("?key=", self.plugin._get_serverlist_url())

    def test_build_api_headers_supports_custom_bearer_token(self):
        self.config[self.plugin.API_KEY_CONFIG_KEY] = "test-api-key"
        self.config[self.plugin.BEARER_TOKEN_CONFIG_KEY] = "test-bearer-token"

        headers = self.plugin._build_api_headers()

        self.assertEqual(headers["X-API-Key"], "test-api-key")
        self.assertEqual(headers["Authorization"], "Bearer test-bearer-token")

    def test_build_api_headers_supports_bearer_only_config(self):
        self.config[self.plugin.BEARER_TOKEN_CONFIG_KEY] = "test-bearer-token"

        headers = self.plugin._build_api_headers()

        self.assertNotIn("X-API-Key", headers)
        self.assertEqual(headers["Authorization"], "Bearer test-bearer-token")

    def test_get_serverlist_url_supports_plugin_config_override(self):
        custom_url = "https://example.com/api/serverlist"
        self.config[self.plugin.SERVERLIST_URL_CONFIG_KEY] = custom_url

        self.assertEqual(self.plugin._get_serverlist_url(), custom_url)

    def test_build_api_headers_requires_plugin_config_credentials(self):
        with self.assertRaisesRegex(
            RuntimeError,
            f"{self.plugin.API_KEY_CONFIG_KEY}` or `{self.plugin.BEARER_TOKEN_CONFIG_KEY}",
        ):
            self.plugin._build_api_headers()

    def test_fetch_server_list_uses_headers_and_never_query_key(self):
        self.config[self.plugin.API_KEY_CONFIG_KEY] = "test-api-key"
        captured = {}
        original_urlopen = self.main.request.urlopen

        def fake_urlopen(req, timeout=0):
            captured["request"] = req
            captured["timeout"] = timeout
            return FakeResponse({"servers": []})

        self.main.request.urlopen = fake_urlopen
        try:
            payload = self.plugin._fetch_server_list_payload()
        finally:
            self.main.request.urlopen = original_urlopen

        parsed_url = urlparse(captured["request"].full_url)
        query_params = parse_qs(parsed_url.query)
        request_headers = dict(captured["request"].header_items())

        self.assertEqual(payload, {"servers": []})
        self.assertEqual(parsed_url.scheme, "https")
        self.assertEqual(parsed_url.netloc, "kepapi.kaish.cn")
        self.assertEqual(parsed_url.path, "/api/kepcs/serverlist")
        self.assertNotIn("key", query_params)
        self.assertEqual(request_headers["X-api-key"], "test-api-key")
        self.assertEqual(request_headers["Authorization"], "Bearer test-api-key")
        self.assertEqual(captured["timeout"], self.plugin.API_TIMEOUT_SECONDS)

    def test_fetch_server_list_supports_bearer_only_header(self):
        self.config[self.plugin.BEARER_TOKEN_CONFIG_KEY] = "test-bearer-token"
        captured = {}
        original_urlopen = self.main.request.urlopen

        def fake_urlopen(req, timeout=0):
            captured["request"] = req
            captured["timeout"] = timeout
            return FakeResponse({"servers": []})

        self.main.request.urlopen = fake_urlopen
        try:
            payload = self.plugin._fetch_server_list_payload()
        finally:
            self.main.request.urlopen = original_urlopen

        request_headers = dict(captured["request"].header_items())

        self.assertEqual(payload, {"servers": []})
        self.assertNotIn("X-api-key", request_headers)
        self.assertEqual(request_headers["Authorization"], "Bearer test-bearer-token")
        self.assertEqual(captured["timeout"], self.plugin.API_TIMEOUT_SECONDS)

    def test_fetch_server_list_rejects_oversized_response(self):
        self.config[self.plugin.API_KEY_CONFIG_KEY] = "test-api-key"
        original_urlopen = self.main.request.urlopen

        def fake_urlopen(_req, timeout=0):
            del timeout
            return FakeResponse(raw_bytes=b"a" * (self.plugin.MAX_RESPONSE_BYTES + 1))

        self.main.request.urlopen = fake_urlopen
        try:
            with self.assertRaisesRegex(RuntimeError, "API response too large"):
                self.plugin._fetch_server_list_payload()
        finally:
            self.main.request.urlopen = original_urlopen

    def test_build_result_sanitizes_remote_fields(self):
        result = self.plugin._build_result(
            {
                "name": "[bad](name)",
                "host": "bad host&evil=1",
                "port": 27015,
                "mode": "ze_pt",
                "status": "ok",
                "current_players": 5,
                "max_players": 64,
                "map": "ze_test_*",
            }
        )

        self.assertEqual(result.group, "ze_pt")
        self.assertEqual(result.player_count, 5)
        self.assertFalse(result.is_unavailable)
        self.assertIn(r"\[bad\]\(name\)", result.line)
        self.assertIn(r"Map: **ze\_test\_\***", result.line)
        self.assertIn("[0.0.0.0:27015]", result.line)
        self.assertIn("ip=0.0.0.0%3A27015", result.line)

    def test_validate_payload_rejects_excessive_server_count(self):
        payload = {"servers": [{}] * (self.plugin.MAX_SERVER_COUNT + 1)}

        with self.assertRaisesRegex(RuntimeError, "too many servers"):
            self.plugin._validate_payload(payload)

    def test_validate_payload_filters_non_dict_entries(self):
        payload = self.plugin._validate_payload({"servers": [{"name": "ok"}, "bad", 1]})

        self.assertEqual(payload, {"servers": [{"name": "ok"}]})


class AsyncFetchProtectionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        install_astrbot_stubs()
        cls.main = importlib.import_module("main")

    async def asyncSetUp(self):
        self.plugin = self.main.KepCsServerStatusPlugin(
            context=None,
            config=self.main.AstrBotConfig(),
        )

    async def test_concurrent_calls_share_single_upstream_fetch(self):
        fetch_count = 0

        def fake_fetch():
            nonlocal fetch_count
            fetch_count += 1
            time.sleep(0.05)
            return {"servers": []}

        self.plugin._fetch_server_list_payload = fake_fetch

        first, second = await asyncio.gather(
            self.plugin._get_server_list_payload(),
            self.plugin._get_server_list_payload(),
        )

        self.assertEqual(first, {"servers": []})
        self.assertEqual(second, {"servers": []})
        self.assertEqual(fetch_count, 1)

    async def test_cached_payload_is_reused_within_cache_window(self):
        fetch_count = 0

        def fake_fetch():
            nonlocal fetch_count
            fetch_count += 1
            return {"servers": [{"name": "cached"}]}

        self.plugin._fetch_server_list_payload = fake_fetch

        first = await self.plugin._get_server_list_payload()
        second = await self.plugin._get_server_list_payload()

        self.assertEqual(first, second)
        self.assertEqual(fetch_count, 1)

    async def test_failed_fetch_is_short_term_cached_to_reduce_retry_storms(self):
        fetch_count = 0

        def fake_fetch():
            nonlocal fetch_count
            fetch_count += 1
            raise RuntimeError("boom")

        self.plugin._fetch_server_list_payload = fake_fetch

        with self.assertRaisesRegex(RuntimeError, "boom"):
            await self.plugin._get_server_list_payload()

        with self.assertRaisesRegex(RuntimeError, "boom"):
            await self.plugin._get_server_list_payload()

        self.assertEqual(fetch_count, 1)


if __name__ == "__main__":
    unittest.main()
