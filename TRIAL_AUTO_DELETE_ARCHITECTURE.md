# Free Trial Auto-Delete Feature - Architecture Diagram

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    TELEGRAM BOT (vpn_bot/bot.py)                │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────────────┐      ┌──────────────────────────┐  │
│  │  User Requests Free     │      │  System Checks if User   │  │
│  │  Trial                  │──┐   │  Already Has Trial       │  │
│  │                         │  │   │  (from claimed_users.json)  │
│  └─────────────────────────┘  │   └──────────────────────────┘  │
│                               │             ▲                    │
│                               ▼             │                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         If No Existing Trial:                            │   │
│  │  ┌──────────────────────────────────────────────────┐   │   │
│  │  │ 1. Create account on X-UI panel                 │   │   │
│  │  │    - Email: FreeTrial_{user_id}                 │   │   │
│  │  │    - Limit: 2GB                                 │   │   │
│  │  │    - Duration: 1 day (expires in system)        │   │   │
│  │  │                                                  │   │   │
│  │  │ 2. Save to claimed_users.json:                  │   │   │
│  │  │    {                                             │   │   │
│  │  │      "user_id": {                               │   │   │
│  │  │        "link": "vless://...",                   │   │   │
│  │  │        "timestamp": 1710086400,    ◄── KEY      │   │   │
│  │  │        "trial_type": "free",       ◄── KEY      │   │   │
│  │  │        "email": "FreeTrial_123",   ◄── KEY      │   │   │
│  │  │        "server_name": "Server 1"                │   │   │
│  │  │      }                                           │   │   │
│  │  │    }                                             │   │   │
│  │  │                                                  │   │   │
│  │  │ 3. Send VPN link to user                        │   │   │
│  │  └──────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  SCHEDULED CLEANUP TASK (Every 1 Hour)                  │   │
│  │                                                          │   │
│  │  cleanup_expired_trials():                              │   │
│  │  ┌──────────────────────────────────────────────────┐   │   │
│  │  │ 1. Load claimed_users.json                      │   │   │
│  │  │    ▼                                             │   │   │
│  │  │ 2. For each user:                               │   │   │
│  │  │    current_age = now - timestamp                │   │   │
│  │  │    ▼                                             │   │   │
│  │  │ 3. If age >= 3 days AND trial_type == 'free':  │   │   │
│  │  │    ▼                                             │   │   │
│  │  │    a) Delete account from X-UI panel            │   │   │
│  │  │       - For each server in SERVERS:             │   │   │
│  │  │       - Call delete_client_by_email(email)      │   │   │
│  │  │       - Remove client from inbound settings     │   │   │
│  │  │    ▼                                             │   │   │
│  │  │    b) Remove from claimed_users.json            │   │   │
│  │  │    ▼                                             │   │   │
│  │  │    c) Send notification to user                 │   │   │
│  │  │       "Your trial expired, upgrade to premium"  │   │   │
│  │  │    ▼                                             │   │   │
│  │  │ 4. Log results                                  │   │   │
│  │  │    "✅ Cleanup complete: X trials deleted"      │   │   │
│  │  └──────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
         ▲                            ▲                    ▲
         │                            │                    │
         │                            │                    │
         └────────────────────────────┼────────────────────┘
                                      │
    ┌─────────────────────────────────┴──────────────────────────┐
    │           X-UI PANEL (VPN Server Management)                │
    ├────────────────────────────────────────────────────────────┤
    │                                                              │
    │  Server 1              Server 2              Server 3        │
    │  ┌─────────┐          ┌─────────┐          ┌─────────┐     │
    │  │ Inbound │          │ Inbound │          │ Inbound │     │
    │  │ Clients │          │ Clients │          │ Clients │     │
    │  │         │          │         │          │         │     │
    │  │ F. T1   │ ◄─ DEL ──│ F. T2   │ ◄─ DEL ──│ F. T3   │     │
    │  │ P. 1    │          │ P. 2    │          │ P. 3    │     │
    │  │ P. 4    │          │         │          │         │     │
    │  └─────────┘          └─────────┘          └─────────┘     │
    │                                                              │
    │  F.T = Free Trial (Auto-deleted after 3 days)              │
    │  P.  = Premium (Manually managed)                          │
    │                                                              │
    └────────────────────────────────────────────────────────────┘
