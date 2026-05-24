"""Отправка уведомлений в Telegram через Bot API."""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)


class TelegramNotifier:
    """Минималистичный клиент Telegram Bot API.

    Использует только метод ``sendMessage`` с HTML-разметкой,
    чтобы не тянуть лишних зависимостей.
    """

    def __init__(self, bot_token: str, chat_id: str) -> None:
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot_token и chat_id обязательны")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._api = f"https://api.telegram.org/bot{bot_token}"

    def send(self, text: str, *, disable_web_page_preview: bool = False) -> None:
        url = f"{self._api}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_web_page_preview,
        }
        for attempt in range(3):
            try:
                resp = requests.post(url, data=payload, timeout=20)
            except requests.RequestException as exc:
                log.warning("Telegram request failed (attempt %d): %s", attempt + 1, exc)
                time.sleep(2 ** attempt)
                continue

            if resp.status_code == 429:
                retry_after = int(resp.json().get("parameters", {}).get("retry_after", 5))
                log.warning("Telegram rate limit, sleeping %ds", retry_after)
                time.sleep(retry_after)
                continue
            if not resp.ok:
                log.error(
                    "Telegram error %s: %s", resp.status_code, resp.text[:300]
                )
                resp.raise_for_status()
            return
        raise RuntimeError("Не удалось отправить сообщение в Telegram после 3 попыток")
