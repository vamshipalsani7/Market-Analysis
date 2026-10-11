"""
India Market Pulse - local data engine.

A tiny, dependency-light HTTP server. It serves the dashboard (index.html) and a
single JSON API at /api/brief?date=YYYY-MM-DD that assembles a market summary for
that date using free data from Yahoo Finance (via yfinance). No API key, no cost.

Run:  python server.py   (or just double-click run.bat on Windows)
Then open http://localhost:8765  (run.bat opens it for you).
"""

import json
import sys
import datetime as dt
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = 8765

# ----------------------------------------------------------------------------
# Symbol maps (Yahoo Finance tickers). Any that fail to resolve are skipped
# gracefully and reported in the response's "notes" rather than crashing.
# ----------------------------------------------------------------------------
INDICES = [
    ("Sensex",             "^BSESN",     "https://www.google.com/finance/quote/SENSEX:INDEXBOM"),
    ("Nifty 50",           "^NSEI",      "https://www.google.com/finance/quote/NIFTY_50:INDEXNSE"),
    ("Nifty Bank",         "^NSEBANK",   "https://www.google.com/finance/quote/NIFTY_BANK:INDEXNSE"),
    ("Nifty Midcap 50",    "^NSEMDCP50", "https://www.google.com/finance/quote/NIFTY_MIDCAP_50:INDEXNSE"),
    ("India VIX",          "^INDIAVIX",  "https://www.google.com/finance/quote/INDIA_VIX:INDEXNSE"),
]

SECTORS = [
    ("IT",            "^CNXIT"),
    ("Auto",          "^CNXAUTO"),
    ("Pharma",        "^CNXPHARMA"),
    ("FMCG",          "^CNXFMCG"),
    ("Metal",         "^CNXMETAL"),
    ("Energy",        "^CNXENERGY"),
    ("Realty",        "^CNXREALTY"),
    ("Media",         "^CNXMEDIA"),
    ("PSU Bank",      "^CNXPSUBANK"),
    ("Infra",         "^CNXINFRA"),
    ("Pvt Bank",      "^CNXFINANCE"),
    ("Commodities",   "^CNXCOMMODITIES"),
]

COMMODITIES = [
    ("Gold (ETF, INR)",   "GOLDBEES.NS",  "per unit"),
    ("Silver (ETF, INR)", "SILVERBEES.NS", "per unit"),
    ("Gold ($/oz)",       "GC=F",         "COMEX future"),
    ("Silver ($/oz)",     "SI=F",         "COMEX future"),
]

# Nifty 50 constituents (NSE .NS tickers) — used for breadth and top movers.
NIFTY50 = [
    "ADANIENT.NS","ADANIPORTS.NS","APOLLOHOSP.NS","ASIANPAINT.NS","AXISBANK.NS",
    "BAJAJ-AUTO.NS","BAJFINANCE.NS","BAJAJFINSV.NS","BEL.NS","BHARTIARTL.NS",
    "CIPLA.NS","COALINDIA.NS","DRREDDY.NS","EICHERMOT.NS","GRASIM.NS",
    "HCLTECH.NS","HDFCBANK.NS","HDFCLIFE.NS","HEROMOTOCO.NS","HINDALCO.NS",
    "HINDUNILVR.NS","ICICIBANK.NS","INDUSINDBK.NS","INFY.NS","ITC.NS",
    "JSWSTEEL.NS","KOTAKBANK.NS","LT.NS","M&M.NS","MARUTI.NS",
    "NESTLEIND.NS","NTPC.NS","ONGC.NS","POWERGRID.NS","RELIANCE.NS",
    "SBILIFE.NS","SBIN.NS","SHRIRAMFIN.NS","SUNPHARMA.NS","TATACONSUM.NS",
    "TATAMOTORS.NS","TATASTEEL.NS","TCS.NS","TECHM.NS","TITAN.NS",
    "TRENT.NS","ULTRACEMCO.NS","UPL.NS","WIPRO.NS","NTPC.NS",
]
PRETTY = {
    "ADANIENT.NS":"Adani Enterprises","ADANIPORTS.NS":"Adani Ports","APOLLOHOSP.NS":"Apollo Hospitals",
    "ASIANPAINT.NS":"Asian Paints","AXISBANK.NS":"Axis Bank","BAJAJ-AUTO.NS":"Bajaj Auto",
    "BAJFINANCE.NS":"Bajaj Finance","BAJAJFINSV.NS":"Bajaj Finserv","BEL.NS":"Bharat Electronics",
    "BHARTIARTL.NS":"Bharti Airtel","CIPLA.NS":"Cipla","COALINDIA.NS":"Coal India",
    "DRREDDY.NS":"Dr Reddy's","EICHERMOT.NS":"Eicher Motors","GRASIM.NS":"Grasim",
    "HCLTECH.NS":"HCL Tech","HDFCBANK.NS":"HDFC Bank","HDFCLIFE.NS":"HDFC Life",
    "HEROMOTOCO.NS":"Hero MotoCorp","HINDALCO.NS":"Hindalco","HINDUNILVR.NS":"Hind. Unilever",
    "ICICIBANK.NS":"ICICI Bank","INDUSINDBK.NS":"IndusInd Bank","INFY.NS":"Infosys",
    "ITC.NS":"ITC","JSWSTEEL.NS":"JSW Steel","KOTAKBANK.NS":"Kotak Bank","LT.NS":"L&T",
    "M&M.NS":"M&M","MARUTI.NS":"Maruti Suzuki","NESTLEIND.NS":"Nestle India","NTPC.NS":"NTPC",
    "ONGC.NS":"ONGC","POWERGRID.NS":"Power Grid","RELIANCE.NS":"Reliance","SBILIFE.NS":"SBI Life",
    "SBIN.NS":"SBI","SHRIRAMFIN.NS":"Shriram Finance","SUNPHARMA.NS":"Sun Pharma",
    "TATACONSUM.NS":"Tata Consumer","TATAMOTORS.NS":"Tata Motors","TATASTEEL.NS":"Tata Steel",
    "TCS.NS":"TCS","TECHM.NS":"Tech Mahindra","TITAN.NS":"Titan","TRENT.NS":"Trent",
    "ULTRACEMCO.NS":"UltraTech","UPL.NS":"UPL","WIPRO.NS":"Wipro",
}


