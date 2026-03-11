# Free Trial Auto-Delete Feature - Quick Reference

## TL;DR (The Short Version)

✅ **What was added:**
- Free trial accounts are **automatically deleted after 3 days**
- System **tracks user Telegram IDs** in `claimed_users.json`
- Cleanup runs **every hour** in the background
- Users get **notified** when their trial expires

## Tracking Method

### How We Know If Someone Already Got a Free Trial

**Answer**: We check `claimed_users.json` file

The file maps:
```
Telegram User ID → Trial Information (link, when it was issued, account name)
```

**Example**:
```json
{
  "8130396030": {
    "link": "vless://...",
    "timestamp": 1710086400,
    "email": "FreeTrial_8130396030",
    "trial_type": "free"
  }
}
```

**Why this works**:
- ✅ Fast: Just a dictionary lookup by user ID
- ✅ Simple: No complex database needed
- ✅ Reliable: Survives bot restarts (stored in file)
- ✅ Has all data needed for auto-delete

## Auto-Delete Mechanism

### Timeline
1. **User gets free trial** → Account created on X-UI panel
2. **System records** → User ID + trial info + timestamp in `claimed_users.json`
3. **Every hour** → Bot checks all trials
4. **After 3 days** → Account is deleted from X-UI panel
5. **User notified** → "Your trial expired, upgrade to premium!"

### Who Gets Deleted?
- ✅ FREE trials older than 3 days
- ❌ Premium accounts (manual deletion only)

## Key Functions

### 1. delete_client_by_email(email)
- **What**: Deletes an account from X-UI panel by email
- **Where**: In `XUIClient` class
- **Used by**: Cleanup task

### 2. load_trial_tracking()
- **What**: Reads `claimed_users.json` with auto-migration
- **Returns**: Dict of user ID → trial info

### 3. save_trial_tracking(data)
- **What**: Writes trial data back to file
- **Used by**: Whenever trial is issued or deleted

### 4. cleanup_expired_trials()
- **What**: Main cleanup job
- **When**: Every hour (configurable)
- **Does**:
  1. Loads all trials
  2. Checks which ones are 3+ days old
  3. Deletes them from X-UI
  4. Removes from tracking file
  5. Notifies user

## Checking If It's Working

### View Active Trials
```bash
cat claimed_users.json
```

### Check Cleanup Logs
```bash
grep "cleanup_expired_trials" bot.log
```

### Manual Cleanup Test
```python
# In bot terminal
python3
>>> import json, time
>>> with open('claimed_users.json') as f: data = json.load(f)
>>> # Modify a timestamp to 3+ days ago
>>> data['USER_ID']['timestamp'] = int(time.time()) - (4 * 24 * 60 * 60)
>>> with open('claimed_users.json', 'w') as f: json.dump(data, f)
>>> # Wait for next hour or restart bot
```

## Configuration

### Change Cleanup Frequency
**File**: `vpn_bot/bot.py`, line 1299

**Current**: Every 1 hour (3600 seconds)

**Change to** (e.g., every 30 minutes):
```python
interval=1800,  # 30 minutes
```

### Change Expiry Duration
**File**: `vpn_bot/bot.py`, line 380

**Current**: 3 days

**Change to** (e.g., 7 days):
```python
seven_days_seconds = 7 * 24 * 60 * 60
if (current_time - trial_timestamp) >= seven_days_seconds:
```

## Troubleshooting

| Problem | Check | Solution |
|---------|-------|----------|
| Trials not deleting | Bot running? | `ps aux \| grep bot.py` |
| Check logs | `tail -f bot.log \| grep cleanup` | |
| File readable? | `ls -la claimed_users.json` | |
| Cleanup not running | Job scheduled? | Check bot startup logs |
| User not notified | Expected | Notification failures are OK (account still deleted) |

## Real Example

### User Flow
```
1. User clicks "Free Trial"
2. Bot creates account: FreeTrial_8130396030
3. Bot saves to claimed_users.json with current timestamp
4. User gets link: vless://...
5. 3 days pass...
6. Cleanup task runs
7. Account deleted from X-UI panel
8. Entry removed from claimed_users.json
9. User gets notification (if online)
```

### Tracking File Evolution
```json
// When issued
{
  "8130396030": {
    "link": "vless://...",
    "timestamp": 1710086400,
    "email": "FreeTrial_8130396030",
    "trial_type": "free",
    "server_name": "Server 1"
  }
}

// After 3 days (at cleanup time)
// This entry is deleted entirely
{}
```

## Summary Table

| Aspect | Implementation |
|--------|-----------------|
| **Tracking Method** | `claimed_users.json` (user ID → trial info) |
| **Tracking Data** | Link, timestamp, email, server, trial type |
| **Auto-Delete Age** | 3 days (259,200 seconds) |
| **Check Frequency** | Every 1 hour |
| **Deletion Scope** | FREE trials only |
| **Notification** | Yes (if user is reachable) |
| **Backward Compatible** | Yes (auto-migrates old format) |
| **Persistence** | Survives bot restarts |

## Key Code Locations

| Feature | File | Lines |
|---------|------|-------|
| Delete function | `vpn_bot/bot.py` | 271-316 |
| Tracking helpers | `vpn_bot/bot.py` | 334-375 |
| Cleanup task | `vpn_bot/bot.py` | 377-422 |
| Trial generation | `vpn_bot/bot.py` | 755-785 |
| Job scheduling | `vpn_bot/bot.py` | 1295-1305 |

---

For detailed documentation, see: [TRIAL_AUTO_DELETE_FEATURE.md](TRIAL_AUTO_DELETE_FEATURE.md)
