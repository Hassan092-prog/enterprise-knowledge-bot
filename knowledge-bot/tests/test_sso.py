import pytest
import json
import base64
import time
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from api.dependencies import get_db, get_current_user
from src.database import Base
from src.models import User, Tenant, TenantSSOConfig
from src.sso.base import SSOUserProfile, RoleMappingEngine
from src.sso.saml import (
    generate_sp_metadata,
    generate_authn_request,
    parse_idp_metadata_xml,
    parse_saml_response,
)
from src.sso.revocation import (
    blacklist_token,
    is_token_blacklisted,
    revoke_user_sessions,
    revoke_tenant_sessions,
    is_session_revoked,
    check_and_record_assertion_id,
)

# Setup in-memory SQLite for testing SSO
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

_mock_admin = User(
    id=1,
    username="tenant_superadmin",
    role="superadmin",
    tenant_id=1,
    is_platform_admin=False
)

def override_get_current_user():
    return _mock_admin

app.dependency_overrides[get_current_user] = override_get_current_user

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    
    tenant = Tenant(
        id=1,
        name="Acme Corp",
        slug="acme-corp",
        status="active",
        allowed_domains="acme.com,corp.acme.com"
    )
    db.add(tenant)
    db.flush()

    sso_cfg = TenantSSOConfig(
        id=1,
        tenant_id=1,
        idp_type="saml",
        is_enabled=True,
        enforce_sso=False,
        idp_entity_id="https://idp.acme.com/metadata",
        idp_sso_url="https://idp.acme.com/sso/saml",
        idp_x509_cert="-----BEGIN CERTIFICATE-----\nMIIFakeCert==\n-----END CERTIFICATE-----",
        allowed_domains="acme.com,corp.acme.com",
        default_role="user",
        role_mapping_json=json.dumps({"IT-Admins": "admin", "Technical-Writers": "editor"})
    )
    db.add(sso_cfg)
    db.commit()
    db.close()
    
    yield
    
    Base.metadata.drop_all(bind=test_engine)


# ──────────────────────────────────────────────────────────────────
# 1. SAML 2.0 Pure-Python SP Engine Tests
# ──────────────────────────────────────────────────────────────────

def test_generate_sp_metadata():
    metadata_xml = generate_sp_metadata(
        entity_id="https://knowledge-engine.internal/auth/sso/saml/metadata",
        acs_url="https://knowledge-engine.internal/auth/sso/saml/acs"
    )
    assert 'entityID="https://knowledge-engine.internal/auth/sso/saml/metadata"' in metadata_xml
    assert 'Location="https://knowledge-engine.internal/auth/sso/saml/acs"' in metadata_xml
    assert 'urn:oasis:names:tc:SAML:2.0:metadata' in metadata_xml
    assert 'urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress' in metadata_xml


def test_generate_authn_request():
    redirect_url, req_id = generate_authn_request(
        idp_sso_url="https://idp.acme.com/sso/saml",
        sp_entity_id="https://knowledge-engine.internal/auth/sso/saml/metadata",
        acs_url="https://knowledge-engine.internal/auth/sso/saml/acs",
        relay_state="tenant=1"
    )
    assert redirect_url.startswith("https://idp.acme.com/sso/saml?SAMLRequest=")
    assert "RelayState=tenant%3D1" in redirect_url
    assert req_id.startswith("ID_")


def test_parse_idp_metadata_xml():
    sample_idp_metadata = """<?xml version="1.0" encoding="UTF-8"?>
    <md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="https://idp.okta.com/exk123">
        <md:IDPSSODescriptor WantAuthnRequestsSigned="false" protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
            <md:KeyDescriptor use="signing">
                <ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
                    <ds:X509Data>
                        <ds:X509Certificate>MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA</ds:X509Certificate>
                    </ds:X509Data>
                </ds:KeyInfo>
            </md:KeyDescriptor>
            <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="https://idp.okta.com/app/sso/saml"/>
        </md:IDPSSODescriptor>
    </md:EntityDescriptor>"""

    parsed = parse_idp_metadata_xml(sample_idp_metadata)
    assert parsed["idp_entity_id"] == "https://idp.okta.com/exk123"
    assert parsed["idp_sso_url"] == "https://idp.okta.com/app/sso/saml"
    assert "-----BEGIN CERTIFICATE-----" in parsed["idp_x509_cert"]
    assert "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA" in parsed["idp_x509_cert"]


