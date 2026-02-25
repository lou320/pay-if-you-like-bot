#!/usr/bin/env python3
"""Apply region selection feature to VPN bot"""

import sys

with open('vpn_bot/bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add helper functions after the global vars
helper_functions = '''
# --- HELPER FUNCTIONS ---
def get_servers_by_region(region):
    """Get all servers for a specific region"""
    return [s for s in SERVERS if s.get('region', '').lower() == region.lower()]

def get_random_server_by_region(region):
    """Get a random server for a specific region"""
    servers = get_servers_by_region(region)
    if not servers:
        return None
    import random
    return random.choice(servers)

'''

# Find where to insert helper functions (after MAIN_MENU_KB line)
insert_pos = content.find('logging.basicConfig')
if insert_pos > 0:
    content = content[:insert_pos] + helper_functions + content[insert_pos:]

# 2. Update button_handler pattern to include region_
old_pattern = "pattern='^(get_|buy_|help|guide_|main_|check_)'"
new_pattern = "pattern='^(get_|buy_|help|guide_|main_|check_|region_)'"
content = content.replace(old_pattern, new_pattern)

# 3. Add region selection for get_free
get_free_selection = '''    if query.data == 'get_free':
        # Show region selection
        text = "🌍 <b>ကဖြစ်ပါသလဲ ရွေးချယ်ပေးပါခင်ဗျာ:</b>"
        keyboard = [
            [InlineKeyboardButton("🇸🇬 Singapore", callback_data='region_free_singapore')],
            [InlineKeyboardButton("🇯🇵 Japan", callback_data='region_free_japan')],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]
        ]
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    if query.data.startswith('region_free_'):
        region = query.data.split('_')[2]
        context.user_data['selected_region'] = region
        
        # Check if user already has a key (simple tracking via file for now)
        try:
            with open('claimed_users.json', 'r') as f:
                claimed = json.load(f)
        except FileNotFoundError:
            claimed = {}
            
        user_id = str(query.from_user.id)
        if user_id in claimed:'''

old_get_free = '''    if query.data == 'get_free':
        # Check if user already has a key (simple tracking via file for now)
        try:
            with open('claimed_users.json', 'r') as f:
                claimed = json.load(f)
        except FileNotFoundError:
            claimed = {}
            
        user_id = str(query.from_user.id)
        if user_id in claimed:'''

content = content.replace(old_get_free, get_free_selection)

# 4. Update region-specific load balancing for free keys
old_load_balance = '''        await query.edit_message_text("⚙️ <b>Key ထုတ်ပေးနေပါသည်... ခဏစောင့်ပါ...</b>", parse_mode='HTML')
        
        # --- SMART LOAD BALANCING LOGIC ---
        # 1. Check all servers
        # 2. Count clients on each
        # 3. Pick the one with FEWEST clients
        selected_server = SERVERS[0]
        min_clients = 99999
        
        try:
            for s in SERVERS:'''

new_load_balance = '''        await query.edit_message_text("⚙️ <b>Key ထုတ်ပေးနေပါသည်... ခဏစောင့်ပါ...</b>", parse_mode='HTML')
        
        # Get selected region from user context
        region = context.user_data.get('selected_region', 'singapore')
        region_servers = get_servers_by_region(region)
        
        if not region_servers:
            await query.edit_message_text(
                f"❌ {region.capitalize()} အဆင်မပြေ။ နောက်အကြိမ်စမ်းကြည့်ပါ။",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]])
            )
            return
        
        # --- SMART LOAD BALANCING LOGIC (Region-specific) ---
        # 1. Check all servers in the selected region
        # 2. Count clients on each
        # 3. Pick the one with FEWEST clients
        selected_server = region_servers[0]
        min_clients = 99999
        
        try:
            for s in region_servers:'''

content = content.replace(old_load_balance, new_load_balance)

# Write the modified content
with open('vpn_bot/bot.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Applied region selection to bot.py")
