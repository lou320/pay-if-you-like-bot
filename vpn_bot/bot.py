import logging
import json
import uuid
import secrets
import string
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
import telegram
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Setup logging FIRST
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)

# --- CONFIGURATION ---
def load_config():
    with open('../config.json', 'r') as f:
        return json.load(f)

CONFIG = load_config()
SERVERS = CONFIG['servers']
ADMIN_IDS = CONFIG['admin_ids']
logging.info(f"Configuration loaded: {len(SERVERS)} servers, {len(ADMIN_IDS)} admins")
for s in SERVERS:
    logging.debug(f"  Server: {s.get('name')}")
MAIN_MENU_KB = ReplyKeyboardMarkup([['အစသို့ပြန်သွားပါ']], resize_keyboard=True)


# --- HELPER FUNCTIONS ---
ROTATION_STATE_FILE = 'server_rotation_state.json'


def get_active_servers():
    """Use enabled servers only; fall back to all servers if none are explicitly enabled."""
    enabled = [s for s in SERVERS if s.get('enabled', True)]
    return enabled if enabled else SERVERS


def load_rotation_state():
    try:
        with open(ROTATION_STATE_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {"next_index": 0}


def save_rotation_state(state):
    try:
        with open(ROTATION_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logging.warning(f"Failed to persist rotation state: {e}")


def get_round_robin_servers():
    """Return active servers ordered by round-robin and advance pointer for equal distribution."""
    servers = get_active_servers()
    if not servers:
        return []

    state = load_rotation_state()
    start_idx = int(state.get('next_index', 0)) % len(servers)
    ordered = servers[start_idx:] + servers[:start_idx]

    state['next_index'] = (start_idx + 1) % len(servers)
    save_rotation_state(state)
    return ordered

# --- X-UI API CLIENT ---
class XUIClient:
    def __init__(self, server_config):
        self.base_url = server_config['panel_url'].rstrip('/')
        self.username = server_config['username']
        self.password = server_config['password']
        self.inbound_id = server_config['inbound_id']
        self.session = requests.Session()
        self.login()

    def login(self):
        login_url = f"{self.base_url}/login"
        payload = {'username': self.username, 'password': self.password}
        try:
            r = self.session.post(login_url, data=payload, verify=False, timeout=10)
            if r.json().get('success'):
                logging.info(f"Logged in to {self.base_url}")
                return True
        except Exception as e:
            logging.error(f"Login failed: {e}")
        return False

    def get_client_stats(self, target_uuid):
        """Find a client by UUID and return stats (up, down, total, expiry)."""
        # If no login cookies, login first
        if not self.session.cookies:
            self.login()

        list_url = f"{self.base_url}/panel/api/inbounds/list"
        try:
            r = self.session.get(list_url, verify=False, timeout=10)
            # If session expired (success: false or auth error), re-login and retry
            if not r.json().get('success'):
                logging.info(f"Session expired for {self.base_url}, re-logging in...")
                self.login()
                r = self.session.get(list_url, verify=False, timeout=10)
            
            if r.json().get('success'):
                inbounds = r.json()['obj']
                for inbound in inbounds:
                    settings = json.loads(inbound['settings'])
                    
                    # 1. Find Client in Settings (Config)
                    target_client = None
                    for client in settings['clients']:
                        if client['id'] == target_uuid:
                            target_client = client
                            break
                    
                    if target_client:
                        # 2. Try to find REAL usage stats from 'clientStats' (dynamic)
                        # X-UI often separates stats from config
                        up = target_client.get('up', 0)
                        down = target_client.get('down', 0)
                        
                        client_stats = inbound.get('clientStats')
                        if client_stats:
                            for stat in client_stats:
                                # Match by Email (most reliable) or ID
                                if stat.get('email') == target_client['email']:
                                    up = stat.get('up', 0)
                                    down = stat.get('down', 0)
                                    break
                        
                        return {
                            "email": target_client['email'],
                            "up": up,
                            "down": down,
                            "total": target_client.get('totalGB', 0),
                            "expiry": target_client.get('expiryTime', 0),
                            "enable": target_client.get('enable', True)
                        }
            return None
        except Exception as e:
            logging.error(f"Error checking stats: {e}")
            return None

    def add_client(self, email, limit_gb=0, expire_days=0):
        # Validate panel URL
        if "vless://" in self.base_url:
            logging.error("Invalid Panel URL (vless link detected). Check config.json")
            return (None, False)

        # Fetch inbound info (with retry on session expiration)
        list_url = f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}"
        try:
            r = self.session.get(list_url, verify=False, timeout=15)
            rj = r.json()
        except Exception as e:
            logging.error(f"Failed to GET inbound info: {e}")
            return (None, False)

        if not rj.get('success'):
            logging.debug(f"Inbound GET success=false, response={rj}. Attempting re-login and retry.")
            self.login()
            try:
                r = self.session.get(list_url, verify=False, timeout=15)
                rj = r.json()
            except Exception as e:
                logging.error(f"Retry GET inbound failed: {e}")
                return (None, False)

        if not rj.get('success'):
            logging.error(f"Inbound GET failed after retry: {rj}")
            return (None, False)

        inbound = rj.get('obj')
        logging.debug(f"Inbound object keys: {inbound.keys() if isinstance(inbound, dict) else 'not a dict'}")

        try:
            settings = json.loads(inbound.get('settings', '{}'))
        except Exception as e:
            logging.error(f"Failed to parse inbound settings JSON: {e}")
            settings = {'clients': []}

        try:
            stream_settings = json.loads(inbound.get('streamSettings', '{}'))
        except Exception as e:
            logging.error(f"Failed to parse inbound streamSettings JSON: {e}")
            stream_settings = {}

        expiry_time = 0
        if expire_days > 0:
            import time
            expiry_time = int((time.time() * 1000) + (expire_days * 86400 * 1000))

        add_url = f"{self.base_url}/panel/api/inbounds/addClient"

        def build_link_for_uuid(uuid_val, remark_val):
            """Construct a vless link from uuid, using Reality settings if available."""
            try:
                reality = stream_settings.get('realitySettings') if isinstance(stream_settings, dict) else None
                rsettings = reality.get('settings') if reality else None
                if isinstance(rsettings, str):
                    try:
                        rsettings = json.loads(rsettings)
                    except Exception:
                        rsettings = None

                pbk = sni = sid = None
                if isinstance(rsettings, dict):
                    pbk = rsettings.get('publicKey')
                if reality and reality.get('serverNames'):
                    sni = reality.get('serverNames')[0]
                if reality and reality.get('shortIds'):
                    sid = reality.get('shortIds')[0]

                ip = self.base_url.split('://')[1].split(':')[0]
                port = inbound.get('port')

                if pbk and sni and sid:
                    return (f"vless://{uuid_val}@{ip}:{port}"
                            f"?type=tcp&security=reality&pbk={pbk}&fp=chrome"
                            f"&sni={sni}&sid={sid}&spx=%2F&flow=xtls-rprx-vision#{remark_val}")
                else:
                    # Fallback for ws or tcp without reality
                    network = stream_settings.get('network') if isinstance(stream_settings, dict) else None
                    if network == 'ws':
                        ws = stream_settings.get('wsSettings') or {}
                        path = ws.get('path', '/')
                        headers = ws.get('headers') or {}
                        host = headers.get('Host') or None
                        params = f"type=ws&security=none&path={path}"
                        if host:
                            params += f"&host={host}"
                    else:
                        params = "type=tcp&security=none"
                    return f"vless://{uuid_val}@{ip}:{port}?{params}#{remark_val}"
            except Exception as e:
                logging.error(f"Failed to build link: {e}")
                return None

        # Try adding the client
        try:
            new_uuid = str(uuid.uuid4())
            sub_id = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(16))
            
            client_data = {
                "id": self.inbound_id,
                "settings": json.dumps({
                    "clients": [{
                        "id": new_uuid,
                        "email": email,
                        "flow": "xtls-rprx-vision",
                        "totalGB": limit_gb * 1024 * 1024 * 1024,
                        "expiryTime": expiry_time,
                        "enable": True,
                        "tgId": "",
                        "subId": sub_id,
                        "limitIp": 1
                    }]
                })
            }

            r = self.session.post(add_url, json=client_data, verify=False, timeout=15)
            logging.debug(f"addClient POST {add_url} email={email} returned status={r.status_code}")

            try:
                resp_json = r.json()
            except Exception as e:
                logging.error(f"addClient response is not JSON: {r.text[:200]}")
                return (None, False)

            if resp_json and resp_json.get('success'):
                link = build_link_for_uuid(new_uuid, email)
                return (link, False) if link else (None, False)

            # Check for duplicate email
            if resp_json and not resp_json.get('success') and 'duplicate' in str(resp_json.get('msg', '')).lower():
                logging.info(f"Duplicate email detected for {email}, searching for existing client...")
                for c in settings.get('clients', []):
                    if c.get('email') == email:
                        existing_uuid = c.get('id')
                        link = build_link_for_uuid(existing_uuid, email)
                        if link:
                            logging.info(f"Found existing client for {email}, returning existing link")
                            return (link, True)
                return (None, False)

            logging.error(f"Failed to add client: response={resp_json}")
            return (None, False)
        except Exception as e:
            logging.error(f"Exception in add_client: {e}")
            return (None, False)

    def delete_client_by_email(self, email):
        """Delete a client from the inbound by email address."""
        try:
            list_url = f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}"
            r = self.session.get(list_url, verify=False, timeout=15)
            rj = r.json()
            
            if not rj.get('success'):
                logging.debug(f"Session expired, re-logging in for delete operation...")
                self.login()
                r = self.session.get(list_url, verify=False, timeout=15)
                rj = r.json()
            
            if not rj.get('success'):
                logging.error(f"Failed to fetch inbound for deletion: {rj}")
                return False
            
            inbound = rj.get('obj')
            settings = json.loads(inbound.get('settings', '{}'))
            
            # Find and remove the client
            target_uuid = None
            for client in settings.get('clients', []):
                if client.get('email') == email:
                    target_uuid = client.get('id')
                    settings['clients'].remove(client)
                    logging.info(f"Found client {email} with UUID {target_uuid}, removing...")
                    break
            
            if not target_uuid:
                logging.warning(f"Client {email} not found on server {self.base_url}")
                return False
            
            # Update the inbound with the modified settings (client removed)
            update_url = f"{self.base_url}/panel/api/inbounds/{self.inbound_id}"
            update_data = {
                "id": self.inbound_id,
                "settings": json.dumps(settings)
            }
            
            r = self.session.post(update_url, json=update_data, verify=False, timeout=15)
            resp_json = r.json()
            
            if resp_json.get('success'):
                logging.info(f"Successfully deleted client {email} (UUID: {target_uuid}) from {self.base_url}")
                return True
            else:
                logging.error(f"Failed to delete client {email}: {resp_json}")
                return False
                
        except Exception as e:
            logging.error(f"Exception in delete_client_by_email: {e}")
            return False

    def reset_and_extend_client(self, target_uuid: str, expire_days: int = 30):
        """Reset traffic counters to 0 and extend expiry by expire_days from now.
        Returns (True, new_expiry_date_str) on success, (False, error_msg) on failure."""
        import time as _time
        from datetime import datetime as _dt

        list_url = f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}"
        try:
            r = self.session.get(list_url, verify=False, timeout=15)
            rj = r.json()
            if not rj.get('success'):
                self.login()
                r = self.session.get(list_url, verify=False, timeout=15)
                rj = r.json()
            if not rj.get('success'):
                return False, "Failed to fetch inbound data"

            inbound  = rj['obj']
            settings = json.loads(inbound.get('settings', '{}'))
            clients  = settings.get('clients', [])

            target_client = None
            for c in clients:
                if c.get('id') == target_uuid:
                    target_client = dict(c)  # shallow copy
                    break

            if not target_client:
                return False, "Client not found in this inbound"

            email = target_client['email']

            # Set new expiry (from now)
            new_expiry_ms = int((_time.time() * 1000) + (expire_days * 86400 * 1000))
            target_client['expiryTime'] = new_expiry_ms
            target_client['totalGB']    = 100 * 1024 * 1024 * 1024  # 100 GB
            target_client['enable']     = True

            # Push updated client to X-UI
            update_url  = f"{self.base_url}/panel/api/inbounds/updateClient/{target_uuid}"
            update_data = {
                "id":       self.inbound_id,
                "settings": json.dumps({"clients": [target_client]})
            }
            r    = self.session.post(update_url, json=update_data, verify=False, timeout=15)
            resp = r.json()
            if not resp.get('success'):
                return False, f"Update failed: {resp.get('msg', resp)}"

            # Reset traffic counters
            reset_url = (
                f"{self.base_url}/panel/api/inbounds/"
                f"{self.inbound_id}/resetClientTraffic/{email}"
            )
            r    = self.session.post(reset_url, verify=False, timeout=15)
            resp = r.json()
            if not resp.get('success'):
                logging.warning(f"Traffic reset non-success for {email}: {resp}")

            expiry_date = _dt.fromtimestamp(new_expiry_ms / 1000).strftime('%Y-%m-%d')
            return True, expiry_date

        except Exception as e:
            logging.error(f"reset_and_extend_client error: {e}")
            return False, str(e)

