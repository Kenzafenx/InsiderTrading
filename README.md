# Insider Watch — 't Warm Buffet

Prototype dashboard tracking **insider transactions** (buys/sells by company
executives, board members and major shareholders) for the Belgian stocks
currently held by the investment club behind
['t Warm Buffet](https://bkb1a.github.io/warm-buffet/).

This is a personal/club project, independent from the warm-buffet repo —
it only *reads* its public `data/dashboard.json`, nothing is pushed there.

## Why

Executives and major shareholders of listed companies are legally required
(EU Market Abuse Regulation, Art. 19) to disclose their own trades to the
national regulator. For Belgium that's the **FSMA**
([transaction-search](https://www.fsma.be/en/transaction-search)) — public
data, just tedious to browse manually. This project mirrors the idea behind
[insiderwatch.be](https://insiderwatch.be/) (same data source, same
filtering philosophy) but scoped down to only the ~4 Belgian stocks our
club actually holds, auto-synced from the portfolio.

## How it works

1. **`scripts/sync_holdings.py`** — fetches 't Warm Buffet's public
   `data/dashboard.json` and keeps only the holdings that are currently
   active **and** listed on Euronext Brussels (ticker ending in `.BR`).
   Writes `data/holdings.json`. Re-run this whenever the club's portfolio
   changes — new Belgian stocks are picked up automatically.

2. **`scripts/scrape_insiders.py`** — resolves each holding to its FSMA
   issuer id, fetches its filed transactions, and parses each transaction's
   detail page (person, type, price, quantity, amount). Classifies each
   transaction as `BUY` / `SELL` / `OTHER` and flags whether it's a
   "genuine open-market trade" (≥ €5,000, excluding grants, option
   exercises, pledges, gifts, subscriptions) — same filter insiderwatch.be
   uses. Writes `data/transactions.json`.

   Re-running is cheap: only transactions not already in
   `data/transactions.json` get fetched.

3. **`index.html`** — static dashboard (no build step, no framework) that
   reads the two JSON files and renders a filterable table + summary cards.

## Running it

```bash
pip install -r requirements.txt

python3 scripts/sync_holdings.py
python3 scripts/scrape_insiders.py            # full backfill (slow, see below)
# or, for a quick first look:
python3 scripts/scrape_insiders.py --max-details-per-issuer 10

python3 -m http.server 8000                   # then open http://localhost:8000
```

### About the 30-second delay

FSMA's `robots.txt` specifies `Crawl-delay: 30`. `fsma_client.py` honors
that by waiting at least 30 seconds between *every* request to fsma.be —
on purpose, out of courtesy to their servers. A full first-time backfill
across all four holdings therefore takes on the order of 20–60 minutes
depending on how much history each company has. Subsequent runs are fast:
only brand-new filings trigger new requests.

## Status / next steps

- [x] Prototype working for personal use, scoped to our own holdings.
- [ ] Decide whether to automate this with a daily scheduled run
      (e.g. GitHub Actions).
- [ ] If this proves useful, propose integrating it into the warm-buffet
      dashboard itself (as a PR, with the repo owner's buy-in) — not done
      yet, by design.

## Disclaimer

For informational purposes only. Not financial advice. Data comes as-is
from the FSMA's public filings; always verify against the official source
before acting on it.