def test_parse_saml_response_unsigned_rejected_and_signed_attributes():
    """Verify unsigned SAML assertions are rejected fail-closed and signed assertions extract attributes."""
    sample_response_xml = """<?xml version="1.0"?>
    <samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
                    xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
                    ID="resp_123" Version="2.0">
        <samlp:Status>
            <samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>
        </samlp:Status>
        <saml:Assertion ID="asrt_123" Version="2.0">
            <saml:Subject>
                <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">alice@acme.com</saml:NameID>
            </saml:Subject>
            <saml:AttributeStatement>
                <saml:Attribute Name="email">
                    <saml:AttributeValue>alice@acme.com</saml:AttributeValue>
                </saml:Attribute>
                <saml:Attribute Name="name">
                    <saml:AttributeValue>Alice Smith</saml:AttributeValue>
                </saml:Attribute>
                <saml:Attribute Name="groups">
                    <saml:AttributeValue>IT-Admins</saml:AttributeValue>
                    <saml:AttributeValue>Engineering</saml:AttributeValue>
                </saml:Attribute>
            </saml:AttributeStatement>
        </saml:Assertion>
    </samlp:Response>"""

    b64_response = base64.b64encode(sample_response_xml.encode("utf-8")).decode("utf-8")

    # C-1: Calling parse_saml_response without an IdP X.509 certificate must fail closed
    with pytest.raises(ValueError, match="requires an IdP X.509 certificate"):
        parse_saml_response(b64_response)

    # Signed assertion verifies signature cleanly
    private_key, cert_pem = _generate_test_idp_keypair()
    _, signed_b64 = _build_signed_saml_response(
        private_key,
        email="alice@acme.com",
        assertion_id="_asrt_attrs_1",
        response_id="_resp_attrs_1",
    )
    with patch("src.sso.saml._verify_saml_signature", return_value=True):
        profile = parse_saml_response(b64_response, idp_cert_pem=cert_pem)
    assert profile.email == "alice@acme.com"
    assert profile.name == "Alice Smith"
    assert "IT-Admins" in profile.groups
    assert "Engineering" in profile.groups

    signed_profile = parse_saml_response(signed_b64, idp_cert_pem=cert_pem)
    assert signed_profile.email == "alice@acme.com"


# ──────────────────────────────────────────────────────────────────
# 2. Corporate Directory Group to RBAC Role Mapping Engine Tests
# ──────────────────────────────────────────────────────────────────

def test_role_mapping_engine():
    mapping_config = json.dumps({
        "Corporate-Admins": "admin",
        "Technical-Writers": "editor",
        "Tier-2-Support": "editor",
        "Employees": "user"
    })

    # Match Admin group
    assert RoleMappingEngine.resolve_role(["Employees", "Corporate-Admins"], mapping_config) == "admin"

    # Match Editor group
    assert RoleMappingEngine.resolve_role(["Employees", "Technical-Writers"], mapping_config) == "editor"

    # Priority tiering: Admin overrides Editor when user is in both groups
    assert RoleMappingEngine.resolve_role(["Technical-Writers", "Corporate-Admins"], mapping_config) == "admin"

    # Fallback to default when no matching corporate group
    assert RoleMappingEngine.resolve_role(["Unknown-Group"], mapping_config, default_role="user") == "user"
    assert RoleMappingEngine.resolve_role([], mapping_config, default_role="user") == "user"


# ──────────────────────────────────────────────────────────────────
# 3. Redis-Backed Centralized Session Revocation & Token Blacklist
# ──────────────────────────────────────────────────────────────────

def test_redis_session_revocation():
    import uuid
    # Test token blacklisting by unique JTI
    jti = f"test-jti-{uuid.uuid4().hex}"
    assert is_token_blacklisted(jti) is False
    blacklist_token(jti, expires_in_seconds=60)
    assert is_token_blacklisted(jti) is True

    # Test user session revocation
    user_id = int(time.time() * 1000) % 900000 + 10000
    now = int(time.time())
    old_iat = now - 50
    future_iat = now + 50

    assert is_session_revoked(user_id=user_id, token_iat=old_iat) is False
    revoke_user_sessions(user_id=user_id)
    # Old token before revocation is revoked
    assert is_session_revoked(user_id=user_id, token_iat=old_iat) is True
    # Future token issued after revocation is valid
    assert is_session_revoked(user_id=user_id, token_iat=future_iat) is False

    # Test tenant session revocation
    tenant_id = int(time.time() * 1000) % 800000 + 20000
    assert is_session_revoked(user_id=user_id + 1, tenant_id=tenant_id, token_iat=old_iat) is False
    revoke_tenant_sessions(tenant_id=tenant_id)
    assert is_session_revoked(user_id=user_id + 1, tenant_id=tenant_id, token_iat=old_iat) is True


# ──────────────────────────────────────────────────────────────────
# 4. Domain Auto-Discovery & Enforce SSO Gating API Endpoints
# ──────────────────────────────────────────────────────────────────

def test_sso_discover_endpoint():
    # Email matching Acme Corp (tenant 1)
    res = client.get("/auth/sso/discover?email=user@acme.com")
    assert res.status_code == 200
    data = res.json()
    assert data["sso_enabled"] is True
    assert data["tenant_id"] == 1
    assert data["idp_type"] == "saml"
    assert "/auth/sso/saml/login?tenant_id=1" in data["login_url"]

    # Non-configured email domain
    res_other = client.get("/auth/sso/discover?email=stranger@randomcorp.io")
    assert res_other.status_code == 200
    data_other = res_other.json()
    assert data_other["sso_enabled"] is False


