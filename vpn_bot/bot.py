import logging
import json
import uuid
import secrets
import string
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# --- CONFIGURATION ---
with open('config.json', 'r') as f:
    CONFIG = json.load(f)

SERVERS = CONFIG['servers']
ADMIN_IDS = CONFIG['admin_ids']
MAIN_MENU_KB = ReplyKeyboardMarkup([['အစသို့ပြန်သွားပါ']], resize_keyboard=True)

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
        # Handle 'vless://' link in panel_url (sometimes passed mistakenly as panel_url)
        if "vless://" in self.base_url:
            logging.error("Invalid Panel URL (vless link detected). Check config.json")
            return None

        # Standard Logic
        list_url = f"{self.base_url}/panel/api/inbounds/get/{self.inbound_id}"
        r = self.session.get(list_url, verify=False)
        if not r.json().get('success'):
            self.login() # Retry login
            r = self.session.get(list_url, verify=False)
        
        inbound = r.json()['obj']
        settings = json.loads(inbound['settings'])
        stream_settings = json.loads(inbound['streamSettings'])
        
        # 2. Prepare new client
        new_uuid = str(uuid.uuid4())
        # Generate random subId (16 chars)
        sub_id = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(16))
        
        # Calculate expiry
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
                    "flow": "xtls-rprx-vision", # Critical for Reality
                    "totalGB": limit_gb * 1024 * 1024 * 1024,
                    "expiryTime": expiry_time,
                    "enable": True,
                    "tgId": "",
                    "subId": sub_id,
                    "limitIp": 1
                }]
            })
        }

        # 3. Add Client API Call
        add_url = f"{self.base_url}/panel/api/inbounds/addClient"
        r = self.session.post(add_url, json=client_data, verify=False)
        
        if r.json().get('success'):
            # 4. Generate VLESS Link (Manual Construction for Reality)
            # Typically: vless://uuid@ip:port?type=tcp&security=reality&pbk=...&fp=chrome&sni=...&sid=...&spx=%2F&flow=xtls-rprx-vision#Name
            
            # Extract Reality Configs
            reality = stream_settings['realitySettings']
            pbk = reality['settings']['publicKey']
            sni = reality['serverNames'][0]
            sid = reality['shortIds'][0]
            
            # Construct Link
            remark = email
            ip = self.base_url.split('://')[1].split(':')[0]
            port = inbound['port']
            
            link = (f"vless://{new_uuid}@{ip}:{port}"
                    f"?type=tcp&security=reality&pbk={pbk}&fp=chrome"
                    f"&sni={sni}&sid={sid}&spx=%2F&flow=xtls-rprx-vision#{remark}")
            
            return link
        else:
            logging.error(f"Failed to add client: {r.text}")
            return None