def _yf():
    """Import yfinance lazily so a missing dependency gives a clean message."""
    import yfinance as yf
    return yf


def _pair_from_history(hist, target_date):
    """Given a daily OHLC DataFrame, return (close_row, prev_close) on/<= target_date.

    Returns dict with close, prev, high, low, change, pct, date — or None if no data.
    """
    if hist is None or len(hist) == 0:
        return None
    # hist index is tz-aware DatetimeIndex; normalise to date for comparison
    rows = [(idx.date(), row) for idx, row in hist.iterrows()]
    rows = [r for r in rows if not _isnan(r[1].get("Close"))]
    if not rows:
        return None
    # last row with date <= target
    on = None
    for d, row in rows:
        if d <= target_date:
            on = (d, row)
        else:
            break
    if on is None:
        return None
    # previous row before 'on'
    idx = rows.index(on)
    prev = rows[idx - 1] if idx > 0 else None
    close = float(on[1]["Close"])
    prev_close = float(prev[1]["Close"]) if prev else None
    change = (close - prev_close) if prev_close is not None else None
    pct = (change / prev_close * 100.0) if prev_close else None
    return {
        "date": on[0].isoformat(),
        "close": close,
        "prev": prev_close,
        "high": float(on[1]["High"]) if not _isnan(on[1].get("High")) else None,
        "low": float(on[1]["Low"]) if not _isnan(on[1].get("Low")) else None,
        "change": change,
        "pct": pct,
    }


def _isnan(x):
    try:
        return x != x
    except Exception:
        return x is None


def _quote(yf, name, ticker, target_date, link=None):
    start = target_date - dt.timedelta(days=12)
    end = target_date + dt.timedelta(days=2)
    hist = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat(),
                                     interval="1d", auto_adjust=False)
    data = _pair_from_history(hist, target_date)
    if not data:
        return None
    data.update({"name": name, "ticker": ticker})
    if link:
        data["link"] = link
    return data


def _pivots(high, low, close):
    if None in (high, low, close):
        return None
    pp = (high + low + close) / 3.0
    return {
        "pp": pp,
        "r1": 2 * pp - low,
        "r2": pp + (high - low),
        "s1": 2 * pp - high,
        "s2": pp - (high - low),
    }