def test_enforce_sso_login_gate():
    db = TestingSessionLocal()
    from src.auth import get_password_hash
    # Create user belonging to Tenant 1
    u = User(
        username="acme_employee",
        hashed_password=get_password_hash("password123"),
        role="user",
        tenant_id=1,
        is_platform_admin=False
    )
    db.add(u)
    db.commit()
    db.close()

    # When enforce_sso is False, password login succeeds
    login_res = client.post("/auth/login", json={"username": "acme_employee", "password": "password123"})
    assert login_res.status_code == 200, f"Expected 200, got: {login_res.status_code} {login_res.text}"

    # Turn on enforce_sso
    db = TestingSessionLocal()
    cfg = db.query(TenantSSOConfig).filter(TenantSSOConfig.tenant_id == 1).first()
    cfg.enforce_sso = True
    db.commit()
    db.close()

    # Now password login must be blocked with 403 Forbidden
    blocked_res = client.post("/auth/login", json={"username": "acme_employee", "password": "password123"})
    assert blocked_res.status_code == 403
    assert "Single Sign-On (SSO) is enforced" in blocked_res.json()["detail"]

    # Verify Break-Glass Access for Tenant SuperAdmin
    db = TestingSessionLocal()
    sa = User(
        username="acme_superadmin",
        hashed_password=get_password_hash("breakglasspass"),
        role="superadmin",
        tenant_id=1,
        is_platform_admin=False
    )
    db.add(sa)
    db.commit()
    db.close()

    sa_res = client.post("/auth/login", json={"username": "acme_superadmin", "password": "breakglasspass"})
    assert sa_res.status_code == 200, f"SuperAdmin break-glass failed: {sa_res.text}"
    assert sa_res.json()["role"] == "superadmin"


def test_saml_assertion_expired_rejected():
    expired_xml = """<?xml version="1.0"?>
    <samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
                    xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
                    ID="resp_exp" Version="2.0">
        <samlp:Status>
            <samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>
        </samlp:Status>
        <saml:Assertion ID="asrt_exp" Version="2.0">
            <saml:Conditions NotBefore="2020-01-01T00:00:00Z" NotOnOrAfter="2020-01-02T00:00:00Z"/>
            <saml:Subject>
                <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">bob@acme.com</saml:NameID>
            </saml:Subject>
        </saml:Assertion>
    </samlp:Response>"""
    b64 = base64.b64encode(expired_xml.encode("utf-8")).decode("ascii")

    with pytest.raises(ValueError, match="expired"):
        parse_saml_response(b64)


def test_saml_audience_restriction_mismatch_rejected():
    future_time = "2099-01-01T00:00:00Z"
    sample_xml = f"""<?xml version="1.0"?>
    <samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
                    xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
                    ID="resp_aud" Version="2.0">
        <samlp:Status>
            <samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>
        </samlp:Status>
        <saml:Assertion ID="asrt_aud" Version="2.0">
            <saml:Conditions NotBefore="2020-01-01T00:00:00Z" NotOnOrAfter="{future_time}">
                <saml:AudienceRestriction>
                    <saml:Audience>https://attacker-sp.internal/metadata</saml:Audience>
                </saml:AudienceRestriction>
            </saml:Conditions>
            <saml:Subject>
                <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">bob@acme.com</saml:NameID>
            </saml:Subject>
        </saml:Assertion>
    </samlp:Response>"""
    b64 = base64.b64encode(sample_xml.encode("utf-8")).decode("ascii")

    with pytest.raises(ValueError, match="Audience restriction failed"):
        parse_saml_response(b64, expected_recipient="https://my-app.internal/auth/sso/saml/metadata")


def test_saml_replay_attack_prevention():
    import uuid
    unique_assertion_id = f"ID_assert_{uuid.uuid4().hex}"
    # First time processing assertion ID succeeds
    assert check_and_record_assertion_id(unique_assertion_id, ttl_seconds=60) is True
    # Second time with identical assertion ID is blocked as replay
    assert check_and_record_assertion_id(unique_assertion_id, ttl_seconds=60) is False


def test_saml_multiple_assertions_xsw_rejected():
    xsw_xml = """<?xml version="1.0"?>
    <samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
                    xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
                    ID="resp_xsw" Version="2.0">
        <samlp:Status>
            <samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>
        </samlp:Status>
        <saml:Assertion ID="asrt_legit" Version="2.0">
            <saml:Subject>
                <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">bob@acme.com</saml:NameID>
            </saml:Subject>
        </saml:Assertion>
        <saml:Assertion ID="asrt_injected" Version="2.0">
            <saml:Subject>
                <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">evil@attacker.com</saml:NameID>
            </saml:Subject>
        </saml:Assertion>
    </samlp:Response>"""
    b64 = base64.b64encode(xsw_xml.encode("utf-8")).decode("ascii")

    with pytest.raises(ValueError, match="Multiple assertions found"):
        parse_saml_response(b64)


def test_auth_logout_blacklists_token():
    """Verify that /auth/logout adds JWT jti to blacklist and blacklisted tokens are blocked."""
    from src.auth import create_access_token, SECRET_KEY, ALGORITHM
    import jwt

    test_token = create_access_token({"sub": "logout_tester", "tenant_id": 1, "role": "user"})
    payload = jwt.decode(test_token, SECRET_KEY, algorithms=[ALGORITHM])
    jti = payload["jti"]

    assert not is_token_blacklisted(jti)

    # Call logout
    res = client.post("/auth/logout", headers={"Authorization": f"Bearer {test_token}"})
    assert res.status_code == 200
    assert res.json()["message"] == "Successfully logged out"

    # Token must now be blacklisted
    assert is_token_blacklisted(jti)


