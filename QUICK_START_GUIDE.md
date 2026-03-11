# Quick Start Guide - Free Trial Auto-Delete Feature

## What's New?

Your VPN bot now **automatically deletes free trial accounts after 3 days**. No manual intervention needed! 🎉

---

## For Users

### What Happens to My Free Trial?

1. **Request trial** → Get 2GB for 24 hours
2. **Use VPN** → Can use for up to 3 days
3. **After 3 days** → Account automatically deleted
4. **Get notified** → Bot tells you when it expires

### How to Get a New Trial After It Expires?

Just do `/start` again → Click "Free Trial" → Select region → Get new link ✅

---

## For Admins/Developers

### Check Active Trials

```bash
cat vpn_bot/claimed_users.json | python3 -m json.tool
```

**Output looks like:**
```json
{
  "8130396030": {
    "link": "vless://...",
    "timestamp": 1710086400,
    "trial_type": "free",
    "email": "FreeTrial_8130396030",
    "server_name": "Server 1"
  }
}
```

### Monitor Cleanup

```bash
# Check if cleanup is running
grep "cleanup_expired_trials" bot.log | tail -10

# See successful deletions
grep "✅ Deleted" bot.log

# See cleanup summary
grep "Cleanup complete" bot.log
```

### Quick Test (Simulate 3-Day Expiry)

```python
import json, time

# Load the file
with open('vpn_bot/claimed_users.json') as f:
    data = json.load(f)

# Get first user ID
user_id = list(data.keys())[0]

# Set timestamp to 4 days ago (force expiration)
data[user_id]['timestamp'] = int(time.time()) - (4 * 24 * 60 * 60)

# Save
with open('vpn_bot/claimed_users.json', 'w') as f:
    json.dump(data, f, indent=2)

# Next cleanup run will delete it
print(f"Modified user {user_id} to expire - wait for next cleanup!")
```

---

## Understanding the Tracking System

### How Do We Know Who Already Got a Trial?

**Simple**: Check if their user ID exists in `claimed_users.json`

```
File: claimed_users.json
├─ user_123 exists? → User already has/had trial ❌ (can't get another)
└─ user_456 missing? → User hasn't got trial yet ✅ (can issue new one)
```

### What Info Do We Store?

| Field | Purpose |
|-------|---------|
| `link` | VPN connection string |
| `timestamp` | When trial was issued (in seconds) |
| `email` | Account name (used to delete later) |
| `trial_type` | "free" (auto-delete) or "premium" (manual) |
| `server_name` | Which server it's on |

**Example:**
```json
{
  "8130396030": {
    "link": "vless://8edc52dd-542c-4e7c@34.97.90.13:443?...",
    "timestamp": 1710086400,      ← Created March 10, 2026 at 10:00 AM
    "email": "FreeTrial_8130396030",
    "trial_type": "free",
    "server_name": "Server 1"
  }
}
```

---

## How Auto-Delete Works

### The Timeline

```
Day 0 (Trial starts)
├─ User requests → Bot creates account
├─ User gets link → Can use VPN
└─ System saves timestamp

Days 1-2 (Active trial)
├─ User enjoys VPN
├─ Every hour: Cleanup runs, sees trial is < 3 days old, skips it
└─ System leaves it alone

Day 3 (Expiration)
├─ Cleanup runs (every 1 hour)
├─ Checks: age = now - timestamp
├─ age ≥ 3 days? YES ✅
├─ Deletes from X-UI panel
├─ Removes from claimed_users.json
├─ Notifies user
└─ Account no longer works

After Day 3
├─ User sees notification
├─ User can request new trial
├─ System treats as new user (old entry deleted)
└─ Cycle repeats
```

### What Gets Deleted?

- ✅ FREE trials older than 3 days
- ❌ Premium accounts (stay until manually deleted)

---

## Configuration

### Change How Often It Checks

**File**: `vpn_bot/bot.py`, Line 1299

```python
# Current: Every 1 hour
interval=3600

# Edit to your preference:
interval=1800   # Check every 30 minutes (more aggressive)
interval=7200   # Check every 2 hours (less frequent)
```

### Change Expiry Time

**File**: `vpn_bot/bot.py`, Line 380

```python
# Current: 3 days
three_days_seconds = 3 * 24 * 60 * 60

# Change to:
five_days_seconds = 5 * 24 * 60 * 60  # 5 days instead
```

---

## Troubleshooting

### "Accounts aren't being deleted"

1. **Is bot running?**
   ```bash
   ps aux | grep bot.py
   ```

2. **Check logs:**
   ```bash
   tail -50 bot.log | grep cleanup
   ```

3. **Is the file readable?**
   ```bash
   ls -la vpn_bot/claimed_users.json
   ```

### "User says their trial is still working after 3 days"

