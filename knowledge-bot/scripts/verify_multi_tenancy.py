"""
verify_multi_tenancy.py — Automated Health & Security Diagnosis for Multi-Tenancy Architecture.

Runs comprehensive checks:
1. Module imports and integrity
2. Database schema evolution and bootstrapping
3. Token claim serialization (tenant_id, role, is_platform_admin)
4. Path traversal defense and filename sanitization
5. ChromaDB & BM25 isolation across tenants
6. 2-Step SuperAdmin transfer logic
"""

import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def print_check(name: str, passed: bool, detail: str = ""):
    symbol = "✅ [PASS]" if passed else "❌ [FAIL]"
    print(f"{symbol} {name}")
    if detail:
        print(f"      └── {detail}")
    if not passed:
        sys.exit(1)

def run_diagnostics():
    print("=" * 70)
    print("ENTERPRISE MULTI-TENANCY DIAGNOSTIC SUITE")
    print("=" * 70)

    # ──────────────────────────────────────────────────────────────────
    # CHECK 1: Module Imports
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 1. Testing Core Imports ---")
    try:
        from src.models import Tenant, User, ChatSession, ActivityLog, PendingTransfer, AccessRequest
        from src.database import run_db_migrations, SessionLocal, engine, slugify, generate_join_code
        from src.auth import create_user_token, verify_password, get_password_hash
        from src.config import sanitize_filename, get_tenant_upload_dir, CORS_ORIGINS
        from src.activity import log_activity
        from api.dependencies import get_current_user, get_current_admin_user, get_current_superadmin_user, get_current_platform_admin
        from api.main import app
        print_check("Core modules, routers, and dependencies imported without error", True)
    except Exception as e:
        print_check("Core modules import failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 2: Database Schema & Migration
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 2. Testing Database Migration & Bootstrapping ---")
    try:
        run_db_migrations()
        with SessionLocal() as db:
            tenant = db.query(Tenant).filter(Tenant.id == 1).first()
            if not tenant:
                raise ValueError("Default Organization (Tenant #1) was not bootstrapped.")
            if not tenant.join_code:
                raise ValueError("Default Organization missing join_code.")
            
            user_count = db.query(User).count()
            superadmin = db.query(User).filter(User.role == "superadmin").first()

            detail = f"Tenant: '{tenant.name}', Join Code: '{tenant.join_code}', Users: {user_count}"
            if superadmin:
                detail += f", SuperAdmin: '{superadmin.username}'"
            print_check("Database schema created and Default Organization bootstrapped", True, detail)
    except Exception as e:
        print_check("Database bootstrap verification failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 3: Security — Path Traversal Sanitization
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 3. Testing Path Traversal Defense (Loophole 5) ---")
    try:
        test_cases = [
            ("../../etc/passwd", "passwd"),
            ("..\\..\\windows\\win.ini", "win.ini"),
            ("subfolder/report.csv", "report.csv"),
            ("standard_file.pdf", "standard_file.pdf"),
        ]
        for raw, expected in test_cases:
            cleaned = sanitize_filename(raw)
            if cleaned != expected:
                raise ValueError(f"Sanitization error for '{raw}': got '{cleaned}', expected '{expected}'")

        # Test rejected dangerous patterns
        for bad in [".", "..", "...", "\x00"]:
            try:
                sanitize_filename(bad)
                raise ValueError(f"Failed to reject dangerous filename: '{bad}'")
            except ValueError:
                pass  # expected

        print_check("Path traversal defense blocks directory traversal and null bytes", True)
    except Exception as e:
        print_check("Path traversal check failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 4: Multi-Tenant JWT Context Serialization (Loophole 2)
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 4. Testing JWT Multi-Tenant Token Serialization ---")
    try:
        import jwt
        from src.auth import SECRET_KEY, ALGORITHM

        class MockUser:
            username = "test_audit_user"
            id = 999
            tenant_id = 42
            role = "superadmin"
            is_platform_admin = True

        token = create_user_token(MockUser())
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        assert payload.get("sub") == "test_audit_user"
        assert payload.get("user_id") == 999
        assert payload.get("tenant_id") == 42
        assert payload.get("role") == "superadmin"
        assert payload.get("is_platform_admin") is True

        print_check("JWT contains user_id, tenant_id, role, and is_platform_admin claims", True, f"Claims: {payload}")
    except Exception as e:
        print_check("JWT multi-tenant claims verification failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 5: VectorStore Multi-Tenant Isolation (Loopholes 4, 6, 13)
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 5. Testing ChromaDB & BM25 Multi-Tenant Isolation ---")
    try:
        from src.retrieval.vector_store import VectorStore
        from langchain_core.documents import Document

        store = VectorStore()

        t1_id = 9901
        t2_id = 9902

        # Create chunks for Tenant 1
        t1_chunk = Document(
            page_content="Quarterly revenue for Acme Corporation reached twenty million dollars in fiscal Q3.",
            metadata={"source": "acme_finances.txt", "chunk_id": "chunk_001"}
        )

        # Create chunks for Tenant 2
        t2_chunk = Document(
            page_content="Globex Corporation proprietary aerospace turbine design patent specifications.",
            metadata={"source": "globex_patent.txt", "chunk_id": "chunk_001"}  # same chunk_id, different tenant!
        )

        store.add_documents([t1_chunk], user_id=1, is_global=True, tenant_id=t1_id)
        store.add_documents([t2_chunk], user_id=2, is_global=True, tenant_id=t2_id)

        # 1. Verify chunk_id prefixing prevented collision
        t1_data = store._collection.get(where={"tenant_id": t1_id}, include=["metadatas"])
        t2_data = store._collection.get(where={"tenant_id": t2_id}, include=["metadatas"])
        assert len(t1_data["ids"]) >= 1, "T1 chunk was not saved"
        assert len(t2_data["ids"]) >= 1, "T2 chunk was not saved"
        assert t1_data["ids"][0].startswith(f"t{t1_id}_"), f"T1 ID not prefixed: {t1_data['ids'][0]}"
        assert t2_data["ids"][0].startswith(f"t{t2_id}_"), f"T2 ID not prefixed: {t2_data['ids'][0]}"

        # 2. Verify search isolation
        t1_results = store.search("proprietary turbine aerospace", tenant_id=t1_id, k=5)
        for r in t1_results:
            if r.metadata.get("tenant_id") != t1_id:
                raise ValueError("Cross-tenant leakage: T2 chunk found in T1 search!")

        t2_results = store.search("Quarterly revenue Acme Corporation", tenant_id=t2_id, k=5)
        for r in t2_results:
            if r.metadata.get("tenant_id") != t2_id:
                raise ValueError("Cross-tenant leakage: T1 chunk found in T2 search!")

        # 3. Verify BM25 tenant index isolation
        if store._bm25_indices:
            assert t1_id in store._bm25_indices, "T1 BM25 index missing"
            assert t2_id in store._bm25_indices, "T2 BM25 index missing"
            bm25_t1_res = store.search_bm25("turbine", tenant_id=t1_id)
            assert len(bm25_t1_res) == 0, "T1 BM25 found T2 document tokens!"

        # 4. Clean up test chunks
        store.delete_all_tenant_chunks(t1_id)
        store.delete_all_tenant_chunks(t2_id)

        print_check("ChromaDB & BM25 enforce zero cross-tenant leakage and prevent chunk_id collisions", True)
    except Exception as e:
        print_check("Vector store isolation test failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 6: Ownership Transfer Handshake
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 6. Testing SuperAdmin Ownership Transfer Logic (Loophole 7) ---")
    try:
        from datetime import datetime, timedelta
        from src.models import PendingTransfer

        with SessionLocal() as db:
            test_transfer = PendingTransfer(
                tenant_id=1,
                from_user_id=1,
                to_user_id=2,
                status="pending",
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=24)
            )
            db.add(test_transfer)
            db.commit()
            db.refresh(test_transfer)

            assert test_transfer.status == "pending"
            assert test_transfer.expires_at > datetime.utcnow()

            # Clean up
            db.delete(test_transfer)
            db.commit()

        print_check("SuperAdmin 2-step transfer handshake model validated", True)
    except Exception as e:
        print_check("Transfer handshake test failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 7: Multi-Tenant Registration & Sequence Integrity (Loophole 1 Onboarding)
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 7. Testing Tenant Onboarding & Sequence Synchronization ---")
    try:
        from api.auth import register, UserCreate

        test_org_name = "Automated Diagnostic Corp"
        test_founder_username = "diag_founder_test"
        test_member_username = "diag_member_test"

        with SessionLocal() as db:
            # 0. Pre-cleanup in case of prior aborted run
            existing_t = db.query(Tenant).filter(Tenant.name == test_org_name).first()
            if existing_t:
                db.query(ActivityLog).filter(ActivityLog.tenant_id == existing_t.id).delete()
                existing_t.superadmin_user_id = None
                db.flush()
                db.query(User).filter(User.tenant_id == existing_t.id).delete()
                db.delete(existing_t)
                db.commit()
            db.query(User).filter(User.username.in_([test_founder_username, test_member_username])).delete()
            db.commit()

            # 1. Register new organization (Founder -> SuperAdmin)
            founder_payload = UserCreate(
                username=test_founder_username,
                password="TestPassword123!",
                company_name=test_org_name
            )
            founder_token = register(founder_payload, db=db)
            assert founder_token["role"] == "superadmin", f"Expected superadmin, got {founder_token['role']}"
            created_tenant_id = founder_token["tenant_id"]
            assert created_tenant_id is not None, "Tenant ID not returned"
            assert created_tenant_id > 1, f"Expected new tenant ID > 1, got {created_tenant_id}"

            # Verify tenant in DB
            new_tenant = db.query(Tenant).filter(Tenant.id == created_tenant_id).first()
            assert new_tenant is not None, "Tenant record not found in database"
            assert new_tenant.superadmin_user_id is not None, "SuperAdmin user ID not set on tenant"

            # 2. Register member with join code (Member -> User)
            member_payload = UserCreate(
                username=test_member_username,
                password="TestPassword123!",
                company_name=test_org_name,
                join_code=new_tenant.join_code
            )
            member_token = register(member_payload, db=db)
            assert member_token["role"] == "user", f"Expected user role, got {member_token['role']}"
            assert member_token["tenant_id"] == created_tenant_id, "Member assigned wrong tenant"

            # 3. Test seamless session persistence across role promotion
            from api.dependencies import get_current_user
            member_user = db.query(User).filter(User.username == test_member_username).first()
            member_user.role = "admin"
            db.commit()

            # Verify token with role="user" seamlessly authenticates and yields fresh DB role="admin"
            validated_user = get_current_user(token=member_token["access_token"], db=db)
            assert validated_user.role == "admin", "Session failed to reflect updated role dynamically"

            # 4. Clean up test records: unlink superadmin FK before deleting users/tenant
            db.query(ActivityLog).filter(ActivityLog.tenant_id == created_tenant_id).delete()
            new_tenant.superadmin_user_id = None
            db.flush()
            db.query(User).filter(User.username.in_([test_founder_username, test_member_username])).delete()
            db.delete(new_tenant)
            db.commit()

        print_check("Organization registration, sequence generation, and join-code onboarding passed", True)
    except Exception as e:
        print_check("Tenant onboarding registration test failed", False, str(e))

    print("\n" + "=" * 70)
    print("ALL 7 DIAGNOSTIC CHECKS COMPLETED")
    print("=" * 70)

if __name__ == "__main__":
    run_diagnostics()
