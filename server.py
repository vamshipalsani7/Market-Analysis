"""
India Market Pulse - local data engine (v2).

Serves the dashboard (index.html) and a JSON API at /api/brief?date=YYYY-MM-DD.

Data sources (all free, no API key):
  * NSE India JSON endpoints  -> live indices, sectors, breadth, FII/DII activity
  * Financial-press RSS feeds -> market news with links
  * Yahoo Finance (yfinance)  -> historical index/sector/commodity data, pivots,
                                 top movers, and a fallback when NSE is unreachable

Nothing leaves the machine except the requests that fetch this public data.

Run:  python server.py        (or double-click run.bat on Windows)
Open: http://localhost:8765
"""

import json
import sys
import os
import datetime as dt
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = 8765
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# ---------------------------------------------------------------- symbol maps
INDICES = [
    ("Sensex",            "^BSESN",     "https://www.google.com/finance/quote/SENSEX:INDEXBOM"),
    ("Nifty 50",          "^NSEI",      "https://www.google.com/finance/quote/NIFTY_50:INDEXNSE"),
    ("Nifty Bank",        "^NSEBANK",   "https://www.google.com/finance/quote/NIFTY_BANK:INDEXNSE"),
    ("Nifty Midcap 50",   "^NSEMDCP50", "https://www.google.com/finance/quote/NIFTY_MIDCAP_50:INDEXNSE"),
    ("India VIX",         "^INDIAVIX",  "https://www.google.com/finance/quote/INDIA_VIX:INDEXNSE"),
]
# NSE allIndices "index" name -> (display name, google link) for the headline cards
NSE_INDEX_CARDS = {
    "NIFTY 50":           ("Nifty 50",         "https://www.google.com/finance/quote/NIFTY_50:INDEXNSE"),
    "NIFTY BANK":         ("Nifty Bank",       "https://www.google.com/finance/quote/NIFTY_BANK:INDEXNSE"),
    "NIFTY MIDCAP 100":   ("Nifty Midcap 100", "https://www.google.com/finance/quote/NIFTY_MIDCAP_100:INDEXNSE"),
    "NIFTY SMALLCAP 100": ("Nifty Smallcap 100","https://www.google.com/finance/quote/NIFTY_SMLCAP_100:INDEXNSE"),
    "INDIA VIX":          ("India VIX",        "https://www.google.com/finance/quote/INDIA_VIX:INDEXNSE"),
}
# NSE sectoral index name -> short label
NSE_SECTORS = {
    "NIFTY IT": "IT", "NIFTY AUTO": "Auto", "NIFTY PHARMA": "Pharma",
    "NIFTY FMCG": "FMCG", "NIFTY METAL": "Metal", "NIFTY REALTY": "Realty",
    "NIFTY MEDIA": "Media", "NIFTY PSU BANK": "PSU Bank",
    "NIFTY PRIVATE BANK": "Pvt Bank", "NIFTY FINANCIAL SERVICES": "Fin Services",
    "NIFTY ENERGY": "Energy", "NIFTY INFRASTRUCTURE": "Infra",
    "NIFTY CONSUMER DURABLES": "Con. Durables", "NIFTY HEALTHCARE INDEX": "Healthcare",
    "NIFTY OIL & GAS": "Oil & Gas",
}

SECTORS_YF = [
    ("IT", "^CNXIT"), ("Auto", "^CNXAUTO"), ("Pharma", "^CNXPHARMA"),
    ("FMCG", "^CNXFMCG"), ("Metal", "^CNXMETAL"), ("Energy", "^CNXENERGY"),
    ("Realty", "^CNXREALTY"), ("Media", "^CNXMEDIA"), ("PSU Bank", "^CNXPSUBANK"),
    ("Infra", "^CNXINFRA"),
]
COMMODITIES = [
    ("Gold (ETF, INR)",   "GOLDBEES.NS",   "per unit"),
    ("Silver (ETF, INR)", "SILVERBEES.NS", "per unit"),
    ("Gold ($/oz)",       "GC=F",          "COMEX future"),
    ("Silver ($/oz)",     "SI=F",          "COMEX future"),
]
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
    "TRENT.NS","ULTRACEMCO.NS","UPL.NS","WIPRO.NS",
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