def test_oidc_csrf_state_validation():
    """Verify /auth/sso/oidc/callback strictly validates state parameter."""
    # 1. Missing state is rejected
    res_no_state = client.post(
        "/auth/sso/oidc/callback",
        json={"code": "auth_code_123", "redirect_uri": "http://localhost:3000/auth/callback", "tenant_id": 1}
    )
    assert res_no_state.status_code == 400
    assert "state parameter is required" in res_no_state.json()["detail"]

    # 2. Forged / invalid state is rejected
    res_invalid_state = client.post(
        "/auth/sso/oidc/callback",
        json={"code": "auth_code_123", "redirect_uri": "http://localhost:3000/auth/callback", "tenant_id": 1, "state": "forged_state_xyz"}
    )
    assert res_invalid_state.status_code == 400
    assert "OIDC state validation failed" in res_invalid_state.json()["detail"]


def test_cross_tenant_sso_spoofing_prevented():
    """Verify SAML ACS prevents cross-tenant identity spoofing if email belongs to another tenant."""
    db = TestingSessionLocal()
    # Create Tenant 2
    t2 = Tenant(id=2, name="Victim Org", slug="victim-org", status="active", allowed_domains="victim.com")
    db.add(t2)
    # Create user in Tenant 2 with email alice@victim.com
    victim_user = User(
        id=200,
        username="alice_victim",
        email="alice@victim.com",
        role="user",
        tenant_id=2,
        is_platform_admin=False
    )
    db.add(victim_user)
    db.commit()
    db.close()

    # Now attempt SAML ACS on Tenant 1 asserting alice@victim.com
    import uuid
    future_time = "2099-01-01T00:00:00Z"
    unique_assert_id = f"asrt_spoof_{uuid.uuid4().hex}"
    spoof_xml = f"""<?xml version="1.0"?>
    <samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
                    xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
                    ID="resp_spoof_{uuid.uuid4().hex}" Version="2.0">
        <samlp:Status>
            <samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>
        </samlp:Status>
        <saml:Assertion ID="{unique_assert_id}" Version="2.0">
            <saml:Conditions NotBefore="2020-01-01T00:00:00Z" NotOnOrAfter="{future_time}">
                <saml:AudienceRestriction>
                    <saml:Audience>https://knowledge.alphalabs.nurexia.co/auth/sso/saml/metadata</saml:Audience>
                </saml:AudienceRestriction>
            </saml:Conditions>
            <saml:Subject>
                <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">alice@victim.com</saml:NameID>
            </saml:Subject>
        </saml:Assertion>
    </samlp:Response>"""
    b64_spoof = base64.b64encode(spoof_xml.encode("utf-8")).decode("ascii")

    with patch("src.sso.saml._verify_saml_signature", return_value=True):
        res = client.post("/auth/sso/saml/acs", data={"SAMLResponse": b64_spoof, "RelayState": "tenant_1"})
        assert res.status_code == 403
        assert "belongs to another organization" in res.json()["detail"]


def test_sso_revoke_endpoint():
    """Verify /auth/sso/revoke enforces explicit targets and handles tenant-scoped revoking."""
    # Seed tenant user in test DB
    db = TestingSessionLocal()
    u = User(id=1, username="tenant_superadmin", role="superadmin", tenant_id=1, is_platform_admin=False)
    db.merge(u)
    db.commit()
    db.close()

    # 1. Empty payload rejected with 400
    res_empty = client.post("/auth/sso/revoke", json={})
    assert res_empty.status_code == 400
    assert "Explicit revocation target required" in res_empty.json()["detail"]

    # 2. Targeted user revocation succeeds
    res_user = client.post("/auth/sso/revoke", json={"user_id": 1, "reason": "Security rotation"})
    assert res_user.status_code == 200
    assert res_user.json()["status"] == "success"


def test_sso_ssrf_and_unsafe_scheme_rejected():
    """Verify SSO config & OIDC discovery reject unsafe schemes and internal/metadata IPs."""
    import pytest
    from src.sso.oidc import discover_oidc_endpoints

    # Ensure tenant 1 exists and admin mock is clean
    db = TestingSessionLocal()
    if not db.query(Tenant).filter(Tenant.id == 1).first():
        db.add(Tenant(id=1, name="Acme Corp", slug="acme-corp"))
    db.commit()
    db.close()

    unsafe_targets = [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8000/internal",
        "http://redis:6379/",
        "https://10.0.0.5/sso",
    ]
    for bad_url in unsafe_targets:
        res_saml = client.post(
            "/admin/sso/config",
            json={"idp_type": "saml", "is_enabled": True, "idp_sso_url": bad_url},
        )
        assert res_saml.status_code == 400, f"Expected 400 for idp_sso_url={bad_url}, got {res_saml.status_code}"

        res_oidc = client.post(
            "/admin/sso/config",
            json={"idp_type": "oidc", "is_enabled": True, "oidc_issuer_url": bad_url},
        )
        assert res_oidc.status_code == 400, f"Expected 400 for oidc_issuer_url={bad_url}, got {res_oidc.status_code}"

        with pytest.raises(ValueError):
            discover_oidc_endpoints(bad_url)


