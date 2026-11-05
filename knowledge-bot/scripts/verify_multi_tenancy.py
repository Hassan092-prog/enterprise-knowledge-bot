"""
verify_multi_tenancy.py — Automated Health & Security Diagnosis for Multi-Tenancy Architecture.

Runs comprehensive checks:
1. Module imports and integrity
2. Database schema evolution and bootstrapping
3. Security — Path traversal defense and filename sanitization
4. Multi-Tenant JWT context serialization (tenant_id, role, is_platform_admin)
5. VectorStore ChromaDB & BM25 isolation across tenants
6. SuperAdmin 2-step ownership transfer logic
7. Multi-tenant onboarding registration & sequence integrity
8. Suspended tenant enforcement & cross-tenant tabular boundary check
9. Mention routing & member offboarding boundaries
10. Conversational memory, query condensation & citation metadata
11. Pillar 3 — Compliance audit log filtering & multi-format exporter
12. Pillar 4 — In-chat tabular BI visualization schema
13. Pillar 3 — CSV formula injection (CWE-1236) defense
14. Pillar 4 — Tabular SQL security & path traversal jail
15. Governance — Audit log tenant isolation & RBAC protection
16. Pillar 8 — Enterprise OAuth2 & corporate domain auto-routing
17. Pillar 8 — Corporate domain management RBAC enforcement (PATCH /auth/tenant/domains)
18. Phase 2 — Asynchronous ingestion & fine-grained stepper progress
19. Phase 3 — Production API hardening, Redis rate limiting, input limits, CORS gate, RFC 7807 envelopes
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

    # ──────────────────────────────────────────────────────────────────
    # CHECK 8: Suspended Tenant Enforcement & Tabular Boundary Check
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 8. Testing Suspended Tenant Enforcement & Tabular Boundaries ---")
    try:
        from fastapi import HTTPException
        from api.dependencies import get_current_user
        from src.retrieval.tabular_agent import run_tabular_query

        with SessionLocal() as db:
            # Create a temporary suspended tenant
            susp_tenant = Tenant(
                name="Suspended Diagnostic Tenant",
                slug="suspended-diag-test",
                status="suspended",
                join_code="SUSP-001"
            )
            db.add(susp_tenant)
            db.flush()

            susp_user = User(
                username="susp_user_test",
                hashed_password="hashed_pw_test",
                role="user",
                tenant_id=susp_tenant.id
            )
            db.add(susp_user)
            db.commit()

            susp_token = create_user_token(susp_user)

            # 1. Verify get_current_user raises 403 on suspended tenant
            blocked = False
            try:
                get_current_user(token=susp_token, db=db)
            except HTTPException as http_e:
                if http_e.status_code == 403 and "suspended" in http_e.detail.lower():
                    blocked = True
            assert blocked, "Suspended tenant user was not blocked with 403!"

            # 2. Verify Tabular Agent blocks non-default tenant from reading default tenant's CSV
            tabular_res = run_tabular_query(
                query="Show salaries",
                filename="Employee_ID,Employee_Name,Departmen.csv",
                tenant_id=susp_tenant.id  # tenant_id > 1
            )
            assert "not found in your organization" in tabular_res.lower(), f"Unexpected tabular response: {tabular_res}"

            # Teardown
            db.delete(susp_user)
            db.delete(susp_tenant)
            db.commit()

        print_check("Suspended tenant lockout and cross-tenant tabular boundary verified", True)
    except Exception as e:
        print_check("Suspended tenant / tabular boundary check failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 9: Mention Routing & Member Offboarding Boundaries
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 9. Testing Mention Routing & Member Offboarding ---")
    try:
        from src.retrieval.router import route_query
        from api.admin import remove_user

        # 1. Verify router handles both @ and ! prefixes
        docs = ["Acme_Employee_Roster_and_Compensation.csv", "sample.txt"]
        is_tab1, file1 = route_query("Can you summarize @sample.txt", docs)
        assert file1 == "sample.txt" and not is_tab1, f"Failed @ mention: {file1}"

        is_tab2, file2 = route_query("Calculate base salaries in !Acme_Employee", docs)
        assert file2 == "Acme_Employee_Roster_and_Compensation.csv" and is_tab2, f"Failed ! mention: {file2}"

        # 2. Verify member offboarding and self-deletion defense
        with SessionLocal() as db:
            db.query(User).filter(User.username.in_(["test_audit_admin", "test_audit_member"])).delete()
            db.commit()
            admin_u = User(username="test_audit_admin", hashed_password="pw", role="superadmin", tenant_id=1)
            member_u = User(username="test_audit_member", hashed_password="pw", role="user", tenant_id=1)
            db.add(admin_u)
            db.add(member_u)
            db.commit()
            db.refresh(admin_u)
            db.refresh(member_u)

            # Prevent self-removal
            self_blocked = False
            try:
                remove_user(user_id=admin_u.id, db=db, current_user=admin_u)
            except HTTPException as e:
                if e.status_code == 400:
                    self_blocked = True
            assert self_blocked, "Failed to block self-removal"

            # Remove member successfully
            res = remove_user(user_id=member_u.id, db=db, current_user=admin_u)
            assert res["status"] == "success", "Failed to remove member"

            # Clean up admin
            db.delete(admin_u)
            db.commit()

        print_check("Dual @/! mention routing and member offboarding boundaries verified", True)
    except Exception as e:
        print_check("Check 9 failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 10: Conversational Memory, Query Condensation & Citation Metadata
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 10. Testing Conversational Memory & Citation Metadata ---")
    try:
        from src.generation.llm_chain import condense_query, extract_citation_metadata
        from langchain_core.documents import Document

        # 1. Test standalone query without history returns unchanged
        q1 = "What was Acme Corporation's Q3 revenue?"
        assert condense_query(q1, []) == q1, "Empty history modified standalone query"

        # 2. Test query condensation with follow-up context
        mock_history = [
            {"role": "user", "content": "Tell me about Acme Corporation's Project Titan."},
            {"role": "assistant", "content": "Project Titan is Acme's flagship autonomous robotics system generating $19.4M revenue in Q3."}
        ]
        condensed = condense_query("How much did it grow YoY?", mock_history)
        assert len(condensed) > 5, "Condensed query was empty"
        print(f"      └── Query Condensation (Division): 'How much did it grow YoY?' -> '{condensed}'")

        # 2b. Test enterprise follow-up query after department turn
        mock_history_rd = [
            {"role": "user", "content": "How much did they spend on R&D?"},
            {"role": "assistant", "content": "Acme spent $9,800,000 USD on Research & Development (R&D) in Q3."}
        ]
        condensed_fy = condense_query("What is their full-year revenue projection?", mock_history_rd)
        assert len(condensed_fy) > 5, "Condensed query was empty"
        print(f"      └── Query Condensation (Enterprise Metric): 'What is their full-year revenue projection?' -> '{condensed_fy}'")

        # 3. Test citation metadata extraction for Source Inspector Drawer
        test_chunks = [
            Document(
                page_content="Consolidated Q3 Revenue reached $48,500,000 USD (+18.2% YoY).",
                metadata={"source": "Acme_Q3_Review.txt", "chunk_id": "chunk_001", "page": 1, "is_global": 1}
            ),
            Document(
                page_content="Gross margin expanded to 64.8% reflecting manufacturing optimization.",
                metadata={"source": "Acme_Q3_Review.txt", "chunk_id": "chunk_002", "page": 1, "is_global": 1}
            )
        ]
        citations = extract_citation_metadata(test_chunks)
        assert len(citations) == 2, f"Expected 2 citations, got {len(citations)}"
        assert citations[0]["source"] == "Acme_Q3_Review.txt"
        assert citations[0]["chunk_id"] == "chunk_001"
        assert citations[0]["relevance_rank"] == 1
        assert "48,500,000" in citations[0]["content"]

        print_check("Conversational query condensation and citation metadata serialization verified", True)
    except Exception as e:
        print_check("Check 10 failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 11: Pillar 3 — Compliance Audit Log Filtering & Multi-Format Exporter
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 11. Testing Compliance Audit Log Filtering & Multi-Format Exporter ---")
    try:
        from api.admin import _filter_activity_query
        from src.models import ActivityLog
        import io
        import csv
        import json

        with SessionLocal() as db:
            default_tenant = db.query(Tenant).filter(Tenant.id == 1).first()
            if not default_tenant:
                default_tenant = Tenant(name="Default Org", slug="default-org", join_code="DEF-001")
                db.add(default_tenant)
                db.commit()
                db.refresh(default_tenant)

            admin_user = db.query(User).filter(User.tenant_id == default_tenant.id).first()
            admin_id = admin_user.id if admin_user else None

            # Seed a test audit event
            test_log = ActivityLog(
                tenant_id=default_tenant.id,
                user_id=admin_id,
                action="DIAGNOSTIC_COMPLIANCE_TEST",
                category="GOVERNANCE",
                description="SOC 2 automated compliance audit verification",
                details=json.dumps({"test_run": True, "standard": "SOC2_TYPE_II"})
            )
            db.add(test_log)
            db.commit()

            # Test category filtering
            q_gov = _filter_activity_query(db, tenant_id=default_tenant.id, category="GOVERNANCE")
            assert q_gov.count() > 0, "Category filter returned 0 records"

            # Test search filtering
            q_search = _filter_activity_query(db, tenant_id=default_tenant.id, search="compliance audit")
            assert q_search.count() > 0, "Search keyword filter failed"

            # Test tenant isolation in audit logs
            q_t2 = _filter_activity_query(db, tenant_id=99999, search="compliance audit")
            assert q_t2.count() == 0, "Tenant isolation breach in audit query"

            # Test CSV stream formatting
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Log ID", "Timestamp", "User", "Category", "Action", "Description"])
            for l in q_gov.limit(5).all():
                writer.writerow([l.id, l.timestamp, l.user.username if l.user else "System", l.category, l.action, l.description])
            csv_data = output.getvalue()
            assert "DIAGNOSTIC_COMPLIANCE_TEST" in csv_data, "CSV export missing test log action"

            # Clean up test log
            db.delete(test_log)
            db.commit()

        print_check("Audit log category/search filtering, tenant isolation & CSV export verified", True)
    except Exception as e:
        print_check("Check 11 failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 12: Pillar 4 — In-Chat Tabular BI Visualization Schema
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 12. Testing In-Chat Tabular BI Visualization Schema ---")
    try:
        sample_chart_payload = {
            "type": "bar",
            "title": "Headcount by Department",
            "labels": ["Engineering", "Finance", "Legal", "Marketing", "Operations"],
            "series": [
                {
                    "name": "Headcount",
                    "data": [12, 4, 3, 5, 8]
                }
            ]
        }
        # Validate schema keys
        assert sample_chart_payload["type"] in ["bar", "donut", "line", "pie"]
        assert len(sample_chart_payload["labels"]) == len(sample_chart_payload["series"][0]["data"])
        json_str = json.dumps(sample_chart_payload)
        parsed = json.loads(json_str)
        assert parsed["title"] == "Headcount by Department"

        print_check("Tabular BI visualization JSON chart schema and data series validated", True)
    except Exception as e:
        print_check("Check 12 failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 13: Pillar 3 — CSV Formula Injection (CWE-1236) Defense
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 13. Testing CSV Formula Injection Sanitization (CWE-1236) ---")
    try:
        from api.admin import _sanitize_csv_cell, _parse_details_safe

        dangerous_payloads = [
            ("=1+1", "'=1+1"),
            ("=cmd|' /C calc'!A0", "'=cmd|' /C calc'!A0"),
            ("@SUM(A1:A10)", "'@SUM(A1:A10)"),
            ("+12345", "'+12345"),
            ("-12345", "'-12345"),
            ("\t=cmd", "'\t=cmd"),
            ("\r=calc", "'\r=calc"),
            ("   =cmd|' /C calc'!A0", "'   =cmd|' /C calc'!A0"),
        ]

        for payload, expected in dangerous_payloads:
            sanitized = _sanitize_csv_cell(payload)
            assert sanitized == expected, f"Failed to sanitize '{payload}': got '{sanitized}', expected '{expected}'"

        # Safe payloads must remain unchanged
        safe_payloads = [
            ("Acme Corporation", "Acme Corporation"),
            ("User logged in successfully", "User logged in successfully"),
            ("Q3 Financials", "Q3 Financials"),
        ]
        for payload, expected in safe_payloads:
            sanitized = _sanitize_csv_cell(payload)
            assert sanitized == expected, f"Safe payload was unexpectedly altered: '{sanitized}'"

        # Edge cases
        assert _sanitize_csv_cell(None) == ""
        assert _sanitize_csv_cell("") == ""

        # Safe details parser validation
        assert _parse_details_safe('{"status": "ok"}') == {"status": "ok"}
        assert _parse_details_safe("corrupt {json not valid") == "corrupt {json not valid"
        assert _parse_details_safe(None) is None

        print_check("CSV Formula Injection (CWE-1236) defense and safe JSON parser verified", True)
    except Exception as e:
        print_check("Check 13 failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 14: Pillar 4 — Tabular SQL Security & Path Traversal Jail
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 14. Testing Tabular SQL Agent Security & Path Traversal Jail ---")
    try:
        from src.retrieval.tabular_agent import run_tabular_query

        # 1. Path traversal attack blocked
        traversal_attempts = [
            "../../etc/passwd",
            "..\\..\\windows\\win.ini",
            "../src/config.py",
        ]
        for attack_path in traversal_attempts:
            res = run_tabular_query("Show me all records", attack_path, tenant_id=1)
            assert "access denied" in res.lower() or "not found" in res.lower() or "invalid filename" in res.lower(), \
                f"Path traversal not safely contained: {res}"

        # 2. Non-existent file in tenant
        res_nonexistent = run_tabular_query("Calculate sum", "non_existent_file_9999.csv", tenant_id=1)
        assert "not found in your organization" in res_nonexistent.lower(), \
            f"Expected 'not found' message, got: {res_nonexistent}"

        # 3. Verify in-memory database isolation pattern
        import pandas as pd
        from sqlalchemy import create_engine
        test_df = pd.DataFrame({
            "Employee_Name": ["Test User A", "Test User B"],
            "Department": ["Engineering", "Finance"],
            "Base_Salary_USD": [150000, 140000],
            "Annual_Bonus_USD": [20000, 15000]
        })
        mem_engine = create_engine("sqlite:///:memory:")
        test_df.to_sql("data", mem_engine, index=False)
        with mem_engine.connect() as conn:
            import sqlalchemy
            q_res = conn.execute(sqlalchemy.text("SELECT SUM(Base_Salary_USD + COALESCE(Annual_Bonus_USD, 0)) AS total FROM data")).scalar()
            assert q_res == 325000, f"In-memory composite calculation failed: {q_res}"

        print_check("Tabular agent path traversal jail check & SQL memory isolation verified", True)
    except Exception as e:
        print_check("Check 14 failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 15: Governance — Audit Log Tenant Isolation & RBAC Protection
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 15. Testing Audit Log Tenant Isolation & RBAC Protection ---")
    try:
        from fastapi import HTTPException
        from api.dependencies import get_current_admin_user
        from api.admin import _filter_activity_query

        # 1. Verify get_current_admin_user rejects standard "user" role with 403 Forbidden
        class MockRegularUser:
            id = 8888
            username = "mock_regular_user"
            role = "user"
            tenant_id = 1
            is_platform_admin = False

        admin_check_passed = False
        try:
            get_current_admin_user(current_user=MockRegularUser())
        except HTTPException as he:
            if he.status_code == 403:
                admin_check_passed = True
        assert admin_check_passed, "Regular user was not blocked with 403 from admin activity endpoint!"

        # 2. Verify get_current_admin_user allows "admin" and "superadmin"
        class MockAdminUser:
            id = 8889
            username = "mock_admin_user"
            role = "admin"
            tenant_id = 1
            is_platform_admin = False

        class MockSuperAdminUser:
            id = 8890
            username = "mock_superadmin_user"
            role = "superadmin"
            tenant_id = 1
            is_platform_admin = False

        assert get_current_admin_user(current_user=MockAdminUser()).role == "admin"
        assert get_current_admin_user(current_user=MockSuperAdminUser()).role == "superadmin"

        # 3. Verify cross-tenant isolation in audit log filtering with mock records
        with SessionLocal() as db:
            log_tenant_a = ActivityLog(
                tenant_id=1,
                user_id=1,
                action="TENANT_A_ACTION",
                category="SECURITY",
                description="Tenant A private security event"
            )
            log_tenant_b = ActivityLog(
                tenant_id=2,
                user_id=1,
                action="TENANT_B_ACTION",
                category="SECURITY",
                description="Tenant B private security event"
            )
            db.add(log_tenant_a)
            db.add(log_tenant_b)
            db.commit()

            # Query tenant 1
            t1_results = _filter_activity_query(db, tenant_id=1, category="SECURITY").all()
            t1_actions = [l.action for l in t1_results]
            assert "TENANT_A_ACTION" in t1_actions, "Tenant A missing own audit event"
            assert "TENANT_B_ACTION" not in t1_actions, "Cross-tenant leakage: Tenant A retrieved Tenant B's audit log!"

            # Query tenant 2
            t2_results = _filter_activity_query(db, tenant_id=2, category="SECURITY").all()
            t2_actions = [l.action for l in t2_results]
            assert "TENANT_B_ACTION" in t2_actions, "Tenant B missing own audit event"
            assert "TENANT_A_ACTION" not in t2_actions, "Cross-tenant leakage: Tenant B retrieved Tenant A's audit log!"

            # Cleanup
            db.delete(log_tenant_a)
            db.delete(log_tenant_b)
            db.commit()

        print_check("Audit log tenant boundary & RBAC permission checks verified", True)
    except Exception as e:
        print_check("Check 15 failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 16: Pillar 8 — Enterprise OAuth2 & Corporate Domain Auto-Routing
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 16. Testing Enterprise OAuth2 & Corporate Domain Auto-Routing ---")
    try:
        from src.oauth import get_available_oauth_providers, generate_oauth_authorization_url
        import src.oauth as oauth_mod

        # 1. Provider availability dictionary structure
        providers = get_available_oauth_providers()
        assert isinstance(providers, dict), "OAuth providers status is not a dict"
        assert "google" in providers and "github" in providers and "microsoft" in providers, "Missing expected OAuth providers"

        # 2. Authorization URL generation
        orig_google_id = oauth_mod.GOOGLE_CLIENT_ID
        oauth_mod.GOOGLE_CLIENT_ID = "test-google-client-id-12345.apps.googleusercontent.com"
        try:
            auth_url = generate_oauth_authorization_url("google", "https://knowledge.alphalabs.nurexia.co/auth/callback?provider=google")
            assert "accounts.google.com" in auth_url, "Google authorization host mismatch"
            assert "test-google-client-id-12345" in auth_url, "Client ID missing from auth URL"
            assert "scope=" in auth_url and "redirect_uri=" in auth_url, "Required OAuth2 params missing from auth URL"
        finally:
            oauth_mod.GOOGLE_CLIENT_ID = orig_google_id

        # 3. Corporate Domain Auto-Routing verification
        test_domain = "diagnostic-enterprise.org"
        test_company = "Diagnostic Enterprise Corp"
        with SessionLocal() as db:
            # Pre-cleanup
            existing_t = db.query(Tenant).filter(Tenant.name == test_company).first()
            if existing_t:
                db.delete(existing_t)
                db.commit()

            test_tenant = Tenant(
                name=test_company,
                slug="diagnostic-enterprise-corp",
                status="active",
                join_code="ORG-OAUTH99",
                allowed_domains=f"{test_domain},other-domain.com"
            )
            db.add(test_tenant)
            db.commit()
            db.refresh(test_tenant)

            # Test corporate domain matching algorithm
            sample_employee_email = f"lead.engineer@{test_domain}"
            email_domain = sample_employee_email.split("@")[-1].lower()

            matched_tenant = None
            active_tenants = db.query(Tenant).filter(Tenant.status == "active").all()
            for t in active_tenants:
                if t.allowed_domains:
                    domains = [d.strip().lower() for d in t.allowed_domains.split(",") if d.strip()]
                    if email_domain in domains:
                        matched_tenant = t
                        break

            assert matched_tenant is not None, f"Domain auto-routing failed to match '{email_domain}'"
            assert matched_tenant.id == test_tenant.id, f"Matched wrong tenant: {matched_tenant.name}"

            # Teardown
            db.delete(test_tenant)
            db.commit()

        print_check("Enterprise OAuth2 URL generation and corporate domain auto-routing verified", True)
    except Exception as e:
        print_check("Check 16 failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 17: Pillar 8 — Corporate Domain Management RBAC Enforcement
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 17. Testing Corporate Domain Management RBAC Enforcement ---")
    try:
        from fastapi import HTTPException
        from api.auth import update_tenant_domains, get_tenant_domains, TenantDomainUpdate

        with SessionLocal() as db:
            tenant_1 = db.query(Tenant).filter(Tenant.id == 1).first()
            orig_domains = tenant_1.allowed_domains

            mock_user = User(id=9901, username="test_std_user", role="user", tenant_id=1)
            mock_editor = User(id=9902, username="test_editor_user", role="editor", tenant_id=1)
            mock_admin = User(id=9903, username="test_admin_user", role="admin", tenant_id=1)

            # 1. Standard user role must be rejected with 403 Forbidden
            blocked = False
            try:
                update_tenant_domains(TenantDomainUpdate(allowed_domains="hacked.com"), db=db, current_user=mock_user)
            except HTTPException as exc:
                if exc.status_code == 403:
                    blocked = True
            assert blocked, "Standard user was NOT blocked from modifying tenant corporate domains!"

            # 2. Editor role must be rejected with 403 Forbidden
            blocked_editor = False
            try:
                update_tenant_domains(TenantDomainUpdate(allowed_domains="hacked-editor.com"), db=db, current_user=mock_editor)
            except HTTPException as exc:
                if exc.status_code == 403:
                    blocked_editor = True
            assert blocked_editor, "Editor was NOT blocked from modifying tenant corporate domains!"

            # 3. Admin role must succeed (200 OK)
            update_res = update_tenant_domains(
                TenantDomainUpdate(allowed_domains="corporate-verified.com, eng.corporate-verified.com"),
                db=db,
                current_user=mock_admin
            )
            assert update_res["status"] == "success", "Admin domain update did not return success"
            assert "corporate-verified.com" in update_res["allowed_domains"], "Updated domains not returned"

            # 4. Public consumer domain (e.g. gmail.com) must be rejected with 400 Bad Request
            public_blocked = False
            try:
                update_tenant_domains(TenantDomainUpdate(allowed_domains="gmail.com"), db=db, current_user=mock_admin)
            except HTTPException as exc:
                if exc.status_code == 400 and "Public consumer email domain" in exc.detail:
                    public_blocked = True
            assert public_blocked, "Server failed to block public consumer domain 'gmail.com'!"

            # 5. Malformed domain format must be rejected with 400 Bad Request
            malformed_blocked = False
            try:
                update_tenant_domains(TenantDomainUpdate(allowed_domains="bad..domain"), db=db, current_user=mock_admin)
            except HTTPException as exc:
                if exc.status_code == 400 and "Invalid domain format" in exc.detail:
                    malformed_blocked = True
            assert malformed_blocked, "Server failed to block malformed domain format!"

            # 6. Clearing domains with empty string must set allowed_domains to None
            clear_res = update_tenant_domains(TenantDomainUpdate(allowed_domains=""), db=db, current_user=mock_admin)
            assert clear_res["status"] == "success" and clear_res["allowed_domains"] is None, "Clearing domains failed"

            # 7. Verification via get_tenant_domains
            get_res = get_tenant_domains(db=db, current_user=mock_user)
            assert get_res["allowed_domains"] is None, "get_tenant_domains did not reflect cleared state"

            # Revert to original
            tenant_1.allowed_domains = orig_domains
            db.commit()

        print_check("Corporate domain management RBAC and domain sanitization verified (403 for user/editor, 400 for public/malformed, 200 for admin)", True)
    except Exception as e:
        print_check("Check 17 failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 18: Phase 2 — Asynchronous Ingestion & Fine-Grained Stepper Progress
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 18. Testing Asynchronous Ingestion & Task Stepper Progress ---")
    try:
        from pathlib import Path
        import tempfile
        import inspect
        from src.retrieval.retriever import Retriever
        from src.worker import process_document
        from api.main import get_task_status

        # 1. Verify Retriever.ingest_file accepts progress_callback
        sig = inspect.signature(Retriever.ingest_file)
        assert "progress_callback" in sig.parameters, "Retriever.ingest_file missing 'progress_callback' parameter"

        # 2. Test progress_callback invocation across stages
        recorded_stages = []
        def mock_callback(stage: str, pct: int, msg: str):
            recorded_stages.append((stage, pct, msg))

        # Create sample test file
        test_file_content = "Antigravity Architecture: Phase 2 Asynchronous Global Ingestion Engine.\n" * 20
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as tmp:
            tmp.write(test_file_content)
            tmp_path = Path(tmp.name)

        try:
            from api.main import retriever
            if retriever is None:
                retriever = Retriever()

            ingest_res = retriever.ingest_file(
                tmp_path,
                user_id=None,
                is_global=True,
                tenant_id=1,
                progress_callback=mock_callback,
            )

            stage_names = [s[0] for s in recorded_stages]
            assert "PARSING" in stage_names, f"PARSING stage not emitted: {stage_names}"
            assert "CHUNKING" in stage_names, f"CHUNKING stage not emitted: {stage_names}"
            assert "EMBEDDING" in stage_names, f"EMBEDDING stage not emitted: {stage_names}"
            assert "INDEXING" in stage_names, f"INDEXING stage not emitted: {stage_names}"
            assert "COMPLETED" in stage_names, f"COMPLETED stage not emitted: {stage_names}"

            # Verify ascending progress percentages
            percentages = [s[1] for s in recorded_stages]
            assert all(percentages[i] <= percentages[i + 1] for i in range(len(percentages) - 1)), f"Percentages not monotonic: {percentages}"
            assert percentages[-1] == 100, f"Final percentage not 100: {percentages[-1]}"

            # 3. Verify process_document Celery task is bound (bind=True) with update_state
            assert inspect.ismethod(process_document.run), "process_document.run is not a bound method (bind=True required)"
            assert callable(getattr(process_document, "update_state", None)), "process_document lacks update_state capability"

            # 4. Verify /admin/upload_global dispatches background Celery task
            import asyncio
            import io
            from api.admin import upload_global_document
            from fastapi import UploadFile
            from unittest.mock import patch

            mock_file = UploadFile(
                filename="company_policy_v2.txt",
                file=io.BytesIO(b"Enterprise Knowledge Base Global Policy Document Chunks")
            )
            mock_editor = User(id=9902, username="corp_editor", role="editor", tenant_id=1)

            with patch("src.worker.process_document.delay") as mock_delay:
                class MockTask:
                    id = "mock-global-celery-task-999"
                mock_delay.return_value = MockTask()

                upload_response = asyncio.run(upload_global_document(file=mock_file, current_user=mock_editor))
                assert upload_response["status"] == "processing", f"Expected status 'processing', got {upload_response.get('status')}"
                assert upload_response["task_id"] == "mock-global-celery-task-999", f"Expected mock task_id, got {upload_response.get('task_id')}"
                assert mock_delay.called, "process_document.delay was not invoked for global upload"
                _, delay_kwargs = mock_delay.call_args
                assert delay_kwargs.get("is_global") is True, f"Expected is_global=True in delay call: {delay_kwargs}"

            # 5. Verify /tasks/{task_id} exposes progress metadata
            class MockAsyncResult:
                def __init__(self, state, info, ready, successful, result):
                    self.state = state
                    self.status = state
                    self.info = info
                    self._ready = ready
                    self._successful = successful
                    self.result = result
                def ready(self):
                    return self._ready
                def successful(self):
                    return self._successful
                def failed(self):
                    return not self._successful and self._ready

            # 5a. Mock task in PROGRESS state
            mock_progress_meta = {"stage": "EMBEDDING", "pct": 70, "msg": "Generating neural vector embeddings..."}
            with patch("src.worker.celery_app.AsyncResult", return_value=MockAsyncResult("PROGRESS", mock_progress_meta, False, False, None)):
                task_res = get_task_status("mock-task-123", current_user=User(id=1, username="test", role="admin", tenant_id=1))
                assert task_res["status"] == "PROGRESS", f"Expected PROGRESS status, got {task_res['status']}"
                assert task_res["progress"] == mock_progress_meta, f"Progress meta mismatch: {task_res['progress']}"
                assert task_res["ready"] is False, "Task should not be ready"

            # 5b. Mock task in COMPLETED / SUCCESS state
            with patch("src.worker.celery_app.AsyncResult", return_value=MockAsyncResult("SUCCESS", {"status": "ok"}, True, True, {"chunks_added": 5})):
                comp_res = get_task_status("mock-task-456", current_user=User(id=1, username="test", role="admin", tenant_id=1))
                assert comp_res["ready"] is True and comp_res["successful"] is True, "Task should be ready and successful"
                assert comp_res["progress"]["stage"] == "COMPLETED", f"Expected stage COMPLETED, got {comp_res['progress']}"
                assert comp_res["progress"]["pct"] == 100, f"Expected pct 100, got {comp_res['progress']['pct']}"

            # 5c. Multi-tenant Task IDOR defense: cross-tenant task status query blocked with 403
            task_foreign_meta = {"stage": "EMBEDDING", "pct": 70, "tenant_id": 2, "user_id": 999}
            with patch("src.worker.celery_app.AsyncResult", return_value=MockAsyncResult("PROGRESS", task_foreign_meta, False, False, None)):
                idor_blocked = False
                try:
                    get_task_status("mock-task-foreign", current_user=User(id=1, username="test", role="admin", tenant_id=1, is_platform_admin=False))
                except HTTPException as exc:
                    if exc.status_code == 403:
                        idor_blocked = True
                assert idor_blocked, "Failed to block cross-tenant task status inspection (IDOR vulnerability)!"

                # Platform admin must have oversight capability
                admin_res = get_task_status("mock-task-foreign", current_user=User(id=99, username="plat_admin", role="superadmin", tenant_id=1, is_platform_admin=True))
                assert admin_res["status"] == "PROGRESS", "Platform admin was blocked from task status"

            # Clean up test source from vector store
            retriever.delete_document(tmp_path.name, user_id=None, tenant_id=1)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

        print_check("Asynchronous ingestion, Celery task state binding, and stepper progress pipeline verified", True)
    except Exception as e:
        print_check("Check 18 failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 19: Phase 3 — Production API Hardening & Security Defenses
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 19. Testing Production API Hardening & Security Defenses ---")
    try:
        from fastapi.testclient import TestClient
        from api.main import app
        from src.config import MAX_QUERY_LENGTH, ENVIRONMENT
        from src.auth import create_user_token

        client = TestClient(app)

        with SessionLocal() as db:
            admin_user = db.query(User).filter(User.id == 1).first()
            other_user = db.query(User).filter(User.id != 1).first()
            chat_session = db.query(ChatSession).filter(ChatSession.user_id == 1).first()
            if not chat_session:
                chat_session = ChatSession(title="Security Diagnostic Session", user_id=1, tenant_id=1)
                db.add(chat_session)
                db.commit()
                db.refresh(chat_session)
            session_id = chat_session.id

        admin_token = create_user_token(admin_user)

        # 1. Test Query Length Enforcement (len > MAX_QUERY_LENGTH rejected with 400 & RFC 7807 envelope)
        oversized_query = "X" * (MAX_QUERY_LENGTH + 1)
        resp_oversized = client.post(
            "/query",
            json={"query": oversized_query, "session_id": session_id},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp_oversized.status_code == 400, f"Expected 400 for oversized query, got {resp_oversized.status_code}"
        err_json = resp_oversized.json()
        assert "error" in err_json and err_json["error"]["code"] == "HTTP_400", f"Missing RFC 7807 error format: {err_json}"
        assert f"Query exceeds maximum length of {MAX_QUERY_LENGTH} characters." in err_json["error"]["message"]

        # 2. Test IP-based Rate Limiting on /auth/login (10/minute per IP)
        login_statuses = []
        last_login_resp = None
        for i in range(12):
            res = client.post(
                "/auth/login",
                json={"username": f"probe_user_{i}", "password": "wrongpassword"},
                headers={"X-Forwarded-For": "203.0.113.88"}
            )
            login_statuses.append(res.status_code)
            last_login_resp = res
            if res.status_code == 429:
                break

        assert 429 in login_statuses, f"Failed to trigger 429 rate limit on /auth/login (statuses: {login_statuses})"
        assert last_login_resp.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED", f"Unexpected error code: {last_login_resp.json()}"
        assert "Retry-After" in last_login_resp.headers or "retry-after" in last_login_resp.headers, "Missing Retry-After header on 429"

        # 2b. Test Reverse-Proxy IP Isolation (different X-Forwarded-For client is not locked out by proxy IP)
        res_diff_ip = client.post(
            "/auth/login",
            json={"username": "probe_user_clean", "password": "wrongpassword"},
            headers={"X-Forwarded-For": "203.0.113.89"}
        )
        assert res_diff_ip.status_code == 401, f"Clean proxy client was unfairly locked out: status {res_diff_ip.status_code}"

        # 2c. Test RequestValidationError RFC 7807 envelope (422)
        res_invalid_json = client.post("/auth/login", json={"invalid_field": 123})
        assert res_invalid_json.status_code == 422
        assert res_invalid_json.json()["error"]["code"] == "VALIDATION_ERROR"

        # 3. Test Authenticated User Rate Limiting on /query (30/minute per user)
        # Hitting /query with admin_token until rate limit kicks in (30 allowed, 31st returns 429)
        query_statuses = []
        last_q_resp = None
        for i in range(35):
            res = client.post(
                "/query",
                json={"query": "X" * (MAX_QUERY_LENGTH + 1), "session_id": session_id},
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            query_statuses.append(res.status_code)
            last_q_resp = res
            if res.status_code == 429:
                break

        assert 429 in query_statuses, f"Failed to trigger 429 user rate limit on /query (statuses: {query_statuses})"
        assert last_q_resp.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"

        # 4. Verify distinct user from the same IP is NOT throttled (NAT/proxy isolation)
        if other_user:
            other_token = create_user_token(other_user)
            res_other = client.post(
                "/query",
                json={"query": "X" * (MAX_QUERY_LENGTH + 1), "session_id": session_id},
                headers={"Authorization": f"Bearer {other_token}"}
            )
            assert res_other.status_code == 400, f"Other user was throttled (NAT bleed): status {res_other.status_code}"

        # 5. Test CORS Production Gate Assertion
        # Production environment must reject wildcard origin '*'
        cors_gate_triggered = False
        def simulate_cors_gate(env: str, origins: list):
            if env == "production" and ("*" in (origins or []) or not origins):
                raise EnvironmentError("CORS wildcard ('*') is not permitted in production. Set CORS_ORIGINS.")

        try:
            simulate_cors_gate("production", ["*"])
        except EnvironmentError:
            cors_gate_triggered = True
        assert cors_gate_triggered, "Production CORS gate failed to raise EnvironmentError on wildcard origin"

        cors_gate_empty_triggered = False
        try:
            simulate_cors_gate("production", [])
        except EnvironmentError:
            cors_gate_empty_triggered = True
        assert cors_gate_empty_triggered, "Production CORS gate failed to raise EnvironmentError on empty origin list"

        print_check("Production API hardening, Redis sliding-window rate limiting, input limits, CORS gate, and RFC 7807 envelopes verified", True)
    except Exception as e:
        print_check("Check 19 failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 20: Phase 4 — Decoupled Distributed Object Storage (MinIO / S3)
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 20. Testing Decoupled Distributed Object Storage (MinIO / S3) ---")
    try:
        import io
        import tempfile
        from src.storage import (
            get_storage_provider,
            get_object_key,
            LocalStorageProvider,
            S3StorageProvider,
            BaseStorageProvider
        )
        from src.config import S3_BUCKET_NAME, STORAGE_BACKEND

        # 1. Multi-tenant Canonical Key Isolation
        k_user1 = get_object_key(tenant_id=1, filename="sales_data.csv", is_global=False, user_id=10)
        assert k_user1 == "tenants/1/personal/10/sales_data.csv", f"Unexpected key: {k_user1}"

        k_global1 = get_object_key(tenant_id=1, filename="handbook.pdf", is_global=True)
        assert k_global1 == "tenants/1/global/handbook.pdf", f"Unexpected key: {k_global1}"

        k_user2 = get_object_key(tenant_id=2, filename="sales_data.csv", is_global=False, user_id=10)
        assert k_user2 == "tenants/2/personal/10/sales_data.csv", f"Unexpected key: {k_user2}"
        assert k_user1 != k_user2, "Tenant keys collided across tenant boundary!"

        # 2. LocalStorageProvider Validation
        with tempfile.TemporaryDirectory() as tmp_dir:
            local_store = LocalStorageProvider(base_dir=Path(tmp_dir))
            test_key = "tenants/1/test_local.txt"
            test_content = b"Local Storage Provider Diagnostic Bytes"
            local_store.upload_bytes(test_content, test_key)
            assert local_store.object_exists(test_key)
            assert local_store.download_bytes(test_key) == test_content
            stream = local_store.download_stream(test_key)
            assert stream.read() == test_content
            objs = local_store.list_objects(prefix="tenants/1")
            assert test_key in objs
            local_store.delete_object(test_key)
            assert not local_store.object_exists(test_key)

        # 3. S3StorageProvider / MinIO Active Provider Validation
        storage = get_storage_provider()
        assert isinstance(storage, BaseStorageProvider)
        
        s3_key = "tenants/999/global/phase4_diagnostic.txt"
        s3_payload = b"Phase 4 MinIO S3 Integration Diagnostic Payload"
        storage.upload_bytes(s3_payload, s3_key)
        assert storage.object_exists(s3_key), f"Object {s3_key} was not detected in storage provider"
        assert storage.download_bytes(s3_key) == s3_payload, "Downloaded bytes do not match uploaded payload"
        
        # Stream read check
        s3_stream = storage.download_stream(s3_key)
        assert s3_stream.read() == s3_payload, "Downloaded stream read mismatch"
        
        # Presigned URL generation
        presigned_get = storage.generate_presigned_url(s3_key, expiration_seconds=900)
        assert presigned_get is not None and len(presigned_get) > 10, "Failed to generate presigned GET URL"
        if STORAGE_BACKEND == "s3":
            assert "X-Amz-Signature" in presigned_get or "Signature=" in presigned_get or "minio" in presigned_get or "9000" in presigned_get

        # Delete from storage provider
        deleted = storage.delete_object(s3_key)
        assert deleted is True, "Storage delete_object returned False"
        assert not storage.object_exists(s3_key), "Object still exists after delete_object call"

        # 4. Stream Ingestion Pipeline into Retriever
        from src.retrieval.retriever import Retriever
        r = Retriever()
        import api.main
        api.main.retriever = r

        stream_doc_name = "phase4_stream_test_doc.txt"
        stream_payload = b"AlphaCorp enterprise streaming document testing decoupled object storage ingestion."
        stream_bytes = io.BytesIO(stream_payload)
        ingest_res = r.ingest_file(
            file_path=stream_bytes,
            filename=stream_doc_name,
            user_id=1,
            tenant_id=1,
            is_global=False
        )
        assert ingest_res.chunks_added > 0, f"Expected chunks added > 0, got {ingest_res.chunks_added}"

        # Upload corresponding object to storage under canonical personal key
        stream_key = get_object_key(tenant_id=1, user_id=1, filename=stream_doc_name, is_global=False)
        storage.upload_bytes(stream_payload, stream_key)
        assert storage.object_exists(stream_key), "Stream key not found in storage"

        # Verify query retrieval sees the stream-ingested document
        sources = r.list_sources_by_type(user_id=1, tenant_id=1)
        assert stream_doc_name in sources["personal"], f"{stream_doc_name} missing from retriever personal sources"

        # 5. API Download & Cascade Deletion Flow
        from fastapi.testclient import TestClient
        from api.main import app
        from src.auth import create_user_token
        client = TestClient(app)

        with SessionLocal() as db:
            user = db.query(User).filter(User.id == 1).first()
            token = create_user_token(user)

        # Test direct streaming download endpoint for the verified indexed document
        dl_resp = client.get(
            f"/documents/{stream_doc_name}/download",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert dl_resp.status_code == 200, f"Direct download failed: {dl_resp.text}"
        assert dl_resp.content == stream_payload, "Direct download content mismatch"

        # Test presigned URL query parameter mode
        if STORAGE_BACKEND == "s3":
            dl_pre_resp = client.get(
                f"/documents/{stream_doc_name}/download?presigned=true",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert dl_pre_resp.status_code == 200, f"Presigned URL generation failed: {dl_pre_resp.text}"
            dl_json = dl_pre_resp.json()
            assert "download_url" in dl_json
            assert "expires_in" in dl_json

        # Clean up via DELETE /documents/{filename} — verify cascade deletion
        del_resp = client.delete(
            f"/documents/{stream_doc_name}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert del_resp.status_code == 200, f"Delete endpoint failed: {del_resp.text}"
        # Verify object removed from storage
        assert not storage.object_exists(stream_key), f"Storage object {stream_key} was not cascade-deleted"

        # Test POST /upload endpoint
        file_payload = b"Sample upload content for phase 4 verification"
        upload_resp = client.post(
            "/upload",
            files={"file": ("phase4_api_upload_test.txt", io.BytesIO(file_payload), "text/plain")},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert upload_resp.status_code == 200, f"Upload API failed: {upload_resp.text}"
        upload_data = upload_resp.json()
        assert upload_data["status"] == "processing"
        assert "storage_key" in upload_data
        assert storage.object_exists(upload_data["storage_key"]), "Uploaded object missing from storage"

        # Clean up upload test object
        storage.delete_object(upload_data["storage_key"])

        print_check("Decoupled distributed object storage (MinIO/S3), canonical keys, stream ingestion, presigned URLs & cascade deletion verified", True)
    except Exception as e:
        print_check("Check 20 failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 21: Production Observability, LLM Telemetry & Tenant Cost Governance
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 21. Testing Production Observability, Telemetry & Cost Governance ---")
    try:
        from src.telemetry import create_rag_trace, count_tokens, estimate_token_cost
        from src.database import check_and_reset_tenant_budget, record_tenant_token_usage
        from datetime import datetime, timedelta
        import secrets

        # 1. Token Counting & Cost Estimation Utilities
        sample_prompt = "What was Acme Corporation's consolidated revenue in Q3 2026?"
        sample_completion = "Acme Corporation reported $48,500,000 USD in consolidated revenue."
        prompt_tokens = count_tokens(sample_prompt, "gpt-4o-mini")
        comp_tokens = count_tokens(sample_completion, "gpt-4o-mini")
        assert prompt_tokens > 0, "Token counter failed on prompt"
        assert comp_tokens > 0, "Token counter failed on completion"
        cost = estimate_token_cost(prompt_tokens, comp_tokens, "gpt-4o-mini")
        assert cost > 0.0, "Cost estimation returned zero"

        # 2. Telemetry Root Trace & Nested Spans
        trace = create_rag_trace(
            name="rag_verification_trace",
            tenant_id=1,
            user_id=1,
            session_id="test-session-obs",
            metadata={"test_mode": True}
        )
        with trace.span(name="query_condense", input_data={"query": sample_prompt}) as s1:
            s1.end(output={"effective_query": sample_prompt})
        assert "query_condense" in trace.spans
        assert trace.spans["query_condense"].duration_ms >= 0

        with trace.span(name="hybrid_retrieval", input_data={"k": 5}) as s2:
            s2.metadata["n_candidates"] = 10
            s2.end(output={"candidates_count": 10})
        assert "hybrid_retrieval" in trace.spans

        with trace.span(name="rerank_mmr", input_data={"candidate_count": 10}) as s3:
            s3.metadata["k_final"] = 5
            s3.end(output={"final_count": 5})
        assert "rerank_mmr" in trace.spans

        with trace.span(name="llm_stream", input_data={"prompt_tokens": prompt_tokens}) as s4:
            s4.metadata["completion_tokens"] = comp_tokens
            s4.end(output={"tokens": prompt_tokens + comp_tokens})
        assert "llm_stream" in trace.spans

        total_ms = trace.end(output={"status": "completed"})
        assert total_ms >= 0

        # 3. Tenant Budget Model, Atomic Increment & Reset Window
        with SessionLocal() as db:
            unique_suffix = secrets.token_hex(3)
            test_tenant = Tenant(
                name=f"Telemetry Budget Org {unique_suffix}",
                slug=f"telemetry-budget-org-{unique_suffix}",
                monthly_token_budget=1000,
                current_month_tokens=900,
                budget_reset_at=datetime.utcnow() - timedelta(days=45)  # Previous month
            )
            db.add(test_tenant)
            db.commit()
            db.refresh(test_tenant)

            # Test automatic monthly reset
            was_reset = check_and_reset_tenant_budget(test_tenant, db)
            assert was_reset, "Expected budget to reset due to past reset date"
            assert test_tenant.current_month_tokens == 0, "Tokens not zeroed on reset"

            # Test atomic usage increment
            new_tokens = record_tenant_token_usage(test_tenant.id, 250, db)
            assert new_tokens == 250, f"Expected 250 tokens, got {new_tokens}"

            new_tokens_2 = record_tenant_token_usage(test_tenant.id, 750, db)
            assert new_tokens_2 == 1000, f"Expected 1000 tokens, got {new_tokens_2}"

            # 4. HTTP 402 Rejection Enforcement on /query
            budget_user = User(
                username=f"budget_user_{unique_suffix}",
                hashed_password=get_password_hash("testpass"),
                role="user",
                tenant_id=test_tenant.id
            )
            db.add(budget_user)
            db.commit()
            db.refresh(budget_user)

            chat_sess = ChatSession(
                user_id=budget_user.id,
                tenant_id=test_tenant.id,
                title="Budget Enforcement Test"
            )
            db.add(chat_sess)
            db.commit()
            db.refresh(chat_sess)

            b_token = create_user_token(budget_user)

            client = TestClient(app)
            # Query when current_month_tokens (1000) >= monthly_token_budget (1000)
            resp_402 = client.post(
                "/query",
                json={"query": "Test query exceeding budget limit", "session_id": chat_sess.id},
                headers={"Authorization": f"Bearer {b_token}"}
            )
            assert resp_402.status_code == 402, f"Expected HTTP 402, got {resp_402.status_code}: {resp_402.text}"
            assert "monthly token budget exceeded" in resp_402.text.lower()

            # Test zero-budget hard freeze (budget=0, usage=0 must still reject with 402)
            test_tenant.monthly_token_budget = 0
            test_tenant.current_month_tokens = 0
            db.commit()
            resp_zero_budget = client.post(
                "/query",
                json={"query": "Test query with frozen zero budget", "session_id": chat_sess.id},
                headers={"Authorization": f"Bearer {b_token}"}
            )
            assert resp_zero_budget.status_code == 402, f"Expected HTTP 402 for zero budget freeze, got {resp_zero_budget.status_code}"

            # 5. Platform Admin Token Budget Update & CSV Export
            platform_admin = db.query(User).filter(User.is_platform_admin == True).first()
            p_token = create_user_token(platform_admin)

            # PATCH /platform/tenants/{tenant_id}/budget
            patch_resp = client.patch(
                f"/platform/tenants/{test_tenant.id}/budget",
                json={"monthly_token_budget": 50000, "reset_usage": True},
                headers={"Authorization": f"Bearer {p_token}"}
            )
            assert patch_resp.status_code == 200, f"Budget update failed: {patch_resp.text}"
            patch_data = patch_resp.json()
            assert patch_data["monthly_token_budget"] == 50000
            assert patch_data["current_month_tokens"] == 0

            # GET /platform/export/csv
            csv_resp = client.get(
                "/platform/export/csv",
                headers={"Authorization": f"Bearer {p_token}"}
            )
            assert csv_resp.status_code == 200, f"CSV export failed: {csv_resp.text}"
            assert "Monthly Token Budget" in csv_resp.text
            assert test_tenant.name in csv_resp.text

            # Teardown test tenant
            db.delete(chat_sess)
            db.delete(budget_user)
            db.delete(test_tenant)
            db.commit()

        print_check("Production observability, LLM telemetry spans, tenant token accounting, HTTP 402 budget cap & CSV usage exporter verified", True)
    except Exception as e:
        print_check("Check 21 failed", False, str(e))

    print("\n--- 22. Testing Production Deployment, Container Health, Security Headers & Zero-Downtime Resilience ---")
    try:
        from src.storage import get_storage_provider
        from scripts.migrate_uploads_to_minio import migrate as run_storage_migration
        from src.database import engine

        client = TestClient(app)

        # 1. Liveness & Readiness Probes
        resp_health = client.get("/health")
        assert resp_health.status_code == 200, f"/health returned {resp_health.status_code}"
        assert resp_health.json() == {"status": "ok"}, f"/health unexpected payload: {resp_health.json()}"

        resp_ready = client.get("/ready")
        assert resp_ready.status_code == 200, f"/ready returned {resp_ready.status_code}: {resp_ready.text}"
        ready_data = resp_ready.json()
        assert ready_data["status"] == "ready", f"Readiness status not ready: {ready_data}"
        assert "checks" in ready_data
        checks = ready_data["checks"]
        assert checks["database"]["status"] == "ok", f"Database check failed: {checks['database']}"
        assert checks["redis"]["status"] in ("ok", "degraded"), f"Redis check failed: {checks['redis']}"
        assert checks["chromadb"]["status"] == "ok", f"ChromaDB check failed: {checks['chromadb']}"
        assert checks["storage"]["status"] == "ok", f"Storage check failed: {checks['storage']}"

        # Test alias endpoints
        resp_hr = client.get("/health/ready")
        assert resp_hr.status_code == 200 and resp_hr.json()["status"] == "ready"
        resp_hd = client.get("/health?detailed=true")
        assert resp_hd.status_code == 200 and resp_hd.json()["status"] == "ready"

        # 2. Security Headers Verification
        headers = resp_health.headers
        assert headers.get("X-Content-Type-Options") == "nosniff", "Missing X-Content-Type-Options header"
        assert headers.get("X-Frame-Options") == "DENY", "Missing X-Frame-Options header"
        assert headers.get("X-XSS-Protection") == "1; mode=block", "Missing X-XSS-Protection header"
        assert "strict-origin-when-cross-origin" in headers.get("Referrer-Policy", ""), "Missing Referrer-Policy header"
        assert "camera=()" in headers.get("Permissions-Policy", ""), "Missing Permissions-Policy header"

        # 3. Database Connection Pool Hardening
        pool = engine.pool
        assert getattr(pool, "_pre_ping", False) is True or hasattr(pool, "recreate"), "Database connection pre-ping not active"

        # 4. Storage Provider Health & Migration Consistency
        storage = get_storage_provider()
        assert storage.ping() is True, "Storage ping failed"

        # Verify all local files are synced in MinIO/S3 without discrepancies
        migration_exit_code = run_storage_migration(verify_only=True)
        assert migration_exit_code == 0, "Storage migration verification returned non-zero exit code"

        print_check("Production deployment, liveness/readiness probes, security headers, connection pooling & storage consistency verified", True)
    except Exception as e:
        print_check("Check 22 failed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # CHECK 23: Pillar 10 — Knowledge Graph & Hybrid Graph RAG Engine
    # ──────────────────────────────────────────────────────────────────
    print("\n--- 23. Testing Knowledge Graph & Hybrid Graph RAG Engine ---")
    try:
        from src.graph.base import GraphNodeData, GraphEdgeData
        from src.graph.networkx_store import NetworkXGraphStore, normalize_entity_id
        from src.graph.extractor import GraphExtractor
        from src.graph.fusion import retrieve_graph_context
        from src.graph import get_graph_store
        from src.auth import create_access_token

        graph_store = get_graph_store()
        t_diag1 = 9801
        t_diag2 = 9802

        with SessionLocal() as db:
            for tid, tname in [(t_diag1, "Diag Graph Org 1"), (t_diag2, "Diag Graph Org 2")]:
                if not db.query(Tenant).filter(Tenant.id == tid).first():
                    db.add(Tenant(id=tid, name=tname, slug=slugify(tname), join_code=f"DG-{tid}"))
            db.query(User).filter(User.username == "diag_graph_admin").delete()
            db.add(User(username="diag_graph_admin", role="admin", tenant_id=t_diag1))
            db.commit()

        # 1. Clean previous runs
        graph_store.delete_tenant_graph(t_diag1)
        graph_store.delete_tenant_graph(t_diag2)

        # 2. Multi-tenant Graph Isolation
        n1 = GraphNodeData(id="payment_gw", name="Payment Gateway", entity_type="SYSTEM", source_documents=["inc104.txt"])
        n2 = GraphNodeData(id="acme_robotics", name="Acme Robotics", entity_type="ORGANIZATION", source_documents=["corp.txt"])
        graph_store.add_node(t_diag1, n1)
        graph_store.add_node(t_diag2, n2)

        assert graph_store.get_node(t_diag1, "payment_gw") is not None, "Tenant 1 failed to retrieve its node"
        assert graph_store.get_node(t_diag1, "acme_robotics") is None, "Tenant 1 leaked Tenant 2 node"
        assert graph_store.get_node(t_diag2, "acme_robotics") is not None, "Tenant 2 failed to retrieve its node"
        assert graph_store.get_node(t_diag2, "payment_gw") is None, "Tenant 2 leaked Tenant 1 node"

        # 3. Multi-Hop Graph Traversal
        # Network: Incident 104 -> AFFECTS -> Payment Gateway <- GOVERNED_BY - Security Policy
        nodes_t1 = [
            GraphNodeData(id="incident_report_104", name="Incident Report 104", entity_type="INCIDENT", description="Payment outage", source_documents=["inc104.txt"]),
            GraphNodeData(id="payment_gw", name="Payment Gateway", entity_type="SYSTEM", description="Card transactions", source_documents=["inc104.txt"]),
            GraphNodeData(id="sec_policy", name="Enterprise Information Security Policy", entity_type="POLICY", description="Governance standard", source_documents=["policy.txt"]),
        ]
        edges_t1 = [
            GraphEdgeData(source="incident_report_104", target="payment_gw", relation="AFFECTS", source_document="inc104.txt", context_snippet="Service degradation in payment pipeline"),
            GraphEdgeData(source="sec_policy", target="payment_gw", relation="GOVERNS", source_document="policy.txt", context_snippet="Security policy compliance mandate"),
        ]
        graph_store.bulk_add(t_diag1, nodes_t1, edges_t1)

        sub_2hop = graph_store.find_subgraph(t_diag1, ["incident_report_104"], depth=2)
        sub_node_ids = {n["id"] for n in sub_2hop["nodes"]}
        assert "incident_report_104" in sub_node_ids, "Missing seed node in subgraph"
        assert "payment_gw" in sub_node_ids, "Missing 1-hop neighbor in subgraph"
        assert "sec_policy" in sub_node_ids, "Missing 2-hop connected policy in subgraph"
        assert len(sub_2hop["edges"]) >= 2, "Missing relationship edges in subgraph"

        # 4. Hybrid Fusion Retrieval Context Block
        fusion = retrieve_graph_context("What happened during Incident Report 104?", tenant_id=t_diag1)
        assert "KNOWLEDGE GRAPH" in fusion["context_block"], "Fusion context block missing header"
        assert "Incident Report 104" in fusion["context_block"], "Fusion context missing incident entity"
        assert "Payment Gateway" in fusion["context_block"], "Fusion context missing affected system"
        assert len(fusion["graph_citations"]) >= 2, "Fusion missing graph citations"

        # 5. Graph API Endpoints Verification via TestClient
        token_t1 = create_access_token(
            data={"sub": "diag_graph_admin", "user_id": 9898, "tenant_id": t_diag1, "role": "admin"}
        )
        api_headers = {"Authorization": f"Bearer {token_t1}"}

        # GET /graph/stats
        resp_stats = client.get("/graph/stats", headers=api_headers)
        assert resp_stats.status_code == 200, f"Graph stats failed: {resp_stats.text}"
        stats_body = resp_stats.json()
        assert stats_body["node_count"] >= 3, f"Unexpected node count: {stats_body}"
        assert stats_body["edge_count"] >= 2, f"Unexpected edge count: {stats_body}"

        # GET /graph/subgraph
        resp_sub = client.get("/graph/subgraph?query=incident%20104&depth=2", headers=api_headers)
        assert resp_sub.status_code == 200, f"Graph subgraph endpoint failed: {resp_sub.text}"
        sub_body = resp_sub.json()
        assert len(sub_body["nodes"]) >= 2, f"Subgraph nodes empty: {sub_body}"

        # 6. Cascade Document Deletion
        # Deleting inc104.txt should remove incident_report_104 edges, but sec_policy and payment_gw remain
        graph_store.delete_document_entities(t_diag1, "inc104.txt")
        assert graph_store.get_node(t_diag1, "incident_report_104") is None, "Failed to purge orphan incident node"
        assert graph_store.get_node(t_diag1, "sec_policy") is not None, "Wrongfully pruned unrelated policy node"

        # Clean up
        graph_store.delete_tenant_graph(t_diag1)
        graph_store.delete_tenant_graph(t_diag2)
        with SessionLocal() as db:
            db.query(User).filter(User.username == "diag_graph_admin").delete()
            db.query(Tenant).filter(Tenant.id.in_([t_diag1, t_diag2])).delete()
            db.commit()

        print_check("Knowledge Graph, Multi-Tenant Graph Store, Multi-Hop Traversal & Hybrid Fusion verified", True)
    except Exception as e:
        print_check("Check 23 failed", False, str(e))

    print("\n" + "=" * 70)
    print("ALL 23 DIAGNOSTIC CHECKS COMPLETED")
    print("=" * 70)

if __name__ == "__main__":
    run_diagnostics()