NEWS_FEEDS = [
    ("Economic Times",  "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Moneycontrol",    "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("Business Standard","https://www.business-standard.com/rss/markets-106.rss"),
    ("Livemint",        "https://www.livemint.com/rss/markets"),
]


# -------------------------------------------------------------------- helpers
def _isnan(x):
    try:
        return x != x
    except Exception:
        return x is None


def _yf():
    import yfinance as yf
    return yf


def _pair_from_history(hist, target_date):
    if hist is None or len(hist) == 0:
        return None
    rows = [(idx.date(), row) for idx, row in hist.iterrows()]
    rows = [r for r in rows if not _isnan(r[1].get("Close"))]
    if not rows:
        return None
    on = None
    for d, row in rows:
        if d <= target_date:
            on = (d, row)
        else:
            break
    if on is None:
        return None
    idx = rows.index(on)
    prev = rows[idx - 1] if idx > 0 else None
    close = float(on[1]["Close"])
    prev_close = float(prev[1]["Close"]) if prev else None
    change = (close - prev_close) if prev_close is not None else None
    pct = (change / prev_close * 100.0) if prev_close else None
    return {
        "date": on[0].isoformat(), "close": close, "prev": prev_close,
        "high": float(on[1]["High"]) if not _isnan(on[1].get("High")) else None,
        "low": float(on[1]["Low"]) if not _isnan(on[1].get("Low")) else None,
        "change": change, "pct": pct,
    }


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
    return {"pp": pp, "r1": 2 * pp - low, "r2": pp + (high - low),
            "s1": 2 * pp - high, "s2": pp - (high - low)}


# --------------------------------------------------------------- NSE (live)
def nse_session():
    """A requests session primed with NSE cookies so /api/ calls are accepted."""
    import requests
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
        "Connection": "keep-alive",
    })
    # priming requests set the cookies the API gateway expects
    s.get("https://www.nseindia.com/", timeout=8)
    s.get("https://www.nseindia.com/market-data/live-equity-market", timeout=8)
    return s


def nse_get(s, url):
    r = s.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


def nse_live(target, notes):
    """Return dict with indices/sectors/breadth/fii_dii from NSE, best-effort."""
    out = {}
    try:
        s = nse_session()
    except Exception as e:
        notes.append(f"NSE unreachable ({e}); using Yahoo data.")
        return out

    # all indices (headline cards + sectors + breadth)
    try:
        data = nse_get(s, "https://www.nseindia.com/api/allIndices").get("data", [])
        by_name = {d.get("index", "").upper(): d for d in data}

        cards = []
        for nse_name, (disp, link) in NSE_INDEX_CARDS.items():
            d = by_name.get(nse_name)
            if not d:
                continue
            cards.append({
                "name": disp, "link": link,
                "close": _f(d.get("last")),
                "change": _f(d.get("variation")),
                "pct": _f(d.get("percentChange")),
            })
        if cards:
            out["indices"] = cards

        secs = []
        for nse_name, label in NSE_SECTORS.items():
            d = by_name.get(nse_name)
            if d and d.get("percentChange") is not None:
                secs.append({"name": label, "pct": _f(d.get("percentChange")),
                             "close": _f(d.get("last"))})
        if secs:
            secs.sort(key=lambda x: (x["pct"] if x["pct"] is not None else 0), reverse=True)
            out["sectors"] = secs

        n50 = by_name.get("NIFTY 50")
        if n50 and n50.get("advances") is not None:
            out["breadth"] = {"adv": int(_f(n50.get("advances")) or 0),
                              "dec": int(_f(n50.get("declines")) or 0),
                              "universe": "Nifty 50"}
    except Exception as e:
        notes.append(f"NSE indices: {e}")

    # FII / DII cash activity (provisional, most recent session)
    try:
        fd = nse_get(s, "https://www.nseindia.com/api/fiidiiTradeReact")
        flows = []
        for row in fd:
            cat = (row.get("category") or "").upper()
            label = "FII" if "FII" in cat or "FPI" in cat else ("DII" if "DII" in cat else cat)
            flows.append({
                "label": label,
                "net": _f(row.get("netValue")),
                "buy": _f(row.get("buyValue")),
                "sell": _f(row.get("sellValue")),
                "date": row.get("date"),
            })
        if flows:
            out["fii_dii"] = flows
    except Exception as e:
        notes.append(f"NSE FII/DII: {e}")

    return out