def test_cross_tenant_corporate_domain_hijacking_blocked():
    """Verify Tenant B cannot claim an allowed corporate domain already owned by Tenant A."""
    from api.dependencies import get_current_user

    db = TestingSessionLocal()
    db.merge(Tenant(id=1, name="Acme Corp", slug="acme-corp", allowed_domains="acme.com"))
    db.merge(Tenant(id=2, name="Rival Corp", slug="rival-corp", allowed_domains="rival.com"))
    db.merge(User(id=1, username="acme_admin", role="superadmin", tenant_id=1))
    db.merge(User(id=2, username="rival_admin", role="superadmin", tenant_id=2))
    db.commit()
    db.close()

    rival_admin = User(id=2, username="rival_admin", role="superadmin", tenant_id=2)
    orig_overrides = app.dependency_overrides.copy()
    try:
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: rival_admin

        # 1. Rival attempts to claim acme.com via PATCH /auth/tenant/domains
        res_patch = client.patch("/auth/tenant/domains", json={"allowed_domains": "acme.com"})
        assert res_patch.status_code == 409

        # 2. Rival attempts to claim acme.com via POST /admin/sso/config
        res_sso = client.post(
            "/admin/sso/config",
            json={
                "idp_type": "saml",
                "is_enabled": False,
                "allowed_domains": "acme.com",
            },
        )
        assert res_sso.status_code == 409
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig_overrides)


def test_access_request_replay_and_superadmin_guard():
    """Verify non-pending access requests cannot be replayed and superadmin role cannot be overwritten."""
    from api.dependencies import get_current_user
    from src.models import AccessRequest

    db = TestingSessionLocal()
    db.merge(Tenant(id=1, name="Acme Corp", slug="acme-corp"))
    db.merge(User(id=1, username="super_owner", role="superadmin", tenant_id=1))
    db.merge(User(id=3, username="member_bob", role="user", tenant_id=1))
    db.query(AccessRequest).filter(AccessRequest.id.in_([901, 902])).delete()
    db.add(AccessRequest(id=901, user_id=3, tenant_id=1, requested_role="editor", status="approved"))
    db.add(AccessRequest(id=902, user_id=1, tenant_id=1, requested_role="editor", status="pending"))
    db.commit()
    db.close()

    super_owner = User(id=1, username="super_owner", role="superadmin", tenant_id=1)
    orig_overrides = app.dependency_overrides.copy()
    try:
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: super_owner

        # Replay approve/reject on already approved request 901 -> 400
        assert client.post("/admin/requests/901/approve").status_code == 400
        assert client.post("/admin/requests/901/reject").status_code == 400

        # Approving request targeting superadmin -> 400 (cannot demote superadmin)
        res_super = client.post("/admin/requests/902/approve")
        assert res_super.status_code == 400
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig_overrides)


def test_google_oauth_rejects_unverified_email():
    """Verify Google OAuth rejects accounts whose email_verified claim is false."""
    import io
    import pytest
    from unittest.mock import patch
    from src.oauth import _exchange_google_code

    class FakeResp:
        def __init__(self, payload: dict):
            self._data = json.dumps(payload).encode("utf-8")

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    responses = [
        FakeResp({"access_token": "tok_123"}),
        FakeResp({"email": "spoof@acme.com", "sub": "g-sub-1", "email_verified": False}),
    ]

    with patch("src.oauth.urllib.request.urlopen", side_effect=responses), \
         patch("src.oauth.GOOGLE_CLIENT_ID", "cid"), \
         patch("src.oauth.GOOGLE_CLIENT_SECRET", "csec"):
        with pytest.raises(ValueError, match="not verified"):
            _exchange_google_code("code_1", "https://app.example.com/callback")


def _generate_test_idp_keypair():
    """Generate an ephemeral RSA-2048 keypair and self-signed X.509 cert PEM for SAML tests."""
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-idp.acme.com")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .sign(private_key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    return private_key, cert_pem