from datetime import datetime, timedelta
import re
import time

# --- TRIAL TRACKING HELPERS ---
"""
Tracking file format (claimed_users.json):
{
    "8130396030": {
        "link": "vless://...",
        "timestamp": 1710086400,  # unix timestamp when trial was issued
        "trial_type": "free",     # "free" or "premium"
        "email": "FreeTrial_8130396030",
        "server_name": "Server 1"
    }
}

This allows us to:
1. Track when each free trial was created
2. Auto-delete accounts after 3 days
3. Prevent users from getting multiple free trials
"""

def load_trial_tracking():
    """Load trial tracking data with support for legacy format."""
    try:
        with open('claimed_users.json', 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    
    # Legacy format migration: if data contains strings (old format), convert to new format
    migrated = False
    for user_id, value in list(data.items()):
        if isinstance(value, str):
            # Old format: {user_id: link} -> new format
            data[user_id] = {
                "link": value,
                "timestamp": int(time.time()),  # Assume "now" for legacy entries
                "trial_type": "free",
                "email": f"FreeTrial_{user_id}",
                "server_name": "Unknown"
            }
            migrated = True
    
    if migrated:
        save_trial_tracking(data)
        logging.info("Migrated trial tracking data to new format")
    
    return data

def save_trial_tracking(data):
    """Save trial tracking data."""
    try:
        with open('claimed_users.json', 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"Failed to save trial tracking: {e}")


def find_client_by_uuid(target_uuid: str):
    """Search every server for a client UUID.
    Returns (server_config, XUIClient_instance, email) or (None, None, None)."""
    for server in SERVERS:
        try:
            client = XUIClient(server)
            stats  = client.get_client_stats(target_uuid)
            if stats:
                return server, client, stats['email']
        except Exception:
            continue
    return None, None, None


async def cleanup_expired_trials(application: Application):
    """
    Background task to delete free trial accounts after 3 days.
    Runs periodically.
    """
    logging.info("🧹 Starting expired trial cleanup task...")
    
    try:
        tracking = load_trial_tracking()
        current_time = int(time.time())
        three_days_seconds = 3 * 24 * 60 * 60  # 259200 seconds
        
        deleted_count = 0
        
        for user_id, trial_info in list(tracking.items()):
            if isinstance(trial_info, dict):
                trial_timestamp = trial_info.get('timestamp', 0)
                email = trial_info.get('email', '')
                server_name = trial_info.get('server_name', '')
                trial_type = trial_info.get('trial_type', 'free')
                
                # Only auto-delete FREE trials after 3 days
                if trial_type == 'free' and (current_time - trial_timestamp) >= three_days_seconds:
                    logging.info(f"Deleting expired trial for user {user_id} (email: {email}, age: {(current_time - trial_timestamp)/86400:.1f} days)")
                    
                    # Find and delete the account from all servers
                    delete_success = False
                    for server in SERVERS:
                        try:
                            client = XUIClient(server)
                            if client.delete_client_by_email(email):
                                delete_success = True
                                logging.info(f"✅ Deleted {email} from {server.get('name')}")
                        except Exception as e:
                            logging.warning(f"Failed to delete from {server.get('name')}: {e}")
                    
                    if delete_success:
                        # Remove from tracking
                        del tracking[user_id]
                        deleted_count += 1
                        
                        # Try to notify user
                        try:
                            await application.bot.send_message(
                                chat_id=int(user_id),
                                text=(
                                    "⏰ <b>Free Trial Expired</b>\n\n"
                                    "Your 3-day free trial has expired and the account has been deleted.\n\n"
                                    "💎 Want to continue using VPN?\n"
                                    "👉 /start and select 'Premium' to get a 1-month plan!"
                                ),
                                parse_mode='HTML'
                            )
                        except Exception as e:
                            logging.warning(f"Failed to notify user {user_id} about trial expiration: {e}")
        
        if deleted_count > 0:
            save_trial_tracking(tracking)
            logging.info(f"✅ Cleanup complete: {deleted_count} expired trials deleted")
        else:
            logging.info("✅ Cleanup complete: No expired trials found")
            
    except Exception as e:
        logging.error(f"Error in cleanup_expired_trials: {e}")


# ... (Previous imports remain)

# --- HELPER FUNCTION: PARSE SLIP ---
def parse_payment_slip(text_from_image):
    # This is a placeholder. Real OCR needs an external API (like Google Vision) or local Tesseract.
    # Since we can't run heavy OCR locally easily, we will simulate the logic or use regex if the user forwards text.
    # For now, we will assume the user sends the transaction ID or date text.
    
    # Mock logic for the "10 minutes" rule:
    # We will ask the user to type the Time on the slip if we can't read it.
    pass

# ... (XUIClient Class remains the same) ...

# --- TELEGRAM BOT LOGIC ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Send Welcome with Persistent Menu (Bottom)
    await update.message.reply_text(
        "<b>မင်္ဂလာပါ @PayIfYouLike မှ ကြိုဆိုပါတယ်!</b> 🇲🇲",
        parse_mode='HTML',
        reply_markup=MAIN_MENU_KB
    )

    # 2. Send Inline Menu (Main Interaction)
    text = (
        "အင်တာနက်လိုင်း ကောင်းမွန်ပြီး လုံခြုံစိတ်ချရတဲ့ VPN ကို ရှာနေပါသလား?\n"
        "လူကြီးမင်းအတွက် အကောင်းဆုံး ဝန်ဆောင်မှုပေးဖို့ အသင့်ရှိပါတယ်။\n\n"
        "👇 <b>ဘာလုပ်ချင်ပါသလဲ ရွေးချယ်ပေးပါခင်ဗျာ:</b>"
    )
    keyboard = [
        [InlineKeyboardButton("🚀 Free စမ်းသုံးမယ် (24 Hours)", callback_data='get_free')],
        [InlineKeyboardButton("💎 1 လစာ (100Gb) ဝယ်ယူမယ်", callback_data='buy_premium')],
        [InlineKeyboardButton("� Key သက်တမ်းတိုးမည် (Renew)", callback_data='renew_key')],
        [InlineKeyboardButton("�📊 Data လက်ကျန်စစ်မယ်", callback_data='check_quota')],
        [InlineKeyboardButton("❓ ဘယ်လိုသုံးရမလဲ", callback_data='help')]
    ]
    await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    photo_file = await update.message.photo[-1].get_file()

    # ── Renewal slip ──────────────────────────────────────────────────────────
    if context.user_data.get('state') == 'awaiting_renew_slip':
        renew_info = context.user_data.get('renew_info', {})
        context.user_data.pop('state', None)
        context.user_data.pop('renew_info', None)

        # Store pending renewal in bot_data so approval_handler can access it
        context.bot_data.setdefault('renew_pending', {})[str(user.id)] = renew_info

        await update.message.reply_text(
            "⏳ <b>ငွေလွှဲပြေစာကို Admin သို့ ပေးပို့ပြီးပါပြီ။</b>\n\n"
            "Admin မှ စစ်ဆေးပြီးပါက Key သက်တမ်း အလိုအလျောက် တိုးပေးပါမည်။\n"
            "Admin ကိုဆက်သွယ်ရန် @payifyoulike",
            parse_mode='HTML',
            reply_markup=MAIN_MENU_KB
        )
        caption = (
            f"🔄 <b>Key Renewal Slip!</b>\n\n"
            f"👤 User: {user.full_name} (ID: <code>{user.id}</code>)\n"
            f"🔗 <a href='tg://user?id={user.id}'>Chat with User</a>\n\n"
            f"📋 <b>Email:</b> <code>{renew_info.get('email', 'N/A')}</code>\n"
            f"🖥 <b>Server:</b> {renew_info.get('server_name', 'N/A')}"
        )
        keyboard = [[
            InlineKeyboardButton("✅ Approve Renewal", callback_data=f'rnw_ok_{user.id}'),
            InlineKeyboardButton("❌ Decline",         callback_data=f'rnw_no_{user.id}')
        ]]
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_photo(
                    chat_id=admin_id, photo=photo_file.file_id,
                    caption=caption, parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logging.error(f"Failed to send renewal slip to admin {admin_id}: {e}")
        return

    # ── Normal new-purchase slip ───────────────────────────────────────────────
    await update.message.reply_text(
        "⏳ <b>ငွေလွှဲပြေစာကို Admin သို့ ပေးပို့ထားပါသည်။</b>\n\n"
        "Admin မှ စစ်ဆေးပြီးပါက Key အလိုအလျောက် ရောက်ရှိလာပါမည်။ ခေတ္တစောင့်ဆိုင်းပေးပါ။\n\n"
        "Admin ကိုဆက်သွယ်ရန် နှိပ်ပါ 👇\n@payifyoulike",
        parse_mode='HTML',
        reply_markup=MAIN_MENU_KB
    )
    caption = (
        f"📩 <b>New Payment Slip!</b>\n\n"
        f"👤 User: {user.full_name} (ID: <code>{user.id}</code>)\n"
        f"🔗 <a href='tg://user?id={user.id}'>Chat with User</a>"
    )
    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f'approve_{user.id}'),
        InlineKeyboardButton("❌ Decline", callback_data=f'decline_{user.id}')
    ]]
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=photo_file.file_id,
                caption=caption,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logging.error(f"Failed to send to admin {admin_id}: {e}")

