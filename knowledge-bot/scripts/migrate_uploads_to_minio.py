"""
One-time / maintenance migration script: Uploads all legacy files on disk to decoupled Object Storage (MinIO / S3).
"""

import os
import sys
from pathlib import Path
import re

# Add parent directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import UPLOAD_DIR
from src.storage import get_storage_provider, get_object_key
from src.logger import get_logger

logger = get_logger("migrate_to_minio")

def determine_storage_key(file_path: Path, upload_root: Path) -> str:
    """
    Determines the canonical storage key for a file based on its relative path under UPLOAD_DIR.
    """
    rel = file_path.relative_to(upload_root)
    parts = list(rel.parts)
    filename = parts[-1]

    # Pattern: tenants/{tenant_id}/users/{user_id}/{filename}
    m = re.match(r"^tenants/(\d+)/users/(\d+)/.+", str(rel).replace("\\", "/"))
    if m:
        tenant_id, user_id = int(m.group(1)), int(m.group(2))
        return get_object_key(tenant_id=tenant_id, user_id=user_id, filename=filename, is_global=False)

    # Pattern: tenants/{tenant_id}/personal/{user_id}/{filename}
    m = re.match(r"^tenants/(\d+)/personal/(\d+)/.+", str(rel).replace("\\", "/"))
    if m:
        tenant_id, user_id = int(m.group(1)), int(m.group(2))
        return get_object_key(tenant_id=tenant_id, user_id=user_id, filename=filename, is_global=False)

    # Pattern: tenants/{tenant_id}/global/{filename}
    m = re.match(r"^tenants/(\d+)/global/.+", str(rel).replace("\\", "/"))
    if m:
        tenant_id = int(m.group(1))
        return get_object_key(tenant_id=tenant_id, user_id=None, filename=filename, is_global=True)

    # Pattern: tenants/{tenant_id}/{filename}
    m = re.match(r"^tenants/(\d+)/[^/]+$", str(rel).replace("\\", "/"))
    if m:
        tenant_id = int(m.group(1))
        return get_object_key(tenant_id=tenant_id, user_id=None, filename=filename, is_global=True)

    # Pattern: tenant_{tenant_id}/{filename}
    m = re.match(r"^tenant_(\d+)/[^/]+$", str(rel).replace("\\", "/"))
    if m:
        tenant_id = int(m.group(1))
        return get_object_key(tenant_id=tenant_id, user_id=None, filename=filename, is_global=True)

    # Root upload dir files: belong to default tenant 1 global
    return get_object_key(tenant_id=1, user_id=None, filename=filename, is_global=True)


def migrate():
    storage = get_storage_provider()
    upload_root = UPLOAD_DIR.resolve()
    print(f"[*] Starting migration from {upload_root} to storage provider ({storage.__class__.__name__})")

    if not upload_root.exists():
        print(f"[!] Upload directory {upload_root} does not exist. Nothing to migrate.")
        return

    scanned = 0
    uploaded = 0
    skipped = 0
    errors = 0

    for file_path in upload_root.rglob("*"):
        if not file_path.is_file():
            continue
        # Skip hidden files or lock files
        if file_path.name.startswith("."):
            continue

        scanned += 1
        storage_key = determine_storage_key(file_path, upload_root)
        try:
            if storage.object_exists(storage_key):
                print(f"[-] Skipped (already exists): {file_path.name} -> {storage_key}")
                skipped += 1
                continue

            print(f"[+] Uploading: {file_path.name} -> {storage_key}")
            storage.upload_file(file_path, storage_key)
            uploaded += 1
        except Exception as e:
            print(f"[!] Error uploading {file_path.name} to {storage_key}: {e}")
            errors += 1

    print("\n" + "=" * 50)
    print("MIGRATION SUMMARY:")
    print(f"  Scanned:  {scanned}")
    print(f"  Uploaded: {uploaded}")
    print(f"  Skipped:  {skipped}")
    print(f"  Errors:   {errors}")
    print("=" * 50)


if __name__ == "__main__":
    migrate()

