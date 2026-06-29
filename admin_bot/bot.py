import logging
import json
import copy
import uuid
import secrets
import string
import requests
import asyncio
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
import telegram
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# --- CONFIGURATION ---
def load_config():
    with open('../config.json', 'r') as f:
        return json.load(f)

CONFIG = load_config()
# The admin bot uses its own token stored under `admin_bot_token` in the
# parent config file.  Previously we were overwriting `CONFIG['bot_token']`
# with this value on startup, which meant that any time the admin endpoint
# wrote the JSON back (add server, toggle, etc.) the customer bot token
# would be replaced by the admin token.  When both processes then polled
# Telegram with the same token we got a 409 Conflict error.  Keep the
# customer token untouched and keep the admin token in a separate variable.
ADMIN_TOKEN = CONFIG.get('admin_bot_token', '8408777363:AAGgMfiFZidu55AmeQTMtLLHU6xAuE7EY4g')

SERVERS = CONFIG['servers']
ADMIN_IDS = CONFIG['admin_ids']

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

INACTIVE_DAYS_THRESHOLD = 7
INACTIVE_CACHE_TTL_SECONDS = 30 * 60
INACTIVE_CARD_LIMIT = 40

AUTO_INBOUND_TEMPLATE = {
    "listen": "",
    "port": 443,
    "protocol": "vless",
    "tag": "in-443-tcp",
    "settings": {
        "clients": [],
        "decryption": "none",
        "encryption": "none",
        "testseed": [900, 500, 900, 256]
    },
    "sniffing": {
        "enabled": False
    },
    "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "tcpSettings": {
            "acceptProxyProtocol": False,
            "header": {
                "type": "none"
            }
        },
        "realitySettings": {
            "show": False,
            "xver": 0,
            "target": "www.intel.com:443",
            "serverNames": ["www.intel.com"],
            "privateKey": "KNI8EUr5yAB1Y6k_5TXYMFtT_gm0WIoW_OE7ha3ABW4",
            "minClientVer": "",
            "maxClientVer": "",
            "maxTimediff": 0,
            "shortIds": [
                "20ceb823",
                "c0ffa938065bb4",
                "b4ff353fa8",
                "770a83",
                "215485f50876d389",
                "45",
                "1de7a68a30e0",
                "0e11"
            ],
            "mldsa65Seed": "",
            "settings": {
                "publicKey": "5SOnt8lwpb7hd8y8Ei8qMGmDZYajkpCivhtPBWSS20k",
                "fingerprint": "chrome",
                "serverName": "",
                "spiderX": "/",
                "mldsa65Verify": ""
            }
        }
    }
}


def get_active_servers():
    enabled = [s for s in SERVERS if s.get('enabled', True)]
    return enabled if enabled else SERVERS


def format_expiry(expiry_ms):
    if int(expiry_ms or 0) <= 0:
        return "Never"
    try:
        return datetime.fromtimestamp(int(expiry_ms) / 1000).strftime('%Y-%m-%d')
    except Exception:
        return "Unknown"


def format_last_online(last_online_ms):
    if not last_online_ms:
        return "Unknown"
    try:
        return datetime.fromtimestamp(int(last_online_ms) / 1000).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return "Unknown"


def normalize_last_online_ms(raw_value):
    """Normalize last-online timestamp to milliseconds if present."""
    try:
        value = int(raw_value or 0)
    except Exception:
        return 0
    if value <= 0:
        return 0
    # Heuristic: values smaller than 10^12 are very likely seconds.
    if value < 10**12:
        return value * 1000
    return value


def collect_inactive_users():
    """Return users that are expired, disabled, unused, or inactive for 7+ days."""
    gb = 1024 * 1024 * 1024
    now_ms = int(time.time() * 1000)
    week_ms = INACTIVE_DAYS_THRESHOLD * 24 * 60 * 60 * 1000
    inactive = []

    for server in get_active_servers():
        try:
            client = XUIClient(server)
            inbound_url = f"{client.base_url}/panel/api/inbounds/get/{client.inbound_id}"
            r = client.session.get(inbound_url, verify=False, timeout=15)
            rj = r.json()

            if not rj.get('success'):
                client.login()
                r = client.session.get(inbound_url, verify=False, timeout=15)
                rj = r.json()

            if not rj.get('success'):
                logging.warning(f"Inactive scan failed on {server.get('name')}: {rj}")
                continue

            inbound = rj.get('obj', {})
            settings = json.loads(inbound.get('settings', '{}'))
            stats_by_email = {}
            for stat in inbound.get('clientStats') or []:
                email = stat.get('email')
                if email:
                    stats_by_email[email] = stat

            for c in settings.get('clients', []):
                email = c.get('email', 'N/A')
                expiry_ms = int(c.get('expiryTime', 0) or 0)
                enabled = bool(c.get('enable', True))
                total = int(c.get('totalGB', 0) or 0)

                stat = stats_by_email.get(email, {})
                up = int(stat.get('up', c.get('up', 0)) or 0)
                down = int(stat.get('down', c.get('down', 0)) or 0)
                used = up + down
                remaining = max(0, total - used)
                last_online_ms = normalize_last_online_ms(stat.get('lastOnline') or c.get('lastOnline'))

                is_expired = expiry_ms > 0 and expiry_ms <= now_ms
                is_disabled = not enabled
                is_unused = used == 0
                expired_over_week = expiry_ms > 0 and (now_ms - expiry_ms) >= week_ms
                inactive_over_week = last_online_ms > 0 and (now_ms - last_online_ms) >= week_ms

                reasons = []
                if is_expired:
                    reasons.append('expired')
                if is_disabled:
                    reasons.append('disabled')
                if is_unused:
                    reasons.append('unused')
                if expired_over_week or inactive_over_week:
                    reasons.append('inactive_7d')

                if reasons:
                    inactive.append({
                        'email': email,
                        'server': server.get('name', 'Unknown'),
                        'panel_url': server.get('panel_url', ''),
                        'inbound_id': int(server.get('inbound_id', 0) or 0),
                        'reasons': reasons,
                        'used_gb': round(used / gb, 2),
                        'total_gb': round(total / gb, 2),
                        'remaining_gb': round(remaining / gb, 2),
                        'status': 'Inactive',
                        'last_online_ms': last_online_ms,
                        'last_online': format_last_online(last_online_ms),
                        'expiry': format_expiry(expiry_ms),
                    })
        except Exception as e:
            logging.warning(f"Inactive scan exception on {server.get('name')}: {e}")

    inactive.sort(key=lambda x: (x['server'], x['email']))
    return inactive


