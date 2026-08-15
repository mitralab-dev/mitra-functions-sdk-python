from __future__ import annotations

import ipaddress
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

import httpx

from .errors import MitraConfigError

DEFAULT_TIMEOUT_SECONDS = 10.0
_HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


@dataclass(frozen=True, slots=True)
class MitraClientConfig:
    """Configuration for a Server Functions SDK client."""

    api_url: str
    access_token: str = field(repr=False)
    app_id: str
    data_source_id: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    http_client: httpx.Client | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        api_url = _normalize_api_url(self.api_url)
        access_token = self.access_token.strip()
        app_id = self.app_id.strip()
        data_source_id = _optional_non_blank(self.data_source_id, "data_source_id")
        if not access_token:
            raise MitraConfigError("access_token must not be blank")
        if not app_id:
            raise MitraConfigError("app_id must not be blank")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise MitraConfigError("timeout_seconds must be positive and finite")

        object.__setattr__(self, "api_url", api_url)
        object.__setattr__(self, "access_token", access_token)
        object.__setattr__(self, "app_id", app_id)
        object.__setattr__(self, "data_source_id", data_source_id)

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> MitraClientConfig:
        source = os.environ if env is None else env
        missing = [
            name
            for name in (
                "MITRA_API_URL",
                "MITRA_PLATFORM_ACCESS_TOKEN",
                "MITRA_APP_ID",
            )
            if not source.get(name, "").strip()
        ]
        if missing:
            raise MitraConfigError(f"Missing required environment variables: {', '.join(missing)}")

        return cls(
            api_url=source["MITRA_API_URL"],
            access_token=source["MITRA_PLATFORM_ACCESS_TOKEN"],
            app_id=source["MITRA_APP_ID"],
            data_source_id=source.get("MITRA_DATA_SOURCE_ID"),
        )


def _optional_non_blank(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise MitraConfigError(f"{field_name} must not be blank when provided")
    return normalized


def _normalize_api_url(value: str) -> str:
    if not isinstance(value, str):
        raise MitraConfigError("api_url must be a valid HTTP(S) base URL without credentials")

    normalized = value.strip()
    if not normalized or any(_is_unsafe_url_character(char) for char in normalized):
        raise MitraConfigError("api_url must be a valid HTTP(S) base URL without credentials")

    parsed_url = _parse_http_url(normalized)
    port = parsed_url.port if parsed_url is not None else None
    host = parsed_url.raw_host.decode("ascii") if parsed_url is not None else ""
    if (
        parsed_url is None
        or parsed_url.scheme not in {"http", "https"}
        or not host
        or not _is_valid_host(host)
        or _has_malformed_explicit_port(normalized)
        or (port is not None and not 1 <= port <= 65535)
        or bool(parsed_url.userinfo)
        or bool(parsed_url.query)
        or bool(parsed_url.fragment)
        or "?" in normalized
        or "#" in normalized
    ):
        raise MitraConfigError("api_url must be a valid HTTP(S) base URL without credentials")

    return str(parsed_url).rstrip("/")


def _parse_http_url(value: str) -> httpx.URL | None:
    try:
        parsed_url = httpx.URL(value)
        _ = parsed_url.port
    except (httpx.InvalidURL, ValueError):
        return None
    return parsed_url


def _has_malformed_explicit_port(value: str) -> bool:
    authority = re.split(r"[/?#]", value.split("://", 1)[-1], maxsplit=1)[0]
    host_and_port = authority.rsplit("@", 1)[-1]
    if host_and_port.startswith("["):
        closing_bracket = host_and_port.find("]")
        suffix = host_and_port[closing_bracket + 1 :]
        if not suffix:
            return False
        port_text = suffix[1:] if suffix.startswith(":") else ""
    elif ":" in host_and_port:
        port_text = host_and_port.rsplit(":", 1)[1]
    else:
        return False
    return not port_text.isascii() or not port_text.isdigit()


def _is_unsafe_url_character(value: str) -> bool:
    return value.isspace() or ord(value) < 32 or ord(value) == 127


def _is_valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return True

    if len(host) > 253 or all(char in "0123456789." for char in host):
        return False
    labels = host.split(".")
    return all(_HOST_LABEL.fullmatch(label) is not None for label in labels)