Possible reasons:
- **Account was created on X-UI with 1-day limit** - the link itself expires after 1 day
- **Not yet 3 days** - check the timestamp in tracking file
- **Cleanup hasn't run yet** - happens every hour, not instant
- **Check old logs** - verify account was actually deleted

---

## File Locations

| File | Purpose | Notes |
|------|---------|-------|
| `vpn_bot/bot.py` | Main bot code | Contains all deletion logic |
| `vpn_bot/claimed_users.json` | Trial tracking | New format with timestamps |
| `TRIAL_AUTO_DELETE_FEATURE.md` | Full documentation | Complete technical details |
| `TRIAL_AUTO_DELETE_QUICK_REFERENCE.md` | Quick reference | Cheat sheet |
| `TRIAL_AUTO_DELETE_ARCHITECTURE.md` | Architecture | Diagrams and flows |
| `IMPLEMENTATION_SUMMARY.md` | Implementation | What was changed |

---

## Key Functions

### In Code (for developers)

```python
# Load trial tracking
tracking = load_trial_tracking()  # Returns dict of all trials

# Save trial tracking
save_trial_tracking(tracking)  # Writes to file

# Delete an account
client.delete_client_by_email("FreeTrial_12345")  # Removes from X-UI

# Manual cleanup (async)
await cleanup_expired_trials(application)  # Checks & deletes expired
```

---

## Example Scenarios

### Scenario 1: User Gets Free Trial

```
10:00 AM - User clicks "Get Free Trial"
10:01 AM - Bot creates: FreeTrial_8130396030 (2GB, 1 day X-UI limit)
10:02 AM - claimed_users.json updated with timestamp: 1710086400
10:03 AM - User gets VPN link

Days 1-2: User uses VPN normally

Day 3 at 10:30 AM - Cleanup runs
- Checks: 10:30 AM - 10:00 AM (3 days ago) = 3+ days ✅
- Deletes FreeTrial_8130396030 from X-UI
- Removes from claimed_users.json
- User gets: "Trial expired, upgrade to premium!"

User tries to use VPN: Connection fails (account deleted)
User requests new trial: Bot allows it (no entry in file)
```

### Scenario 2: User Gets Premium

```
10:00 AM - User buys premium
10:01 AM - Bot creates: PremiumUser_8130396030 (100GB, 30 days)
10:02 AM - claimed_users.json has: "trial_type": "premium"
10:03 AM - User gets VPN link

Every day for 30 days:
- Cleanup runs
- Sees: trial_type == "premium" (not "free")
- Skips deletion ⏭️

Day 31:
- User manually purchases renewal or account expires naturally
- Premium accounts are managed separately
```

---

## Monitoring Dashboard (What to Watch)

### Every Hour
```bash
# After bot runs cleanup, check logs
tail -5 bot.log
```

**Good sign**:
```
🧹 Starting expired trial cleanup task...
✅ Cleanup complete: 2 expired trials deleted
```

**Problem sign**:
```
❌ Error in cleanup_expired_trials: ...
```

### Daily
```bash
# Check active trials count
python3 -c "import json; print(len(json.load(open('vpn_bot/claimed_users.json'))))"
```

Should stay reasonable (less than 1000 typically)

---

## Testing Checklist

- [ ] Bot starts with "Scheduled cleanup_expired_trials job" message
- [ ] Generate a free trial, check it's in `claimed_users.json`
- [ ] Check timestamp is recent (within last hour)
- [ ] Manually set timestamp to 4 days ago
- [ ] Wait for cleanup to run (every hour) or restart bot
- [ ] Check that trial is deleted from `claimed_users.json`
- [ ] Verify X-UI panel account is gone
- [ ] Check logs for "✅ Deleted" message
- [ ] Try generating new trial (should work)

---

## Quick Reference

| Action | Command | Purpose |
|--------|---------|---------|
| View trials | `cat vpn_bot/claimed_users.json \| python3 -m json.tool` | See all active trials |
| Count trials | `python3 -c "import json; print(len(json.load(open('vpn_bot/claimed_users.json'))))"` | How many trials active |
| Check cleanup | `grep "cleanup" bot.log \| tail -20` | See last 20 cleanup runs |
| View deletions | `grep "✅ Deleted" bot.log` | See successful deletions |
| Test cleanup | See "Manual Cleanup Test" above | Simulate 3-day expiry |
| Configure | Edit `vpn_bot/bot.py` lines 380 or 1299 | Change intervals |

---

## Need Help?

1. **Check logs** → `tail -f bot.log`
2. **Read docs** → See doc files above
3. **Test manually** → Use test checklist
4. **Review code** → Look at bot.py comments

---

**Status**: ✅ Ready to Use  
**Last Updated**: March 11, 2026  
**Questions?**: See full documentation files
