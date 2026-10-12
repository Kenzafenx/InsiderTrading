# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small pipeline + static dashboard that tracks insider transactions
(buy/sell filings by executives, board members, major shareholders) for
the Belgian-listed stocks held by the 't Warm Buffet investment club
(https://bkb1a.github.io/warm-buffet/). It reads warm-buffet's public data
only — this repo is independent and never pushes to that one.

## Commands

```bash
pip install -r requirements.txt

python3 scripts/sync_holdings.py                       # refresh data/holdings.json from warm-buffet
python3 scripts/scrape_insiders.py                      # full FSMA backfill (slow, see below)
python3 scripts/scrape_insiders.py --max-details-per-issuer 10   # quick partial run
python3 scripts/scrape_insiders.py --refresh-issuers    # force re-scrape of the issuer name->id cache

python3 -m http.server 8000                              # serve index.html locally, then open http://localhost:8000
```

There is no test suite, build step, or linter configured.

## Architecture

Three-stage pipeline, each stage writing JSON that the next stage (or the
dashboard) reads — no database, no server beyond a static file host:

1. **`scripts/sync_holdings.py`** fetches warm-buffet's public
   `data/dashboard.json` (raw GitHub URL) and filters to holdings that are
   `active == true` **and** have a ticker ending in `.BR` (Euronext
   Brussels). This is the single rule that decides "what counts as one of
   our Belgian holdings" — it requires no manual list maintenance; a newly
   bought Belgian stock is picked up automatically next run. Output:
   `data/holdings.json`.

2. **`scripts/fsma_client.py`** is the FSMA scraping client, used by
   `scrape_insiders.py`. Key things to know before touching it:
   - FSMA's search form filters by a **numeric taxonomy term id**, not by
     company name (e.g. SOFINA = `159078`). `get_issuer_id_map()` scrapes
     the `<select name="issuer">` dropdown once and caches
     name→id to `data/issuer_ids.json`.
   - `_throttled_get()` is a module-level rate limiter that enforces FSMA's
     `robots.txt` `Crawl-delay: 30` — every single request to fsma.be
     (listing pages and detail pages alike) waits out the full 30s since
     the previous one. This is deliberate and should not be shortened; a
     full backfill across all holdings can take 20–60 minutes as a result.
   - `classify_transaction()` normalizes FSMA's raw "Transaction Type"
     text into `BUY`/`SELL`/`OTHER`, and separately flags `included`
     (genuine open-market trade ≥ nothing-filtered-here — amount
     filtering happens in the dashboard) by checking the "Transaction Type
     Specifications" text for remuneration/option/grant/pledge/gift/
     subscription keywords. This mirrors insiderwatch.be's published
     methodology on purpose, for consistency with that reference site.

3. **`scripts/scrape_insiders.py`** is the orchestrator: loads
   `data/holdings.json`, resolves each holding's display name to an FSMA
   issuer id (`resolve_issuer_id()` — exact match, then leading-word
   prefix match against the issuer map, then `config/issuer_overrides.json`
   as a manual fallback), fetches new transactions per issuer, dedupes
   against existing `data/transactions.json` by the FSMA URL slug (e.g.
   `sofina-58`), and writes the merged, sorted result back. Re-running is
   incremental — only transaction ids not already on file trigger a detail
   page fetch.

   If a holding can't be auto-resolved to an issuer id, the script logs a
   `[WARN]` and skips it — add an override under `overrides` in
   `config/issuer_overrides.json` (keyed by ticker, value = the exact FSMA
   issuer display name) to fix it.

4. **`index.html`** is a single-file static dashboard (vanilla JS, no
   build step, no framework) that `fetch()`s `data/transactions.json` and
   `data/holdings.json` directly. Must be served over HTTP (not opened as
   a `file://` URL) for the `fetch()` calls to work. Filtering between
   all/BUY/SELL/"relevant only" happens client-side over the already-loaded
   data; there is no backend API.

## Working with FSMA scraping

- Respect the 30s crawl delay in `fsma_client.py` — do not parallelize
  requests or reduce the delay, even for testing.
- `data/issuer_ids.json` is a long-lived cache (FSMA's issuer list changes
  rarely); only pass `--refresh-issuers` if a known holding fails to
  resolve and you suspect the dropdown changed.
- European number formatting (`1.216.002,40` style) in FSMA's detail pages
  is parsed by `fsma_client._parse_eu_number()` — thousands separator `.`,
  decimal separator `,`.
