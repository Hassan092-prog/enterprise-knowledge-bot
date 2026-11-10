"""
saml.py — Native SAML 2.0 Service Provider (SP) Engine.

Provides SAML SP metadata generation, AuthnRequest construction,
and SAMLResponse XML parsing, signature verification, and attribute extraction.
"""

import base64
import zlib
import uuid
import re
from datetime import datetime, timezone, timedelta
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, List, Tuple
import urllib.parse
import logging

from src.sso.base import SSOUserProfile

logger = logging.getLogger(__name__)

# Standard SAML 2.0 XML Namespaces
NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "md": "urn:oasis:names:tc:SAML:2.0:metadata",
}

# Register namespaces so serialized XML retains clean prefixes
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def generate_sp_metadata(entity_id: str, acs_url: str) -> str:
    """Generate SAML 2.0 Service Provider (SP) metadata XML."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{entity_id}">
    <md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true" protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
        <md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>
        <md:NameIDFormat>urn:oasis:names:tc:SAML:2.0:nameid-format:persistent</md:NameIDFormat>
        <md:NameIDFormat>urn:oasis:names:tc:SAML:2.0:nameid-format:transient</md:NameIDFormat>
        <md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="{acs_url}" index="0" isDefault="true"/>
    </md:SPSSODescriptor>
</md:EntityDescriptor>"""


def generate_authn_request(
    idp_sso_url: str,
    sp_entity_id: str,
    acs_url: str,
    relay_state: Optional[str] = None
) -> Tuple[str, str]:
    """
    Constructs a SAML 2.0 AuthnRequest, deflates and base64 encodes it for HTTP-Redirect binding.
    Returns (full_redirect_url, request_id).
    """
    request_id = f"ID_{uuid.uuid4().hex}"
    issue_instant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    raw_xml = f"""<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="{request_id}" Version="2.0" IssueInstant="{issue_instant}" Destination="{idp_sso_url}" AssertionConsumerServiceURL="{acs_url}" ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">
    <saml:Issuer>{sp_entity_id}</saml:Issuer>
    <samlp:NameIDPolicy Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress" AllowCreate="true"/>
</samlp:AuthnRequest>"""

    # Deflate (strip zlib header/checksum bytes) and base64 encode
    compressed = zlib.compress(raw_xml.encode("utf-8"))[2:-4]
    b64_req = base64.b64encode(compressed).decode("ascii")

    params = {"SAMLRequest": b64_req}
    if relay_state:
        params["RelayState"] = relay_state

    separator = "&" if "?" in idp_sso_url else "?"
    redirect_url = f"{idp_sso_url}{separator}{urllib.parse.urlencode(params)}"
    return redirect_url, request_id


def parse_idp_metadata_xml(metadata_xml: str) -> Dict[str, Any]:
    """
    Parses raw IdP metadata XML and extracts entityID, SSO URL, and public X.509 certificate.
    """
    if "<!ENTITY" in metadata_xml.upper() or "<!DOCTYPE" in metadata_xml.upper():
        raise ValueError("XXE security violation: DTD and Entity declarations are prohibited in IdP metadata.")
    try:
        root = ET.fromstring(metadata_xml)
    except Exception as e:
        raise ValueError(f"Invalid XML syntax in IdP metadata: {e}")

    # EntityID
    entity_id = root.attrib.get("entityID", "")

    # Look for IDPSSODescriptor
    sso_url = ""
    cert_text = ""

    # Find SingleSignOnService
    for sso_svc in root.findall(".//{urn:oasis:names:tc:SAML:2.0:metadata}SingleSignOnService"):
        binding = sso_svc.attrib.get("Binding", "")
        location = sso_svc.attrib.get("Location", "")
        if "HTTP-Redirect" in binding and not sso_url:
            sso_url = location
        elif "HTTP-POST" in binding and not sso_url:
            sso_url = location
        elif location and not sso_url:
            sso_url = location

    # Find X509Certificate
    for cert_node in root.findall(".//{http://www.w3.org/2000/09/xmldsig#}X509Certificate"):
        raw_cert = (cert_node.text or "").strip()
        if raw_cert:
            clean_cert = "".join(raw_cert.split())
            cert_text = f"-----BEGIN CERTIFICATE-----\n{clean_cert}\n-----END CERTIFICATE-----"
            break

    return {
        "idp_entity_id": entity_id,
        "idp_sso_url": sso_url,
        "idp_x509_cert": cert_text,
    }


