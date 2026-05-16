import os
import zipfile
from datetime import datetime
from google.cloud import storage
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

BUCKET_NAME = os.getenv("GCP_BUCKET_NAME", "")
GCP_KEY_PATH = os.path.join(BASE_DIR, "gcp-backup-key.json")
RESTORE_DIR = "/tmp/antigravity_restore"

def list_available_backups():
    """Lists all available backups in the GCS bucket."""
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GCP_KEY_PATH
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blobs = sorted(bucket.list_blobs(), key=lambda b: b.time_created, reverse=True)

    if not blobs:
        print("No backups found in the cloud bucket.")
        return []

    print("\nAvailable backups in Google Cloud:")
    print("-" * 55)
    for i, blob in enumerate(blobs):
        size_mb = blob.size / (1024 * 1024)
        created = blob.time_created.strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"  [{i}] {blob.name}  ({size_mb:.2f} MB)  |  {created}")
    print("-" * 55)
    return blobs

def download_and_restore(blob, auto=False):
    """Downloads a backup ZIP and restores all files to the project directory."""
    os.makedirs(RESTORE_DIR, exist_ok=True)
    zip_path = os.path.join(RESTORE_DIR, blob.name)

    print(f"\nDownloading {blob.name}...")
    blob.download_to_filename(zip_path)
    print("Download complete.")

    if not auto:
        # Safety check - stop the bot first!
        print("\n[!] WARNING: About to overwrite live files.")
        print("[!] It is STRONGLY recommended to stop the bot before proceeding.")
        confirm = input("Type 'YES' to continue with the restore: ").strip()
        if confirm != "YES":
            print("Restore cancelled.")
            return

    print(f"\nExtracting files to {BASE_DIR}...")
    with zipfile.ZipFile(zip_path, 'r') as zipf:
        for file in zipf.namelist():
            print(f"  Restoring: {file}")
            zipf.extract(file, BASE_DIR)

        # Rename the DB snapshot back to the original name
        snapshot_path = os.path.join(BASE_DIR, "bot_memory_snapshot.db")
        original_path = os.path.join(BASE_DIR, "bot_memory.db")
        if os.path.exists(snapshot_path):
            os.replace(snapshot_path, original_path)
            print("  Renamed bot_memory_snapshot.db -> bot_memory.db")

    # Cleanup
    os.remove(zip_path)
    print("\n[OK] Restore completed successfully!")
    print("[!] You can now restart the bot with: bash runner.sh")

if __name__ == "__main__":
    import sys
    auto_mode = '--auto' in sys.argv

    if not os.path.exists(GCP_KEY_PATH):
        print(f"ERROR: GCP key not found at {GCP_KEY_PATH}")
        exit(1)

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GCP_KEY_PATH

    print("=== Antigravity Cloud Restore Tool ===")
    blobs = list_available_backups()

    if not blobs:
        exit(1)

    if auto_mode:
        print("\n[AUTO MODE] Automatically restoring the latest backup...")
        selected = blobs[0]  # newest first (sorted desc)
        download_and_restore(selected, auto=True)
    else:
        choice = input("\nEnter the number of the backup to restore (or 'q' to quit): ").strip()
        if choice.lower() == 'q':
            print("Exiting.")
            exit(0)
        try:
            selected = blobs[int(choice)]
            download_and_restore(selected)
        except (ValueError, IndexError):
            print("Invalid selection. Exiting.")
