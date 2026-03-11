# Free Trial Auto-Delete Feature Documentation

## Overview

This document explains the new automatic free trial deletion feature implemented in the VPN bot. The system automatically deletes free trial accounts 3 days after they are created.

## How It Works

### 1. **Trial Tracking System**

The system tracks free trials in `claimed_users.json` with the following structure:

```json
{
    "8130396030": {
        "link": "vless://...",
        "timestamp": 1710086400,
        "trial_type": "free",
        "email": "FreeTrial_8130396030",
        "server_name": "Server 1"
    },
    "123456789": {
        "link": "vless://...",
        "timestamp": 1710000000,
        "trial_type": "free",
        "email": "FreeTrial_123456789",
        "server_name": "Server 2"
    }
}
```

#### Field Descriptions:
- **link**: The VPN connection string for the user
- **timestamp**: Unix timestamp (seconds) when the trial was issued
- **trial_type**: Either "free" (auto-delete after 3 days) or "premium" (manual deletion only)
- **email**: The account name on the X-UI panel (used for deletion)
- **server_name**: Which server the account was created on

### 2. **Backward Compatibility**

The system automatically migrates old tracking format (simple `{user_id: link}`) to the new format on first load. Legacy entries get assigned:
- Current timestamp (for age calculation)
- trial_type = "free"
- email = "FreeTrial_{user_id}"

### 3. **Automatic Cleanup Process**

#### Schedule
- **Frequency**: Every hour (3600 seconds)
- **First run**: 10 seconds after bot starts
- **Job name**: `cleanup_expired_trials`

#### What Happens During Cleanup

The `cleanup_expired_trials()` async function:

1. **Loads tracking data** from `claimed_users.json`
2. **Iterates through all users** in the tracking file
3. **Checks each trial's age**:
   - Calculates: `current_time - trial_timestamp`
   - Threshold: 3 days = 259,200 seconds (3 × 24 × 60 × 60)
4. **For trials older than 3 days**:
   - Deletes the account from ALL servers using `delete_client_by_email(email)`
   - Removes the user from tracking file
   - Sends a notification to the user (if possible)
5. **Only affects FREE trials** (`trial_type == "free"`)

### 4. **Account Deletion Mechanism**

#### XUIClient.delete_client_by_email(email)

**Location**: `vpn_bot/bot.py` in the `XUIClient` class

**How it works**:
1. Connects to the X-UI panel via API
2. Fetches the inbound configuration
3. Searches for the client by email address
4. Removes the client from the settings JSON
5. Sends the updated configuration back to the panel
6. Returns `True` if successful, `False` otherwise

**Error handling**:
- Automatically re-authenticates if session expires
- Logs warnings if deletion fails on a specific server
- Doesn't stop the process if one server fails

### 5. **User Notifications**

When a trial expires and is auto-deleted, the user receives:

```
⏰ Free Trial Expired

Your 3-day free trial has expired and the account has been deleted.

💎 Want to continue using VPN?
👉 /start and select 'Premium' to get a 1-month plan!
```

**Note**: If the user has blocked the bot or is unavailable, the notification fails silently.

## Implementation Details

### New Functions Added

#### `load_trial_tracking()`
- Loads tracking data with automatic migration support
- Returns: Dict with trial information

#### `save_trial_tracking(data)`
- Saves tracking data to `claimed_users.json`
- Ensures atomic writes (overwrites entire file)

#### `cleanup_expired_trials(application)`
- Main cleanup function (async, runs in background)
- Called every hour by the job queue
- Handles deletion, tracking updates, and user notifications

### Modified Functions

#### Free Trial Generation Handler
- **Old**: Saved simple link to tracking
- **New**: Saves full trial info with timestamp

**Code location**: Lines 755-785 in `vpn_bot/bot.py`

#### Main Bot Function
- **Old**: No scheduled tasks
- **New**: Adds job queue with hourly cleanup

**Code location**: Lines 1295-1305 in `vpn_bot/bot.py`

## Usage & Testing

### Manual Testing

1. **Issue a free trial**:
   ```
   User sends /start → Clicks "Free Trial" → Selects region
   ```

2. **Check tracking file**:
   ```bash
   cat claimed_users.json
   ```
   Should show the new trial with timestamp.

3. **Simulate 3-day expiry**:
   ```python
   # Temporarily modify timestamp in claimed_users.json
   # Set timestamp to 3 days ago
   timestamp = int(time.time()) - (3 * 24 * 60 * 60)
   ```