```

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        FREE TRIAL LIFECYCLE                       │
└─────────────────────────────────────────────────────────────────┘

Day 0 (User requests trial):
├─ User sends: /start → Click "Free Trial" → Select region
├─ Bot creates account: FreeTrial_8130396030 on X-UI
├─ Bot records in claimed_users.json:
│  └─ timestamp: 1710086400 (now)
│  └─ trial_type: "free"
│  └─ email: "FreeTrial_8130396030"
└─ User gets VPN link ✅

Days 1-2 (Active usage):
├─ User can use the VPN
├─ Cleanup task runs every hour
│  └─ age = now - 1710086400
│  └─ age < 259200 seconds (3 days)
│  └─ Skip deletion ⏭️
└─ User continues using VPN

Day 3 (Expiration):
├─ Cleanup task runs
├─ age = now - 1710086400 ≥ 259200 (3 days passed)
├─ DELETE:
│  ├─ Remove from X-UI panel (all servers)
│  ├─ Remove from claimed_users.json
│  └─ Notify user 🔔
└─ Account no longer works ❌

If user requests trial again after deletion:
├─ Bot checks claimed_users.json
├─ User ID not found (was deleted)
└─ Can issue new trial ✅ (back to Day 0)
```

## Tracking System Detail

```
┌─────────────────────────────────────────────────────────────┐
│              claimed_users.json Structure                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  {                                                            │
│    "8130396030": {           ◄─ Telegram User ID            │
│      "link": "vless://...",  ◄─ VPN connection string       │
│      "timestamp": 1710086400, ◄─ Unix timestamp (seconds)    │
│                                  Used to calculate age:      │
│                                  age = now - timestamp       │
│      "trial_type": "free",   ◄─ "free" or "premium"        │
│                                  Only "free" auto-deletes    │
│      "email": "FreeTrial_8130396030", ◄─ Account name       │
│                                  Used for deletion from      │
│                                  X-UI panel                  │
│      "server_name": "Server 1"  ◄─ Which server it's on     │
│    },                                                         │
│    "123456789": {                                            │
│      "link": "vless://...",                                  │
│      "timestamp": 1710000000,                                │
│      "trial_type": "premium", ◄─ Won't auto-delete          │
│      "email": "PremiumUser_123",                             │
│      "server_name": "Server 2"                               │
│    }                                                          │
│  }                                                            │
│                                                               │
│  Legacy Format (auto-migrated):                              │
│  "8130396030": "vless://..." ◄─ Old format (string)         │
│               ▼                                               │
│      Converted to:                                           │
│  "8130396030": {                                             │
│    "link": "vless://...",                                    │
│    "timestamp": <current_time>,                              │
│    "trial_type": "free",                                     │
│    "email": "FreeTrial_8130396030",                          │
│    "server_name": "Unknown"                                  │
│  }                                                            │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Deletion Process Detail

```
┌──────────────────────────────────────────────────────────────┐
│         delete_client_by_email() Function Flow                │
├──────────────────────────────────────────────────────────────┤
│                                                                │
│  Input: email = "FreeTrial_8130396030"                       │
│         server_config = {panel_url, username, password, ...} │
│                                                                │
│  Step 1: Connect to X-UI Panel API                           │
│  ├─ GET /panel/api/inbounds/get/{inbound_id}                │
│  └─ Retrieve current inbound configuration                  │
│                                                                │
│  Step 2: Parse Configuration                                │
│  ├─ settings = JSON.parse(inbound['settings'])              │
│  ├─ clients = settings['clients']  ◄─ List of all clients   │
│  └─ Example:                                                 │
│     [                                                         │
│       {                                                       │
│         "id": "uuid-123",                                    │
│         "email": "FreeTrial_8130396030",  ◄─ TARGET          │
│         "totalGB": 2GB,                                      │
│         "expiryTime": 86400000                               │
│       },                                                      │
│       {                                                       │
│         "id": "uuid-456",                                    │
│         "email": "OtherUser",                                │
│         "totalGB": 100GB                                     │
│       }                                                       │
│     ]                                                         │
│                                                                │
│  Step 3: Find & Remove Target Client                        │
│  ├─ For each client in clients:                             │
│  │  └─ If client['email'] == "FreeTrial_8130396030":        │
│  │     └─ Remove this client from list                      │
│  └─ Result: clients = [{uuid-456, OtherUser, ...}]          │
│                                                                │
│  Step 4: Update X-UI Panel                                  │
│  ├─ POST /panel/api/inbounds/{inbound_id}                   │
│  ├─ Payload: {"id": inbound_id, "settings": JSON_STRING}    │
│  └─ X-UI validates & saves new configuration                │
│                                                                │
│  Step 5: Verify Success                                     │
│  ├─ Response: {"success": true}                             │
│  └─ Return: True (deletion successful)                      │
│                                                                │
│  On Error:                                                    │
│  ├─ Session expired? Re-login and retry                     │
│  ├─ Client not found? Log warning, return False             │
│  ├─ API error? Log error details, return False              │
│  └─ Network error? Exception caught, return False           │
│                                                                │
│  Output: True = Account deleted from X-UI panel             │
│         False = Deletion failed, account remains             │
│                                                                │
└──────────────────────────────────────────────────────────────┘
```

## Cleanup Job Timeline

```
┌────────────────────────────────────────────────────────────┐
│  CLEANUP JOB EXECUTION TIMELINE                             │
├────────────────────────────────────────────────────────────┤
│                                                              │
│  Bot Starts                                                  │
│  │                                                           │
│  ├─ Load config, initialize bot                            │
│  │                                                           │
│  ├─ Register handlers                                      │
│  │                                                           │
│  ├─ Setup job_queue                                        │
│  │  └─ job_queue.run_repeating(                            │
│  │       cleanup_expired_trials,                           │
│  │       interval=3600,    ◄─ Every 1 hour (3600 sec)     │
│  │       first=10          ◄─ First run after 10 seconds   │
│  │     )                                                    │
│  │                                                           │
│  ├─ Log: "✅ Scheduled cleanup job to run every hour"      │
│  │                                                           │
│  ├─ Start polling                                          │
│  │                                                           │
│  │                                                           │
│  Timeline (after bot starts):                              │
│  │                                                           │
│  ├─ +10 sec   → CLEANUP JOB RUN #1                         │
│  │               Load trials, check ages, delete if needed  │
│  │               Log results                                │
│  │                                                           │
│  ├─ +1h 10sec → CLEANUP JOB RUN #2                         │
│  │               (1 hour after first run)                   │
│  │                                                           │
│  ├─ +2h 10sec → CLEANUP JOB RUN #3                         │
│  │                                                           │
│  ├─ ...                                                      │
│  │                                                           │
│  └─ Continues running every hour until bot stops           │
│                                                              │
│  Example: If trial created at 10:00 AM                     │
│           3-day deadline: 10:00 AM + 72 hours              │
│           Will be deleted during any cleanup run            │
│           at or after that time ✅                          │
│                                                              │
└────────────────────────────────────────────────────────────┘
```

## Key Decision Points

```
┌──────────────────────────────────────────────────────────────┐
│         CLEANUP TASK DECISION TREE                            │
├──────────────────────────────────────────────────────────────┤
│                                                                │
│           Load claimed_users.json                            │
│                   │                                           │
│                   ▼                                           │
│        For each user in file:                               │
│                   │                                           │
│                   ├─ trial_type == "free"? ─── NO ──────┐   │
│                   │                                      │   │
│                   └─ YES                                 │   │
│                      │                                   │   │
│                      ▼                                   │   │
│           age = now - timestamp                         │   │
│                      │                                   │   │
│                      ├─ age < 3 days? ──── YES ─────┐   │   │
│                      │                              │   │   │
│                      └─ NO (3+ days)                │   │   │
│                         │                           │   │   │
│                         ▼                           │   │   │
│          DELETE account from all servers            │   │   │
│                         │                           │   │   │
│                         ▼                           │   │   │
│          REMOVE from claimed_users.json             │   │   │
│                         │                           │   │   │
│                         ▼                           │   │   │
│          NOTIFY user (if online)                    │   │   │
│                         │                           │   │   │
│                         └───────────────────┐       │   │   │
│                                             │       │   │   │
│      (Premium trials, active trials) ◄─────┴───────┴───┴───┘
│      Skip deletion, keep in file                        │   │
│                                                          │   │
│      Log: "✅ Cleanup complete: X trials deleted"       │   │
│                                                          │   │
└──────────────────────────────────────────────────────────┘
```

## Component Interaction

```
┌─────────────────────────────────────────────────────────────┐
│            COMPONENT INTERACTION DIAGRAM                      │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  TELEGRAM              PYTHON BOT          X-UI PANEL        │
│    USER                                                       │
│     │                   │                    │                │
│     ├─ /start ─────────►│                    │                │
│     │                   │                    │                │
│     │◄─── Menu ─────────┤                    │                │
│     │                   │                    │                │
│     ├─ Get Trial ──────►│                    │                │
│     │                   ├─ Add Client ──────►│                │
│     │                   │                    │ Create         │
│     │                   │◄─ Link ────────────┤ FreeTrial_XXX  │
│     │                   │                    │                │
│     │◄─ VPN Link ───────┤                    │                │
│     │                   │                    │                │
│     │                   ├─ Save to claimed_users.json         │
│     │                   │  {user_id, link, timestamp}         │
│     │                   │                    │                │
│     │                   │                    │                │
│     │                   │   [Every 1 hour]   │                │
│     │                   │                    │                │
│     │                   ├─ Cleanup Task ────┐│                │
│     │                   │  Check ages ──────►│ List clients   │
│     │                   │                    │                │
│     │                   │◄── Client list ────┤                │
│     │                   │                    │                │
│     │                   ├─ If 3+ days ──────►│ Delete         │
│     │                   │                    │ FreeTrial_XXX  │
│     │                   │◄── Success ────────┤                │
│     │                   │                    │                │
│     │◄─ Notification ───┤                    │                │
│     │  "Trial Expired"  │ (if user online)   │                │
│     │                   │                    │                │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

For implementation details, see [TRIAL_AUTO_DELETE_FEATURE.md](TRIAL_AUTO_DELETE_FEATURE.md)