async def approval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CONFIG, SERVERS
    query = update.callback_query
    await query.answer()
    
    data = query.data

    # ── Renewal approval (rnw_ok_USERID / rnw_no_USERID) ──────────────────────
    if data.startswith('rnw_'):
        _, sub_action, uid_str = data.split('_', 2)
        user_id = int(uid_str)

        if sub_action == 'no':
            try:
                await query.edit_message_caption(
                    caption=f"{query.message.caption}\n\n❌ <b>RENEWAL DECLINED</b>",
                    parse_mode='HTML'
                )
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "❌ <b>Key သက်တမ်းတိုး မအောင်မြင်ပါ။</b>\n\n"
                    "ငွေလွှဲပြေစာ မှားယွင်းနေသည် သို့မဟုတ် Admin မှ ငြင်းပယ်ပါသည်။\n"
                    "Admin ကိုဆက်သွယ်ရန် @payifyoulike"
                ),
                parse_mode='HTML',
                reply_markup=MAIN_MENU_KB
            )
            return

        # sub_action == 'ok'
        pending = context.bot_data.get('renew_pending', {}).get(str(user_id))
        if not pending:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ No pending renewal found for user {user_id}. It may have expired."
            )
            return

        try:
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\n✅ <b>RENEWAL APPROVED</b>",
                parse_mode='HTML'
            )
        except Exception:
            pass

        target_uuid  = pending['uuid']
        server_name  = pending.get('server_name', '')
        email        = pending.get('email', '')

        # Find the right server and extend
        success = False
        expiry_date = ''
        for server in SERVERS:
            if server.get('name') == server_name:
                try:
                    xui = XUIClient(server)
                    success, expiry_date = xui.reset_and_extend_client(target_uuid)
                    if success:
                        break
                except Exception as e:
                    logging.error(f"Renew on {server_name} failed: {e}")

        # Fallback: try other servers if name didn't match or failed
        if not success:
            server_obj, xui, resolved_email = find_client_by_uuid(target_uuid)
            if xui:
                success, expiry_date = xui.reset_and_extend_client(target_uuid)

        # Clean up pending
        context.bot_data.get('renew_pending', {}).pop(str(user_id), None)

        if success:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ <b>Key သက်တမ်းတိုးခြင်း အောင်မြင်ပါသည်။</b>\n\n"
                    f"👤 <b>Email:</b> <code>{email}</code>\n"
                    f"📅 <b>New Expiry:</b> {expiry_date}\n"
                    f"📦 <b>Data:</b> 100GB (Reset to 0)\n\n"
                    "Key အတူတူပဲ ဆက်သုံးနိုင်ပါပြီ။"
                ),
                parse_mode='HTML',
                reply_markup=MAIN_MENU_KB
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Key သက်တမ်းတိုး မအောင်မြင်ပါ။ Admin ကိုဆက်သွယ်ပါ @payifyoulike",
                parse_mode='HTML',
                reply_markup=MAIN_MENU_KB
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"⚠️ Renewal extend failed for user {user_id} / UUID {target_uuid}"
            )
        return

    # ── New premium key approval (approve_USERID / decline_USERID) ────────────
    action, uid_str = data.split('_', 1)
    user_id = int(uid_str)

    if action == 'approve':
        # Reconstruct caption with link
        old_text = query.message.caption
        import re
        try:
            match = re.search(r"User: (.+) \(ID: (\d+)\)", old_text)
            user_name = match.group(1) if match else "User"
        except Exception:
            user_name = "User"

        new_caption = (
            f"📩 <b>New Payment Slip!</b>\n\n"
            f"👤 User: {user_name} (ID: <code>{user_id}</code>)\n"
            f"🔗 <a href='tg://user?id={user_id}'>Chat with User</a>\n\n"
            f"✅ <b>APPROVED</b>"
        )

        try:
            await query.edit_message_caption(caption=new_caption, parse_mode='HTML')
        except Exception as e:
            logging.warning(f"Caption edit failed: {e}")

        # Generate Key
        try:
            username = f"Premium_{user_id}_{secrets.token_hex(2)}"
            target_server = None
            link = None
            existed = False

            candidate_servers = get_round_robin_servers()
            for server in candidate_servers:
                try:
                    client = XUIClient(server)
                    result = client.add_client(email=username, limit_gb=100, expire_days=30)
                    if isinstance(result, tuple):
                        link, existed = result
                    else:
                        link = result
                        existed = False
                    if link:
                        target_server = server
                        break
                except Exception as server_error:
                    logging.warning(f"Premium key generation failed on {server.get('name')}: {server_error}")

            if link:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        "✅ <b>ငွေလွှဲအောင်မြင်ပါသည်။</b>\n\n"
                        "💎 <b>Premium Key (1 Month / 100GB):</b>\n"
                        f"Server: {target_server.get('name')}\n"
                        "👇 <b>အောက်ပါ Key ကို Copy ယူပါ:</b>"
                    ),
                    parse_mode='HTML'
                )
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"<code>{link}</code>",
                    parse_mode='HTML'
                )
                if existed:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="⚠️ You already have an existing key; a new key cannot be issued.",
                        parse_mode='HTML'
                    )
                await context.bot.send_message(
                    chat_id=user_id,
                    text="👆 <b>Key ကို Copy ယူပါ။</b>\n\nအသုံးပြုနည်းကြည့်ရန် /start ကိုနှိပ်ပြီး\n'❓ ဘယ်လိုသုံးရမလဲ' ကို ရွေးပါ။",
                    parse_mode='HTML',
                    reply_markup=MAIN_MENU_KB
                )
            else:
                await context.bot.send_message(chat_id=query.message.chat_id, text="❌ Error generating key.")

        except Exception as e:
            logging.error(f"Approval Error: {e}")
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"❌ System Error: {e}")

    elif action == 'decline':
        try:
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\n❌ <b>DECLINED</b>",
                parse_mode='HTML'
            )
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "❌ <b>ငွေလွှဲမအောင်မြင်ပါ။</b>\n\n"
                "အသေးစိတ်သိရှိလိုပါက Admin ကို ဆက်သွယ်ပါ။\n\n"
                "👇 Admin ကိုဆက်သွယ်ရန် နှိပ်ပါ\n@payifyoulike"
            ),
            parse_mode='HTML',
            reply_markup=MAIN_MENU_KB
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'get_free':
        # Check if user already has a key using new tracking system
        tracking = load_trial_tracking()
        user_id = str(query.from_user.id)
        
        if user_id in tracking:
            trial_info = tracking[user_id]
            if isinstance(trial_info, dict):
                old_link = trial_info.get('link', '')
            else:
                # Fallback for old format
                old_link = trial_info

            # 1. Edit existing message (Warning)
            await query.edit_message_text(
                "⚠️ <b>လူကြီးမင်းသည် Free Trial ရယူပြီးသား ဖြစ်ပါသည်။</b>\n\n"
                "👇 <b>လူကြီးမင်း၏ Key အဟောင်း:</b>",
                parse_mode='HTML'
            )
            
            # 2. Send Key (Isolated)
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"<code>{old_link}</code>",
                parse_mode='HTML'
            )

            # 3. Send Instructions + Upsell
            final_msg = (
                "👆 <b>Key ကို Copy ယူပါ။</b>\n\n"
                "အသုံးပြုနည်းကြည့်ရန် /start ကိုနှိပ်ပြီး\n"
                "'❓ ဘယ်လိုသုံးရမလဲ' ကို ရွေးပါ။\n\n"
                "💡 <b>Free Trial သက်တမ်းကုန်ဆုံးပါက Premium ဝယ်ယူအသုံးပြုနိုင်ပါသည်။</b>"
            )
            upsell_kb = [[InlineKeyboardButton("💎 1 လစာ (100Gb) ဝယ်ယူမယ်", callback_data='buy_premium')]]
            
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=final_msg,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(upsell_kb)
            )
            return

        await query.edit_message_text("⚙️ <b>Key ထုတ်ပေးနေပါသည်... ခဏစောင့်ပါ...</b>", parse_mode='HTML')

        candidate_servers = get_round_robin_servers()
        logging.info(f"Round-robin candidates for free trial: {[s.get('name') for s in candidate_servers]}")

        if not candidate_servers:
            await query.edit_message_text(
                "❌ Server မရရှိနိုင်သေးပါ။ နောက်အကြိမ်စမ်းကြည့်ပါ။",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]])
            )
            return
            
        # Generate on round-robin server order
        try:
            username = f"FreeTrial_{query.from_user.id}"
            selected_server = None
            link = None
            existed = False

            for server in candidate_servers:
                try:
                    client = XUIClient(server)
                    result = client.add_client(email=username, limit_gb=2, expire_days=1)
                    if isinstance(result, tuple):
                        link, existed = result
                    else:
                        link = result
                        existed = False

                    if link:
                        selected_server = server
                        break
                except Exception as server_error:
                    logging.warning(f"Free trial generation failed on {server.get('name')}: {server_error}")
            
            if link:
                if existed:
                    # User already has a free trial - update tracking with current timestamp
                    if user_id not in tracking:
                        tracking[user_id] = {
                            "link": link,
                            "timestamp": int(time.time()),
                            "trial_type": "free",
                            "email": username,
                            "server_name": selected_server.get('name')
                        }
                        save_trial_tracking(tracking)

                    await query.edit_message_text(
                        "⚠️ <b>လူကြီးမင်းသည် အရင်ကပဲ Free Trial ရယူထားပြီးပါပြီ။</b>\n\n"
                        "❗️ မကြာခဏ Free Trial ထပ်မံပေးမည်မဟုတ်ပါ။\n"
                        "👇 <b>လူကြီးမင်း၏ ရှိပြီးသား Key:</b>",
                        parse_mode='HTML'
                    )
                    await context.bot.send_message(chat_id=query.message.chat_id, text=f"`{link}`", parse_mode='MarkdownV2')
                    return

                # New key issued - save with timestamp
                tracking[user_id] = {
                    "link": link,
                    "timestamp": int(time.time()),
                    "trial_type": "free",
                    "email": username,
                    "server_name": selected_server.get('name')
                }
                save_trial_tracking(tracking)

                await query.edit_message_text(
                    "✅ <b>အောင်မြင်ပါတယ်!</b>\n\n"
                    f"Server: {selected_server.get('name')}\n"
                    "လူကြီးမင်း၏ 24-နာရီ Free Trial Key (2GB):\n"
                    "👇 <b>အောက်ပါ Vpn Key Copy ကူးယူပါ:</b>",
                    parse_mode='HTML'
                )
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"`{link}`",
                    parse_mode='MarkdownV2'
                )
                # Combined Instructions + Upsell
                final_msg = (
                    "👆 <b>Key ကို Copy ယူပါ။</b>\n\n"
                    "အသုံးပြုနည်းကြည့်ရန် /start ကိုနှိပ်ပြီး\n"
                    "'❓ ဘယ်လိုသုံးရမလဲ' ကို ရွေးပါ။\n\n"
                    "💡 <b>Free Trial သက်တမ်းကုန်ဆုံးပါက Premium ဝယ်ယူအသုံးပြုနိုင်ပါသည်။</b>"
                )
                upsell_kb = [[InlineKeyboardButton("💎 1 လစာ (100Gb) ဝယ်ယူမယ်", callback_data='buy_premium')]]
                
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=final_msg,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(upsell_kb)
                )
            else:
                logging.error(f"Link generation failed on {selected_server.get('name')}")
                await query.edit_message_text("❌ Error: Server returned no link. Please contact admin.")
                
        except Exception as e:
            logging.error(f"Detailed Error: {e}")
            await query.edit_message_text(f"❌ System Error: {str(e)[:50]}...")


    elif query.data == 'renew_key':
        context.user_data['state'] = 'awaiting_renew_key'
        msg = (
            "🔄 <b>Key သက်တမ်းတိုးခြင်း</b>\n\n"
            "လူကြီးမင်း၏ ရှိပြီးသား <b>VLESS Key</b> ကို ပေးပို့ပါ။\n"
            "Bot မှ Key ရှိမရှိ စစ်ဆေးပြီး ငွေပေးချေရန်နောက်တစ်ဆင့် ပြသပါမည်။\n\n"
            "<i>(Key အစအဆုံး <code>vless://...</code> မှစ၍ Copy ကူးထည့်ပါ)</i>"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]]
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif query.data == 'buy_premium':
        # Payment Instructions
        msg = (
            "💎 <b>1လစာ ဝယ်ယူမည်</b>\n\n"
            "အောက်ပါ KPay အကောင့်သို့ <b>5,000 Ks</b> လွှဲပေးပါ။\n\n"
            "📞 <b>09799881201</b> (Daw Tin Tin Yee)\n"
            "📝 Note နေရာတွင် <code>Payment</code> လို့ပဲထည့်ပေးပါနော် တခြားဘာမှမထည့်ပါနဲ့ဗျ\n\n"
            "✅ <b>ငွေလွှဲပြီးပါက ငွေလွှဲပြေစာ (Slip) ဓာတ်ပုံကို ဒီ Bot သို့ ပို့ပေးပါ။ စစ်ဆေးပြီး Key ပို့ပေးပါမည်။</b>\n",
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]]
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == 'help':
        text = "❓ <b>အသုံးပြုလိုသော Device ကို ရွေးချယ်ပါ:</b>"
        keyboard = [
            [InlineKeyboardButton("🤖 Android", callback_data='guide_android')],
            [InlineKeyboardButton("🍏 iOS (iPhone/iPad)", callback_data='guide_ios')],
            [InlineKeyboardButton("💻 PC (Computer)", callback_data='guide_pc')],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]
        ]
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data in ['guide_android', 'guide_ios', 'guide_pc']:
        device = "Android" if "android" in query.data else "iOS" if "ios" in query.data else "PC"
        
        # Guide Content
        if device == "Android":
            # Step 1: Install
            caption1 = "<b>အဆင့် (၁) - Install V2Box</b>\n\nPlayStore မှ <b>V2Box - V2ray Client</b> ကို ရှာပြီး Install လုပ်ပါ။"
            try:
                with open('images/android_1.jpg', 'rb') as photo:
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=photo,
                        caption=caption1,
                        parse_mode='HTML'
                    )
            except FileNotFoundError:
                pass

            # Step 2: Import & Connect
            caption2 = "<b>အဆင့် (၂) - Import & Connect</b>\n\nအရင်ဦးဆုံး ပေးပို့ထားသော VPN Key ကို Telegram မှ Copy ယူပါ။\n\nV2Box App ထဲသို့ဝင်ပြီး ပုံပါအတိုင်း တစ်ဆင့်ခြင်းစီ ပြုလုပ်ပြီးပါက အသုံးပြုနိုင်ပါပြီ။"
            try:
                with open('images/android_2.jpg', 'rb') as photo:
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=photo,
                        caption=caption2,
                        parse_mode='HTML'
                    )
            except FileNotFoundError:
                pass
        elif device == "iOS":
            # Step 1: Install
            caption1 = "<b>အဆင့် (၁) - Install V2Box</b>\n\nAppStore မှ <b>V2Box - V2ray Client</b> ကို ရှာပြီး Install လုပ်ပါ။"
            try:
                with open('images/ios_1.jpg', 'rb') as photo:
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=photo,
                        caption=caption1,
                        parse_mode='HTML'
                    )
            except FileNotFoundError:
                pass

            # Step 2: Import & Connect
            caption2 = "<b>အဆင့် (၂) - Import & Connect</b>\n\nအရင်ဦးဆုံး ပေးပို့ထားသော VPN Key ကို Telegram မှ Copy ယူပါ။\n\nV2Box App ထဲသို့ဝင်ပြီး ပုံပါအတိုင်း တစ်ဆင့်ခြင်းစီ ပြုလုပ်ပြီးပါက အသုံးပြုနိုင်ပါပြီ။"
            try:
                with open('images/ios_2.jpg', 'rb') as photo:
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=photo,
                        caption=caption2,
                        parse_mode='HTML'
                    )
            except FileNotFoundError:
                pass
        else:
            msg = f"<b>{device} အသုံးပြုနည်းလမ်းညွှန်</b>\n\n(ပုံနှင့်တကွ ရှင်းပြချက်များကို Admin မှ မကြာမီ ထည့်သွင်းပေးပါမည်။)"
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='help')]]
            await query.edit_message_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Add Back button separately for photo message
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='help')]]
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="နောက်သို့ပြန်သွားရန်:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == 'check_quota':
        msg = (
            "📊 <b>Data လက်ကျန်စစ်ဆေးရန်</b>\n\n"
            " <b>VLESS Key</b> ကို ဤနေရာသို့ ပေးပို့လိုက်ပါ။\n\n"
            "<i>(Key အစအဆုံး <code>vless://...</code> မှ စပြီး Copy ကူးထည့်ပါ)</i>"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]]
        
        # Force send new message (Avoid Edit conflicts)
        await query.answer()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=msg,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif query.data == 'main_menu':
        # Re-send the start message
        text = (
            "<b>မင်္ဂလာပါ @PayIfYouLike မှ ကြိုဆိုပါတယ်!</b> 🇲🇲\n\n"
            "အင်တာနက်လိုင်း ကောင်းမွန်ပြီး လုံခြုံစိတ်ချရတဲ့ VPN ကို ရှာနေပါသလား?\n"
            "လူကြီးမင်းအတွက် အကောင်းဆုံး ဝန်ဆောင်မှုပေးဖို့ အသင့်ရှိပါတယ်။\n\n"
            "👇 <b>ဘာလုပ်ချင်ပါသလဲ ရွေးချယ်ပေးပါခင်ဗျာ:</b>"
        )
        keyboard = [
            [InlineKeyboardButton("🚀 Free စမ်းသုံးမယ် (24 Hours)", callback_data='get_free')],
            [InlineKeyboardButton("💎 1 လစာ (100Gb) ဝယ်ယူမယ်", callback_data='buy_premium')],
            [InlineKeyboardButton("📊 Data လက်ကျန်စစ်မယ်", callback_data='check_quota')],
            [InlineKeyboardButton("❓ ဘယ်လိုသုံးရမလဲ", callback_data='help')]
        ]
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