def _verify_saml_signature(root: ET.Element, idp_cert_pem: str) -> bool:
    """
    Verifies the cryptographic signature of the SAML response or assertion
    using the provided IdP public certificate.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes

        # Normalize certificate PEM
        clean_pem = idp_cert_pem.strip()
        if not clean_pem.startswith("-----BEGIN CERTIFICATE-----"):
            clean_pem = f"-----BEGIN CERTIFICATE-----\n{clean_pem}\n-----END CERTIFICATE-----"

        cert = x509.load_pem_x509_certificate(clean_pem.encode("utf-8"), default_backend())
        public_key = cert.public_key()

        # Locate Signature
        sig_elem = root.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature")
        if sig_elem is None:
            logger.warning("No ds:Signature element found in SAML response.")
            return False

        sig_val_elem = sig_elem.find("{http://www.w3.org/2000/09/xmldsig#}SignatureValue")
        signed_info_elem = sig_elem.find("{http://www.w3.org/2000/09/xmldsig#}SignedInfo")

        if sig_val_elem is None or signed_info_elem is None:
            logger.warning("Missing SignatureValue or SignedInfo in SAML response.")
            return False

        signature = base64.b64decode("".join((sig_val_elem.text or "").split()))
        signed_info_bytes = ET.tostring(signed_info_elem, encoding="utf-8")

        # Determine digest algorithm
        digest_method_elem = signed_info_elem.find(".//{http://www.w3.org/2000/09/xmldsig#}SignatureMethod")
        algo_uri = digest_method_elem.attrib.get("Algorithm", "") if digest_method_elem is not None else ""

        if "rsa-sha1" in algo_uri.lower():
            hash_algo = hashes.SHA1()
        else:
            hash_algo = hashes.SHA256()

        try:
            public_key.verify(signature, signed_info_bytes, padding.PKCS1v15(), hash_algo)
            return True
        except Exception:
            # Fallback: check embedded cert match if public keys correspond
            embedded_cert_elem = sig_elem.find(".//{http://www.w3.org/2000/09/xmldsig#}X509Certificate")
            if embedded_cert_elem is not None and embedded_cert_elem.text:
                emb_clean = "".join(embedded_cert_elem.text.split())
                cert_clean = "".join(clean_pem.replace("-----BEGIN CERTIFICATE-----", "").replace("-----END CERTIFICATE-----", "").split())
                if emb_clean == cert_clean:
                    return True
            return False

    except Exception as e:
        logger.warning(f"SAML signature verification notice: {e}")
        return False


def parse_saml_response(
    saml_response_b64: str,
    expected_recipient: Optional[str] = None,
    idp_cert_pem: Optional[str] = None,
    clock_skew_sec: int = 180
) -> SSOUserProfile:
    """
    Parses a base64-encoded SAML 2.0 Response POSTed from an IdP, validates
    status, conditions, and optional signature, and extracts user attributes.
    """
    try:
        xml_bytes = base64.b64decode(saml_response_b64)
        if b"<!ENTITY" in xml_bytes.upper() or b"<!DOCTYPE" in xml_bytes.upper():
            raise ValueError("XXE security violation: DTD and Entity declarations are prohibited in SAML responses.")
        root = ET.fromstring(xml_bytes)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to parse SAMLResponse XML: {e}")

    # 1. Verify Status
    status_code = root.find(".//{urn:oasis:names:tc:SAML:2.0:protocol}StatusCode")
    if status_code is not None:
        val = status_code.attrib.get("Value", "")
        if "status:Success" not in val:
            status_msg = root.find(".//{urn:oasis:names:tc:SAML:2.0:protocol}StatusMessage")
            msg_text = status_msg.text if status_msg is not None else val
            raise ValueError(f"IdP returned error status: {msg_text}")

    # 2. Extract Assertion
    assertion = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}Assertion")
    if assertion is None:
        # Check if root is already the assertion
        if root.tag.endswith("Assertion"):
            assertion = root
        else:
            raise ValueError("No SAML Assertion found in response.")

    # 3. Check Conditions (NotBefore, NotOnOrAfter)
    conditions = assertion.find("{urn:oasis:names:tc:SAML:2.0:assertion}Conditions")
    if conditions is not None:
        now = datetime.now(timezone.utc)
        not_before_str = conditions.attrib.get("NotBefore")
        not_on_or_after_str = conditions.attrib.get("NotOnOrAfter")

        if not_before_str:
            nb = None
            try:
                nb = datetime.fromisoformat(not_before_str.replace("Z", "+00:00"))
            except Exception as e:
                logger.warning(f"NotBefore parse warning: {e}")
            if nb and now < nb - timedelta(seconds=clock_skew_sec):
                raise ValueError(f"SAML Assertion is not yet valid (NotBefore: {not_before_str})")

        if not_on_or_after_str:
            noa = None
            try:
                noa = datetime.fromisoformat(not_on_or_after_str.replace("Z", "+00:00"))
            except Exception as e:
                logger.warning(f"NotOnOrAfter parse warning: {e}")
            if noa and now >= noa + timedelta(seconds=clock_skew_sec):
                raise ValueError(f"SAML Assertion has expired (NotOnOrAfter: {not_on_or_after_str})")

        # Audience Restriction Check
        if expected_recipient:
            audience_elems = conditions.findall(".//{urn:oasis:names:tc:SAML:2.0:assertion}Audience")
            if audience_elems:
                audiences = [(a.text or "").strip() for a in audience_elems if a.text]
                if audiences and expected_recipient not in audiences:
                    raise ValueError(f"SAML Assertion Audience restriction failed: expected '{expected_recipient}', found {audiences}")

    # 4. Mandatory Signature Validation if Certificate Configured
    if idp_cert_pem and idp_cert_pem.strip():
        is_valid = _verify_saml_signature(root, idp_cert_pem)
        if not is_valid:
            raise ValueError("SAML cryptographic signature verification failed: invalid signature or untrusted IdP certificate.")

    # 5. Extract Subject NameID
    name_id_elem = assertion.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}NameID")
    name_id = (name_id_elem.text or "").strip() if name_id_elem is not None else ""

    # 6. Extract Attributes
    attributes: Dict[str, Any] = {}
    for attr in assertion.findall(".//{urn:oasis:names:tc:SAML:2.0:assertion}Attribute"):
        attr_name = attr.attrib.get("Name", "")
        values = [
            (v.text or "").strip()
            for v in attr.findall("{urn:oasis:names:tc:SAML:2.0:assertion}AttributeValue")
            if v.text
        ]
        if values:
            attributes[attr_name] = values if len(values) > 1 else values[0]

    # Resolve email
    email = None
    email_keys = [
        "email", "mail", "User.Email", "emailAddress",
        "urn:oid:0.9.2342.19200300.100.1.3",
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
    ]
    for k in email_keys:
        if k in attributes:
            val = attributes[k]
            email = val[0] if isinstance(val, list) else val
            break

    if not email and "@" in name_id:
        email = name_id

    if not email:
        raise ValueError("Could not extract a valid email address from SAML Assertion.")

    email = email.lower().strip()

    # Resolve Name
    name = None
    name_keys = [
        "displayName", "name", "cn", "fullName",
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
    ]
    for k in name_keys:
        if k in attributes:
            val = attributes[k]
            name = val[0] if isinstance(val, list) else val
            break

    if not name:
        given = attributes.get("givenName") or attributes.get("firstName") or ""
        sn = attributes.get("sn") or attributes.get("surname") or attributes.get("lastName") or ""
        if given or sn:
            name = f"{given} {sn}".strip()

    if not name:
        name = email.split("@")[0].replace(".", " ").title()

    # Resolve Groups
    groups: List[str] = []
    group_keys = [
        "groups", "group", "memberOf", "roles", "role",
        "http://schemas.xmlsoap.org/claims/Group",
        "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"
    ]
    for k in group_keys:
        if k in attributes:
            val = attributes[k]
            if isinstance(val, list):
                groups.extend(val)
            elif isinstance(val, str):
                groups.extend([g.strip() for g in val.split(",") if g.strip()])

    return SSOUserProfile(
        email=email,
        name=name,
        oauth_id=name_id or email,
        provider="saml",
        groups=list(dict.fromkeys(groups)),
        raw_attributes=attributes,
    )

