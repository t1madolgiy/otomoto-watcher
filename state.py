"""Хранилище ID уже отправленных объявлений в JSON-файле."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class SeenStore:
    """Простой JSON-стейт.

    Формат файла::

        {
            "version": 1,
            "updated_at": "2026-05-24T19:00:00+00:00",
            "seen_ids": ["6123456789", "6123456790", ...]
        }

    Чтобы файл не разрастался бесконечно, храним только последние ``max_size`` ID.
    """

    def __init__(self, path: Path | str, max_size: int = 5000) -> None:
        self.path = Path(path)
        self.max_size = max_size
        self._ids: list[str] = []
        self._loaded = False

    def load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            ids = data.get("seen_ids") or []
            self._ids = [str(x) for x in ids if x is not None]
        self._loaded = True

    @property
    def ids(self) -> set[str]:
        if not self._loaded:
            self.load()
        return set(self._ids)

    def add_many(self, new_ids: list[str]) -> None:
        if not self._loaded:
            self.load()
        existing = set(self._ids)
        for new_id in new_ids:
            if new_id in existing:
                continue
            self._ids.append(new_id)
            existing.add(new_id)
        if len(self._ids) > self.max_size:
            self._ids = self._ids[-self.max_size :]

    def save(self) -> None:
        payload = {
            "version": 1,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            "seen_ids": self._ids,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