def build_inactive_report(rows, max_rows=60):
    if not rows:
        return "✅ <b>No inactive users found.</b>"

    lines = [
        f"🧊 <b>Inactive Users</b>\nTotal: <b>{len(rows)}</b>\n",
        "Format: <code>email | server | reasons | usedGB | expiry</code>\n"
    ]

    for idx, row in enumerate(rows[:max_rows], start=1):
        reasons = ','.join(row['reasons'])
        lines.append(
            f"{idx}. <code>{row['email']} | {row['server']} | {reasons} | {row['used_gb']} | {row['expiry']}</code>"
        )

    if len(rows) > max_rows:
        lines.append(f"\n... showing first {max_rows} of {len(rows)} users")

    return "\n".join(lines)


def build_inactive_card(row):
    reasons_text = ', '.join(row.get('reasons', []))
    return (
        "📊 <b>Inactive User Status</b>\n\n"
        f"👤 <b>Name:</b> {row.get('email', 'N/A')}\n"
        f"🖥 <b>Server:</b> {row.get('server', 'Unknown')}\n"
        f"🔋 <b>Status:</b> ❌ {row.get('status', 'Inactive')}\n\n"
        f"📦 <b>Total:</b> {row.get('total_gb', 0)} GiB\n"
        f"📉 <b>Used:</b> {row.get('used_gb', 0)} GiB\n"
        f"📈 <b>Remaining:</b> {row.get('remaining_gb', 0)} GiB\n\n"
        f"⏳ <b>Expires:</b> {row.get('expiry', 'Unknown')}\n"
        f"🕒 <b>Last Active:</b> {row.get('last_online', 'Unknown')}\n"
        f"⚠️ <b>Reason:</b> {reasons_text}"
    )


def cache_inactive_rows(context: ContextTypes.DEFAULT_TYPE, rows):
    now = int(time.time())
    cache = context.bot_data.setdefault('inactive_cache', {})

    # Evict stale cache items first.
    stale_keys = [k for k, v in cache.items() if (now - int(v.get('ts', 0))) > INACTIVE_CACHE_TTL_SECONDS]
    for key in stale_keys:
        cache.pop(key, None)

    tokens = []
    for row in rows:
        token = secrets.token_hex(4)
        while token in cache:
            token = secrets.token_hex(4)
        cache[token] = {'row': row, 'ts': now}
        tokens.append((token, row))
    return tokens


