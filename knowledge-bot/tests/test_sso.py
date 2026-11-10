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


def test_parse_saml_response_unsigned():
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

    import base64
    b64_response = base64.b64encode(sample_response_xml.encode("utf-8")).decode("utf-8")

    profile = parse_saml_response(b64_response)
    assert profile.email == "alice@acme.com"
    assert profile.name == "Alice Smith"
    assert "IT-Admins" in profile.groups
    assert "Engineering" in profile.groups


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


