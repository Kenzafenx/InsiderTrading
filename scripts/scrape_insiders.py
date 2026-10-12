"""
Main pipeline: resolve our tracked Belgian holdings to FSMA issuer ids,
fetch their insider transactions, and write data/transactions.json for the
dashboard to render.

Usage:
    python3 scripts/scrape_insiders.py [--max-details-per-issuer N] [--refresh-issuers]

Respects FSMA's robots.txt Crawl-delay of 30s between every request (see
fsma_client.py), so a full run over several companies can take a while —
that's expected and intentional. Re-runs are cheap: only transactions not
already in data/transactions.json get their detail page fetched.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fsma_client  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HOLDINGS_PATH = DATA_DIR / "holdings.json"
ISSUER_CACHE_PATH = DATA_DIR / "issuer_ids.json"
TRANSACTIONS_PATH = DATA_DIR / "transactions.json"
OVERRIDES_PATH = ROOT / "config" / "issuer_overrides.json"


def load_overrides() -> dict[str, str]:
    data = json.loads(OVERRIDES_PATH.read_text())
    return data.get("overrides", {})


def normalize(name: str) -> str:
    name = name.upper()
    name = re.sub(r"[./]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def resolve_issuer_id(
    holding: dict, issuer_map: dict[str, str], overrides: dict[str, str]
) -> str | None:
    ticker = holding["ticker"]
    if ticker in overrides:
        override_name = overrides[ticker]
        return issuer_map.get(override_name)

    norm_name = normalize(holding["name"])
    norm_to_id = {normalize(k): v for k, v in issuer_map.items()}

    if norm_name in norm_to_id:
        return norm_to_id[norm_name]

    # Try matching on the leading word(s) of the holding's name against a
    # full FSMA issuer name, since FSMA's names are often a short form of
    # the warm-buffet display name (e.g. "AGEAS" vs "AGEAS NV/SA").
    first_word = norm_name.split(" ")[0]
    candidates = [k for k in norm_to_id if k == first_word or k.startswith(first_word)]
    if len(candidates) == 1:
        return norm_to_id[candidates[0]]

    return None


def load_existing_transactions() -> dict[str, dict]:
    if not TRANSACTIONS_PATH.exists():
        return {}
    items = json.loads(TRANSACTIONS_PATH.read_text())
    return {item["id"]: item for item in items}


def slug_from_detail_path(detail_path: str) -> str:
    return detail_path.strip("/").split("/")[-1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-details-per-issuer",
        type=int,
        default=None,
        help="Cap how many new detail pages to fetch per issuer this run "
        "(useful for a quick first look; omit for a full backfill).",
    )
    parser.add_argument(
        "--refresh-issuers",
        action="store_true",
        help="Re-scrape the FSMA issuer name->id list instead of using the cache.",
    )
    args = parser.parse_args()

    if not HOLDINGS_PATH.exists():
        print("No data/holdings.json found — run scripts/sync_holdings.py first.")
        sys.exit(1)

    holdings = json.loads(HOLDINGS_PATH.read_text())
    overrides = load_overrides()
    issuer_map = fsma_client.get_issuer_id_map(
        ISSUER_CACHE_PATH, refresh=args.refresh_issuers
    )

    existing = load_existing_transactions()
    new_count = 0

    for holding in holdings:
        issuer_id = resolve_issuer_id(holding, issuer_map, overrides)
        if issuer_id is None:
            print(
                f"[WARN] Could not resolve '{holding['name']}' ({holding['ticker']}) "
                f"to an FSMA issuer. Add an override in config/issuer_overrides.json."
            )
            continue

        print(f"Fetching transactions for {holding['name']} ({holding['ticker']})...")
        listing = fsma_client.list_transactions(issuer_id)

        fetched_this_issuer = 0
        for row in listing:
            tx_id = slug_from_detail_path(row["detail_path"])
            if tx_id in existing:
                continue
            if (
                args.max_details_per_issuer is not None
                and fetched_this_issuer >= args.max_details_per_issuer
            ):
                print(
                    f"  (reached --max-details-per-issuer limit, "
                    f"{len(listing) - fetched_this_issuer} more available next run)"
                )
                break

            print(f"  + {tx_id}")
            detail = fsma_client.get_transaction_detail(row["detail_path"])
            norm_type, included = fsma_client.classify_transaction(
                detail.get("type_raw", ""), detail.get("specifications", "")
            )

            existing[tx_id] = {
                "id": tx_id,
                "ticker": holding["ticker"],
                "issuer_name": detail.get("issuer_name", holding["name"]),
                "person": detail.get("person", row["person"]),
                "declarer_type": detail.get("declarer_type"),
                "publication_date": fsma_client.to_iso_date(
                    detail.get("publication_date", row["publication_date"])
                ),
                "transaction_date": fsma_client.to_iso_date(
                    detail.get("transaction_date", "")
                ),
                "type_raw": detail.get("type_raw"),
                "type": norm_type,
                "included": included,
                "specifications": detail.get("specifications"),
                "instrument_type": detail.get("instrument_type"),
                "isin": detail.get("isin"),
                "currency": detail.get("currency"),
                "quantity": detail.get("quantity"),
                "price": detail.get("price"),
                "amount": detail.get("amount"),
                "detail_url": detail.get("detail_url"),
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }
            new_count += 1
            fetched_this_issuer += 1

    all_transactions = sorted(
        existing.values(),
        key=lambda t: t.get("publication_date") or "",
        reverse=True,
    )
    TRANSACTIONS_PATH.write_text(
        json.dumps(all_transactions, indent=2, ensure_ascii=False)
    )

    print(f"\nDone. {new_count} new transaction(s) fetched this run.")
    print(f"Total in {TRANSACTIONS_PATH}: {len(all_transactions)}")


if __name__ == "__main__":
    main()
