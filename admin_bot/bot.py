import logging
import json
import uuid
import secrets
import string
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
import telegram
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# --- CONFIGURATION ---
def load_config():
    with open('../config.json', 'r') as f:
        return json.load(f)

CONFIG = load_config()
# Use specific admin token if available in root config, else legacy
CONFIG['bot_token'] = CONFIG.get('admin_bot_token', '8408777363:AAGgMfiFZidu55AmeQTMtLLHU6xAuE7EY4g')

SERVERS = CONFIG['servers']
ADMIN_IDS = CONFIG['admin_ids']

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

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

    def add_client(self, email, limit_gb=0, expire_days=0):
        list_url = f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}"
        try:
            r = self.session.get(list_url, verify=False)
            if not r.json().get('success'):
                self.login()
                r = self.session.get(list_url, verify=False)
            
            inbound = r.json()['obj']
            settings = json.loads(inbound['settings'])
            stream_settings = json.loads(inbound['streamSettings'])
            
            new_uuid = str(uuid.uuid4())
            sub_id = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(16))
            
            expiry_time = 0
            if expire_days > 0:
                import time
                expiry_time = int((time.time() * 1000) + (expire_days * 86400 * 1000))

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

            add_url = f"{self.base_url}/panel/api/inbounds/addClient"
            r = self.session.post(add_url, json=client_data, verify=False)
            
            if r.json().get('success'):
                reality = stream_settings['realitySettings']
                pbk = reality['settings']['publicKey']
                sni = reality['serverNames'][0]
                sid = reality['shortIds'][0]
                remark = email
                ip = self.base_url.split('://')[1].split(':')[0]
                port = inbound['port']
                
                link = (f"vless://{new_uuid}@{ip}:{port}"
                        f"?type=tcp&security=reality&pbk={pbk}&fp=chrome"
                        f"&sni={sni}&sid={sid}&spx=%2F&flow=xtls-rprx-vision#{remark}")
                return link
            else:
                return None
        except Exception as e:
            logging.error(f"XUI Client Error: {e}")
            return None

# --- TELEGRAM BOT LOGIC ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔️ This bot is for Admins only.")
        return

    keyboard = [
        [InlineKeyboardButton("➕ Generate 1 Month Key", callback_data='admin_gen_1m')],
        [InlineKeyboardButton("⚡️ Generate Trial Key", callback_data='admin_gen_trial')],
        [InlineKeyboardButton("⚙️ Manage Servers", callback_data='admin_manage_menu')],
        [InlineKeyboardButton("🔌 Add New Server", callback_data='admin_add_server')]
    ]
    await update.message.reply_text("👑 <b>Admin Control Panel</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ensure we modify the module-level config and servers
    global CONFIG, SERVERS

    query = update.callback_query
    await query.answer()
    
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
        
        # Details
        msg = (
            f"🖥 <b>{s.get('name')}</b>\n\n"
            f"🔗 <b>URL:</b> <code>{s.get('panel_url')}</code>\n"
            f"🔌 <b>Status:</b> {'✅ Enabled' if is_enabled else '❌ Disabled'}\n"
            f"⭐️ <b>Priority:</b> {'High (Default)' if is_default else 'Normal'}\n"
        )
        
        # Actions
        keyboard = []
        
        # Toggle Enable/Disable
        toggle_txt = "🔴 Disable" if is_enabled else "🟢 Enable"
        keyboard.append([InlineKeyboardButton(toggle_txt, callback_data=f'toggle_srv_{idx}')])
        
        # Set Default
        if not is_default:
            keyboard.append([InlineKeyboardButton("⭐️ Set as Default", callback_data=f'set_def_{idx}')])
            
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
                "expire_days": 30
            }
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
    app = Application.builder().token(CONFIG['bot_token']).build()
    app.add_handler(CommandHandler("start", start))
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