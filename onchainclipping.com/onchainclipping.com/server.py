#!/usr/bin/env python3
"""clippd local marketplace server — campaigns, Solana vaults, deposit checks."""
from __future__ import print_function

import json
import os
import random
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from nacl.signing import SigningKey

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_env(path):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


load_env(os.path.join(ROOT, ".env"))

DATA_DIR = os.path.join(ROOT, "data")
CAMPAIGNS_PATH = os.path.join(DATA_DIR, "campaigns.json")
KEYS_PATH = os.path.join(DATA_DIR, "vault-keys.json")
KEYS_TXT = os.path.join(DATA_DIR, "VAULT_KEYS.txt")
os.chdir(ROOT)
os.makedirs(DATA_DIR, exist_ok=True)

MIN_BUDGET_USD = float(os.environ.get("MIN_BUDGET_USD") or 10)
LOCK = threading.Lock()
QUOTE_CACHE = {"price": None, "at": 0}

RPCS = []
helius = (os.environ.get("HELIUS_API_KEY") or "").strip()
if helius:
    RPCS.append("https://mainnet.helius-rpc.com/?api-key=%s" % helius)
for key in ("SOLANA_RPC_URL", "SOLANA_RPC_FALLBACK", "SOLANA_RPC_FALLBACK_2"):
    url = (os.environ.get(key) or "").strip()
    if url and url not in RPCS:
        RPCS.append(url)
if not RPCS:
    RPCS = ["https://api.mainnet-beta.solana.com"]

PRICE_URLS = [
    os.environ.get("PRICE_URL") or "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
    os.environ.get("PRICE_URL_FALLBACK") or "https://lite-api.jup.ag/price/v2?ids=So11111111111111111111111111111111111111112",
]

B58 = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
PLATFORMS = ("tiktok", "instagram", "youtube", "x")
DEMO_ID = "ansem"


def demo_campaign():
    tiktok = "https://www.tiktok.com/@scout2015/video/6718335390845095173"
    insta = "https://www.instagram.com/p/BwglRkehKXj/"
    yt = "https://www.youtube.com/shorts/2lCCc7kmHMk"
    x = "https://x.com/solana/status/1740000000000000000"
    return {
        "id": DEMO_ID,
        "ticker": "$ANSEM",
        "name": "$ANSEM",
        "demo": True,
        "contract": "9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump",
        "hashtag": "#ansem",
        "brief": "Clip Ansem. Face-cam UGC hits the boosted rate. Original edits only — no straight reposts.",
        "budget_usd": 2000,
        "rate_per_1k_usd": 1.5,
        "ugc_rate_per_1k_usd": 3.5,
        "viral_bonus_usd": 500,
        "min_views": 5000,
        "duration_days": 10,
        "platforms": list(PLATFORMS),
        "status": "live",
        "vault_address": "ClippdDemoVault111111111111111111111111111",
        "expected_sol": 10,
        "expected_lamports": 10_000_000_000,
        "sol_price_usd": 200,
        "received_sol": 10,
        "received_lamports": 10_000_000_000,
        "created_at": "2026-08-01T00:00:00+00:00",
        "funded_at": "2026-08-01T00:00:00+00:00",
        "funding_signature": None,
        "spent_usd": 742,
        "color": "#3B82F6",
        "image": "/__l5e/assets-v1/050112d9-b324-41b8-af85-71eeff3c373d/ansem.avif",
        "submissions": [
            {
                "id": "demo-tt-1",
                "url": tiktok,
                "platform": "tiktok",
                "handle": "@crypto_native",
                "created_at": "2026-08-20T14:00:00+00:00",
                "status": "verified",
                "embed": embed_info(tiktok, "tiktok"),
            },
            {
                "id": "demo-ig-1",
                "url": insta,
                "platform": "instagram",
                "handle": "@ne_reels",
                "created_at": "2026-08-19T11:20:00+00:00",
                "status": "verified",
                "embed": embed_info(insta, "instagram"),
            },
            {
                "id": "demo-yt-1",
                "url": yt,
                "platform": "youtube",
                "handle": "@clipped_daily",
                "created_at": "2026-08-18T09:10:00+00:00",
                "status": "submitted",
                "embed": embed_info(yt, "youtube"),
            },
            {
                "id": "demo-x-1",
                "url": x,
                "platform": "x",
                "handle": "@nickisback_",
                "created_at": "2026-08-17T18:40:00+00:00",
                "status": "submitted",
                "embed": embed_info(x, "x"),
            },
        ],
    }