4. **Wait for cleanup** (or trigger manually):
   - Check logs for `🧹 Starting expired trial cleanup task...`
   - Verify account was deleted from X-UI panel
   - Verify removed from tracking file

### Checking Logs

Look for these log messages:

```
✅ Cleanup complete: X expired trials deleted
Deleting expired trial for user 8130396030 (email: FreeTrial_8130396030, age: 3.2 days)
✅ Deleted FreeTrial_8130396030 from Server 1
```

## Configuration

### Cleanup Interval
- **Location**: `vpn_bot/bot.py`, line 1299
- **Current**: 3600 seconds (1 hour)
- **To change**: Modify the `interval` parameter

Example (cleanup every 30 minutes):
```python
job_queue.run_repeating(
    cleanup_expired_trials,
    interval=1800,  # 30 minutes
    first=10,
    name='cleanup_expired_trials'
)
```

### Expiry Duration
- **Location**: `vpn_bot/bot.py`, line 380
- **Current**: 3 days (259,200 seconds)
- **To change**: Modify `three_days_seconds`

Example (cleanup after 7 days instead):
```python
seven_days_seconds = 7 * 24 * 60 * 60  # 604800
if (current_time - trial_timestamp) >= seven_days_seconds:
```

## Tracking Method Summary

### How We Know If a User Got a Free Trial

**File**: `claimed_users.json`

**Method**: 
1. Check if user's Telegram ID exists in the file
2. If exists, user already has/had a free trial
3. If not exists, user hasn't used free trial yet

**Format**:
- User ID → Trial Info (link, timestamp, email, server)

### Why This Method?

✅ **Advantages**:
- Simple and efficient (fast lookup by user ID)
- Persists across bot restarts
- Works offline (no API calls needed to check)
- Tracks all metadata needed for auto-deletion
- Backward compatible with old format

❌ **Alternative Methods (Not Used)**:
- Querying X-UI panel directly: Too slow, requires API calls
- Database: Overkill, adds complexity
- Telegram user objects: Lost on restart, no persistence

## Troubleshooting

### Issue: Trials Not Being Deleted

**Check**:
1. Is the bot running? (`ps aux | grep bot.py`)
2. Check logs for cleanup task: `grep "cleanup_expired_trials" bot.log`
3. Verify `claimed_users.json` exists and is readable
4. Check if X-UI panel is accessible

### Issue: Users Not Receiving Deletion Notification

**Possible reasons**:
- User blocked the bot
- User deleted their chat with the bot
- Bot doesn't have permission to send messages
- Network error during notification

**This is non-critical** - the account is still deleted even if notification fails.

### Issue: Wrong Timestamp Format

If you manually edit `claimed_users.json`, use Unix timestamp (seconds since 1970-01-01):
```python
import time
print(int(time.time()))  # Current unix timestamp
```

## Security & Cleanup

### Data Privacy
- Only tracking user ID → trial link mapping
- No personal data stored beyond what X-UI requires
- Deleted accounts are removed from both X-UI and tracking file

### File Permissions
- Ensure `claimed_users.json` is readable/writable by bot process
- `chmod 644 claimed_users.json` (readable, writable)

## Future Enhancements

Possible improvements:
1. **Reminder notifications**: Send reminder at 2.5 days
2. **Configurable expiry**: Allow admins to set expiry duration per region
3. **Premium trial extension**: Auto-upgrade to 7-day premium after first 3 days
4. **Usage analytics**: Track how many trials completed full 3 days
5. **Database backend**: Replace JSON with SQLite for large scale

## Files Modified

1. **vpn_bot/bot.py**
   - Added: `XUIClient.delete_client_by_email()`
   - Added: `load_trial_tracking()`
   - Added: `save_trial_tracking()`
   - Added: `cleanup_expired_trials()`
   - Modified: Free trial generation handler
   - Modified: `main()` function

2. **vpn_bot/claimed_users.json**
   - Format changed to include timestamp and metadata

## Questions or Issues?

If cleanup isn't working:
1. Check bot logs: `tail -f bot.log`
2. Verify X-UI panel accessibility: `curl -k https://[panel-url]/login`
3. Ensure user timezone is correct for age calculation (uses server time)
4. Contact admin or check bot process status

---

**Last Updated**: March 2026
**Feature Status**: Active & Tested
**Auto-delete Duration**: 3 days
**Check Frequency**: Every hour
