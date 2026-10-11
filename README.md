# India Market Pulse

A small, free, **local** tool for a one-glance summary of the Indian market on any
trading day. Double-click, pick a date, click **Generate** — you get indices,
sector performance, commodities, top movers, market breadth and key support/
resistance levels in a clean dashboard.

No account, no API key, no cost. Nothing leaves your PC except the requests that
fetch this public data.

**Data sources**
- **NSE India** (official JSON) — live indices, all sectoral indices, market
  breadth, and FII/DII cash activity, for the latest session.
- **Financial-press RSS** (Economic Times, Moneycontrol, Business Standard,
  Livemint) — the day's market news with working links.
- **Yahoo Finance** (`yfinance`) — index/sector/commodity data and top movers for
  any historical date, pivot levels, and a fallback whenever NSE is unreachable.

> Note on Groww / Zerodha / Screener: these don't publish open daily-market APIs,
> and scraping a broker's logged-in pages is fragile and against their terms. NSE
> (official) plus the news feeds cover everything needed for a daily market view;
> Screener is per-company fundamentals, not daily market data.

> The only thing this tool doesn't reproduce from the **7 PM phone brief** is the
> AI-written cause-and-effect *takeaways*. Everything else — numbers, flows, news
> — is here, on demand, for whatever date you pick.

---

## Run it (Windows)

1. Make sure **Python 3** is installed — <https://www.python.org/downloads/>
   (tick *"Add Python to PATH"* during setup).
2. Double-click **`run.bat`**.
   - The first run installs the data library automatically (takes a minute).
   - Your browser opens at <http://localhost:8765>.
3. Keep the little black window open while you use the tool. Close it to stop.

### Run it (Mac / Linux)

```bash
pip install -r requirements.txt
python server.py
# then open http://localhost:8765
```

---

## Using it

- **Trading date** — pick any past market day (weekends/holidays return "markets
  closed"; the tool falls back to the nearest trading day where sensible).
- **Quick chips** — *Last session*, *Yesterday*, *1 week ago*.
- **Index cards** are tappable and open that index's live chart on Google Finance.
- **Key Levels** are classic floor-trader pivots computed from the day's
  high/low/close — a guide to the next session's support & resistance.
- **Theme** — the ◐ button toggles light/dark; your choice is remembered.

The first lookup of the day can take ~15–30s while data warms up; later ones are
quick.

---

## What's inside

| File | What it does |
|------|--------------|
| `run.bat` | One-click launcher for Windows (installs deps, opens browser, starts server) |
| `server.py` | Local HTTP server + the free-data engine (Yahoo Finance) |
| `index.html` | The dashboard UI (self-contained HTML/CSS/JS) |
| `requirements.txt` | Python dependency (`yfinance`) |

Change the port by passing it as an argument: `python server.py 9000`.

---

## Notes & limits

- Figures are **end-of-day, provisional** data and can differ slightly from the
  exchange's official close. For information only — **not investment advice**.
- Breadth and top movers are computed across the **Nifty 50** constituents.
- A few sector symbols occasionally don't resolve on the data source; those are
  skipped and listed under *Data notes* rather than breaking the page.
- Gold/Silver use NSE-listed ETFs (GOLDBEES / SILVERBEES, in INR) plus the
  international COMEX futures as a cross-reference.
