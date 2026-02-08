import os
from typing import Optional
from dataclasses import dataclass
from functools import lru_cache

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

DEFAULT_REQUEST_TIMEOUT = 30.0


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    internal_token: str
    vk_access_token: str
    vk_peer_id: str
    vk_api_version: str
    vk_group_id: Optional[str] = None
    vk_api_url: str = "https://api.vk.com/method/messages.send"
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"{name} is not set")
    return value


def _parse_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc


@lru_cache
def get_settings() -> Settings:
    return Settings(
        internal_token=_require_env("INTERNAL_TOKEN"),
        vk_access_token=_require_env("VK_ACCESS_TOKEN"),
        vk_peer_id=_require_env("VK_PEER_ID"),
        vk_api_version=os.getenv("VK_API_VERSION", "5.131"),
        vk_group_id=os.getenv("VK_GROUP_ID"),
        request_timeout=_parse_float("VK_REQUEST_TIMEOUT", DEFAULT_REQUEST_TIMEOUT),
    )