async def send_inactive_cards(chat_id: int, context: ContextTypes.DEFAULT_TYPE, rows):
    if not rows:
        await context.bot.send_message(chat_id=chat_id, text="✅ <b>No inactive users found.</b>", parse_mode='HTML')
        return

    limited_rows = rows[:INACTIVE_CARD_LIMIT]
    tokens = cache_inactive_rows(context, limited_rows)

    summary = (
        f"🧊 <b>Inactive Users: {len(rows)}</b>\n"
        f"Showing: <b>{len(limited_rows)}</b>\n"
        "Tap <b>Delete</b> under a user card to remove that account."
    )
    if len(rows) > INACTIVE_CARD_LIMIT:
        summary += f"\n\n(Showing first {INACTIVE_CARD_LIMIT} users)"

    await context.bot.send_message(chat_id=chat_id, text=summary, parse_mode='HTML')

    for token, row in tokens:
        keyboard = [[InlineKeyboardButton("🗑 Delete", callback_data=f"inactdel_{token}")]]
        await context.bot.send_message(
            chat_id=chat_id,
            text=build_inactive_card(row),
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def send_inactive_report(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    rows = collect_inactive_users()
    report = build_inactive_report(rows)
    await context.bot.send_message(chat_id=chat_id, text=report, parse_mode='HTML')

# --- X-UI API CLIENT ---
class XUIClient:
    def __init__(self, server_config):
        self.base_url = server_config['panel_url'].rstrip('/')
        self.username = server_config['username']
        self.password = server_config['password']
        self.inbound_id = server_config['inbound_id']
        self.session = requests.Session()
        self.last_error = ""
        self.login()

    def login(self):
        login_url = f"{self.base_url}/login"
        payload = {'username': self.username, 'password': self.password}
        try:
            r = self.session.post(login_url, data=payload, verify=False, timeout=10)
            if r.json().get('success'):
                logging.info(f"Logged in to {self.base_url}")
                return True
            self.last_error = f"Login failed: {r.text[:200]}"
        except Exception as e:
            logging.error(f"Login failed: {e}")
            self.last_error = f"Login failed: {e}"
        return False

    def _try_get_json(self, url):
        try:
            r = self.session.get(url, verify=False, timeout=15)
            return r.json()
        except Exception:
            return None

    def _try_post_json(self, url, payload):
        try:
            r = self.session.post(url, json=payload, verify=False, timeout=15)
            try:
                body = r.json()
                if isinstance(body, dict) and not body.get('success') and body.get('msg'):
                    self.last_error = str(body.get('msg'))
                return body
            except Exception:
                self.last_error = f"HTTP {r.status_code}: {r.text[:200]}"
                return None
        except Exception as e:
            self.last_error = f"POST error: {e}"
            return None

    def _try_post_form(self, url, payload):
        try:
            r = self.session.post(url, data=payload, verify=False, timeout=15)
            try:
                body = r.json()
                if isinstance(body, dict) and not body.get('success') and body.get('msg'):
                    self.last_error = str(body.get('msg'))
                return body
            except Exception:
                self.last_error = f"HTTP {r.status_code}: {r.text[:200]}"
                return None
        except Exception as e:
            self.last_error = f"POST(form) error: {e}"
            return None

    def _inbound_get_urls(self, inbound_id):
        return [
            f"{self.base_url}/panel/api/inbounds/get/{inbound_id}",
            f"{self.base_url}/xui/API/inbounds/get/{inbound_id}",
            f"{self.base_url}/xui/api/inbounds/get/{inbound_id}",
            f"{self.base_url}/api/inbounds/get/{inbound_id}",
        ]

    def _inbound_list_urls(self):
        return [
            f"{self.base_url}/panel/api/inbounds/list",
            f"{self.base_url}/xui/API/inbounds/list",
            f"{self.base_url}/xui/api/inbounds/list",
            f"{self.base_url}/api/inbounds/list",
        ]

    def _inbound_add_urls(self):
        return [
            f"{self.base_url}/panel/api/inbounds/addClient",
            f"{self.base_url}/xui/API/inbounds/addClient",
            f"{self.base_url}/xui/api/inbounds/addClient",
            f"{self.base_url}/api/inbounds/addClient",
        ]

    def _inbound_create_urls(self):
        return [
            f"{self.base_url}/panel/api/inbounds/add",
            f"{self.base_url}/xui/API/inbounds/add",
            f"{self.base_url}/xui/api/inbounds/add",
            f"{self.base_url}/api/inbounds/add",
            f"{self.base_url}/panel/inbound/add",
            f"{self.base_url}/inbound/add",
        ]

    def _fetch_inbound(self, inbound_id):
        for url in self._inbound_get_urls(inbound_id):
            data = self._try_get_json(url)
            if isinstance(data, dict) and data.get('success') and data.get('obj'):
                return data.get('obj')
        return None

    def discover_preferred_inbound_id(self):
        for url in self._inbound_list_urls():
            data = self._try_get_json(url)
            if not isinstance(data, dict) or not data.get('success'):
                continue
            inbounds = data.get('obj') or []
            if not isinstance(inbounds, list) or not inbounds:
                continue

            vless_reality = []
            vless_any = []
            enabled_any = []

            for ib in inbounds:
                if not isinstance(ib, dict):
                    continue
                ib_id = ib.get('id')
                if ib_id is None:
                    continue
                protocol = str(ib.get('protocol', '')).lower()
                enabled = bool(ib.get('enable', True))
                if enabled:
                    enabled_any.append(ib)
                if protocol == 'vless':
                    vless_any.append(ib)
                    try:
                        ss = json.loads(ib.get('streamSettings', '{}'))
                    except Exception:
                        ss = {}
                    if isinstance(ss, dict) and ss.get('realitySettings'):
                        vless_reality.append(ib)

            chosen = None
            if vless_reality:
                chosen = vless_reality[0]
            elif vless_any:
                chosen = vless_any[0]
            elif enabled_any:
                chosen = enabled_any[0]
            else:
                chosen = inbounds[0]

            try:
                return int(chosen.get('id'))
            except Exception:
                return self.inbound_id

        return self.inbound_id

    def create_auto_inbound(self, remark: str = "Auto-Inbound", port: int = 443):
        base = copy.deepcopy(AUTO_INBOUND_TEMPLATE)
        base["remark"] = remark
        base["port"] = int(port)
        base["tag"] = f"in-{int(port)}-tcp"

        # x-ui variants accept different shapes:
        # 1) nested object fields (newer)
        # 2) settings/streamSettings/sniffing as JSON strings + extra top-level fields (legacy)
        payload_object = copy.deepcopy(base)
        payload_legacy = {
            "up": 0,
            "down": 0,
            "total": 0,
            "remark": base.get("remark"),
            "enable": True,
            "expiryTime": 0,
            "listen": base.get("listen", ""),
            "port": base.get("port"),
            "protocol": base.get("protocol"),
            "settings": json.dumps(base.get("settings", {})),
            "streamSettings": json.dumps(base.get("streamSettings", {})),
            "sniffing": json.dumps(base.get("sniffing", {})),
            "allocate": json.dumps({"strategy": "always", "refresh": 5, "concurrency": 3}),
            "tag": base.get("tag"),
        }

        responses = []
        tried = []
        for payload in (payload_legacy, payload_object):
            for url in self._inbound_create_urls():
                resp = self._try_post_json(url, payload)
                tried.append(url + " [json]")
                if resp:
                    responses.append(resp)
                if isinstance(resp, dict) and resp.get("success"):
                    detected_id = self.discover_preferred_inbound_id()
                    self.inbound_id = int(detected_id)
                    return True, int(detected_id), "Inbound created"

                # Some 3x-ui routes accept form-encoded body instead of JSON.
                resp = self._try_post_form(url, payload)
                tried.append(url + " [form]")
                if resp:
                    responses.append(resp)
                if isinstance(resp, dict) and resp.get("success"):
                    detected_id = self.discover_preferred_inbound_id()
                    self.inbound_id = int(detected_id)
                    return True, int(detected_id), "Inbound created"

        err_msg = ""
        for resp in responses:
            if isinstance(resp, dict) and resp.get("msg"):
                err_msg = str(resp.get("msg"))
                break
        if not err_msg and self.last_error:
            err_msg = self.last_error
        if not err_msg:
            err_msg = "Failed to create inbound (API rejected request)."

        # Keep it short enough for Telegram while still showing endpoint coverage.
        tried_preview = "; ".join(tried[:4])
        if tried_preview:
            err_msg = f"{err_msg} Tried: {tried_preview}"

        self.last_error = err_msg
        return False, None, self.last_error

    def add_client(self, email, limit_gb=0, expire_days=0):
        try:
            inbound = self._fetch_inbound(self.inbound_id)
            if not inbound:
                self.login()
                inbound = self._fetch_inbound(self.inbound_id)

            # Auto-detect inbound for newer/changed 3x-ui setups.
            if not inbound:
                detected_id = self.discover_preferred_inbound_id()
                if detected_id != self.inbound_id:
                    logging.info(f"Auto-switched inbound id from {self.inbound_id} to {detected_id} on {self.base_url}")
                    self.inbound_id = detected_id
                inbound = self._fetch_inbound(self.inbound_id)

            if not inbound:
                self.last_error = "Failed to load inbound (check inbound ID or API path compatibility)."
                return None

            try:
                stream_settings = json.loads(inbound.get('streamSettings', '{}'))
            except Exception:
                stream_settings = {}
            
            new_uuid = str(uuid.uuid4())
            sub_id = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(16))
            
            expiry_time = 0
            if expire_days > 0:
                import time
                expiry_time = int((time.time() * 1000) + (expire_days * 86400 * 1000))

            def build_payload(include_flow=True):
                client_obj = {
                    "id": new_uuid,
                    "email": email,
                    "totalGB": limit_gb * 1024 * 1024 * 1024,
                    "expiryTime": expiry_time,
                    "enable": True,
                    "tgId": "",
                    "subId": sub_id,
                    "limitIp": 1
                }
                if include_flow:
                    client_obj["flow"] = "xtls-rprx-vision"
                return {
                    "id": self.inbound_id,
                    "settings": json.dumps({"clients": [client_obj]})
                }

            # Try with flow first, then retry without flow for newer variants.
            responses = []
            add_success = False
            for include_flow in (True, False):
                payload = build_payload(include_flow=include_flow)
                for add_url in self._inbound_add_urls():
                    resp = self._try_post_json(add_url, payload)
                    if resp:
                        responses.append(resp)
                    if isinstance(resp, dict) and resp.get('success'):
                        add_success = True
                        break
                if add_success:
                    break

            if not add_success:
                msg = ""
                for resp in responses:
                    if isinstance(resp, dict) and resp.get('msg'):
                        msg = str(resp.get('msg'))
                        break
                self.last_error = msg or "Add client API rejected request."
                return None

            remark = email
            ip = self.base_url.split('://')[1].split(':')[0]
            port = inbound.get('port')

            reality = stream_settings.get('realitySettings') if isinstance(stream_settings, dict) else None
            pbk = sni = sid = None
            if isinstance(reality, dict):
                settings_obj = reality.get('settings')
                if isinstance(settings_obj, str):
                    try:
                        settings_obj = json.loads(settings_obj)
                    except Exception:
                        settings_obj = None
                if isinstance(settings_obj, dict):
                    pbk = settings_obj.get('publicKey')
                names = reality.get('serverNames') or []
                shorts = reality.get('shortIds') or []
                sni = names[0] if names else None
                sid = shorts[0] if shorts else None

            if pbk and sni and sid:
                link = (f"vless://{new_uuid}@{ip}:{port}"
                        f"?type=tcp&security=reality&pbk={pbk}&fp=chrome"
                        f"&sni={sni}&sid={sid}&spx=%2F&flow=xtls-rprx-vision#{remark}")
            else:
                link = f"vless://{new_uuid}@{ip}:{port}?type=tcp&security=none#{remark}"
            return link
        except Exception as e:
            logging.error(f"XUI Client Error: {e}")
            self.last_error = str(e)
            return None

    def delete_client_by_email(self, email):
        """Delete one client from this inbound by email."""
        try:
            list_url = f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}"
            r = self.session.get(list_url, verify=False, timeout=15)
            rj = r.json()

            if not rj.get('success'):
                self.login()
                r = self.session.get(list_url, verify=False, timeout=15)
                rj = r.json()

            if not rj.get('success'):
                logging.error(f"Delete failed to fetch inbound: {rj}")
                return False

            inbound = rj.get('obj', {})
            settings = json.loads(inbound.get('settings', '{}'))
            clients = settings.get('clients', [])

            original_count = len(clients)
            settings['clients'] = [c for c in clients if c.get('email') != email]
            if len(settings['clients']) == original_count:
                logging.warning(f"Client not found for delete: {email}")
                return False

            payload = {
                "id": self.inbound_id,
                "settings": json.dumps(settings)
            }
            candidate_urls = [
                f"{self.base_url}/panel/api/inbounds/update/{self.inbound_id}",
                f"{self.base_url}/panel/api/inbounds/{self.inbound_id}",
            ]

            for update_url in candidate_urls:
                try:
                    r = self.session.post(update_url, json=payload, verify=False, timeout=15)
                    resp = r.json()
                except Exception:
                    continue

                if resp.get('success'):
                    logging.info(f"Deleted client {email} from {self.base_url}")
                    return True

            logging.error(f"Delete update failed for {email} on all endpoints")
            return False
        except Exception as e:
            logging.error(f"delete_client_by_email exception: {e}")
            return False

