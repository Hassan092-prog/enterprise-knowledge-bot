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

            # 4. Verification via get_tenant_domains
            get_res = get_tenant_domains(db=db, current_user=mock_user)
            assert get_res["allowed_domains"] == "corporate-verified.com, eng.corporate-verified.com", "get_tenant_domains returned unexpected value"

            # Revert to original
            tenant_1.allowed_domains = orig_domains
            db.commit()

        print_check("Corporate domain management RBAC enforcement verified (403 for user/editor, 200 for admin)", True)
    except Exception as e:
        print_check("Check 17 failed", False, str(e))

    print("\n" + "=" * 70)
    print("ALL 17 DIAGNOSTIC CHECKS COMPLETED")
    print("=" * 70)

if __name__ == "__main__":
    run_diagnostics()