def _f(v):
    if v is None:
        return None
    try:
        if isinstance(v, str):
            v = v.replace(",", "").strip()
            if v in ("", "-"):
                return None
        return float(v)
    except Exception:
        return None


# --------------------------------------------------------------- News (RSS)
def fetch_news(notes, limit=8):
    import requests
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    items = []
    headers = {"User-Agent": UA}
    for source, url in NEWS_FEEDS:
        try:
            r = requests.get(url, headers=headers, timeout=8)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            for it in root.iter("item"):
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").strip()
                pub = (it.findtext("pubDate") or "").strip()
                if not title or not link:
                    continue
                ts = None
                try:
                    ts = parsedate_to_datetime(pub)
                except Exception:
                    ts = None
                items.append({"source": source, "title": title, "link": link,
                              "ts": ts.timestamp() if ts else 0,
                              "when": ts.strftime("%d %b, %H:%M") if ts else ""})
        except Exception as e:
            notes.append(f"News {source}: {e}")
    items.sort(key=lambda x: x["ts"], reverse=True)
    # de-dupe by title
    seen, uniq = set(), []
    for it in items:
        k = it["title"].lower()[:70]
        if k in seen:
            continue
        seen.add(k)
        uniq.append({k2: it[k2] for k2 in ("source", "title", "link", "when")})
        if len(uniq) >= limit:
            break
    return uniq


# ------------------------------------------------------------------- builder
def last_trading_day(today=None):
    d = today or dt.date.today()
    while d.weekday() >= 5:   # Sat/Sun -> previous Friday
        d -= dt.timedelta(days=1)
    return d