def _build_signed_saml_response(
    private_key,
    email: str = "alice@acme.com",
    issuer: str = "https://idp.acme.com/metadata",
    assertion_id: str = "_assert_1",
    response_id: str = "_resp_1",
    name_id_inner: str = None,
    include_assertion_id: bool = True,
) -> tuple[str, str]:
    """Build a canonical Exclusive-C14N XMLDSig-signed SAML 2.0 Response.

    Returns (raw_xml, base64_encoded_xml).
    """
    from datetime import datetime, timedelta, timezone
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    now = datetime.now(timezone.utc)
    not_before = (now - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    not_on_or_after = (now + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    name_id_xml = name_id_inner if name_id_inner is not None else email

    def _sign_target(target_xml: str, ref_id: str) -> str:
        digest = hashes.Hash(hashes.SHA256())
        digest.update(target_xml.encode("utf-8"))
        digest_b64 = base64.b64encode(digest.finalize()).decode("ascii")

        signed_info_xml = (
            '<ds:SignedInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
            '<ds:CanonicalizationMethod Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"></ds:CanonicalizationMethod>'
            '<ds:SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"></ds:SignatureMethod>'
            f'<ds:Reference URI="#{ref_id}">'
            '<ds:Transforms>'
            '<ds:Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"></ds:Transform>'
            '<ds:Transform Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"></ds:Transform>'
            '</ds:Transforms>'
            '<ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"></ds:DigestMethod>'
            f'<ds:DigestValue>{digest_b64}</ds:DigestValue>'
            '</ds:Reference>'
            '</ds:SignedInfo>'
        )
        sig_bytes = private_key.sign(
            signed_info_xml.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        sig_b64 = base64.b64encode(sig_bytes).decode("ascii")
        return (
            '<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
            f"{signed_info_xml}"
            f"<ds:SignatureValue>{sig_b64}</ds:SignatureValue>"
            "</ds:Signature>"
        )

    id_attr = f'ID="{assertion_id}" ' if include_assertion_id else ""
    assertion_body = (
        f"<saml:Issuer>{issuer}</saml:Issuer>"
        f'<saml:Subject><saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{name_id_xml}</saml:NameID></saml:Subject>'
        f'<saml:Conditions NotBefore="{not_before}" NotOnOrAfter="{not_on_or_after}"></saml:Conditions>'
    )
    assertion_open = f'<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" {id_attr}Version="2.0">'
    status_xml = '<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"></samlp:StatusCode></samlp:Status>'

    if include_assertion_id:
        unsigned_assertion = f"{assertion_open}{assertion_body}</saml:Assertion>"
        sig_xml = _sign_target(unsigned_assertion, assertion_id)
        signed_assertion = (
            f"{assertion_open}<saml:Issuer>{issuer}</saml:Issuer>{sig_xml}"
            f'<saml:Subject><saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{name_id_xml}</saml:NameID></saml:Subject>'
            f'<saml:Conditions NotBefore="{not_before}" NotOnOrAfter="{not_on_or_after}"></saml:Conditions>'
            "</saml:Assertion>"
        )
        full_xml = (
            f'<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" ID="{response_id}" Version="2.0">'
            f"{status_xml}{signed_assertion}</samlp:Response>"
        )
    else:
        unsigned_assertion = f"{assertion_open}{assertion_body}</saml:Assertion>"
        unsigned_resp = (
            f'<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" ID="{response_id}" Version="2.0">'
            f"{status_xml}{unsigned_assertion}</samlp:Response>"
        )
        sig_xml = _sign_target(unsigned_resp, response_id)
        full_xml = (
            f'<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" ID="{response_id}" Version="2.0">'
            f"{sig_xml}{status_xml}{unsigned_assertion}</samlp:Response>"
        )

    b64 = base64.b64encode(full_xml.encode("utf-8")).decode("ascii")
    return full_xml, b64


def test_saml_acs_rejects_unsigned_without_relay_state_or_cert():
    """Unsigned assertions without matching RelayState/IdP cert must return 400 and never fall back to Tenant 1."""
    unsigned_xml = """<?xml version="1.0"?>
    <samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
                    xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
                    ID="_resp_unverified" Version="2.0">
        <samlp:Status>
            <samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>
        </samlp:Status>
        <saml:Assertion ID="_asrt_unverified" Version="2.0">
            <saml:Issuer>https://unknown-idp.evil.com/metadata</saml:Issuer>
            <saml:Subject>
                <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">victim@acme.com</saml:NameID>
            </saml:Subject>
        </saml:Assertion>
    </samlp:Response>"""
    b64 = base64.b64encode(unsigned_xml.encode("utf-8")).decode("ascii")

    # Missing RelayState + unknown Issuer must fail closed (never fall back to Tenant 1)
    res_no_relay = client.post("/auth/sso/saml/acs", data={"SAMLResponse": b64})
    assert res_no_relay.status_code == 400

    # Tenant configured with SAML enabled but missing X.509 cert must also reject with 400
    with TestingSessionLocal() as db:
        t2 = Tenant(id=2, name="No Cert Org", slug="nocert", allowed_domains="nocert.com", status="active")
        db.add(t2)
        db.add(TenantSSOConfig(
            tenant_id=2,
            idp_type="saml",
            is_enabled=True,
            idp_entity_id="https://idp.nocert.com/metadata",
            idp_sso_url="https://idp.nocert.com/sso",
            idp_x509_cert="",
            allowed_domains="nocert.com",
        ))
        db.commit()

    res_no_cert = client.post(
        "/auth/sso/saml/acs",
        data={"SAMLResponse": b64, "RelayState": "tenant_2"},
    )
    assert res_no_cert.status_code == 400


def test_saml_xmldsig_signed_assertion_and_digest_tamper_rejected():
    """Verify valid XMLDSig passes and NameID tampering fails Reference DigestValue verification."""
    private_key, cert_pem = _generate_test_idp_keypair()
    raw_xml, b64 = _build_signed_saml_response(private_key, email="alice@acme.com", assertion_id="_asrt_signed_1")

    profile = parse_saml_response(b64, idp_cert_pem=cert_pem)
    assert profile.email == "alice@acme.com"

    # Tamper NameID without updating SignedInfo / SignatureValue
    tampered_xml = raw_xml.replace(">alice@acme.com<", ">admin@acme.com<")
    assert tampered_xml != raw_xml
    tampered_b64 = base64.b64encode(tampered_xml.encode("utf-8")).decode("ascii")

    with pytest.raises(ValueError, match="(?i)digest|signature"):
        parse_saml_response(tampered_b64, idp_cert_pem=cert_pem)


def test_saml_rejects_xml_comment_injection():
    """XML comments inside Assertion (even when validly signed) must be rejected."""
    private_key, cert_pem = _generate_test_idp_keypair()
    _, b64 = _build_signed_saml_response(
        private_key,
        name_id_inner="alice@acme.com<!--evil-->@attacker.com",
        assertion_id="_asrt_comment_1",
    )

    with pytest.raises(ValueError, match="(?i)comment"):
        parse_saml_response(b64, idp_cert_pem=cert_pem)

    with TestingSessionLocal() as db:
        cfg = db.query(TenantSSOConfig).filter(TenantSSOConfig.tenant_id == 1).first()
        cfg.idp_x509_cert = cert_pem
        db.commit()

    res = client.post(
        "/auth/sso/saml/acs",
        data={"SAMLResponse": b64, "RelayState": "tenant_1"},
    )
    assert res.status_code == 400


def test_saml_acs_replay_without_assertion_id_and_fragment_redirect():
    """Verify browser redirect uses URL #token= fragment and replay protection blocks reused assertions."""
    import uuid

    private_key, cert_pem = _generate_test_idp_keypair()
    with TestingSessionLocal() as db:
        cfg = db.query(TenantSSOConfig).filter(TenantSSOConfig.tenant_id == 1).first()
        cfg.idp_x509_cert = cert_pem
        db.commit()

    _, b64 = _build_signed_saml_response(
        private_key,
        email="alice@acme.com",
        response_id=f"_resp_noid_{uuid.uuid4().hex}",
        include_assertion_id=False,
    )

    res1 = client.post(
        "/auth/sso/saml/acs",
        data={"SAMLResponse": b64, "RelayState": "tenant_1"},
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert res1.status_code == 303
    location = res1.headers.get("location", "")
    assert "#token=" in location
    assert "?token=" not in location

    # Replaying identical assertion without an Assertion ID attribute must still be blocked
    res2 = client.post(
        "/auth/sso/saml/acs",
        data={"SAMLResponse": b64, "RelayState": "tenant_1"},
    )
    assert res2.status_code in (400, 401, 403)


def test_oauth_only_user_password_login_returns_401():
    """OAuth/SAML users with hashed_password=None must get 401 on password login, not 500."""
    with TestingSessionLocal() as db:
        db.add(User(
            username="sso_only_user",
            email="sso_only@acme.com",
            hashed_password=None,
            auth_provider="saml",
            oauth_id="saml_sso_only_user",
            tenant_id=1,
            role="user",
        ))
        db.commit()

    res = client.post(
        "/auth/login",
        json={"username": "sso_only_user", "password": "any-password"},
    )
    assert res.status_code == 401


def test_oauth_callback_validates_state_and_enforces_sso():
    """Social OAuth callback requires valid single-use CSRF state and respects TenantSSOConfig.enforce_sso."""
    with TestingSessionLocal() as db:
        t2 = Tenant(id=2, name="Locked Corp", slug="locked-corp", allowed_domains="lockedcorp.com", status="active")
        db.add(t2)
        db.add(TenantSSOConfig(
            tenant_id=2,
            idp_type="saml",
            is_enabled=True,
            enforce_sso=True,
            idp_entity_id="https://idp.lockedcorp.com/metadata",
            idp_sso_url="https://idp.lockedcorp.com/sso",
            allowed_domains="lockedcorp.com",
        ))
        db.commit()

    with patch("src.oauth.GOOGLE_CLIENT_ID", "cid"):
        auth_res = client.get(
            "/auth/oauth/google/authorize",
            params={"redirect_uri": "http://localhost:3000/auth/callback"},
        )
    assert auth_res.status_code == 200
    valid_state = auth_res.json()["state"]

    # Missing or invalid state must fail 400
    bad_state_res = client.post(
        "/auth/oauth/google/callback",
        json={
            "code": "auth_code_bad",
            "redirect_uri": "http://localhost:3000/auth/callback",
            "state": "forged_csrf_state",
        },
    )
    assert bad_state_res.status_code == 400

    class FakeResp:
        def __init__(self, payload: dict):
            self._data = json.dumps(payload).encode("utf-8")

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    responses = [
        FakeResp({"access_token": "tok_google"}),
        FakeResp({"email": "bob@lockedcorp.com", "sub": "g-bob-1", "name": "Bob", "email_verified": True}),
    ]

    with patch("src.oauth.urllib.request.urlopen", side_effect=responses), \
         patch("src.oauth.GOOGLE_CLIENT_ID", "cid"), \
         patch("src.oauth.GOOGLE_CLIENT_SECRET", "csec"):
        blocked_res = client.post(
            "/auth/oauth/google/callback",
            json={
                "code": "auth_code_1",
                "redirect_uri": "http://localhost:3000/auth/callback",
                "state": valid_state,
            },
        )
    assert blocked_res.status_code == 403

    # Reusing already-consumed state must fail 400
    replay_state_res = client.post(
        "/auth/oauth/google/callback",
        json={
            "code": "auth_code_1",
            "redirect_uri": "http://localhost:3000/auth/callback",
            "state": valid_state,
        },
    )
    assert replay_state_res.status_code == 400


def test_github_oauth_rejects_unverified_email():
    """Verify GitHub OAuth checks /user/emails and rejects unverified profile emails."""
    from src.oauth import _exchange_github_code

    class FakeResp:
        def __init__(self, payload):
            self._data = json.dumps(payload).encode("utf-8")

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    responses = [
        FakeResp({"access_token": "gh_tok_123"}),
        FakeResp({"id": 999, "login": "spoof", "email": "ceo@acme.com"}),
        FakeResp([{"email": "ceo@acme.com", "verified": False, "primary": True}]),
    ]

    with patch("src.oauth.urllib.request.urlopen", side_effect=responses), \
         patch("src.oauth.GITHUB_CLIENT_ID", "gh_cid"), \
         patch("src.oauth.GITHUB_CLIENT_SECRET", "gh_csec"):
        with pytest.raises(ValueError, match="verified email"):
            _exchange_github_code("code_gh", "http://localhost:3000/auth/callback")


def test_saml_subject_confirmation_recipient_validation():
    """C-2: Reject SubjectConfirmationData Recipient targeting a different SP while accepting our ACS URL."""
    _, cert_pem = _generate_test_idp_keypair()
    future_time = "2099-01-01T00:00:00Z"

    def _make_xml(recipient: str) -> str:
        xml = f"""<?xml version="1.0"?>
        <samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
                        xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
                        ID="_resp_recip" Version="2.0">
            <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
            <saml:Assertion ID="_asrt_recip" Version="2.0">
                <saml:Subject>
                    <saml:NameID>alice@acme.com</saml:NameID>
                    <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
                        <saml:SubjectConfirmationData Recipient="{recipient}" NotOnOrAfter="{future_time}"/>
                    </saml:SubjectConfirmation>
                </saml:Subject>
                <saml:Conditions NotBefore="2020-01-01T00:00:00Z" NotOnOrAfter="{future_time}"/>
            </saml:Assertion>
        </samlp:Response>"""
        return base64.b64encode(xml.encode("utf-8")).decode("ascii")

    with patch("src.sso.saml._verify_saml_signature", return_value=True):
        with pytest.raises(ValueError, match="Recipient mismatch"):
            parse_saml_response(
                _make_xml("https://evil-sp.attacker.com/acs"),
                expected_recipient="https://app.example.com/auth/sso/saml/metadata",
                expected_acs_url="https://app.example.com/auth/sso/saml/acs",
                idp_cert_pem=cert_pem,
            )

        ok_profile = parse_saml_response(
            _make_xml("https://app.example.com/auth/sso/saml/acs"),
            expected_recipient="https://app.example.com/auth/sso/saml/metadata",
            expected_acs_url="https://app.example.com/auth/sso/saml/acs",
            idp_cert_pem=cert_pem,
        )
        assert ok_profile.email == "alice@acme.com"


def test_oidc_nonce_generation_and_callback_verification():
    """C-3: OIDC authorize sends nonce and callback rejects mismatched or stripped ID token nonce."""
    with TestingSessionLocal() as db:
        cfg = db.query(TenantSSOConfig).filter(TenantSSOConfig.tenant_id == 1).first()
        cfg.idp_type = "oidc"
        cfg.oidc_issuer_url = "https://idp.acme.com"
        cfg.oidc_client_id = "oidc_cid"
        cfg.oidc_client_secret = "oidc_csec"
        db.commit()

    fake_endpoints = {
        "authorization_endpoint": "https://idp.acme.com/authorize",
        "token_endpoint": "https://idp.acme.com/token",
        "userinfo_endpoint": "https://idp.acme.com/userinfo",
        "jwks_uri": "https://idp.acme.com/keys",
        "issuer": "https://idp.acme.com",
    }
    with patch("src.sso.oidc.discover_oidc_endpoints", return_value=fake_endpoints):
        auth_res = client.get("/auth/sso/oidc/authorize?tenant_id=1&redirect_uri=http://localhost:3000/auth/callback")
    assert auth_res.status_code == 200
    body = auth_res.json()
    assert "nonce=" in body["redirect_url"]
    state = body["state"]

    # Callback with wrong nonce in ID token must fail 400
    spoof_profile = SSOUserProfile(
        email="alice@acme.com",
        name="Alice",
        oauth_id="sub-1",
        provider="oidc",
        nonce="wrong_nonce",
    )
    with patch("api.sso.exchange_oidc_code", return_value=spoof_profile):
        cb_res = client.post(
            "/auth/sso/oidc/callback",
            json={
                "code": "code_123",
                "redirect_uri": "http://localhost:3000/auth/callback",
                "tenant_id": 1,
                "state": state,
            },
        )
    assert cb_res.status_code == 400
    assert "nonce verification failed" in cb_res.json()["detail"]



