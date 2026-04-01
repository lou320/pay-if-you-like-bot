"""
Pay If You Like — Admin Dashboard
Run:  python app.py
      DASH_USER=admin DASH_PASS=yourpassword DASH_PORT=5050 python app.py
"""

import os
import json
import time
import requests
import urllib3
from flask import Flask, render_template, jsonify, Response, request
from functools import wraps
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH    = os.path.join(BASE_DIR, '..', 'config.json')
TRACKING_PATH  = os.path.join(BASE_DIR, '..', 'vpn_bot', 'claimed_users.json')
ROTATION_PATH  = os.path.join(BASE_DIR, '..', 'vpn_bot', 'server_rotation_state.json')

DASHBOARD_USER = os.environ.get('DASH_USER', 'admin')
DASHBOARD_PASS = os.environ.get('DASH_PASS', 'changeme')

# Simple in-memory cache — avoids hammering X-UI on every page load
_server_cache      = None
_server_cache_time = 0
CACHE_TTL          = 30  # seconds


# ── Auth ──────────────────────────────────────────────────────────────────────

def check_auth(username: str, password: str) -> bool:
    return username == DASHBOARD_USER and password == DASHBOARD_PASS


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                'Login required.',
                401,
                {'WWW-Authenticate': 'Basic realm="Dashboard"'},
            )
        return f(*args, **kwargs)
    return decorated


# ── Data helpers ──────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_tracking() -> dict:
    try:
        with open(TRACKING_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def load_rotation() -> dict:
    try:
        with open(ROTATION_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"next_index": 0}


def fmt_bytes(b: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


# ── X-UI thin client ──────────────────────────────────────────────────────────

class XUIClient:
    def __init__(self, server: dict):
        self.base_url   = server['panel_url'].rstrip('/')
        self.username   = server['username']
        self.password   = server['password']
        self.inbound_id = server['inbound_id']
        self.session    = requests.Session()

    def login(self) -> bool:
        try:
            r = self.session.post(
                f"{self.base_url}/login",
                data={'username': self.username, 'password': self.password},
                verify=False, timeout=8,
            )
            return r.json().get('success', False)
        except Exception:
            return False

    def get_inbound(self) -> dict | None:
        if not self.login():
            return None
        try:
            r  = self.session.get(
                f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}",
                verify=False, timeout=8,
            )
            rj = r.json()
            if not rj.get('success'):
                return None
            obj      = rj['obj']
            settings = json.loads(obj.get('settings', '{}'))
            clients  = settings.get('clients', [])
            up = down = 0
            for stat in (obj.get('clientStats') or []):
                up   += stat.get('up', 0)
                down += stat.get('down', 0)
            return {'clients': clients, 'total_up': up, 'total_down': down}
        except Exception:
            return None


def _check_one(args) -> dict:
    idx, server, default_idx = args
    data   = XUIClient(server).get_inbound()
    online = data is not None
    return {
        'name':         server.get('name', f'Server {idx + 1}'),
        'online':       online,
        'enabled':      server.get('enabled', True),
        'is_default':   idx == default_idx,
        'client_count': len(data['clients']) if online else 0,
        'upload':       fmt_bytes(data['total_up'])   if online else '—',
        'download':     fmt_bytes(data['total_down']) if online else '—',
    }


def get_server_status() -> list:
    global _server_cache, _server_cache_time
    if _server_cache and (time.time() - _server_cache_time) < CACHE_TTL:
        return _server_cache

    config      = load_config()
    servers     = config.get('servers', [])
    default_idx = config.get('default_server_id', 0)

    results = [None] * len(servers)
    with ThreadPoolExecutor(max_workers=min(len(servers), 10)) as pool:
        futures = {
            pool.submit(_check_one, (i, s, default_idx)): i
            for i, s in enumerate(servers)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception:
                s = servers[idx]
                results[idx] = {
                    'name': s.get('name', f'Server {idx + 1}'),
                    'online': False, 'enabled': s.get('enabled', True),
                    'is_default': idx == default_idx,
                    'client_count': 0, 'upload': '—', 'download': '—',
                }

    _server_cache      = results
    _server_cache_time = time.time()
    return results


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
@require_auth
def index():
    return render_template('index.html')


@app.route('/api/servers')
@require_auth
def api_servers():
    return jsonify(get_server_status())


@app.route('/api/stats')
@require_auth
def api_stats():
    tracking    = load_tracking()
    now         = int(time.time())
    three_days  = 3 * 24 * 3600
    rotation    = load_rotation()

    free_active = free_expired = premium = 0
    for info in tracking.values():
        if not isinstance(info, dict):
            continue
        t   = info.get('trial_type', 'free')
        age = now - info.get('timestamp', 0)
        if t == 'free':
            if age < three_days:
                free_active += 1
            else:
                free_expired += 1
        else:
            premium += 1

    return jsonify({
        'total_users':     len(tracking),
        'free_active':     free_active,
        'free_expired':    free_expired,
        'premium':         premium,
        'est_revenue_ks':  premium * 5000,
        'next_rr_index':   rotation.get('next_index', 0),
    })


@app.route('/api/timeline')
@require_auth
def api_timeline():
    tracking       = load_tracking()
    now            = int(time.time())
    days           = 30
    free_buckets    = defaultdict(int)
    premium_buckets = defaultdict(int)

    for info in tracking.values():
        if not isinstance(info, dict):
            continue
        ts = info.get('timestamp', 0)
        if (now - ts) > days * 86400:
            continue
        label = datetime.fromtimestamp(ts).strftime('%b %d')
        if info.get('trial_type', 'free') == 'free':
            free_buckets[label] += 1
        else:
            premium_buckets[label] += 1

    labels, free_vals, premium_vals = [], [], []
    for i in range(days - 1, -1, -1):
        label = (datetime.now() - timedelta(days=i)).strftime('%b %d')
        labels.append(label)
        free_vals.append(free_buckets.get(label, 0))
        premium_vals.append(premium_buckets.get(label, 0))

    return jsonify({'labels': labels, 'free': free_vals, 'premium': premium_vals})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('DASH_PORT', 5050))
    if DASHBOARD_PASS == 'changeme':
        print("\n  ⚠️  WARNING: Using default password. Set DASH_PASS env var before exposing to internet.\n")
    print(f"  Dashboard:   http://0.0.0.0:{port}")
    print(f"  Credentials: {DASHBOARD_USER} / {DASHBOARD_PASS}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
