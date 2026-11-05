"""
One-time / maintenance migration script: Uploads all legacy files on disk to decoupled Object Storage (MinIO / S3).
"""

import os
import sys
from pathlib import Path
import re
import argparse

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


def migrate(verify_only: bool = False, tenant_filter: int = None, force: bool = False) -> int:
    storage = get_storage_provider()
    upload_root = UPLOAD_DIR.resolve()
    mode_str = "VERIFY ONLY (dry-run)" if verify_only else "SYNC / MIGRATE"
    print(f"[*] Mode: {mode_str}")
    print(f"[*] Source directory: {upload_root}")
    print(f"[*] Storage provider: {storage.__class__.__name__}")
    if tenant_filter is not None:
        print(f"[*] Tenant filter: {tenant_filter}")

    if not upload_root.exists():
        print(f"[!] Upload directory {upload_root} does not exist. Nothing to migrate.")
        return 0

    scanned = 0
    uploaded = 0
    skipped = 0
    verified = 0
    mismatched = 0
    missing = 0
    errors = 0

    for file_path in upload_root.rglob("*"):
        if not file_path.is_file():
            continue
        # Skip hidden files or lock files
        if file_path.name.startswith("."):
            continue

        storage_key = determine_storage_key(file_path, upload_root)

        # Apply tenant filter if specified
        if tenant_filter is not None:
            if not storage_key.startswith(f"tenants/{tenant_filter}/"):
                continue

        scanned += 1
        local_size = file_path.stat().st_size

        try:
            exists = storage.object_exists(storage_key)

            if verify_only:
                if not exists:
                    print(f"[MISSING] {file_path.name} -> {storage_key}")
                    missing += 1
                else:
                    remote_size = storage.get_object_size(storage_key)
                    if remote_size is not None and remote_size != local_size:
                        print(f"[MISMATCH] {file_path.name} -> {storage_key} (local={local_size}B, remote={remote_size}B)")
                        mismatched += 1
                    else:
                        print(f"[VERIFIED] {file_path.name} -> {storage_key} ({local_size}B)")
                        verified += 1
                continue

            # Migration mode
            if exists and not force:
                print(f"[-] Skipped (already exists): {file_path.name} -> {storage_key}")
                skipped += 1
                continue

            print(f"[+] Uploading: {file_path.name} -> {storage_key} ({local_size}B)")
            storage.upload_file(file_path, storage_key)
            uploaded += 1
        except Exception as e:
            print(f"[!] Error processing {file_path.name} ({storage_key}): {e}")
            errors += 1

    print("\n" + "=" * 55)
    print("MIGRATION & VERIFICATION SUMMARY:")
    print(f"  Scanned:    {scanned}")
    if verify_only:
        print(f"  Verified:   {verified}")
        print(f"  Missing:    {missing}")
        print(f"  Mismatched: {mismatched}")
    else:
        print(f"  Uploaded:   {uploaded}")
        print(f"  Skipped:    {skipped}")
    print(f"  Errors:     {errors}")
    print("=" * 55)

    if verify_only:
        return 0 if (missing == 0 and mismatched == 0 and errors == 0) else 1
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate and verify local upload storage in MinIO / S3")
    parser.add_argument("--verify-only", "-v", action="store_true", help="Verify remote object presence and size without uploading")
    parser.add_argument("--tenant-id", "-t", type=int, default=None, help="Migrate/verify only files for a specific tenant ID")
    parser.add_argument("--force", "-f", action="store_true", help="Force re-upload of existing files")
    args = parser.parse_args()

    sys.exit(migrate(verify_only=args.verify_only, tenant_filter=args.tenant_id, force=args.force))

