import os
import time
import sqlite3
import zipfile
import glob
from datetime import datetime, timedelta
from google.cloud import storage
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# ==========================================
# CONFIGURATION
# ==========================================
# Your Google Cloud Storage Bucket Name loaded from .env
BUCKET_NAME = os.getenv("GCP_BUCKET_NAME", "antigravity-backups-123")

# Path to your downloaded GCP Service Account key
# By default, we expect it in the MCPTA folder named 'gcp-backup-key.json'
GCP_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gcp-backup-key.json')

# Retention: how many days of backups to keep in the cloud?
RETENTION_DAYS = 7
# ==========================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = "/tmp/antigravity_backup"

def safe_sqlite_backup(source_db, dest_db):
    """Performs a safe, non-blocking backup of an active SQLite database."""
    print(f"Creating safe snapshot of {source_db}...")
    try:
        def progress(status, remaining, total):
            print(f'Copied {total-remaining} of {total} pages...')

        with sqlite3.connect(source_db) as src, sqlite3.connect(dest_db) as dst:
            src.backup(dst, pages=250, progress=progress)
        print("Database snapshot complete.")
        return True
    except Exception as e:
        print(f"Error during SQLite backup: {e}")
        return False

def create_zip_archive(zip_filepath):
    """Zips the DB snapshot and all critical config files."""
    print(f"Creating archive: {zip_filepath}")
    db_source = os.path.join(BASE_DIR, "bot_memory.db")
    db_snapshot = os.path.join(TEMP_DIR, "bot_memory_snapshot.db")
    
    # 1. Safe DB snapshot
    if os.path.exists(db_source):
        safe_sqlite_backup(db_source, db_snapshot)

    # 2. Files to include
    files_to_backup = [
        db_snapshot,
        os.path.join(BASE_DIR, "autonomic_learning.json"),
        os.path.join(BASE_DIR, "macro_intel.json"),
        os.path.join(BASE_DIR, "tg_signals.json"),
        os.path.join(BASE_DIR, "video_intel.json"),
        os.path.join(BASE_DIR, ".env"),
        os.path.join(BASE_DIR, "credentials.json"),
        os.path.join(BASE_DIR, "token.json"),
        os.path.join(BASE_DIR, "engine.log")
    ]
    
    # Also include any Telegram .session files
    files_to_backup.extend(glob.glob(os.path.join(BASE_DIR, "*.session")))

    with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in files_to_backup:
            if os.path.exists(file):
                # Store files at the root of the ZIP
                arcname = os.path.basename(file)
                zipf.write(file, arcname)
                print(f"Added {arcname} to archive.")

    # Cleanup DB snapshot
    if os.path.exists(db_snapshot):
        os.remove(db_snapshot)

    print("Archive created successfully.")

def upload_to_gcs(zip_filepath, bucket_name):
    """Uploads the zip file to Google Cloud Storage."""
    if not os.path.exists(GCP_KEY_PATH):
        print(f"CRITICAL ERROR: GCP Service Account key not found at {GCP_KEY_PATH}")
        return False

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GCP_KEY_PATH
    
    print(f"Connecting to Google Cloud Storage (Bucket: {bucket_name})...")
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        
        blob_name = os.path.basename(zip_filepath)
        blob = bucket.blob(blob_name)
        
        print(f"Uploading {blob_name}...")
        blob.upload_from_filename(zip_filepath)
        print("Upload complete!")
        return True
    except Exception as e:
        print(f"Failed to upload to GCS: {e}")
        return False

def cleanup_old_backups(bucket_name):
    """Deletes backups older than RETENTION_DAYS from the bucket."""
    print("Checking for old backups to prune...")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GCP_KEY_PATH
    
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blobs = bucket.list_blobs()
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        
        for blob in blobs:
            if blob.time_created < cutoff_date:
                print(f"Deleting old backup: {blob.name} (Created: {blob.time_created})")
                blob.delete()
        print("Cleanup routine finished.")
    except Exception as e:
        print(f"Error during cleanup: {e}")

if __name__ == "__main__":
    from datetime import timezone
    print(f"--- Antigravity Cloud Backup Started at {datetime.now()} ---")
    
    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR)
        
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = os.path.join(TEMP_DIR, f"antigravity_backup_{timestamp}.zip")
    
    # 1. Create Archive
    create_zip_archive(zip_filename)
    
    # 2. Upload to Cloud
    if BUCKET_NAME != "antigravity-backups-123":
        success = upload_to_gcs(zip_filename, BUCKET_NAME)
        if success:
            # 3. Clean up old backups in the cloud
            cleanup_old_backups(BUCKET_NAME)
    else:
        print("\n[!] WARNING: BUCKET_NAME is not configured in the script!")
        print(f"[!] Local archive created at {zip_filename} but NOT uploaded.")
    
    # Cleanup local zip
    if os.path.exists(zip_filename):
        os.remove(zip_filename)
        
    print("--- Backup Process Completed ---")