def build_brief(date_str):
    target = dt.date.fromisoformat(date_str)
    yf = _yf()
    notes = []
    out = {"date": target.isoformat(),
           "generated_at": dt.datetime.now().isoformat(timespec="seconds")}
    out["weekend"] = target.weekday() >= 5

    last_sess = last_trading_day()
    is_live = target >= last_sess
    out["live"] = False

    nse = nse_live(target, notes) if is_live else {}
    if nse.get("indices"):
        out["live"] = True

    # ---- Indices ----
    if nse.get("indices"):
        indices = list(nse["indices"])
        # add Sensex (BSE) from Yahoo since NSE allIndices has no Sensex
        try:
            sx = _quote(yf, "Sensex", "^BSESN", target,
                        "https://www.google.com/finance/quote/SENSEX:INDEXBOM")
            if sx:
                indices.insert(0, {k: sx.get(k) for k in ("name", "link", "close", "change", "pct")})
        except Exception as e:
            notes.append(f"Sensex: {e}")
        out["indices"] = indices
    else:
        indices = []
        for name, tkr, link in INDICES:
            try:
                q = _quote(yf, name, tkr, target, link)
                if q:
                    indices.append(q)
            except Exception as e:
                notes.append(f"{name}: {e}")
        out["indices"] = indices

    # verdict from Nifty 50
    nifty = next((i for i in out["indices"] if i["name"] == "Nifty 50"), None)
    if nifty and nifty.get("pct") is not None:
        p = nifty["pct"]
        tone = ("Markets ended sharply higher" if p >= 0.75 else
                "Markets closed higher" if p >= 0.1 else
                "Markets ended flat" if p > -0.1 else
                "Markets closed lower" if p > -0.75 else
                "Markets ended sharply lower")
        out["verdict"] = f"{tone} — Nifty {'+' if p>=0 else ''}{p:.2f}%, at {nifty['close']:,.2f}."
    else:
        out["verdict"] = "Market summary for the selected date."

    ad = next((i.get("date") for i in out["indices"] if i.get("date")), None)
    if ad:
        out["actual_date"] = ad

    # ---- Sectors ----
    if nse.get("sectors"):
        out["sectors"] = nse["sectors"]
    else:
        secs = []
        for name, tkr in SECTORS_YF:
            try:
                q = _quote(yf, name, tkr, target)
                if q and q.get("pct") is not None:
                    secs.append({"name": name, "pct": q["pct"], "close": q["close"]})
            except Exception as e:
                notes.append(f"Sector {name}: {e}")
        secs.sort(key=lambda s: s["pct"], reverse=True)
        out["sectors"] = secs

    # ---- Breadth ----
    if nse.get("breadth"):
        out["breadth"] = nse["breadth"]

    # ---- FII / DII ----
    if nse.get("fii_dii"):
        out["fii_dii"] = nse["fii_dii"]

    # ---- Commodities (Yahoo) ----
    commodities = []
    for name, tkr, sub in COMMODITIES:
        try:
            q = _quote(yf, name, tkr, target)
            if q and q.get("pct") is not None:
                commodities.append({"name": name, "sub": sub, "close": q["close"], "pct": q["pct"]})
        except Exception as e:
            notes.append(f"Commodity {name}: {e}")
    out["commodities"] = commodities

    # ---- Technicals (pivots) from Yahoo OHLC ----
    techs = []
    for want, tkr in (("Nifty 50", "^NSEI"), ("Nifty Bank", "^NSEBANK")):
        try:
            q = _quote(yf, want, tkr, target)
            if q:
                pv = _pivots(q.get("high"), q.get("low"), q.get("close"))
                if pv:
                    techs.append({"name": want, **pv})
        except Exception as e:
            notes.append(f"Pivots {want}: {e}")
    out["technicals"] = techs

    # ---- Breadth + movers from Nifty 50 constituents (Yahoo) ----
    if "breadth" not in out or not out.get("breadth"):
        pass  # may be filled below
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
                lvl0 = df.columns.get_level_values(0)
                sub = df[t] if t in lvl0 else None
                if sub is None:
                    continue
                q = _pair_from_history(sub, target)
                if q and q.get("pct") is not None:
                    moves.append({"name": PRETTY.get(t, t.replace(".NS", "")), "pct": q["pct"]})
            except Exception:
                continue
        if moves:
            if not out.get("breadth"):
                out["breadth"] = {"adv": sum(1 for m in moves if m["pct"] > 0),
                                  "dec": sum(1 for m in moves if m["pct"] < 0),
                                  "universe": "Nifty 50"}
            moves.sort(key=lambda m: m["pct"], reverse=True)
            out["gainers"] = moves[:5]
            out["losers"] = list(reversed(moves[-5:]))
    except Exception as e:
        notes.append(f"Movers: {e}")

    # ---- News (RSS, most recent) ----
    try:
        news = fetch_news(notes)
        if news:
            out["news"] = news
    except Exception as e:
        notes.append(f"News: {e}")

    if not out["indices"]:
        notes.append("No index data — markets may have been closed on this date, or the "
                     "data sources were unreachable. Check your internet connection.")

    out["notes"] = notes
    return out


# ----------------------------------------------------------------- HTTP layer
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

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
                self._send(200, json.dumps(build_brief(date_str)))
            except ModuleNotFoundError as e:
                self._send(200, json.dumps({
                    "error": f"A required library is missing ({e}). Run:  pip install -r requirements.txt",
                    "fatal": True}))
            except Exception as e:
                self._send(200, json.dumps({"error": str(e),
                                            "trace": traceback.format_exc(), "fatal": True}))
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
