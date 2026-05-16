# Cloud Backup & Restore Guide

The Antigravity bot includes an automated cloud backup system that securely snapshots all critical data to **Google Cloud Storage** every night at 3:00 AM.

## What Gets Backed Up

| File | Description |
|---|---|
| `bot_memory.db` | Full trade ledger and performance history |
| `autonomic_learning.json` | Bot's self-tuning parameters |
| `macro_intel.json` | Latest macro sentiment data |
| `tg_signals.json` | Latest Telegram signals |
| `video_intel.json` | Latest video analysis data |
| `.env` | Environment configuration |
| `credentials.json` + `token.json` | Google OAuth credentials |
| `engine.log` | Last 24h of engine logs |
| `*.session` | Telegram session files |

Backups older than **7 days** are automatically deleted from the cloud bucket.

---

## Automated Backup (Cron)

The backup runs automatically every night. No action required.

To check the log of the last backup:
```bash
tail ~/MCPTA/backup.log
```

To trigger a manual backup immediately:
```bash
cd ~/MCPTA && source venv/bin/activate && python cloud_backup.py
```

---

## Restoring From a Backup

Use this procedure if you need to recover data after a failure, hardware replacement, or accidental data loss.

### Step 1 – Stop the bot
```bash
bash ~/MCPTA/stop_bot.sh
```

### Step 2 – Launch the restore tool
```bash
cd ~/MCPTA && source venv/bin/activate && python cloud_restore.py
```

The tool will display a numbered list of all available backups in the cloud with their dates and sizes. Select the one you want to restore by entering its number.

### Step 3 – Confirm the restore
You will be prompted to type `YES` to confirm overwriting the current files. The tool will then download and extract all files automatically.

### Step 4 – Restart the bot
```bash
bash ~/MCPTA/runner.sh
```

---

## Common Recovery Scenarios

| Scenario | Action |
|---|---|
| Corrupted `bot_memory.db` | Run restore, select latest backup |
| Lost `.env` file | Run restore, then restart bot |
| New Raspberry Pi / SD card replacement | Install project, copy `gcp-backup-key.json`, run restore |
| Accidental file deletion | Run restore, select backup from before the incident |

---

## Configuration Reference

| Variable | Location | Description |
|---|---|---|
| `GCP_BUCKET_NAME` | `.env` on Raspberry Pi | Name of your Google Cloud Storage bucket |
| `gcp-backup-key.json` | `~/MCPTA/` on Raspberry Pi | GCP Service Account key (never commit to Git!) |
| `RETENTION_DAYS` | `cloud_backup.py` line 23 | Number of days to keep backups (default: 7) |
| Cron schedule | `crontab -e` | Currently set to `0 3 * * *` (3:00 AM daily) |
