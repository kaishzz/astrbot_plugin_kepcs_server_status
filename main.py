import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib import error, request
from urllib.parse import urlencode

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


@dataclass(frozen=True)
class ServerStatusLine:
    group: str
    line: str
    player_count: int
    is_unavailable: bool


@register(
    "astrbot_plugin_kepcs_server_status",
    "kaish",
    "查询 KepCs 服务端信息",
    "1.2",
)
class KepCsServerStatusPlugin(Star):
    DEFAULT_SERVERLIST_URL = "https://kepapi.kaish.cn/api/kepcs/serverlist"
    SERVERLIST_URL_CONFIG_KEY = "serverlist_url"
    API_KEY_CONFIG_KEY = "api_key"
    BEARER_TOKEN_CONFIG_KEY = "bearer_token"
    USER_AGENT = "astrbot_plugin_kepcs_server_status"
    API_TIMEOUT_SECONDS = 5
    CACHE_TTL_SECONDS = 10
    ERROR_CACHE_TTL_SECONDS = 5
    MAX_RESPONSE_BYTES = 1024 * 1024
    MAX_SERVER_COUNT = 256
    MAX_TEXT_LENGTH = 120
    MAX_ERROR_TEXT_LENGTH = 180
    STATUS_OK = "ok"
    EMPTY_DATA_MESSAGE = "No server data from API"
    UNAVAILABLE_MESSAGE = "All servers unavailable\nOr being updated/maintained"
    OUTPUT_TITLE = "KepCS ServerList"
    ALL_BUSY_MESSAGE = "_All available servers are currently occupied_"
    GROUP_MAP = {
        "ze": "Play map",
        "ze_practice": "Practice map",
    }
    GROUP_ORDER = {
        "ze_practice": 0,
        "ze": 1,
    }
    SAFE_GROUP_PATTERN = re.compile(r"^[a-z0-9_-]{1,32}$")
    SAFE_HOST_PATTERN = re.compile(r"^[A-Za-z0-9.\-:]+$")
    MARKDOWN_ESCAPE_MAP = str.maketrans(
        {
            "\\": r"\\",
            "*": r"\*",
            "_": r"\_",
            "[": r"\[",
            "]": r"\]",
            "(": r"\(",
            ")": r"\)",
            "`": r"\`",
        }
    )

    def __init__(self, context: Context, config: Optional[AstrBotConfig] = None):
        super().__init__(context)
        self.context = context
        self.config = {} if config is None else config
        self._cache_lock = asyncio.Lock()
        self._cached_payload: Optional[Dict[str, List[Dict[str, Any]]]] = None
        self._cached_payload_at = 0.0
        self._last_fetch_error = ""
        self._last_fetch_error_at = 0.0

    @filter.command("kepcs_status")
    async def server_status(self, event: AstrMessageEvent):
        """Query KepCS server list."""

        try:
            payload = await self._get_server_list_payload()
            results = self._build_results(payload["servers"])

            if not results:
                yield event.plain_result(self.EMPTY_DATA_MESSAGE)
                return

            if all(result.is_unavailable for result in results):
                yield event.plain_result(self.UNAVAILABLE_MESSAGE)
                return

            yield event.plain_result(self._format_status_output(results))
        except RuntimeError as exc:
            logger.exception("Runtime error while querying KepCs status API")
            yield event.plain_result(f"Query error: {exc}")
        except Exception:
            logger.exception("Unexpected error while querying KepCs status API")
            yield event.plain_result("Query error: internal error")

    async def _get_server_list_payload(self) -> Dict[str, List[Dict[str, Any]]]:
        cached_payload = self._get_cached_payload()
        if cached_payload is not None:
            return cached_payload

        cached_error = self._get_cached_error()
        if cached_error is not None:
            raise RuntimeError(cached_error)

        async with self._cache_lock:
            cached_payload = self._get_cached_payload()
            if cached_payload is not None:
                return cached_payload

            cached_error = self._get_cached_error()
            if cached_error is not None:
                raise RuntimeError(cached_error)

            try:
                payload = await asyncio.to_thread(self._fetch_server_list_payload)
            except RuntimeError as exc:
                self._remember_failure(str(exc))
                raise

            self._remember_success(payload)
            return payload

    def _get_cached_payload(self) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        if self._cached_payload is None:
            return None
        if time.monotonic() - self._cached_payload_at > self.CACHE_TTL_SECONDS:
            self._cached_payload = None
            self._cached_payload_at = 0.0
            return None
        return self._cached_payload

    def _get_cached_error(self) -> Optional[str]:
        if not self._last_fetch_error:
            return None
        if time.monotonic() - self._last_fetch_error_at > self.ERROR_CACHE_TTL_SECONDS:
            self._last_fetch_error = ""
            self._last_fetch_error_at = 0.0
            return None
        return self._last_fetch_error

    def _remember_success(self, payload: Dict[str, List[Dict[str, Any]]]) -> None:
        self._cached_payload = payload
        self._cached_payload_at = time.monotonic()
        self._last_fetch_error = ""
        self._last_fetch_error_at = 0.0

    def _remember_failure(self, error_message: str) -> None:
        self._cached_payload = None
        self._cached_payload_at = 0.0
        self._last_fetch_error = error_message
        self._last_fetch_error_at = time.monotonic()

    def _fetch_server_list_payload(self) -> Dict[str, List[Dict[str, Any]]]:
        request_object = self._build_server_list_request()

        try:
            with request.urlopen(request_object, timeout=self.API_TIMEOUT_SECONDS) as response:
                raw_data = response.read(self.MAX_RESPONSE_BYTES + 1)
        except error.URLError as exc:
            raise RuntimeError(f"Failed to fetch API: {exc}") from exc

        if len(raw_data) > self.MAX_RESPONSE_BYTES:
            raise RuntimeError("API response too large")

        try:
            decoded_data = raw_data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"Invalid API encoding: {exc}") from exc

        try:
            payload = json.loads(decoded_data)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid API JSON: {exc}") from exc

        return self._validate_payload(payload)

    def _validate_payload(self, payload: Any) -> Dict[str, List[Dict[str, Any]]]:
        if not isinstance(payload, dict):
            raise RuntimeError("Invalid API response: root should be an object")

        servers = payload.get("servers")
        if not isinstance(servers, list):
            raise RuntimeError("Invalid API response: missing servers array")
        if len(servers) > self.MAX_SERVER_COUNT:
            raise RuntimeError("Invalid API response: too many servers")

        filtered_servers = [server for server in servers if isinstance(server, dict)]
        return {"servers": filtered_servers}

    def _build_server_list_request(self) -> request.Request:
        return request.Request(
            url=self._get_serverlist_url(),
            headers=self._build_api_headers(),
        )

    @staticmethod
    def _normalize_config_text(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        return ""

    def _get_config_text(self, key: str) -> str:
        return self._normalize_config_text(self.config.get(key, ""))

    def _get_serverlist_url(self) -> str:
        configured_url = self._get_config_text(self.SERVERLIST_URL_CONFIG_KEY)
        if configured_url:
            return configured_url
        return self.DEFAULT_SERVERLIST_URL

    def _build_api_headers(self) -> Dict[str, str]:
        api_key = self._get_config_text(self.API_KEY_CONFIG_KEY)
        bearer_token = self._get_config_text(self.BEARER_TOKEN_CONFIG_KEY)
        if not api_key and not bearer_token:
            raise RuntimeError(
                "Missing API credentials: set plugin config "
                f"`{self.API_KEY_CONFIG_KEY}` or `{self.BEARER_TOKEN_CONFIG_KEY}`"
            )

        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json",
        }
        if api_key:
            headers["X-API-Key"] = api_key

        effective_bearer_token = bearer_token or api_key
        if effective_bearer_token:
            headers["Authorization"] = f"Bearer {effective_bearer_token}"

        return headers

    def _build_results(self, servers: List[Dict[str, Any]]) -> List[ServerStatusLine]:
        return [self._build_result(server) for server in servers]

    def _format_status_output(self, results: List[ServerStatusLine]) -> str:
        grouped_data: Dict[str, List[ServerStatusLine]] = {}
        hidden_non_idle_count = 0
        total_players = sum(item.player_count for item in results)

        for result in results:
            if not result.is_unavailable and result.player_count > 0:
                hidden_non_idle_count += 1
                continue
            grouped_data.setdefault(result.group, []).append(result)

        output = [self.OUTPUT_TITLE]

        if not grouped_data:
            output.append(self.ALL_BUSY_MESSAGE)
        else:
            for group_key in sorted(
                grouped_data.keys(),
                key=lambda key: (self.GROUP_ORDER.get(key, 99), key),
            ):
                display_name = self.GROUP_MAP.get(group_key, group_key)
                output.append(f"**--- {display_name} ---**")
                output.extend(result.line for result in grouped_data[group_key])
                output.append("")

        output.append(f"Total player: **{total_players}**")
        if hidden_non_idle_count > 0:
            output.append("__Non idle server hidden__")
        return "\n".join(output)

    def _build_result(self, server: Dict[str, Any]) -> ServerStatusLine:
        name = self._safe_text(server.get("name"), "Unknown", self.MAX_TEXT_LENGTH)
        host = self._safe_host(server.get("host"))
        port = self._safe_port(server.get("port"))
        group = self._safe_group(server.get("mode"))
        status = self._normalize_status(server.get("status"))
        api_error = self._safe_optional_text(
            server.get("error"),
            self.MAX_ERROR_TEXT_LENGTH,
        )

        player_count = self._safe_non_negative_int(server.get("current_players"))
        max_count = self._format_player_cap(server.get("max_players"))
        map_name = self._safe_text(server.get("map"), "Unknown", self.MAX_TEXT_LENGTH)
        is_ok = status == self.STATUS_OK
        join_target = self._build_join_target(host, port)

        if is_ok:
            line = (
                f"· {name} ( {player_count} / {max_count} )\n"
                f"Map: **{map_name}**\n"
                f"Join: [{host}:{port}]({join_target})"
            )
        else:
            line = f"· {name} ( {status} )"
            if api_error:
                line += f" ({api_error})"
            line += f"\nJoin: [{host}:{port}]({join_target})"

        return ServerStatusLine(
            group=group,
            line=line,
            player_count=player_count if is_ok else 0,
            is_unavailable=not is_ok,
        )

    def _normalize_status(self, value: Any) -> str:
        text = str(value).strip().lower() if value is not None else ""
        if not text:
            text = "unknown"
        return self._truncate_text(text.translate(self.MARKDOWN_ESCAPE_MAP), 32)

    def _safe_group(self, value: Any) -> str:
        text = str(value).strip().lower() if value is not None else ""
        if self.SAFE_GROUP_PATTERN.fullmatch(text):
            return text
        return "other"

    def _safe_non_negative_int(self, value: Any) -> int:
        if type(value) is int and value >= 0:
            return value
        return 0

    def _format_player_cap(self, value: Any) -> Any:
        if type(value) is int and value >= 0:
            return value
        return "?"

    def _safe_port(self, value: Any) -> int:
        if type(value) is int and 0 <= value <= 65535:
            return value
        return 0

    def _safe_host(self, value: Any) -> str:
        text = str(value).strip() if value is not None else ""
        if text and self.SAFE_HOST_PATTERN.fullmatch(text):
            return text
        return "0.0.0.0"

    def _safe_text(self, value: Any, default: str, max_length: int) -> str:
        text = str(value).strip() if value is not None else ""
        if not text:
            text = default
        escaped_text = text.translate(self.MARKDOWN_ESCAPE_MAP)
        return self._truncate_text(escaped_text, max_length)

    def _safe_optional_text(self, value: Any, max_length: int) -> str:
        text = str(value).strip() if value is not None else ""
        if not text:
            return ""
        escaped_text = text.translate(self.MARKDOWN_ESCAPE_MAP)
        return self._truncate_text(escaped_text, max_length)

    def _truncate_text(self, text: str, max_length: int) -> str:
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."

    def _build_join_target(self, host: str, port: int) -> str:
        return "https://vauff.com/connect.php?" + urlencode({"ip": f"{host}:{port}"})

    async def terminate(self):
        logger.info("卸载插件: astrbot_plugin_kepcs_server_status")
