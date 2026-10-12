"""
Minimal client for FSMA's public "Managers' Transactions" register
(https://www.fsma.be/en/transaction-search).

This is public disclosure data: EU Market Abuse Regulation (Art. 19) requires
company insiders to report their own-account trades to the national regulator.
FSMA publishes these filings openly for anyone to consult.

Politeness: FSMA's robots.txt specifies `Crawl-delay: 30`. We honor that by
waiting at least 30 seconds between every HTTP request to fsma.be, regardless
of which page we're fetching.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.fsma.be"
SEARCH_PATH = "/en/transaction-search"
CRAWL_DELAY_SECONDS = 30

HEADERS = {
    "User-Agent": (
        "InsiderTradingPrototype/0.1 "
        "(personal, non-commercial research tool; "
        "contact: anton.vanommeslaeghe@gmail.com)"
    )
}

_last_request_at: float | None = None


def _throttled_get(url: str, params: dict | None = None) -> requests.Response:
    """GET that always waits CRAWL_DELAY_SECONDS since the previous request."""
    global _last_request_at
    if _last_request_at is not None:
        elapsed = time.monotonic() - _last_request_at
        wait = CRAWL_DELAY_SECONDS - elapsed
        if wait > 0:
            time.sleep(wait)
    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    _last_request_at = time.monotonic()
    resp.raise_for_status()
    return resp


def get_issuer_id_map(cache_path: Path, refresh: bool = False) -> dict[str, str]:
    """Scrape the issuer <select> once and cache name -> taxonomy term id.

    The FSMA search form filters by a numeric taxonomy id, not by the
    company's display name, so we need this lookup table.
    """
    if cache_path.exists() and not refresh:
        return json.loads(cache_path.read_text())

    resp = _throttled_get(f"{BASE_URL}{SEARCH_PATH}")
    soup = BeautifulSoup(resp.text, "html.parser")
    select = soup.find("select", {"name": "issuer"})
    mapping: dict[str, str] = {}
    for option in select.find_all("option"):
        value = option.get("value", "").strip()
        name = option.get_text(strip=True)
        if value and name and name != "- Any -":
            mapping[name] = value

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False))
    return mapping


def list_transactions(issuer_id: str) -> list[dict]:
    """Return [{publication_date, person, detail_path}] for one issuer."""
    resp = _throttled_get(f"{BASE_URL}{SEARCH_PATH}", params={"issuer": issuer_id})
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")
    if table is None:
        return []

    rows = table.find_all("tr")[1:]  # skip header
    results = []
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        pub_date = cells[0].get_text(strip=True)
        person = cells[2].get_text(strip=True)
        link = row.find("a")
        if link is None:
            continue
        detail_path = link.get("href")
        results.append(
            {
                "publication_date": pub_date,
                "person": person,
                "detail_path": detail_path,
            }
        )
    return results


_FIELD_LABELS = {
    "Date of publication": "publication_date",
    "Notifying person": "person",
    "Declarer Type": "declarer_type",
    "Issuer": "issuer_name",
    "Instrument Type": "instrument_type",
    "Instrument ISIN Code": "isin",
    "Transaction Type": "type_raw",
    "Transaction Type Specifications": "specifications",
    "Transaction Place": "place",
    "Transaction Date": "transaction_date",
    "Transaction Currency": "currency",
    "Transaction Quantity": "quantity_raw",
    "Transaction Price": "price_raw",
    "Transaction Amount": "amount_raw",
}


def _parse_eu_number(raw: str) -> float | None:
    """'1.216.002,40' -> 1216002.40 ; '5.000' -> 5000.0"""
    if not raw:
        return None
    cleaned = raw.strip().replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def get_transaction_detail(detail_path: str) -> dict:
    """Fetch and parse one manager-transaction detail page."""
    url = urljoin(BASE_URL, detail_path)
    resp = _throttled_get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    main = soup.find("main") or soup

    text = main.get_text("\n", strip=True)
    lines = [line for line in text.split("\n") if line]

    fields: dict[str, str] = {}
    i = 0
    while i < len(lines) - 1:
        label = lines[i]
        if label in _FIELD_LABELS:
            fields[_FIELD_LABELS[label]] = lines[i + 1]
            i += 2
        else:
            i += 1

    detail = dict(fields)
    detail["detail_url"] = url
    detail["quantity"] = _parse_eu_number(fields.get("quantity_raw", ""))
    detail["price"] = _parse_eu_number(fields.get("price_raw", ""))
    detail["amount"] = _parse_eu_number(fields.get("amount_raw", ""))
    return detail


def classify_transaction(type_raw: str, specifications: str) -> tuple[str, bool]:
    """Normalize to BUY/SELL/OTHER and decide if it belongs in the 'genuine
    open-market trade' view, mirroring insiderwatch.be's methodology:
    exclude remuneration-linked transactions (grants, option exercises,
    pledges, gifts, subscriptions) even if the base type says buy/sell.
    """
    type_raw = (type_raw or "").lower()
    specifications = (specifications or "").lower()

    if "purchase" in type_raw or "acquisition" in type_raw:
        norm = "BUY"
    elif "sale" in type_raw or "disposal" in type_raw:
        norm = "SELL"
    else:
        norm = "OTHER"

    exclude_markers = (
        "remuneration",
        "option",
        "warrant",
        "grant",
        "vesting",
        "gift",
        "donation",
        "pledge",
        "subscription",
        "capital increase",
    )
    is_remuneration_linked = any(marker in specifications for marker in exclude_markers)

    included = norm in ("BUY", "SELL") and not is_remuneration_linked
    return norm, included


_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def to_iso_date(ddmmyyyy: str) -> str | None:
    match = _DATE_RE.match((ddmmyyyy or "").strip())
    if not match:
        return None
    dd, mm, yyyy = match.groups()
    return f"{yyyy}-{mm}-{dd}"
