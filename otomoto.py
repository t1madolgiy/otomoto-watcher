"""Парсер объявлений Otomoto.

Otomoto — сайт на Next.js, поэтому самый надёжный способ получить
структурированные данные — это вытащить JSON из тега <script id="__NEXT_DATA__">.
Если структура JSON изменится — есть fallback на парсинг HTML.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass
class Listing:
    """Минимальная информация об объявлении."""

    id: str
    title: str
    url: str
    price: str | None = None
    currency: str | None = None
    year: int | None = None
    mileage_km: int | None = None
    fuel_type: str | None = None
    location: str | None = None
    created_at: datetime | None = None
    short_description: str | None = None

    def format_telegram(self) -> str:
        """HTML-сообщение для Telegram."""
        lines: list[str] = [f"<b>{_escape(self.title)}</b>"]
        price_bits: list[str] = []
        if self.price:
            price_bits.append(self.price)
        if self.currency:
            price_bits.append(self.currency)
        if price_bits:
            lines.append("💰 " + " ".join(_escape(p) for p in price_bits))
        details: list[str] = []
        if self.year:
            details.append(str(self.year))
        if self.mileage_km is not None:
            details.append(f"{self.mileage_km:,} km".replace(",", " "))
        if self.fuel_type:
            details.append(self.fuel_type)
        if details:
            lines.append("🚗 " + _escape(" • ".join(details)))
        if self.location:
            lines.append("📍 " + _escape(self.location))
        if self.created_at:
            lines.append("🕒 " + _escape(self.created_at.strftime("%Y-%m-%d %H:%M")))
        lines.append(f'\n<a href="{_escape(self.url)}">Открыть объявление</a>')
        return "\n".join(lines)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def fetch_listings(search_url: str, *, timeout: int = 20) -> list[Listing]:
    """Загрузить и распарсить страницу поиска Otomoto."""
    log.info("Fetching %s", search_url)
    resp = requests.get(search_url, headers=DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    html = resp.text
    listings = _extract_from_next_data(html)
    if listings:
        log.info("Parsed %d listings from __NEXT_DATA__", len(listings))
        return listings
    log.warning("__NEXT_DATA__ parse failed, falling back to HTML")
    return _extract_from_html(html)


def _extract_from_next_data(html: str) -> list[Listing]:
    """Достаём JSON из тега <script id=\"__NEXT_DATA__\">.

    Otomoto использует Urql (GraphQL-клиент) и кеширует ответы в
    ``props.pageProps.urqlState[<hash>].data`` как **строку** с JSON.
    Поэтому нужно сначала развернуть эти строки, и только потом искать ``edges``.
    """
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        return []
    try:
        data = json.loads(tag.string)
    except json.JSONDecodeError as exc:  # pragma: no cover
        log.warning("Failed to parse __NEXT_DATA__: %s", exc)
        return []

    edges = _find_listing_edges(data)
    listings: list[Listing] = []
    seen_ids: set[str] = set()
    for edge in edges:
        node = edge.get("node") if isinstance(edge, dict) else None
        if not isinstance(node, dict):
            continue
        listing = _listing_from_node(node)
        if listing and listing.id not in seen_ids:
            seen_ids.add(listing.id)
            listings.append(listing)
    return listings


def _find_listing_edges(data: Any) -> list[dict[str, Any]]:
    """Рекурсивный поиск массива объявлений.

    Дополнительно: если встречаем строку, которая выглядит как JSON
    (начинается с ``{`` или ``[``) — пытаемся её распарсить и продолжить
    обход. Это нужно для ``urqlState[<hash>].data``.
    """
    found: list[dict[str, Any]] = []

    def walk(obj: Any, depth: int = 0) -> None:
        if depth > 30:
            return
        if isinstance(obj, dict):
            edges = obj.get("edges")
            if isinstance(edges, list) and edges and _looks_like_listing_edges(edges):
                found.extend(edges)
            for value in obj.values():
                walk(value, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, depth + 1)
        elif isinstance(obj, str) and len(obj) > 20:
            s = obj.lstrip()
            if s.startswith("{") or s.startswith("["):
                try:
                    inner = json.loads(obj)
                except (json.JSONDecodeError, ValueError):
                    return
                walk(inner, depth + 1)

    walk(data)
    return found


def _looks_like_listing_edges(edges: list[Any]) -> bool:
    sample = edges[0]
    if not isinstance(sample, dict):
        return False
    node = sample.get("node")
    if not isinstance(node, dict):
        return False
    return "id" in node and ("url" in node or "title" in node)


def _listing_from_node(node: dict[str, Any]) -> Listing | None:
    try:
        listing_id = str(node["id"])
    except KeyError:
        return None
    title = str(node.get("title") or "Bez tytułu")
    url = str(node.get("url") or "")
    if url and not url.startswith("http"):
        url = "https://www.otomoto.pl" + url

    price_obj = node.get("price") or {}
    amount: Any = None
    currency: Any = None
    if isinstance(price_obj, dict):
        amount_obj = price_obj.get("amount") or {}
        if isinstance(amount_obj, dict):
            amount = (
                amount_obj.get("units")
                if amount_obj.get("units") is not None
                else amount_obj.get("value")
            )
            currency = amount_obj.get("currencyCode")
        else:
            amount = price_obj.get("value")
            currency = price_obj.get("currency")

    location_obj = node.get("location") or {}
    city = ""
    region = ""
    if isinstance(location_obj, dict):
        city_obj = location_obj.get("city") or {}
        region_obj = location_obj.get("region") or {}
        if isinstance(city_obj, dict):
            city = str(city_obj.get("name") or "")
        if isinstance(region_obj, dict):
            region = str(region_obj.get("name") or "")
    location = ", ".join(part for part in (city, region) if part) or None

    created_at = _parse_created_at(node.get("createdAt") or node.get("created_at"))

    params = _extract_params(node)
    year_val = params.get("year", {}).get("value")
    mileage_val = params.get("mileage", {}).get("value")
    fuel_val = params.get("fuel_type", {}).get("display") or params.get(
        "fuel_type", {}
    ).get("value")

    return Listing(
        id=listing_id,
        title=title,
        url=url or f"https://www.otomoto.pl/osobowe/oferta/-ID{listing_id}.html",
        price=_format_amount(amount),
        currency=currency,
        year=_safe_int(year_val),
        mileage_km=_safe_int(mileage_val),
        fuel_type=str(fuel_val) if fuel_val else None,
        location=location,
        created_at=created_at,
        short_description=str(node.get("shortDescription") or "") or None,
    )


def _extract_params(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Otomoto хранит параметры в виде массива ``parameters``.

    Возвращаем словарь вида ``{key: {"value": ..., "display": ...}}``,
    чтобы при форматировании можно было выбирать читаемое значение.
    """
    result: dict[str, dict[str, Any]] = {}
    params = node.get("parameters")
    if isinstance(params, list):
        for p in params:
            if not isinstance(p, dict):
                continue
            key = p.get("key")
            if key:
                result[str(key)] = {
                    "value": p.get("value"),
                    "display": p.get("displayValue"),
                }
    return result


def _parse_created_at(raw: Any) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw / 1000 if raw > 1e12 else raw, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _format_amount(amount: Any) -> str | None:
    if amount is None:
        return None
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    if value.is_integer():
        return f"{int(value):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ")


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).replace(" ", "").replace("km", "").strip())
    except (TypeError, ValueError):
        return None


# Резервный путь — если структура __NEXT_DATA__ радикально изменится.
def _extract_from_html(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    listings: list[Listing] = []
    seen_ids: set[str] = set()
    for article in soup.select("article"):
        link = article.find("a", href=True)
        if not link:
            continue
        url = link["href"]
        match = re.search(r"-ID([A-Za-z0-9]+)\.html", url)
        if not match:
            continue
        listing_id = match.group(1)
        if listing_id in seen_ids:
            continue
        seen_ids.add(listing_id)
        title = (link.get_text(strip=True) or "Bez tytułu").strip()
        listings.append(
            Listing(
                id=listing_id,
                title=title,
                url=url if url.startswith("http") else f"https://www.otomoto.pl{url}",
            )
        )
    return listings


def filter_new(listings: Iterable[Listing], seen_ids: set[str]) -> list[Listing]:
    """Оставить только объявления, которых нет в ``seen_ids``."""
    fresh: list[Listing] = []
    for listing in listings:
        if listing.id not in seen_ids:
            fresh.append(listing)
    return fresh
