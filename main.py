"""Точка входа Otomoto Watcher.

Запускается раз в N минут (через GitHub Actions, cron, планировщик задач Windows
или вручную). Для каждого URL поиска:

  1. Загружает страницу.
  2. Извлекает список объявлений.
  3. Отсеивает уже виденные (по ID).
  4. Отсеивает слишком старые (если задан ``max_age_hours``).
  5. Отправляет новые в Telegram.
  6. Сохраняет ID отправленных в state.json.
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timedelta, timezone

from config import AppConfig, load_config
from notifier import TelegramNotifier
from otomoto import Listing, fetch_listings, filter_new
from state import SeenStore

log = logging.getLogger("otomoto-watcher")


def _is_recent_enough(listing: Listing, max_age_hours: int) -> bool:
    if max_age_hours <= 0 or listing.created_at is None:
        return True
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=max_age_hours)
    created = listing.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created >= cutoff


def run(config: AppConfig) -> int:
    store = SeenStore(config.state_path)
    store.load()
    seen = store.ids
    log.info("State loaded: %d known listing IDs", len(seen))

    notifier: TelegramNotifier | None = None
    if not config.seed_only:
        notifier = TelegramNotifier(
            bot_token=config.telegram.bot_token,
            chat_id=config.telegram.chat_id,
        )

    total_new = 0
    total_sent = 0

    for search_url in config.search_urls:
        try:
            listings = fetch_listings(search_url, max_pages=config.max_pages)
        except Exception as exc:
            log.error("Failed to fetch %s: %s", search_url, exc)
            continue
        listings = listings[: config.max_listings_per_run]
        fresh = filter_new(listings, seen)
        log.info(
            "URL %s: %d total, %d new (before age filter)",
            search_url,
            len(listings),
            len(fresh),
        )

        for listing in fresh:
            if not _is_recent_enough(listing, config.max_age_hours):
                log.debug(
                    "Skipping old listing %s (created %s)", listing.id, listing.created_at
                )
                continue
            total_new += 1
            if notifier is not None:
                try:
                    notifier.send(listing.format_telegram())
                    total_sent += 1
                except Exception as exc:
                    log.error("Failed to notify about %s: %s", listing.id, exc)
                    continue
                time.sleep(0.5)
            seen.add(listing.id)

        store.add_many([lst.id for lst in listings])

    store.save()
    if config.seed_only:
        log.info(
            "Seed-only run: saved %d IDs as already seen (no messages sent)",
            len(store.ids),
        )
    else:
        log.info("Done. %d new listings, %d notifications sent.", total_new, total_sent)
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    try:
        config = load_config()
    except ValueError as exc:
        log.error("Configuration error: %s", exc)
        return 2
    return run(config)


if __name__ == "__main__":
    sys.exit(main())
