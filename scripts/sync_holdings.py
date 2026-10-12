"""
Pull the current list of Belgian-listed individual holdings straight from
't Warm Buffet's public dashboard data (bkb1a/warm-buffet on GitHub).

A holding counts as "Belgian, to be tracked" when:
  - it is currently active in the portfolio (active == true), and
  - its ticker is listed on Euronext Brussels (ticker ends with ".BR")

This keeps the tracked list in sync automatically: whenever the club buys a
new Belgian stock, it shows up here the next time this script runs, with no
code change needed.
"""
import json
from pathlib import Path

import requests

WARM_BUFFET_DASHBOARD_URL = (
    "https://raw.githubusercontent.com/bkb1a/warm-buffet/main/data/dashboard.json"
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_PATH = DATA_DIR / "holdings.json"


def fetch_belgian_holdings() -> list[dict]:
    resp = requests.get(WARM_BUFFET_DASHBOARD_URL, timeout=30)
    resp.raise_for_status()
    dashboard = resp.json()

    holdings = []
    for h in dashboard.get("holdings", []):
        ticker = (h.get("ticker") or "").strip()
        if h.get("active") and ticker.endswith(".BR"):
            holdings.append({"name": h["name"], "ticker": ticker})
    return holdings


def main() -> None:
    holdings = fetch_belgian_holdings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(holdings, indent=2, ensure_ascii=False))

    print(f"Synced {len(holdings)} active Belgian holding(s) from warm-buffet:")
    for h in holdings:
        print(f"  - {h['name']} ({h['ticker']})")
    print(f"Written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