def build_brief(date_str):
    target = dt.date.fromisoformat(date_str)
    yf = _yf()
    notes = []
    out = {"date": target.isoformat(), "generated_at": dt.datetime.now().isoformat(timespec="seconds")}

    weekday = target.weekday()  # 0=Mon .. 6=Sun
    out["weekend"] = weekday >= 5

    # ---- Indices ----
    indices = []
    for name, tkr, link in INDICES:
        try:
            q = _quote(yf, name, tkr, target, link)
            if q:
                indices.append(q)
            else:
                notes.append(f"No data for {name} ({tkr}).")
        except Exception as e:
            notes.append(f"{name}: {e}")
    out["indices"] = indices

    # Verdict from Nifty 50
    nifty = next((i for i in indices if i["name"] == "Nifty 50"), None)
    if nifty and nifty.get("pct") is not None:
        p = nifty["pct"]
        if p >= 0.75:
            tone = "Markets ended sharply higher"
        elif p >= 0.1:
            tone = "Markets closed higher"
        elif p > -0.1:
            tone = "Markets ended flat"
        elif p > -0.75:
            tone = "Markets closed lower"
        else:
            tone = "Markets ended sharply lower"
        out["verdict"] = f"{tone} — Nifty {'+' if p>=0 else ''}{p:.2f}%, closing {nifty['close']:,.2f}."
        out["actual_date"] = nifty["date"]
    else:
        out["verdict"] = "Summary for the selected date."

    # ---- Sectors ----
    sectors = []
    for name, tkr in SECTORS:
        try:
            q = _quote(yf, name, tkr, target)
            if q and q.get("pct") is not None:
                sectors.append({"name": name, "pct": q["pct"], "close": q["close"]})
        except Exception as e:
            notes.append(f"Sector {name}: {e}")
    sectors.sort(key=lambda s: s["pct"], reverse=True)
    out["sectors"] = sectors

    # ---- Commodities ----
    commodities = []
    for name, tkr, sub in COMMODITIES:
        try:
            q = _quote(yf, name, tkr, target)
            if q and q.get("pct") is not None:
                commodities.append({"name": name, "sub": sub, "close": q["close"], "pct": q["pct"]})
        except Exception as e:
            notes.append(f"Commodity {name}: {e}")
    out["commodities"] = commodities

    # ---- Technicals (pivots) for Nifty & Bank Nifty ----
    techs = []
    for want in ("Nifty 50", "Nifty Bank"):
        src = next((i for i in indices if i["name"] == want), None)
        if src:
            pv = _pivots(src.get("high"), src.get("low"), src.get("close"))
            if pv:
                techs.append({"name": want, **pv})
    out["technicals"] = techs

    # ---- Breadth + Top movers (Nifty 50 constituents) ----
    try:
        tickers = sorted(set(NIFTY50))
        start = target - dt.timedelta(days=12)
        end = target + dt.timedelta(days=2)
        df = yf.download(tickers, start=start.isoformat(), end=end.isoformat(),
                         interval="1d", auto_adjust=False, group_by="ticker",
                         threads=True, progress=False)
        moves = []
        for t in tickers:
            try:
                sub = df[t] if t in df.columns.get_level_values(0) else None
                if sub is None:
                    continue
                q = _pair_from_history(sub, target)
                if q and q.get("pct") is not None:
                    moves.append({"name": PRETTY.get(t, t.replace(".NS", "")), "pct": q["pct"]})
            except Exception:
                continue
        if moves:
            adv = sum(1 for m in moves if m["pct"] > 0)
            dec = sum(1 for m in moves if m["pct"] < 0)
            out["breadth"] = {"adv": adv, "dec": dec, "universe": "Nifty 50"}
            moves.sort(key=lambda m: m["pct"], reverse=True)
            out["gainers"] = moves[:5]
            out["losers"] = list(reversed(moves[-5:]))
        else:
            notes.append("No constituent data for breadth/movers on this date.")
    except Exception as e:
        notes.append(f"Breadth/movers: {e}")

    if not indices:
        notes.append("No index data returned — the market may have been closed on this date, "
                     "or the data source was unreachable. Check your internet connection.")

    out["notes"] = notes
    return out


# ----------------------------------------------------------------------------
# HTTP server
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # keep the console quiet

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            try:
                import os
                here = os.path.dirname(os.path.abspath(__file__))
                with open(os.path.join(here, "index.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except Exception as e:
                self._send(500, f"Could not load index.html: {e}", "text/plain; charset=utf-8")
            return

        if parsed.path == "/api/brief":
            qs = parse_qs(parsed.query)
            date_str = (qs.get("date", [""])[0]) or dt.date.today().isoformat()
            try:
                brief = build_brief(date_str)
                self._send(200, json.dumps(brief))
            except ModuleNotFoundError:
                self._send(200, json.dumps({
                    "error": "yfinance is not installed. Run:  pip install yfinance",
                    "fatal": True,
                }))
            except Exception as e:
                self._send(200, json.dumps({
                    "error": f"{e}",
                    "trace": traceback.format_exc(),
                    "fatal": True,
                }))
            return

        self._send(404, "Not found", "text/plain; charset=utf-8")


def main():
    port = PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("=" * 52)
    print("  India Market Pulse is running")
    print(f"  Open:  http://localhost:{port}")
    print("  Press Ctrl+C in this window to stop.")
    print("=" * 52)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        srv.server_close()


if __name__ == "__main__":
    main()
