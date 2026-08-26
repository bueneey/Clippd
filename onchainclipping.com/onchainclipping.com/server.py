#!/usr/bin/env python3
"""Clippd marketplace server — campaigns, Solana vaults, deposit checks."""
from __future__ import print_function

import json
import os
import random
import re
import threading
import time
import uuid
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from solders.hash import Hash
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

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
            # Railway (and other hosts) inject PORT. A local .env PORT=5173 would
            # make the process listen where the proxy is not sending traffic.
            if key in ("PORT", "HOST"):
                continue
            if key and key not in os.environ:
                os.environ[key] = val


def on_railway():
    return bool(
        os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("RAILWAY_ENVIRONMENT_ID")
        or os.environ.get("RAILWAY_PROJECT_ID")
    )


def listen_bind():
    host = "0.0.0.0"
    raw = (os.environ.get("PORT") or "").strip()
    if raw:
        return host, int(raw)
    if on_railway():
        return host, 8080
    return host, 5173


load_env(os.path.join(ROOT, ".env"))


def ensure_admin_password():
    if (os.environ.get("ADMIN_PASSWORD") or "").strip():
        return
    # Railway / read-only images cannot append .env. Ops stays locked until ADMIN_PASSWORD is set in host env.
    if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_ENVIRONMENT_ID"):
        return
    pw = "clippd-" + secrets.token_urlsafe(10)
    os.environ["ADMIN_PASSWORD"] = pw
    env_path = os.path.join(ROOT, ".env")
    try:
        with open(env_path, "a") as f:
            f.write("\nADMIN_PASSWORD=%s\n" % pw)
    except OSError:
        pass


ensure_admin_password()

DATA_DIR = os.path.join(ROOT, "data")
CAMPAIGNS_PATH = os.path.join(DATA_DIR, "campaigns.json")
USERS_PATH = os.path.join(DATA_DIR, "users.json")
KEYS_PATH = os.path.join(DATA_DIR, "vault-keys.json")
KEYS_TXT = os.path.join(DATA_DIR, "VAULT_KEYS.txt")
os.chdir(ROOT)
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except OSError as e:
    print("data dir not writable: %s" % e, flush=True)