# --- ADMIN COMMANDS ---

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔️ Access Denied.")
        return

    keyboard = [
        [InlineKeyboardButton("➕ Generate 1 Month Key", callback_data='admin_gen_1m')],
        [InlineKeyboardButton("⚡️ Generate Trial Key", callback_data='admin_gen_trial')],
        [InlineKeyboardButton("� Extend a Key (No Payment)", callback_data='admin_extend_key')],
        [InlineKeyboardButton("�🖥️ Server Status", callback_data='admin_status')],
        [InlineKeyboardButton("🔌 Add New Server", callback_data='admin_add_server')]
    ]
    await update.message.reply_text("👑 <b>Admin Control Panel</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CONFIG, SERVERS
    query = update.callback_query
    await query.answer()
    
    # Cancel button handler
    if query.data == 'admin_cancel':
        context.user_data.clear()
        await query.edit_message_text("❌ Cancelled.", parse_mode='HTML')
        return

    if query.data.startswith('admin_gen'):
        # Step 1: Save intent (1m or trial)
        context.user_data['temp_gen_type'] = "1m" if "1m" in query.data else "trial"
        
        # Step 2: Show Server List
        keyboard = []
        for i, s in enumerate(SERVERS):
            name = s.get('name', f"Server {i+1}")
            keyboard.append([InlineKeyboardButton(f"🖥 {name}", callback_data=f'admin_sel_srv_{i}')])
        
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='admin_cancel')])
        await query.edit_message_text("👉 <b>Select Server:</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif query.data.startswith('admin_sel_srv_'):
        # Step 3: Server selected, now ask for username
        idx = int(query.data.split('_')[-1])
        context.user_data['gen_server_idx'] = idx
        # Promote temp intent to actual active state
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

    elif query.data == 'admin_extend_key':
        context.user_data['gen_type'] = 'extend_key'
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='admin_cancel')]]
        await query.edit_message_text(
            "🔄 <b>Extend a Key (No Payment)</b>\n\n"
            "ချဲ့ထွင်လိုသော <b>VLESS Key</b> ကို ပေးပို့ပါ။\n"
            "Bot မှ အလိုအလျောက် Traffic reset + 30 ရက် သက်တမ်းတိုးပေးပါမည်။\n\n"
            "<i>(vless://... key အပြည့်အစုံ ကူးထည့်ပါ)</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif query.data == 'admin_add_server':
        context.user_data['gen_type'] = "add_server"
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='admin_cancel')]]
        await query.edit_message_text(
            "🖥️ <b>Add New Server</b>\n\n"
            "Send the details in this exact format:\n\n"
            "<code>URL|Username|Password|InboundID</code>\n\n"
            "Example:\n"
            "<code>https://1.2.3.4:2053/panel/|admin|pass123|1</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif query.data == 'admin_status':
        # Check all servers
        msg = "🖥️ <b>Server Status:</b>\n\n"
        for idx, s in enumerate(SERVERS):
            try:
                # Simple reachability check (login)
                client = XUIClient(s)
                status = "✅ Online"
            except:
                status = "❌ Offline"
            msg += f"Server {idx+1}: {status}\n"
        
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='admin_back')]]
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == 'admin_back':
        # Show main admin menu again
        keyboard = [
            [InlineKeyboardButton("➕ Generate 1 Month Key", callback_data='admin_gen_1m')],
            [InlineKeyboardButton("⚡️ Generate Trial Key", callback_data='admin_gen_trial')],
            [InlineKeyboardButton("🖥️ Server Status", callback_data='admin_status')]
        ]
        await query.edit_message_text("👑 <b>Admin Control Panel</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CONFIG, SERVERS
    text = update.message.text.strip()

    # Check for "Back to Start" button
    if text == "အစသို့ပြန်သွားပါ":
        await start(update, context)
        return

    # ── User renewal: waiting for VLESS key ───────────────────────────────────
    if context.user_data.get('state') == 'awaiting_renew_key':
        if not text.startswith('vless://'):
            await update.message.reply_text(
                "⚠️ VLESS Key ပုံစံမှားနေပါသည်။\n"
                "<code>vless://</code> ဖြင့် စသောKey ကိုသာ ပေးပို့ပါ။",
                parse_mode='HTML'
            )
            return

        status_msg = await update.message.reply_text("🔍 Key စစ်ဆေးနေပါသည်...", parse_mode='HTML')
        import re
        match = re.search(r'vless://([a-f0-9\-]+)@', text)
        if not match:
            await status_msg.edit_text("❌ Key ပုံစံ မမှန်ကန်ပါ (UUID မတွေ့ရပါ)။")
            return

        target_uuid = match.group(1)
        server_obj, xui, email = find_client_by_uuid(target_uuid)

        if not server_obj:
            await status_msg.edit_text(
                "❌ ဤ Key ကို Server ပေါ်တွင် မတွေ့ရှိပါ။\n"
                "Key မှန်မှန်ကန်ကန် ထည့်ပေးပါ သို့မဟုတ် Admin ကိုဆက်သွယ်ပါ။"
            )
            return

        # Key is valid — store info and ask for payment slip
        context.user_data['state']      = 'awaiting_renew_slip'
        context.user_data['renew_info'] = {
            'uuid':        target_uuid,
            'email':       email,
            'server_name': server_obj.get('name', ''),
        }
        context.user_data.pop('state', None)   # will be re-set below
        context.user_data['state'] = 'awaiting_renew_slip'

        await status_msg.edit_text(
            f"✅ <b>Key တွေ့ပါသည်!</b>\n\n"
            "💳 <b>ငွေပေးချေရန်</b>\n"
            "အောက်ပါ KPay အကောင့်သို့ <b>5,000 Ks</b> လွှဲပေးပါ။\n\n"
            "📞 <b>09799881201</b> (Daw Tin Tin Yee)\n"
            "📝 Note နေရာတွင် <code>Payment</code> လို့ပဲထည့်ပေးပါနော် တခြားဘာမှမထည့်ပါနဲ့ဗျ\n\n"
            "✅ <b>ငွေလွှဲပြီးပါက ငွေလွှဲပြေစာ (Slip) ဓာတ်ပုံကို ဒီ Bot သို့ ပို့ပေးပါ။ Admin မှ စစ်ဆေးပြီး Key သက်တမ်းတိုးပေးပါမည်။</b>\n",
            parse_mode='HTML'
        )
        return

    # ── Admin direct extend: waiting for VLESS key ────────────────────────────
    if context.user_data.get('gen_type') == 'extend_key':
        if not text.startswith('vless://'):
            await update.message.reply_text("⚠️ Please send a valid <code>vless://</code> key.", parse_mode='HTML')
            return

        context.user_data['gen_type'] = None
        status_msg = await update.message.reply_text("🔍 Searching...", parse_mode='HTML')
        import re
        match = re.search(r'vless://([a-f0-9\-]+)@', text)
        if not match:
            await status_msg.edit_text("❌ Invalid key format (UUID not found).")
            return

        target_uuid = match.group(1)
        server_obj, xui, email = find_client_by_uuid(target_uuid)

        if not xui:
            await status_msg.edit_text("❌ Key not found on any server.")
            return

        await status_msg.edit_text("⚙️ Extending...")
        success, result = xui.reset_and_extend_client(target_uuid)

        if success:
            await status_msg.edit_text(
                f"✅ <b>Extended Successfully!</b>\n\n"
                f"👤 Email: <code>{email}</code>\n"
                f"🖥 Server: {server_obj.get('name')}\n"
                f"📅 New Expiry: {result}\n"
                "📦 Traffic reset to 0 · 100 GB quota restored",
                parse_mode='HTML'
            )
        else:
            await status_msg.edit_text(f"❌ Failed: {result}")
        return

    # ── Generic VLESS key → Quota Check ───────────────────────────────────────
    if text.startswith("vless://"):
        try:
            status_msg = await update.message.reply_text("🔍 <b>ရှာဖွေနေပါသည်...</b>", parse_mode='HTML')
        except Exception as e:
            logging.error(f"Reply failed: {e}")
            return
        
        # Extract UUID
        try:
            # Format: vless://UUID@...
            import re
            match = re.search(r'vless://([a-f0-9\-]+)@', text)
            if not match:
                await status_msg.edit_text("❌ Key ပုံစံမှားယွင်းနေပါသည်။")
                return
            
            target_uuid = match.group(1)
            found = False
            
            # Scan all servers
            for s in SERVERS:
                try:
                    # Just use simple timeout, no complex logic
                    client = XUIClient(s)
                    # We need to manually add get_client_stats here if it's missing in older cached version
                    # But assuming XUIClient has it now
                    stats = client.get_client_stats(target_uuid)
                    
                    if stats:
                        found = True
                        # Calculate Data
                        total = stats['total']
                        used = stats['up'] + stats['down']
                        left = total - used
                        
                        # Helper for formatting bytes
                        def sizeof_fmt(num, suffix="B"):
                            for unit in ["", "Ki", "Mi", "Gi", "Ti"]:
                                if abs(num) < 1024.0:
                                    return f"{num:3.1f} {unit}{suffix}"
                                num /= 1024.0
                            return f"{num:.1f} Yi{suffix}"

                        # Calculate Days
                        import time
                        from datetime import datetime
                        if stats['expiry'] > 0:
                            # Convert expiry timestamp (ms) to date
                            expiry_ts = stats['expiry'] / 1000
                            expiry_date = datetime.fromtimestamp(expiry_ts).strftime('%Y-%m-%d %H:%M')
                            # User requested date ONLY
                            days_str = expiry_date
                        else:
                            days_str = "Unlimited"

                        msg = (
                            f"📊 <b>အကောင့်အခြေအနေ</b>\n\n"
                            f"👤 <b>Name:</b> {stats['email']}\n"
                            f"🖥 <b>Server:</b> {s.get('name')}\n"
                            f"🔋 <b>Status:</b> {'✅ Active' if stats['enable'] and days_str != 'Expired' else '❌ Disabled'}\n\n"
                            f"📦 <b>Total:</b> {sizeof_fmt(total)}\n"
                            f"📉 <b>Used:</b> {sizeof_fmt(used)}\n"
                            f"📈 <b>Remaining:</b> {sizeof_fmt(left)}\n\n"
                            f"⏳ <b>Expires:</b> {days_str}"
                        )
                        
                        await status_msg.edit_text(msg, parse_mode='HTML')
                        break # Stop searching
                except Exception as e:
                    logging.error(f"Error checking server {s.get('name')}: {e}")
                    continue
            
            if not found:
                await status_msg.edit_text("❌ Server ပေါ်တွင် ဤ Key ကိုမတွေ့ရှိပါ။")
                
        except Exception as e:
            logging.error(f"Quota Check Error: {e}")
            await status_msg.edit_text("❌ Error checking quota.")
        return
    if context.user_data.get('gen_type') == 'add_server':
        raw = update.message.text
        try:
            # Try parsing raw X-UI install script output
            if "Access URL:" in raw:
                import re
                try:
                    user = re.search(r'Username:\s*(\S+)', raw).group(1)
                    pwd = re.search(r'Password:\s*(\S+)', raw).group(1)
                    url = re.search(r'Access URL:\s*(\S+)', raw).group(1)
                    iid = 1 # Default to 1 for fresh servers
                except AttributeError:
                    raise ValueError("Could not find Username, Password, or URL in the text.")
            else:
                # Fallback to pipe format: URL|User|Pass|ID
                url, user, pwd, iid = raw.split('|')

            new_server = {
                "name": f"Server {len(SERVERS)+1}",
                "panel_url": url.strip(),
                "username": user.strip(),
                "password": pwd.strip(),
                "inbound_id": int(str(iid).strip()),
                "flow_limit_gb": 100,
                "expire_days": 30
            }
            SERVERS.append(new_server)
            
            # Save to config.json
            CONFIG['servers'] = SERVERS
            with open('../config.json', 'w') as f:
                json.dump(CONFIG, f, indent=4)
                
            await update.message.reply_text(
                f"✅ <b>Server Added!</b>\n"
                f"Name: {new_server['name']}\n"
                f"URL: {new_server['panel_url']}\n"
                f"Inbound ID: {new_server['inbound_id']} (Default)",
                parse_mode='HTML'
            )
            context.user_data['gen_type'] = None
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Invalid Format. Error: {e}\n\nTry format: URL|User|Pass|ID")
            return

    # Check if waiting for username input from Admin
    if context.user_data.get('gen_type'):
        username = update.message.text
        gen_type = context.user_data['gen_type']
        
        # Clear state
        context.user_data['gen_type'] = None
        
        limit_gb = 100 if gen_type == "1m" else 2
        days = 30 if gen_type == "1m" else 1
        
        status_msg = await update.message.reply_text("⚙️ Generating...")
        
        try:
            # Use selected server
            server_idx = context.user_data.get('gen_server_idx', 0)
            target_server = SERVERS[server_idx] if server_idx < len(SERVERS) else SERVERS[0]
            
            client = XUIClient(target_server)
            result = client.add_client(email=username, limit_gb=limit_gb, expire_days=days)
            if isinstance(result, tuple):
                link, existed = result
            else:
                link = result
                existed = False
            
            if link:
                msg = (
                    f"✅ <b>Key Generated!</b>\n\n"
                    f"Server: {target_server.get('name')}\n"
                    f"Name: {username}\n"
                    f"Limit: {limit_gb} GB\n"
                    f"Days: {days}\n\n"
                    f"<code>{link}</code>"
                )
                if existed:
                    msg += "\n\n⚠️ Note: Existing key returned (duplicate)."
                await status_msg.edit_text(msg, parse_mode='HTML')
            else:
                await status_msg.edit_text("❌ Failed. Name might duplicate.")
        except Exception as e:
            await status_msg.edit_text(f"❌ Error: {e}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document uploads (payment slips sent as files)"""
    user = update.message.from_user
    
    # Check if document is an image
    if update.message.document.mime_type and 'image' in update.message.document.mime_type:
        document_file = await update.message.document.get_file()

        # ── Renewal slip (file) ────────────────────────────────────────────────
        if context.user_data.get('state') == 'awaiting_renew_slip':
            renew_info = context.user_data.get('renew_info', {})
            context.user_data.pop('state', None)
            context.user_data.pop('renew_info', None)

            context.bot_data.setdefault('renew_pending', {})[str(user.id)] = renew_info

            await update.message.reply_text(
                "⏳ <b>ငွေလွှဲပြေစာကို Admin သို့ ပေးပို့ပြီးပါပြီ။</b>\n\n"
                "Admin မှ စစ်ဆေးပြီးပါက Key သက်တမ်း အလိုအလျောက် တိုးပေးပါမည်。\n"
                "Admin ကိုဆက်သွယ်ရန် @payifyoulike",
                parse_mode='HTML',
                reply_markup=MAIN_MENU_KB
            )
            caption = (
                f"🔄 <b>Key Renewal Slip (File)!</b>\n\n"
                f"👤 User: {user.full_name} (ID: <code>{user.id}</code>)\n"
                f"🔗 <a href='tg://user?id={user.id}'>Chat with User</a>\n\n"
                f"📋 <b>Email:</b> <code>{renew_info.get('email', 'N/A')}</code>\n"
                f"🖥 <b>Server:</b> {renew_info.get('server_name', 'N/A')}"
            )
            keyboard = [[
                InlineKeyboardButton("✅ Approve Renewal", callback_data=f'rnw_ok_{user.id}'),
                InlineKeyboardButton("❌ Decline",         callback_data=f'rnw_no_{user.id}')
            ]]
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_document(
                        chat_id=admin_id, document=document_file.file_id,
                        caption=caption, parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as e:
                    logging.error(f"Failed to send renewal doc to admin {admin_id}: {e}")
            return

        # ── New purchase slip (file) ───────────────────────────────────────────
        await update.message.reply_text(
            "⏳ <b>ငွေလွှဲပြေစာကို Admin သို့ ပေးပို့ထားပါသည်။</b>\n\n"
            "Admin မှ စစ်ဆေးပြီးပါက Key အလိုအလျောက် ရောက်ရှိလာပါမည်။ ခေတ္တစောင့်ဆိုင်းပေးပါ။\n\n"
            "Admin ကိုဆက်သွယ်ရန် နှိပ်ပါ 👇\n@payifyoulike",
            parse_mode='HTML',
            reply_markup=MAIN_MENU_KB
        )
        caption = (
            f"📩 <b>New Payment Slip (File)!</b>\n\n"
            f"👤 User: {user.full_name} (ID: <code>{user.id}</code>)\n"
            f"🔗 <a href='tg://user?id={user.id}'>Chat with User</a>"
        )
        keyboard = [[
            InlineKeyboardButton("✅ Approve", callback_data=f'approve_{user.id}'),
            InlineKeyboardButton("❌ Decline", callback_data=f'decline_{user.id}')
        ]]
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_document(
                    chat_id=admin_id,
                    document=document_file.file_id,
                    caption=caption,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                logging.info(f"Sent document approval to admin {admin_id}")
            except Exception as e:
                logging.error(f"Failed to send document to admin {admin_id}: {e}")
    else:
        await update.message.reply_text("❌ Image files only, please. (PNG, JPG, etc.)")

def main():
    app = Application.builder().token(CONFIG['bot_token']).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(button_handler, pattern='^(get_|buy_|renew_|help|guide_|main_|check_)'))
    app.add_handler(CallbackQueryHandler(approval_handler, pattern='^(approve_|decline_|rnw_ok_|rnw_no_)'))
    app.add_handler(CallbackQueryHandler(admin_handler, pattern='^admin_'))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Centralized error handler
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        try:
            logging.exception("Exception while handling an update", exc_info=context.error)
        except Exception:
            logging.exception("Exception in error handler")

        err = getattr(context, 'error', None)
        if err and isinstance(err, telegram.error.Conflict):
            logging.error("Conflict: terminated by other getUpdates request; ensure only one bot instance is running or switch to webhooks.")

    app.add_error_handler(error_handler)
    
    # Add periodic cleanup job for expired free trials (every hour)
    job_queue = app.job_queue
    if job_queue is not None:
        job_queue.run_repeating(
            cleanup_expired_trials,
            interval=3600,  # 1 hour
            first=10,  # Start after 10 seconds
            name='cleanup_expired_trials'
        )
        logging.info("✅ Scheduled cleanup_expired_trials job to run every hour")
    else:
        logging.warning("⚠️  JobQueue not available. Install via: pip install 'python-telegram-bot[job-queue]'. Cleanup task will NOT run.")
    
    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()