def b58encode(data):
    n = int.from_bytes(data, "big")
    out = bytearray()
    while n > 0:
        n, r = divmod(n, 58)
        out.append(B58[r])
    pad = 0
    for b in data:
        if b == 0:
            pad += 1
        else:
            break
    return (B58[0:1] * pad + out[::-1]).decode("ascii")


def b58decode(s):
    n = 0
    for ch in s.encode("ascii"):
        n = n * 58 + B58.index(ch)
    full = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = 0
    for ch in s:
        if ch == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + full


def valid_solana_address(addr):
    try:
        raw = b58decode(str(addr or "").strip())
        return len(raw) == 32
    except Exception:
        return False


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def write_keys_txt(keys, campaigns):
    campaigns_by_id = {c["id"]: c for c in campaigns}
    lines = [
        "clippd campaign vault keys",
        "KEEP THIS FILE SECRET.",
        "Each campaign has its own Solana wallet. Import secret_json in Phantom (legacy private key)",
        "or secret_base58 in a Solana CLI/wallet that accepts a 64-byte secret.",
        "",
    ]
    for k in keys:
        c = campaigns_by_id.get(k["campaign_id"], {})
        lines.extend(
            [
                "=" * 64,
                "%s  /  %s" % (c.get("ticker") or k.get("ticker"), c.get("name") or ""),
                "campaign_id:     %s" % k["campaign_id"],
                "created:         %s" % k.get("created_at", ""),
                "status:          %s" % c.get("status", ""),
                "budget_usd:      $%s" % c.get("budget_usd", ""),
                "expected_sol:    %s" % c.get("expected_sol", ""),
                "received_sol:    %s" % c.get("received_sol", 0),
                "sol_price_usd:   %s" % c.get("sol_price_usd", ""),
                "address:         %s" % k["address"],
                "secret_base58:   %s" % k["secret_base58"],
                "secret_json:     %s" % json.dumps(k["secret_json"]),
                "",
            ]
        )
    with open(KEYS_TXT, "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def generate_wallet():
    sk = SigningKey.generate()
    seed = sk.encode()
    pub = bytes(sk.verify_key)
    secret64 = seed + pub
    return {
        "address": b58encode(pub),
        "secret_base58": b58encode(secret64),
        "secret_json": list(secret64),
    }


def http_json(url, payload=None, timeout=12):
    body = None
    headers = {"Accept": "application/json", "User-Agent": "clippd/1.0"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def sol_usd_price():
    now = time.time()
    if QUOTE_CACHE["price"] and now - QUOTE_CACHE["at"] < 30:
        return QUOTE_CACHE["price"]
    price = None
    try:
        data = http_json(PRICE_URLS[0])
        price = float(data["solana"]["usd"])
    except Exception:
        try:
            data = http_json(PRICE_URLS[1])
            price = float(data["data"]["So11111111111111111111111111111111111111112"]["price"])
        except Exception:
            price = QUOTE_CACHE["price"]
    if not price:
        raise RuntimeError("Could not fetch SOL price")
    QUOTE_CACHE["price"] = price
    QUOTE_CACHE["at"] = now
    return price


def rpc(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last = None
    for url in RPCS:
        try:
            data = http_json(url, payload, timeout=10)
            if data.get("error"):
                last = data["error"]
                continue
            return data.get("result")
        except Exception as e:
            last = e
            continue
    raise RuntimeError("Solana RPC failed: %s" % last)


def get_balance_lamports(address):
    result = rpc("getBalance", [address, {"commitment": "confirmed"}])
    if isinstance(result, dict):
        return int(result.get("value") or 0)
    return int(result or 0)


def latest_sig(address):
    try:
        result = rpc("getSignaturesForAddress", [address, {"limit": 1}])
        if result:
            return result[0].get("signature")
    except Exception:
        return None
    return None


def slugify(ticker):
    s = re.sub(r"[^a-z0-9]+", "-", ticker.lower().lstrip("$")).strip("-")
    return s or "campaign"


def public_campaign(c, include_submissions=True):
    out = dict(c)
    if not include_submissions:
        out.pop("submissions", None)
    return out


def stored_campaigns():
    return load_json(CAMPAIGNS_PATH, [])


def find_campaign(cid):
    rows = stored_campaigns()
    found = next((x for x in rows if x.get("id") == cid), None)
    if found:
        if cid == DEMO_ID:
            found["demo"] = True
        return found
    if cid == DEMO_ID:
        return demo_campaign()
    return None


def list_campaigns():
    rows = [c for c in stored_campaigns() if c.get("id") != DEMO_ID]
    demo = next((x for x in stored_campaigns() if x.get("id") == DEMO_ID), None)
    if demo:
        demo["demo"] = True
        rows.insert(0, demo)
    else:
        rows.insert(0, demo_campaign())
    return rows


def refresh_deposit(c):
    if c.get("demo"):
        return c
    if not c.get("vault_address"):
        return c
    lamports = get_balance_lamports(c["vault_address"])
    sol = lamports / 1e9
    c["received_lamports"] = lamports
    c["received_sol"] = round(sol, 9)
    c["balance_checked_at"] = utcnow()
    expected = int(c.get("expected_lamports") or 0)
    if c.get("status") != "live" and expected and lamports >= max(0, expected - 5000):
        c["status"] = "live"
        c["funded_at"] = utcnow()
        c["funding_signature"] = latest_sig(c["vault_address"])
    return c


def quote_payload(usd):
    price = sol_usd_price()
    usd = float(usd)
    sol = usd / price
    return {
        "usd": round(usd, 2),
        "sol": round(sol, 9),
        "lamports": int(sol * 1e9),
        "sol_price_usd": round(price, 4),
        "min_budget_usd": MIN_BUDGET_USD,
    }


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args), flush=True)

    def _json(self, code, obj):
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            if path == "/api/campaigns":
                return self._create_campaign()
            m = re.match(r"^/api/campaigns/([^/]+)/clips$", path)
            if m:
                return self._add_clip(m.group(1))
            self._json(404, {"error": "not found"})
        except Exception as e:
            self._json(400, {"error": str(e)})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/api/quote":
            try:
                usd = float((qs.get("usd") or ["10"])[0])
                self._json(200, quote_payload(usd))
            except Exception as e:
                self._json(502, {"error": str(e)})
            return

        if path == "/api/campaigns":
            with LOCK:
                campaigns = stored_campaigns()
                changed = False
                for c in campaigns:
                    if c.get("demo") or c.get("id") == DEMO_ID:
                        continue
                    try:
                        refresh_deposit(c)
                        changed = True
                    except Exception:
                        pass
                if changed:
                    save_json(CAMPAIGNS_PATH, campaigns)
                    write_keys_txt(load_json(KEYS_PATH, []), campaigns)
                out = [public_campaign(c) for c in list_campaigns()]
            self._json(200, {"campaigns": out})
            return

        m = re.match(r"^/api/campaigns/([^/]+)/?$", path)
        if m:
            cid = m.group(1)
            with LOCK:
                c = find_campaign(cid)
                if not c:
                    self._json(404, {"error": "campaign not found"})
                    return
                if not c.get("demo") and c.get("id") != DEMO_ID:
                    try:
                        refresh_deposit(c)
                        rows = stored_campaigns()
                        for i, row in enumerate(rows):
                            if row.get("id") == cid:
                                rows[i] = c
                        save_json(CAMPAIGNS_PATH, rows)
                        write_keys_txt(load_json(KEYS_PATH, []), rows)
                    except Exception:
                        pass
            self._json(200, {"campaign": public_campaign(c)})
            return

        if path in ("/dashboard", "/dashboard/"):
            self.send_response(302)
            self.send_header("Location", "/launch")
            self.end_headers()
            return

        app_routes = path == "/launch" or path.startswith("/launch/") or path == "/campaigns" or path.startswith("/campaigns/")
        local = self.translate_path(self.path)
        is_asset = path.startswith("/assets/") or path.startswith("/__l5e/") or path.lower().endswith(
            (".js", ".css", ".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".svg", ".woff", ".woff2", ".mp4", ".map")
        )
        if path != "/" and not os.path.exists(local):
            if is_asset:
                self.send_error(404, "File not found")
                return
            if app_routes:
                self.path = "/app.html"
            else:
                self.path = "/index.html"
        return SimpleHTTPRequestHandler.do_GET(self)

    def _create_campaign(self):
        body = self._read_json()
        ticker = str(body.get("ticker") or "").strip().upper()
        if ticker and not ticker.startswith("$"):
            ticker = "$" + ticker
        name = str(body.get("name") or ticker or "").strip()
        if not ticker or len(ticker) < 2:
            return self._json(400, {"error": "Token ticker is required"})
        creator = str(body.get("creator_wallet") or "").strip()
        creator_wallet_name = str(body.get("creator_wallet_name") or "").strip()
        if not valid_solana_address(creator):
            return self._json(400, {"error": "Connect a Solana wallet (Phantom, Solflare, or MetaMask) to launch."})
        try:
            budget_usd = float(body.get("budget_usd"))
            rate_per_1k_usd = float(body.get("rate_per_1k_usd"))
        except Exception:
            return self._json(400, {"error": "Budget and rate per 1K views are required"})
        if budget_usd < MIN_BUDGET_USD:
            return self._json(400, {"error": "Minimum budget is $%s USD" % int(MIN_BUDGET_USD)})
        if rate_per_1k_usd <= 0:
            return self._json(400, {"error": "Rate per 1K views must be greater than 0"})

        platforms = [p for p in (body.get("platforms") or PLATFORMS) if p in PLATFORMS]
        if not platforms:
            platforms = list(PLATFORMS)

        q = quote_payload(budget_usd)
        wallet = generate_wallet()
        cid = "%s-%s" % (slugify(ticker), uuid.uuid4().hex[:6])
        ugc = body.get("ugc_rate_per_1k_usd")
        viral = body.get("viral_bonus_usd")
        try:
            min_views = int(body.get("min_views") or 1000)
        except Exception:
            min_views = 1000
        try:
            days = int(body.get("duration_days") or 14)
        except Exception:
            days = 14

        campaign = {
            "id": cid,
            "ticker": ticker,
            "name": name,
            "contract": str(body.get("contract") or "").strip(),
            "hashtag": str(body.get("hashtag") or "").strip(),
            "brief": str(body.get("brief") or "").strip(),
            "budget_usd": round(budget_usd, 2),
            "rate_per_1k_usd": round(rate_per_1k_usd, 4),
            "ugc_rate_per_1k_usd": round(float(ugc), 4) if ugc not in (None, "") else None,
            "viral_bonus_usd": round(float(viral), 2) if viral not in (None, "") else None,
            "min_views": max(0, min_views),
            "duration_days": max(1, days),
            "platforms": platforms,
            "status": "awaiting_deposit",
            "vault_address": wallet["address"],
            "expected_sol": q["sol"],
            "expected_lamports": q["lamports"],
            "sol_price_usd": q["sol_price_usd"],
            "received_sol": 0,
            "received_lamports": 0,
            "created_at": utcnow(),
            "funded_at": None,
            "funding_signature": None,
            "spent_usd": 0,
            "color": random.choice(["#40bd85", "#3B82F6", "#F59E0B", "#EC4899", "#8B5CF6"]),
            "image": (str(body.get("image") or "").strip()[:400000] or None),
            "creator_wallet": creator,
            "creator_wallet_name": creator_wallet_name,
            "submissions": [],
        }
        key_row = {
            "campaign_id": cid,
            "ticker": ticker,
            "name": name,
            "address": wallet["address"],
            "secret_base58": wallet["secret_base58"],
            "secret_json": wallet["secret_json"],
            "created_at": campaign["created_at"],
            "expected_sol": q["sol"],
            "budget_usd": campaign["budget_usd"],
        }
        with LOCK:
            campaigns = load_json(CAMPAIGNS_PATH, [])
            campaigns.insert(0, campaign)
            save_json(CAMPAIGNS_PATH, campaigns)
            keys = load_json(KEYS_PATH, [])
            keys.insert(0, key_row)
            save_json(KEYS_PATH, keys)
            write_keys_txt(keys, campaigns)

        self._json(
            201,
            {
                "campaign": public_campaign(campaign),
                "vault": {
                    "address": wallet["address"],
                    "secret_base58": wallet["secret_base58"],
                    "secret_json": wallet["secret_json"],
                    "keys_file": "data/VAULT_KEYS.txt",
                },
                "quote": q,
            },
        )

    def _add_clip(self, cid):
        body = self._read_json()
        url = str(body.get("url") or "").strip()
        clipper = str(body.get("clipper_wallet") or "").strip()
        clipper_wallet_name = str(body.get("clipper_wallet_name") or "").strip()
        if not valid_solana_address(clipper):
            return self._json(400, {"error": "Connect a Solana wallet (Phantom, Solflare, or MetaMask) to submit a clip."})
        if not url or not re.match(r"^https?://", url, re.I):
            return self._json(400, {"error": "Paste a full http(s) link to the clip"})
        platform = detect_platform(url)
        if not platform:
            return self._json(400, {"error": "Link must be TikTok, Instagram, YouTube, or X"})
        with LOCK:
            c = find_campaign(cid)
            if not c:
                return self._json(404, {"error": "campaign not found"})
            if not c.get("demo"):
                try:
                    refresh_deposit(c)
                except Exception:
                    pass
            if c.get("status") != "live":
                return self._json(400, {"error": "Campaign is not live yet. Vault must be funded first."})
            if platform not in c.get("platforms", PLATFORMS):
                return self._json(400, {"error": "This campaign does not accept %s clips" % platform})
            clip = {
                "id": "clip-%s" % uuid.uuid4().hex[:8],
                "url": url,
                "platform": platform,
                "handle": str(body.get("handle") or "").strip(),
                "clipper_wallet": clipper,
                "clipper_wallet_name": clipper_wallet_name,
                "created_at": utcnow(),
                "status": "submitted",
                "embed": embed_info(url, platform),
            }
            c.setdefault("submissions", []).insert(0, clip)
            rows = stored_campaigns()
            idx = next((i for i, row in enumerate(rows) if row.get("id") == c["id"]), None)
            if idx is None:
                rows.insert(0, c)
            else:
                rows[idx] = c
            save_json(CAMPAIGNS_PATH, rows)
        self._json(201, {"clip": clip, "campaign": public_campaign(c)})


def detect_platform(url):
    u = url.lower()
    if "tiktok.com" in u or "vm.tiktok.com" in u:
        return "tiktok"
    if "instagram.com" in u:
        return "instagram"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "twitter.com" in u or "x.com" in u:
        return "x"
    return None


def embed_info(url, platform):
    info = {"platform": platform, "url": url}
    if platform == "tiktok":
        m = re.search(r"/video/(\d+)", url)
        if m:
            info["id"] = m.group(1)
            info["iframe"] = "https://www.tiktok.com/embed/v2/%s" % m.group(1)
    elif platform == "instagram":
        m = re.search(r"instagram.com/(?:reel|p|tv)/([^/?#]+)", url, re.I)
        if m:
            info["id"] = m.group(1)
            kind = "reel" if "/reel/" in url.lower() else "p"
            info["iframe"] = "https://www.instagram.com/%s/%s/embed" % (kind, m.group(1))
    elif platform == "youtube":
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{6,})", url)
        if m:
            info["id"] = m.group(1)
            info["iframe"] = "https://www.youtube.com/embed/%s" % m.group(1)
    return info


if __name__ == "__main__":
    port = int(os.environ.get("PORT") or 5173)
    host = os.environ.get("HOST") or "0.0.0.0"
    server = ThreadingHTTPServer((host, port), Handler)
    print("clippd marketplace  http://%s:%s" % (host, port), flush=True)
    print("vault keys          %s" % KEYS_TXT, flush=True)
    server.serve_forever()