# --- TELEGRAM BOT LOGIC ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔️ This bot is for Admins only.")
        return

    keyboard = [
        [InlineKeyboardButton("➕ Generate 1 Month Key", callback_data='admin_gen_1m')],
        [InlineKeyboardButton("⚡️ Generate Trial Key", callback_data='admin_gen_trial')],
        [InlineKeyboardButton("📦 Bulk Generate Users", callback_data='admin_bulk_gen')],
        [InlineKeyboardButton("🧊 Inactive Users", callback_data='admin_inactive_users')],
        [InlineKeyboardButton("⚙️ Manage Servers", callback_data='admin_manage_menu')],
        [InlineKeyboardButton("🔌 Add New Server", callback_data='admin_add_server')]
    ]
    await update.message.reply_text("👑 <b>Admin Control Panel</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def inactive_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔️ This bot is for Admins only.")
        return

    wait_msg = await update.message.reply_text("🔍 Scanning inactive users across servers...")
    rows = collect_inactive_users()
    await wait_msg.edit_text(f"✅ Found {len(rows)} inactive users. Sending cards...")
    await send_inactive_cards(update.effective_chat.id, context, rows)

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ensure we modify the module-level config and servers
    global CONFIG, SERVERS

    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("⛔️ This bot is for Admins only.")
        return
    
    # Cancel button handler
    if query.data == 'admin_cancel':
        context.user_data.clear()
        await query.edit_message_text("❌ Cancelled.", parse_mode='HTML')
        return

    if query.data == 'admin_manage_menu':
        # List all servers for management
        default_idx = CONFIG.get('default_server_id', 0)
        keyboard = []
        for i, s in enumerate(SERVERS):
            # Extract IP from URL for label
            try:
                ip_label = s.get('panel_url').split('://')[1].split(':')[0]
            except:
                ip_label = s.get('name', f"Server {i+1}")

            is_enabled = s.get('enabled', True)
            
            # Status Icons
            status_icon = "🟢" if is_enabled else "🔴"
            star_icon = "⭐️" if i == default_idx else ""
            
            btn_text = f"{status_icon} {ip_label} {star_icon}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f'manage_srv_{i}')])
            
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='admin_back')])
        await query.edit_message_text("⚙️ <b>Server Management</b>\n\nSelect a server to configure:", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif query.data.startswith('manage_srv_'):
        idx = int(query.data.split('_')[-1])
        if idx >= len(SERVERS):
            await query.edit_message_text("❌ Server not found.")
            return
            
        s = SERVERS[idx]
        default_idx = CONFIG.get('default_server_id', 0)
        is_default = (idx == default_idx)
        is_enabled = s.get('enabled', True)
        vpn_status_scope = s.get('vpn_status_scope', False)
        vpn_block_new_profiles = s.get('vpn_block_new_profiles', False)
        vpn_block_renewals = s.get('vpn_block_renewals', False)
        
        # Details
        msg = (
            f"🖥 <b>{s.get('name')}</b>\n\n"
            f"🔗 <b>URL:</b> <code>{s.get('panel_url')}</code>\n"
            f"🔌 <b>Status:</b> {'✅ Enabled' if is_enabled else '❌ Disabled'}\n"
            f"⭐️ <b>Priority:</b> {'High (Default)' if is_default else 'Normal'}\n"
            f"📊 <b>VPN Status Scope:</b> {'✅ Included' if vpn_status_scope else '➖ Not Included'}\n"
            f"🆕 <b>VPN New Profiles:</b> {'⛔ Blocked' if vpn_block_new_profiles else '✅ Allowed'}\n"
            f"🔄 <b>VPN Renewals:</b> {'⛔ Blocked' if vpn_block_renewals else '✅ Allowed'}\n"
        )
        
        # Actions
        keyboard = []
        
        # Toggle Enable/Disable
        toggle_txt = "🔴 Disable" if is_enabled else "🟢 Enable"
        keyboard.append([InlineKeyboardButton(toggle_txt, callback_data=f'toggle_srv_{idx}')])
        
        # Set Default
        if not is_default:
            keyboard.append([InlineKeyboardButton("⭐️ Set as Default", callback_data=f'set_def_{idx}')])

        scope_txt = "📊 Remove from VPN Status" if vpn_status_scope else "📊 Include in VPN Status"
        keyboard.append([InlineKeyboardButton(scope_txt, callback_data=f'toggle_scope_{idx}')])

        block_new_txt = "🆕 Allow VPN New Profiles" if vpn_block_new_profiles else "🆕 Block VPN New Profiles"
        keyboard.append([InlineKeyboardButton(block_new_txt, callback_data=f'toggle_vpn_new_{idx}')])

        block_renew_txt = "🔄 Allow VPN Renewals" if vpn_block_renewals else "🔄 Block VPN Renewals"
        keyboard.append([InlineKeyboardButton(block_renew_txt, callback_data=f'toggle_vpn_renew_{idx}')])

        keyboard.append([InlineKeyboardButton("🧩 Create Inbound Auto", callback_data=f'create_inb_{idx}')])
            
        # Delete
        keyboard.append([InlineKeyboardButton("🗑 Delete Server", callback_data=f'del_srv_{idx}')])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='admin_manage_menu')])
        
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif query.data.startswith('toggle_srv_'):
        idx = int(query.data.split('_')[-1])
        # Reload latest config before modify
        CONFIG = load_config()
        SERVERS = CONFIG['servers']
        
        s = SERVERS[idx]
        current = s.get('enabled', True)
        s['enabled'] = not current
        SERVERS[idx] = s
        CONFIG['servers'] = SERVERS
        with open('../config.json', 'w') as f:
            json.dump(CONFIG, f, indent=4)
        
        # Refresh Menu
        query.data = f'manage_srv_{idx}'
        await admin_handler(update, context)
        return

    elif query.data.startswith('set_def_'):
        idx = int(query.data.split('_')[-1])
        CONFIG = load_config()
        CONFIG['default_server_id'] = idx
        with open('../config.json', 'w') as f:
            json.dump(CONFIG, f, indent=4)
        
        query.data = f'manage_srv_{idx}'
        await admin_handler(update, context)
        return

    elif query.data.startswith('toggle_scope_'):
        idx = int(query.data.split('_')[-1])
        CONFIG = load_config()
        SERVERS = CONFIG['servers']

        if idx >= len(SERVERS):
            await query.edit_message_text("❌ Server not found.")
            return

        s = SERVERS[idx]
        s['vpn_status_scope'] = not bool(s.get('vpn_status_scope', False))
        SERVERS[idx] = s
        CONFIG['servers'] = SERVERS
        with open('../config.json', 'w') as f:
            json.dump(CONFIG, f, indent=4)

        query.data = f'manage_srv_{idx}'
        await admin_handler(update, context)
        return

    elif query.data.startswith('toggle_vpn_new_'):
        idx = int(query.data.split('_')[-1])
        CONFIG = load_config()
        SERVERS = CONFIG['servers']

        if idx >= len(SERVERS):
            await query.edit_message_text("❌ Server not found.")
            return

        s = SERVERS[idx]
        s['vpn_block_new_profiles'] = not bool(s.get('vpn_block_new_profiles', False))
        SERVERS[idx] = s
        CONFIG['servers'] = SERVERS
        with open('../config.json', 'w') as f:
            json.dump(CONFIG, f, indent=4)

        query.data = f'manage_srv_{idx}'
        await admin_handler(update, context)
        return

    elif query.data.startswith('toggle_vpn_renew_'):
        idx = int(query.data.split('_')[-1])
        CONFIG = load_config()
        SERVERS = CONFIG['servers']

        if idx >= len(SERVERS):
            await query.edit_message_text("❌ Server not found.")
            return

        s = SERVERS[idx]
        s['vpn_block_renewals'] = not bool(s.get('vpn_block_renewals', False))
        SERVERS[idx] = s
        CONFIG['servers'] = SERVERS
        with open('../config.json', 'w') as f:
            json.dump(CONFIG, f, indent=4)

        query.data = f'manage_srv_{idx}'
        await admin_handler(update, context)
        return

    elif query.data.startswith('create_inb_'):
        idx = int(query.data.split('_')[-1])
        CONFIG = load_config()
        SERVERS = CONFIG['servers']

        if idx >= len(SERVERS):
            await query.edit_message_text("❌ Server not found.")
            return

        s = SERVERS[idx]
        client = XUIClient(s)
        ok, detected_id, detail = client.create_auto_inbound(
            remark=s.get('name', f"Server {idx+1}"),
            port=443
        )

        if not ok:
            await query.edit_message_text(
                f"❌ Failed to create inbound on <b>{s.get('name')}</b>.\n\n"
                f"Reason: <code>{detail}</code>",
                parse_mode='HTML'
            )
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data=f'manage_srv_{idx}')]]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            return

        s['inbound_id'] = int(detected_id)
        SERVERS[idx] = s
        CONFIG['servers'] = SERVERS
        with open('../config.json', 'w') as f:
            json.dump(CONFIG, f, indent=4)

        await query.edit_message_text(
            f"✅ Inbound created on <b>{s.get('name')}</b>.\n"
            f"🆔 Inbound ID set to: <b>{detected_id}</b>",
            parse_mode='HTML'
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data=f'manage_srv_{idx}')]]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif query.data.startswith('del_srv_'):
        idx = int(query.data.split('_')[-1])
        CONFIG = load_config() # Reload
        SERVERS = CONFIG['servers']
        s = SERVERS[idx]
        msg = f"⚠️ <b>Delete Server?</b>\n\nAre you sure you want to delete <b>{s.get('name')}</b>?\nThis cannot be undone."
        keyboard = [
            [InlineKeyboardButton("✅ Yes, Delete", callback_data=f'confirm_del_{idx}')],
            [InlineKeyboardButton("❌ No, Cancel", callback_data=f'manage_srv_{idx}')]
        ]
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif query.data.startswith('confirm_del_'):
        idx = int(query.data.split('_')[-1])
        CONFIG = load_config()
        SERVERS = CONFIG['servers']
        if idx < len(SERVERS):
            deleted = SERVERS.pop(idx)
            CONFIG['servers'] = SERVERS
            
            # Reset default if needed
            if CONFIG.get('default_server_id', 0) >= idx:
                CONFIG['default_server_id'] = max(0, CONFIG.get('default_server_id', 0) - 1)
                
            with open('../config.json', 'w') as f:
                json.dump(CONFIG, f, indent=4)
            
            await query.edit_message_text(f"🗑 Deleted <b>{deleted.get('name')}</b>.", parse_mode='HTML')
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='admin_manage_menu')]]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text("❌ Error: Server index out of range.")
        return

    if query.data.startswith('admin_gen'):
        context.user_data['temp_gen_type'] = "1m" if "1m" in query.data else "trial"
        keyboard = []
        for i, s in enumerate(SERVERS):
            # Extract IP from URL for label
            try:
                ip_label = s.get('panel_url').split('://')[1].split(':')[0]
            except:
                ip_label = s.get('name', f"Server {i+1}")
            
            keyboard.append([InlineKeyboardButton(f"🖥 {ip_label}", callback_data=f'admin_sel_srv_{i}')])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='admin_cancel')])
        await query.edit_message_text("👉 <b>Select Server:</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif query.data == 'admin_bulk_gen':
        keyboard = []
        for i, s in enumerate(SERVERS):
            try:
                ip_label = s.get('panel_url').split('://')[1].split(':')[0]
            except:
                ip_label = s.get('name', f"Server {i+1}")
            keyboard.append([InlineKeyboardButton(f"🖥 {ip_label}", callback_data=f'admin_bulk_sel_srv_{i}')])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='admin_cancel')])
        await query.edit_message_text("👉 <b>Select Server For Bulk Creation:</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif query.data.startswith('admin_bulk_sel_srv_'):
        idx = int(query.data.split('_')[-1])
        context.user_data['gen_server_idx'] = idx
        context.user_data['gen_type'] = 'bulk_generate'
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='admin_cancel')]]
        await query.edit_message_text(
            "📦 <b>Bulk Generate Users</b>\n\n"
            "Reply with this format:\n"
            "<code>prefix|count|gb|days</code>\n\n"
            "Example:\n"
            "<code>teamA|5|200|30</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif query.data.startswith('admin_sel_srv_'):
        idx = int(query.data.split('_')[-1])
        context.user_data['gen_server_idx'] = idx
        context.user_data['gen_type'] = context.user_data.get('temp_gen_type', 'trial')
        duration = "1 Month" if context.user_data['gen_type'] == "1m" else "Trial"
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='admin_cancel')]]
        await query.edit_message_text(
            f"👤 <b>Enter Username for {duration}:</b>\n"
            f"Selected: Server {idx+1}\n\n"
            "Reply with the name.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif query.data == 'admin_add_server':
        context.user_data['gen_type'] = "add_server"
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='admin_cancel')]]
        await query.edit_message_text(
            "🖥️ <b>Add New Server</b>\n"
            "Paste the raw output text from X-UI install script.\n"
            "Or use format: <code>URL|Username|Password|InboundID</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif query.data == 'admin_status':
        # Check all servers
        msg = "🖥️ <b>Server Status:</b>\n\n"
        for idx, s in enumerate(SERVERS):
            # Extract IP
            try:
                ip_label = s.get('panel_url').split('://')[1].split(':')[0]
            except:
                ip_label = s.get('name', f"Server {i+1}")

            is_enabled = s.get('enabled', True)
            status_emoji = "✅"
            if not is_enabled:
                status_emoji = "⛔️ (Disabled)"
            else:
                try:
                    # Quick login check
                    client = XUIClient(s)
                    status_emoji = "✅ Online"
                except:
                    status_emoji = "❌ Offline"
            
            msg += f"{ip_label}: {status_emoji}\n"
            
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='admin_back')]]
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == 'admin_inactive_users':
        await query.edit_message_text("🔍 Scanning inactive users across servers...", parse_mode='HTML')
        rows = collect_inactive_users()
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='admin_back')]]
        await query.edit_message_text(
            f"✅ Found {len(rows)} inactive users. Sending cards below.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await send_inactive_cards(query.message.chat_id, context, rows)

    elif query.data.startswith('inactdel_'):
        token = query.data.split('_', 1)[1]
        cache = context.bot_data.get('inactive_cache', {})
        cached = cache.get(token)

        if not cached:
            await query.edit_message_text("⚠️ This delete action is expired. Please refresh inactive users list.", parse_mode='HTML')
            return

        age = int(time.time()) - int(cached.get('ts', 0))
        if age > INACTIVE_CACHE_TTL_SECONDS:
            cache.pop(token, None)
            await query.edit_message_text("⚠️ This delete action is expired. Please refresh inactive users list.", parse_mode='HTML')
            return

        row = cached.get('row', {})
        email = row.get('email')
        panel_url = str(row.get('panel_url', '')).rstrip('/')
        inbound_id = int(row.get('inbound_id', 0) or 0)

        target_server = None
        for server in SERVERS:
            if str(server.get('panel_url', '')).rstrip('/') == panel_url and int(server.get('inbound_id', 0) or 0) == inbound_id:
                target_server = server
                break

        if not target_server:
            await query.edit_message_text(
                f"❌ Could not find target server for <code>{email}</code>.",
                parse_mode='HTML'
            )
            return

        client = XUIClient(target_server)
        deleted = client.delete_client_by_email(email)
        cache.pop(token, None)

        if deleted:
            await query.edit_message_text(
                f"🗑 <b>Deleted inactive user</b>\n\n"
                f"👤 <code>{email}</code>\n"
                f"🖥 {target_server.get('name', 'Unknown')}",
                parse_mode='HTML'
            )
        else:
            await query.edit_message_text(
                f"❌ Failed to delete <code>{email}</code>. It may already be removed.",
                parse_mode='HTML'
            )

    elif query.data == 'admin_back':
        await start(update, context) # Reuse start logic

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ensure we modify the module-level config and servers
    global CONFIG, SERVERS

    # Check if adding a server
    if context.user_data.get('gen_type') == 'add_server':
        raw = update.message.text
        # Try parsing raw X-UI install script output
        try:
            if "Access URL:" in raw:
                import re
                try:
                    user = re.search(r'Username:\s*(\S+)', raw).group(1)
                    pwd = re.search(r'Password:\s*(\S+)', raw).group(1)
                    # Extract full URL but keep only up to port/root
                    url_match = re.search(r'Access URL:\s*(\S+)', raw)
                    if url_match:
                        full_url = url_match.group(1).rstrip('\\') 
                        # Clean up weird trailing chars or paths if needed
                        # Usually X-UI gives https://ip:port/path/
                        url = full_url
                    else:
                        raise ValueError("URL not found")
                    iid = 1
                except AttributeError:
                    raise ValueError("Regex parsing failed. Check input format.")
            else:
                # Fallback to pipe format: URL|User|Pass|ID
                url, user, pwd, iid = raw.split('|')

            # Ensure valid URL structure
            if not url.startswith("http"):
                url = "https://" + url

            new_server = {
                "name": f"Server {len(SERVERS)+1}",
                "panel_url": url.strip(),
                "username": user.strip(),
                "password": pwd.strip(),
                "inbound_id": int(str(iid).strip()),
                "flow_limit_gb": 100,
                "expire_days": 30,
                "vpn_status_scope": False,
                "vpn_block_new_profiles": False,
                "vpn_block_renewals": False
            }

            # Try to auto-detect the most suitable inbound for this panel.
            try:
                probe_client = XUIClient(new_server)
                detected_id = probe_client.discover_preferred_inbound_id()
                new_server["inbound_id"] = int(detected_id)
            except Exception:
                pass

            # Reload the config just before writing to ensure we don't persist any
            # accidental in-memory changes.
            CONFIG = load_config()
            SERVERS = CONFIG.get('servers', [])
            SERVERS.append(new_server)
            CONFIG['servers'] = SERVERS
            # Write back to parent config.json (root)
            with open('../config.json', 'w') as f:
                json.dump(CONFIG, f, indent=4)
            await update.message.reply_text("✅ Server Added Successfully!")
            context.user_data['gen_type'] = None
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Invalid Format: {e}")
            return

    if context.user_data.get('gen_type') == 'bulk_generate':
        raw = update.message.text.strip()
        try:
            prefix, count_raw, gb_raw, days_raw = [x.strip() for x in raw.split('|')]
            count = int(count_raw)
            limit_gb = int(gb_raw)
            expire_days = int(days_raw)
            if count <= 0 or count > 30:
                raise ValueError("count must be between 1 and 30")
            if limit_gb <= 0:
                raise ValueError("gb must be greater than 0")
            if expire_days <= 0:
                raise ValueError("days must be greater than 0")
            if not prefix:
                raise ValueError("prefix cannot be empty")

            server_idx = context.user_data.get('gen_server_idx', CONFIG.get('default_server_id', 0))
            target_server = SERVERS[server_idx] if server_idx < len(SERVERS) else SERVERS[0]
            status_msg = await update.message.reply_text("⚙️ Generating bulk users...")

            client = XUIClient(target_server)
            created = []
            skipped = []
            failed = []
            fail_reason = ""

            for i in range(1, count + 1):
                username = f"{prefix}_{i}"
                result = client.add_client(email=username, limit_gb=limit_gb, expire_days=expire_days)
                if isinstance(result, tuple):
                    link, existed = result
                else:
                    link = result
                    existed = False

                if link and not existed:
                    created.append((username, link))
                elif link and existed:
                    skipped.append(username)
                else:
                    failed.append(username)
                    if not fail_reason:
                        fail_reason = client.last_error

            context.user_data['gen_type'] = None
            summary = (
                f"✅ <b>Bulk Generation Finished</b>\n\n"
                f"🖥 Server: {target_server.get('name')}\n"
                f"📦 Requested: {count}\n"
                f"✅ Created: {len(created)}\n"
                f"⚠️ Duplicate: {len(skipped)}\n"
                f"❌ Failed: {len(failed)}\n"
                f"📊 Plan: {limit_gb} GB / {expire_days} days"
            )
            await status_msg.edit_text(summary, parse_mode='HTML')

            if created:
                lines = [f"{name}:\n<code>{link}</code>" for name, link in created]
                await update.message.reply_text("\n\n".join(lines), parse_mode='HTML')
            if skipped:
                await update.message.reply_text(
                    "⚠️ Duplicate users skipped:\n" + "\n".join(skipped),
                    parse_mode='HTML'
                )
            if failed:
                await update.message.reply_text(
                    "❌ Failed users:\n" + "\n".join(failed),
                    parse_mode='HTML'
                )
                if fail_reason:
                    await update.message.reply_text(
                        f"⚠️ Failure reason: <code>{fail_reason}</code>",
                        parse_mode='HTML'
                    )
            return
        except Exception as e:
            await update.message.reply_text(
                f"❌ Invalid bulk format: {e}\n\n"
                "Use: <code>prefix|count|gb|days</code>\n"
                "Example: <code>teamA|5|200|30</code>",
                parse_mode='HTML'
            )
            return

    # Check if waiting for username
    if context.user_data.get('gen_type'):
        username = update.message.text
        gen_type = context.user_data['gen_type']
        context.user_data['gen_type'] = None
        
        limit_gb = 100 if gen_type == "1m" else 2
        days = 30 if gen_type == "1m" else 1
        
        status_msg = await update.message.reply_text("⚙️ Generating...")
        
        try:
            # Default to Server 0 if server selection logic is bypassed (or from old menu flow)
            server_idx = context.user_data.get('gen_server_idx', CONFIG.get('default_server_id', 0))
            # Safely get target server
            target_server = SERVERS[server_idx] if server_idx < len(SERVERS) else SERVERS[0]
            
            client = XUIClient(target_server)
            result = client.add_client(email=username, limit_gb=limit_gb, expire_days=days)
            if isinstance(result, tuple):
                link, existed = result
            else:
                link = result
                existed = False

            if link:
                await status_msg.edit_text(
                    f"✅ <b>Key Generated!</b>\n\n"
                    f"Server: {target_server.get('name')}\n"
                    f"Name: {username}\n"
                    f"Limit: {limit_gb} GB\n"
                    f"Days: {days}\n\n"
                    f"<code>{link}</code>",
                    parse_mode='HTML'
                )
                if existed:
                    await status_msg.edit_text("⚠️ Note: Existing key returned (duplicate).")
            else:
                await status_msg.edit_text("❌ Failed. Name might duplicate.")
        except Exception as e:
            await status_msg.edit_text(f"❌ Error: {e}")

def main():
    # use the explicit admin token, not whatever `bot_token` happens to be in
    # the JSON file.
    app = Application.builder().token(ADMIN_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("inactive_users", inactive_users_command))
    app.add_handler(CommandHandler("inactive", inactive_users_command))
    app.add_handler(CallbackQueryHandler(admin_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    # Centralized error handler to log exceptions from handlers
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        try:
            logging.exception("Exception while handling an update", exc_info=context.error)
        except Exception:
            logging.exception("Exception in error handler")

        # Provide helpful guidance for Conflict errors
        err = getattr(context, 'error', None)
        if err and isinstance(err, telegram.error.Conflict):
            logging.error("Conflict: terminated by other getUpdates request; ensure only one bot instance is running or switch to webhooks.")

    app.add_error_handler(error_handler)
    print("Admin Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()