MIN_BUDGET_USD = float(os.environ.get("MIN_BUDGET_USD") or 1)
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
        "ticker": "$CLIPPD",
        "name": "Clippd",
        "demo": True,
        "contract": "",
        "hashtag": "#Clippd",
        "brief": "Clip $CLIPPD. Original edits only — no straight reposts.",
        "budget_usd": 2000,
        "rate_per_1k_usd": 1.5,
        "ugc_rate_per_1k_usd": 3.5,
        "viral_bonus_usd": 500,
        "min_views": 5000,
        "duration_days": 10,
        "platforms": list(PLATFORMS),
        "status": "live",
        "vault_address": None,
        "vault_demo": True,
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
        "image": "/assets/clippdpfp.png",
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
        Pubkey.from_string(str(addr or "").strip())
        return True
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
        "Clippd campaign vault keys",
        "KEEP THIS FILE SECRET.",
        "One campaign_id maps to exactly one Solana vault address.",
        "",
        "INDEX",
        "%-36s  %-14s  %s" % ("campaign_id", "ticker", "vault"),
    ]
    for k in keys:
        c = campaigns_by_id.get(k["campaign_id"], {})
        lines.append(
            "%-36s  %-14s  %s"
            % (k["campaign_id"], c.get("ticker") or k.get("ticker") or "", k["address"])
        )
    lines.append("")
    for k in keys:
        c = campaigns_by_id.get(k["campaign_id"], {})
        lines.extend(
            [
                "=" * 64,
                "%s  /  %s" % (c.get("ticker") or k.get("ticker"), c.get("name") or ""),
                "campaign_id:     %s" % k["campaign_id"],
                "created:         %s" % k.get("created_at", ""),
                "status:          %s" % c.get("status", ""),
                "onchain:         %s" % c.get("vault_onchain", ""),
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
    kp = Keypair()
    secret64 = bytes(kp)
    return {
        "address": str(kp.pubkey()),
        "secret_base58": b58encode(secret64),
        "secret_json": list(secret64),
    }


def operator_keypair():
    raw = (os.environ.get("OPERATOR_SECRET") or "").strip()
    if not raw:
        return None
    try:
        if raw.startswith("["):
            return Keypair.from_bytes(bytes(json.loads(raw)))
        return Keypair.from_base58_string(raw)
    except Exception:
        try:
            return Keypair.from_bytes(b58decode(raw))
        except Exception:
            return None


def account_onchain(address):
    try:
        result = rpc("getAccountInfo", [address, {"encoding": "base64", "commitment": "confirmed"}])
        val = result.get("value") if isinstance(result, dict) else None
        if not val:
            return False, 0
        return True, int(val.get("lamports") or 0)
    except Exception:
        return False, 0


RENT_FALLBACK = 890880


def open_vault_onchain(address):
    exists, lamports = account_onchain(address)
    if exists:
        return {"vault_onchain": True, "seed_lamports": 0, "open_signature": None}
    payer = operator_keypair()
    if not payer:
        return {
            "vault_onchain": False,
            "seed_lamports": 0,
            "open_signature": None,
            "open_error": "OPERATOR_SECRET is not set. Vault key exists; the account appears on Solana when the first SOL arrives.",
        }
    try:
        rent = int(rpc("getMinimumBalanceForRentExemption", [0]) or RENT_FALLBACK)
    except Exception:
        rent = RENT_FALLBACK
    try:
        bh = rpc("getLatestBlockhash", [{"commitment": "confirmed"}])
        blockhash = Hash.from_string(bh["value"]["blockhash"])
        dest = Pubkey.from_string(address)
        ix = transfer(TransferParams(from_pubkey=payer.pubkey(), to_pubkey=dest, lamports=rent))
        tx = Transaction.new_signed_with_payer([ix], payer.pubkey(), [payer], blockhash)
        sig = rpc(
            "sendTransaction",
            [
                base64.b64encode(bytes(tx)).decode("ascii"),
                {"encoding": "base64", "preflightCommitment": "confirmed"},
            ],
        )
        for _ in range(8):
            time.sleep(0.4)
            exists, lamports = account_onchain(address)
            if exists:
                break
        return {
            "vault_onchain": bool(exists),
            "seed_lamports": rent,
            "open_signature": sig,
            "open_error": None if exists else "Rent transfer sent; waiting for confirmation.",
        }
    except Exception as e:
        return {"vault_onchain": False, "seed_lamports": 0, "open_signature": None, "open_error": str(e)}


def http_json(url, payload=None, timeout=12):
    body = None
    headers = {"Accept": "application/json", "User-Agent": "Clippd/1.0"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def sol_usd_price():
    now = time.time()
    if QUOTE_CACHE["price"] and now - QUOTE_CACHE["at"] < 8:
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
    for k in ("secret_base58", "secret_json", "secret", "open_error"):
        out.pop(k, None)
    if not include_submissions:
        out.pop("submissions", None)
    if out.get("demo") or out.get("id") == DEMO_ID:
        out["vault_address"] = None
        out["vault_demo"] = True
    return out


def load_users():
    data = load_json(USERS_PATH, {})
    if isinstance(data, list):
        return {u["address"]: u for u in data if isinstance(u, dict) and u.get("address")}
    return data if isinstance(data, dict) else {}


def upsert_user(address, wallet_name="", handle=""):
    address = str(address or "").strip()
    if not valid_solana_address(address):
        return None
    users = load_users()
    row = users.get(address) or {
        "address": address,
        "handle": "",
        "wallet_name": "",
        "created_at": utcnow(),
    }
    if wallet_name:
        row["wallet_name"] = str(wallet_name).strip()
    cleaned = str(handle or "").strip()
    if cleaned:
        row["handle"] = cleaned
    row["last_seen"] = utcnow()
    users[address] = row
    save_json(USERS_PATH, users)
    return row


def profile_for(address):
    address = str(address or "").strip()
    users = load_users()
    user = dict(users.get(address) or {"address": address, "handle": "", "wallet_name": ""})
    user["address"] = address
    clips = []
    launched = []
    for c in list_campaigns():
        if c.get("creator_wallet") == address:
            launched.append(public_campaign(c, include_submissions=False))
        for clip in c.get("submissions") or []:
            if clip.get("clipper_wallet") != address:
                continue
            clips.append(
                {
                    "id": clip.get("id"),
                    "url": clip.get("url"),
                    "platform": clip.get("platform"),
                    "handle": clip.get("handle"),
                    "created_at": clip.get("created_at"),
                    "status": clip.get("status"),
                    "embed": clip.get("embed"),
                    "campaign_id": c.get("id"),
                    "campaign_ticker": c.get("ticker"),
                    "campaign_name": c.get("name"),
                    "campaign_image": c.get("image"),
                    "campaign_color": c.get("color"),
                }
            )
            if clip.get("handle") and not user.get("handle"):
                user["handle"] = clip.get("handle")
    clips.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {
        "user": user,
        "clips": clips,
        "campaigns": launched,
        "stats": {"clips": len(clips), "campaigns": len(launched)},
    }


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


def refresh_quote(c):
    if c.get("demo") or c.get("status") == "live":
        return c
    try:
        q = quote_payload(float(c.get("budget_usd") or 0))
        c["expected_sol"] = q["sol"]
        c["expected_lamports"] = q["lamports"]
        c["sol_price_usd"] = q["sol_price_usd"]
        c["quoted_at"] = utcnow()
    except Exception:
        pass
    return c


def refresh_deposit(c):
    if c.get("demo"):
        return c
    if not c.get("vault_address"):
        return c
    if c.get("status") != "live":
        refresh_quote(c)
    onchain, lamports = account_onchain(c["vault_address"])
    if not onchain and c.get("status") != "live" and not c.get("open_signature"):
        opened = open_vault_onchain(c["vault_address"])
        if opened.get("open_signature"):
            c["open_signature"] = opened["open_signature"]
        if opened.get("seed_lamports"):
            c["seed_lamports"] = int(opened["seed_lamports"])
        onchain = bool(opened.get("vault_onchain"))
        if onchain:
            onchain, lamports = account_onchain(c["vault_address"])
    if not onchain:
        try:
            lamports = get_balance_lamports(c["vault_address"])
        except Exception:
            lamports = int(c.get("received_lamports") or 0)
        onchain = lamports > 0
    c["vault_onchain"] = bool(onchain)
    seed = int(c.get("seed_lamports") or 0)
    net = max(0, lamports - seed)
    c["received_lamports"] = lamports
    c["received_sol"] = round(lamports / 1e9, 9)
    c["net_received_sol"] = round(net / 1e9, 9)
    c["balance_checked_at"] = utcnow()
    expected = int(c.get("expected_lamports") or 0)
    due = max(0, expected - net)
    c["remaining_lamports"] = due
    c["remaining_sol"] = round(due / 1e9, 9)
    if c.get("status") != "live" and expected and net >= max(0, expected - 5000):
        c["status"] = "live"
        c["funded_at"] = utcnow()
        c["funding_signature"] = latest_sig(c["vault_address"])
    return c


def admin_password():
    return (os.environ.get("ADMIN_PASSWORD") or "").strip()


def ops_cookie_value():
    pw = admin_password()
    if not pw:
        return None
    return hmac.new(pw.encode("utf-8"), b"clippd-ops", hashlib.sha256).hexdigest()


def cookie_map(header):
    out = {}
    for part in (header or "").split(";"):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def ops_authed(handler):
    token = ops_cookie_value()
    if not token:
        return False
    got = cookie_map(handler.headers.get("Cookie")).get("clippd_ops") or ""
    if len(got) != len(token):
        return False
    return hmac.compare_digest(got, token)


def ops_cookie_header(handler, token, clear=False):
    secure = (handler.headers.get("X-Forwarded-Proto") or "").lower() == "https"
    parts = ["clippd_ops=" + ("" if clear else token), "HttpOnly", "SameSite=Strict", "Path=/"]
    if clear:
        parts.append("Max-Age=0")
    else:
        parts.append("Max-Age=2592000")
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


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

    def _json(self, code, obj, extra_headers=None):
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(raw)))
        for key, val in extra_headers or []:
            self.send_header(key, val)
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
            if path == "/api/users":
                return self._update_user()
            if path == "/api/ops/unlock":
                return self._ops_unlock()
            if path == "/api/ops/lock":
                return self._ops_lock()
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

        if path in ("/health", "/healthz", "/health/", "/healthz/"):
            self._json(200, {"ok": True})
            return

        if path == "/api/quote":
            try:
                usd = float((qs.get("usd") or ["10"])[0])
                if usd < MIN_BUDGET_USD:
                    self._json(400, {"error": "Minimum budget is $%s USD" % int(MIN_BUDGET_USD)})
                    return
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
                out = [public_campaign(c) for c in list_campaigns() if c.get("status") == "live" or c.get("demo")]
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

        if path in ("/api/ops/vaults", "/api/ops/vaults/"):
            return self._ops_vaults()

        m = re.match(r"^/api/users/([^/]+)/?$", path)
        if m:
            addr = m.group(1)
            if not valid_solana_address(addr):
                self._json(400, {"error": "Not a Solana address"})
                return
            with LOCK:
                self._json(200, profile_for(addr))
            return

        if path in ("/dashboard", "/dashboard/"):
            self.send_response(302)
            self.send_header("Location", "/launch")
            self.end_headers()
            return

        app_routes = (
            path == "/launch"
            or path.startswith("/launch/")
            or path == "/campaigns"
            or path.startswith("/campaigns/")
            or path.startswith("/u/")
            or path == "/ops"
            or path.startswith("/ops/")
        )
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
        opened = open_vault_onchain(wallet["address"])
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
            "vault_onchain": bool(opened.get("vault_onchain")),
            "seed_lamports": int(opened.get("seed_lamports") or 0),
            "open_signature": opened.get("open_signature"),
            "expected_sol": q["sol"],
            "expected_lamports": q["lamports"],
            "sol_price_usd": q["sol_price_usd"],
            "received_sol": 0,
            "received_lamports": 0,
            "net_received_sol": 0,
            "remaining_sol": q["sol"],
            "remaining_lamports": q["lamports"],
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
            "vault_onchain": campaign.get("vault_onchain"),
            "open_signature": campaign.get("open_signature"),
        }
        with LOCK:
            campaigns = load_json(CAMPAIGNS_PATH, [])
            campaigns.insert(0, campaign)
            save_json(CAMPAIGNS_PATH, campaigns)
            keys = load_json(KEYS_PATH, [])
            keys.insert(0, key_row)
            save_json(KEYS_PATH, keys)
            write_keys_txt(keys, campaigns)
            upsert_user(creator, creator_wallet_name)

        self._json(
            201,
            {
                "campaign": public_campaign(campaign),
                "vault": {"address": wallet["address"]},
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
            upsert_user(clipper, clipper_wallet_name, clip.get("handle"))
        self._json(201, {"clip": clip, "campaign": public_campaign(c)})

    def _ops_unlock(self):
        pw = admin_password()
        if not pw:
            return self._json(503, {"error": "ADMIN_PASSWORD is not set on the server."})
        body = self._read_json()
        given = str(body.get("password") or "")
        if len(given) != len(pw) or not hmac.compare_digest(given, pw):
            return self._json(401, {"error": "Wrong password."})
        token = ops_cookie_value()
        return self._json(200, {"ok": True}, extra_headers=[("Set-Cookie", ops_cookie_header(self, token))])

    def _ops_lock(self):
        return self._json(200, {"ok": True}, extra_headers=[("Set-Cookie", ops_cookie_header(self, "", clear=True))])

    def _ops_vaults(self):
        if not admin_password():
            return self._json(503, {"error": "ADMIN_PASSWORD is not set on the server."})
        if not ops_authed(self):
            return self._json(401, {"error": "Unlock required"})
        with LOCK:
            campaigns = stored_campaigns()
            campaigns_by_id = {c.get("id"): c for c in campaigns}
            keys = load_json(KEYS_PATH, [])
            keys_by_id = {k.get("campaign_id"): k for k in keys if k.get("campaign_id")}
            vaults = []
            seen = set()

            def row_for(cid, c, k):
                return {
                    "campaign_id": cid,
                    "ticker": (c or {}).get("ticker") or (k or {}).get("ticker"),
                    "name": (c or {}).get("name") or (k or {}).get("name"),
                    "status": (c or {}).get("status") or "",
                    "address": (k or {}).get("address") or (c or {}).get("vault_address"),
                    "secret_base58": (k or {}).get("secret_base58"),
                    "created_at": (k or {}).get("created_at") or (c or {}).get("created_at"),
                    "budget_usd": (c or {}).get("budget_usd") or (k or {}).get("budget_usd"),
                    "vault_onchain": (c or {}).get("vault_onchain"),
                }

            for c in campaigns:
                cid = c.get("id")
                if not cid or c.get("demo") or cid == DEMO_ID:
                    continue
                k = keys_by_id.get(cid)
                if not k and not c.get("vault_address"):
                    continue
                seen.add(cid)
                vaults.append(row_for(cid, c, k))
            for k in keys:
                cid = k.get("campaign_id")
                if not cid or cid in seen or cid == DEMO_ID:
                    continue
                vaults.append(row_for(cid, campaigns_by_id.get(cid) or {}, k))
            vaults.sort(key=lambda v: (0 if v.get("status") == "live" else 1, v.get("created_at") or ""), reverse=False)
        return self._json(200, {"host": self.headers.get("Host") or "", "site": os.environ.get("SITE_URL") or "", "vaults": vaults})

    def _update_user(self):
        body = self._read_json()
        address = str(body.get("address") or body.get("wallet") or "").strip()
        if not valid_solana_address(address):
            return self._json(400, {"error": "Connect a Solana wallet first."})
        with LOCK:
            user = upsert_user(address, body.get("wallet_name") or "", body.get("handle") or "")
            self._json(200, profile_for(address) if user else {"error": "Could not save profile"})


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
    host, port = listen_bind()
    site = (os.environ.get("SITE_URL") or "https://getclippd.fun").rstrip("/")
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((host, port), Handler)
    print("Clippd marketplace   http://%s:%s" % (host, port), flush=True)
    print("public site         %s" % site, flush=True)
    print("env PORT            %s" % (os.environ.get("PORT") or "(not set)"), flush=True)
    print("vault keys          %s" % KEYS_TXT, flush=True)
    print("ops vaults          %s/ops" % site, flush=True)
    if not operator_keypair():
        print("OPERATOR_SECRET     not set — vaults stay off Solscan until the first SOL lands", flush=True)
    if not admin_password():
        print("ADMIN_PASSWORD      not set — /ops stays locked", flush=True)
    server.serve_forever()
