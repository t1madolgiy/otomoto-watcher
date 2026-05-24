"""Загрузка конфигурации из YAML или переменных окружения."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str


@dataclass
class AppConfig:
    search_urls: list[str]
    telegram: TelegramConfig
    max_listings_per_run: int = 32
    max_age_hours: int = 24
    seed_only: bool = False
    state_path: Path = field(default_factory=lambda: Path("state.json"))


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    """Загрузить конфиг.

    Приоритет:
    1. Переменные окружения (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
       `OTOMOTO_SEARCH_URLS` через перенос строки или `;`, `SEED_ONLY`,
       `MAX_AGE_HOURS`).
    2. YAML-файл (по умолчанию ``config.yaml`` в текущей директории).
    """
    data: dict = {}
    yaml_path = Path(path) if path else Path("config.yaml")
    if yaml_path.exists():
        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    env_urls = os.environ.get("OTOMOTO_SEARCH_URLS") or os.environ.get(
        "OTOMOTO_SEARCH_URL"
    )
    if env_urls:
        urls = [u.strip() for u in env_urls.replace(";", "\n").splitlines() if u.strip()]
    else:
        urls = list(data.get("search_urls") or [])
    if not urls:
        raise ValueError(
            "Не указан ни один URL поиска. Заполните 'search_urls' в config.yaml "
            "или передайте переменную окружения OTOMOTO_SEARCH_URLS."
        )

    tg_cfg = data.get("telegram") or {}
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") or tg_cfg.get("bot_token") or ""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or tg_cfg.get("chat_id") or ""
    if not bot_token or not chat_id:
        raise ValueError(
            "Не указаны TELEGRAM_BOT_TOKEN и/или TELEGRAM_CHAT_ID."
        )

    max_listings = int(
        os.environ.get("MAX_LISTINGS_PER_RUN")
        or data.get("max_listings_per_run")
        or 32
    )
    max_age_hours = int(
        os.environ.get("MAX_AGE_HOURS")
        if os.environ.get("MAX_AGE_HOURS") is not None
        else data.get("max_age_hours", 24)
    )
    seed_only_raw = os.environ.get("SEED_ONLY")
    if seed_only_raw is None:
        seed_only = bool(data.get("seed_only", False))
    else:
        seed_only = seed_only_raw.lower() in {"1", "true", "yes", "on"}

    return AppConfig(
        search_urls=urls,
        telegram=TelegramConfig(bot_token=str(bot_token), chat_id=str(chat_id)),
        max_listings_per_run=max_listings,
        max_age_hours=max_age_hours,
        seed_only=seed_only,
        state_path=Path(os.environ.get("STATE_PATH") or "state.json"),
    )