from datetime import datetime, timedelta
import re

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
        [InlineKeyboardButton("❓ ဘယ်လိုသုံးရမလဲ", callback_data='help')]
    ]
    await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Process only if photo sent
    user = update.message.from_user
    photo_file = await update.message.photo[-1].get_file()
    
    # Notify user: pending check
    await update.message.reply_text(
        "⏳ <b>ငွေလွှဲပြေစာကို Admin သို့ ပေးပို့ထားပါသည်။</b>\n\n"
        "Admin မှ စစ်ဆေးပြီးပါက Key အလိုအလျောက် ရောက်ရှိလာပါမည်။ ခေတ္တစောင့်ဆိုင်းပေးပါ။\n\n"
        "Admin ကိုဆက်သွယ်ရန် နှိပ်ပါ 👇\n@payifyoulike",
        parse_mode='HTML',
        reply_markup=MAIN_MENU_KB
    )

    # Forward to Admins with Buttons
    caption = (
        f"📩 <b>New Payment Slip!</b>\n\n"
        f"👤 User: {user.full_name} (ID: <code>{user.id}</code>)\n"
        f"🔗 <a href='tg://user?id={user.id}'>Chat with User</a>"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f'approve_{user.id}'),
            InlineKeyboardButton("❌ Decline", callback_data=f'decline_{user.id}')
        ]
    ]
    
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
    query = update.callback_query
    await query.answer()
    
    data = query.data
    action, user_id = data.split('_')
    user_id = int(user_id)
    
    if action == 'approve':
        # Reconstruct caption with link
        old_text = query.message.caption
        # Try to extract Name and ID. Format: 📩 New Payment Slip!\n\n👤 User: {name} (ID: {id})...
        import re
        try:
            match = re.search(r"User: (.+) \(ID: (\d+)\)", old_text)
            if match:
                user_name = match.group(1)
                # user_id is already known from callback_data
            else:
                user_name = "User"
        except:
            user_name = "User"

        new_caption = (
            f"📩 <b>New Payment Slip!</b>\n\n"
            f"👤 User: {user_name} (ID: <code>{user_id}</code>)\n"
            f"🔗 <a href='tg://user?id={user_id}'>Chat with User</a>\n\n"
            f"✅ <b>APPROVED</b>"
        )

        try:
            await query.edit_message_caption(
                caption=new_caption,
                parse_mode='HTML'
            )
        except Exception as e:
            logging.warning(f"Caption edit failed: {e}")
        
        # Generate Key
        try:
            # Load Balancing Logic
            target_server = SERVERS[CONFIG.get('default_server_id', 0)]
            min_clients = 99999
            for s in SERVERS:
                try:
                    temp_c = XUIClient(s)
                    # Simplified check
                    list_url = f"{temp_c.base_url}/panel/api/inbounds/get/{temp_c.inbound_id}"
                    r = temp_c.session.get(list_url, verify=False, timeout=5)
                    if r.json().get('success'):
                        count = len(json.loads(r.json()['obj']['settings'])['clients'])
                        if count < min_clients:
                            min_clients = count
                            target_server = s
                except:
                    continue
            
            client = XUIClient(target_server)
            username = f"Premium_{user_id}_{secrets.token_hex(2)}"
            link = client.add_client(email=username, limit_gb=100, expire_days=30)
            
            if link:
                # Send to User (1. Info)
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"✅ <b>ငွေလွှဲအောင်မြင်ပါသည်။</b>\n\n"
                        f"💎 <b>Premium Key (1 Month / 100GB):</b>\n"
                        f"Server: {target_server.get('name')}\n"
                        "👇 <b>အောက်ပါ Key ကို Copy ယူပါ:</b>"
                    ),
                    parse_mode='HTML'
                )
                
                # Send to User (2. Key Isolated)
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"<code>{link}</code>",
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
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ <b>DECLINED</b>")
        # Notify User
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
        # Check if user already has a key (simple tracking via file for now)
        try:
            with open('claimed_users.json', 'r') as f:
                claimed = json.load(f)
        except FileNotFoundError:
            claimed = {}
            
        user_id = str(query.from_user.id)
        if user_id in claimed:
            old_link = claimed[user_id]
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
        
        # --- SMART LOAD BALANCING LOGIC ---
        # 1. Check all servers
        # 2. Count clients on each
        # 3. Pick the one with FEWEST clients
        selected_server = SERVERS[0]
        min_clients = 99999
        
        try:
            for s in SERVERS:
                try:
                    temp_client = XUIClient(s)
                    list_url = f"{temp_client.base_url}/panel/api/inbounds/get/{temp_client.inbound_id}"
                    r = temp_client.session.get(list_url, verify=False, timeout=5)
                    if r.json().get('success'):
                        # Count active clients
                        count = len(json.loads(r.json()['obj']['settings'])['clients'])
                        if count < min_clients:
                            min_clients = count
                            selected_server = s
                except Exception as e:
                    logging.warning(f"Server {s.get('name')} check failed: {e}")
                    continue
        except:
            pass # Fallback to Server 0
            
        # Generate on the selected best server
        try:
            client = XUIClient(selected_server)
            username = f"FreeTrial_{query.from_user.id}"
            
            # Create Key (2GB Limit, 1 Day)
            link = client.add_client(email=username, limit_gb=2, expire_days=1)
            
            if link:
                claimed[user_id] = link
                with open('claimed_users.json', 'w') as f:
                    json.dump(claimed, f)

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


    elif query.data == 'buy_premium':
        # Payment Instructions
        msg = (
            "💎 <b>1လစာ ဝယ်ယူမည် (Auto)</b>\n\n"
            "အောက်ပါ KPay အကောင့်သို့ <b>5,000 Ks</b> လွှဲပေးပါ။\n\n"
            "📞 <b>09799881201</b> (Daw Tin Tin Yee)\n"
            "📝 Note နေရာတွင် <code>Payment</code> လို့ပဲထည့်ပေးပါနော် တခြားဘာမှမထည့်ပါနဲ့ဗျ\n\n"
            "✅ <b>ငွေလွှဲပြီးပါက ငွေလွှဲပြေစာ (Slip) ဓာတ်ပုံကို ဒီ Bot သို့ ပို့ပေးပါ။</b>\n"
            "စစ်ဆေးပြီး ၁၀ စက္ကန့်အတွင်း Key ပို့ပေးပါမည်။"
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
        [InlineKeyboardButton("🖥️ Server Status", callback_data='admin_status')],
        [InlineKeyboardButton("🔌 Add New Server", callback_data='admin_add_server')]
    ]
    await update.message.reply_text("👑 <b>Admin Control Panel</b>", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    # Check for "Back to Start" button
    if update.message.text == "အစသို့ပြန်သွားပါ":
        await start(update, context)
        return

    # Check if adding a server
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
            with open('config.json', 'w') as f:
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
            link = client.add_client(email=username, limit_gb=limit_gb, expire_days=days)
            
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
            else:
                await status_msg.edit_text("❌ Failed. Name might duplicate.")
        except Exception as e:
            await status_msg.edit_text(f"❌ Error: {e}")

def main():
    app = Application.builder().token(CONFIG['bot_token']).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(button_handler, pattern='^(get_|buy_|help|guide_|main_)'))
    app.add_handler(CallbackQueryHandler(approval_handler, pattern='^(approve_|decline_)'))
    app.add_handler(CallbackQueryHandler(admin_handler, pattern='^admin_'))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()