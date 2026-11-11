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


def _collect_utilized_prefixes(elem) -> tuple[bool, set[str]]:
    """Collect visibly utilized namespace prefixes (and default NS usage) across a DOM subtree."""
    uses_default = False
    prefixes: set[str] = set()

    def _walk(node):
        nonlocal uses_default
        if node.nodeType != node.ELEMENT_NODE:
            return
        if node.prefix:
            prefixes.add(node.prefix)
        elif node.namespaceURI:
            uses_default = True
        for i in range(node.attributes.length):
            attr = node.attributes.item(i)
            if attr.name == "xmlns" or attr.name.startswith("xmlns:"):
                continue
            if attr.prefix:
                prefixes.add(attr.prefix)
        for child in node.childNodes:
            _walk(child)

    _walk(elem)
    return uses_default, prefixes


def _canonicalize_dom_subtree(node, exclusive: bool = True, exc_prefix_list: Optional[List[str]] = None) -> bytes:
    """Propagate in-scope xmlns declarations onto a cloned DOM subtree and apply W3C C14N."""
    in_scope: Dict[str, str] = {}
    ancestors = []
    cur = node
    while cur is not None and getattr(cur, "nodeType", None) == cur.ELEMENT_NODE:
        ancestors.append(cur)
        cur = cur.parentNode
    for anc in reversed(ancestors):
        for i in range(anc.attributes.length):
            attr = anc.attributes.item(i)
            if attr.name == "xmlns":
                in_scope[""] = attr.value
            elif attr.name.startswith("xmlns:"):
                in_scope[attr.name[6:]] = attr.value

    clone = node.cloneNode(deep=True)
    if exclusive:
        uses_default, utilized = _collect_utilized_prefixes(clone)
        if exc_prefix_list:
            for p in exc_prefix_list:
                if p == "#default":
                    uses_default = True
                elif p:
                    utilized.add(p)
        if uses_default and "" in in_scope and not clone.hasAttribute("xmlns"):
            clone.setAttribute("xmlns", in_scope[""])
        for p in sorted(utilized):
            if p in in_scope and not clone.hasAttribute(f"xmlns:{p}"):
                clone.setAttribute(f"xmlns:{p}", in_scope[p])
    else:
        for p, uri in sorted(in_scope.items()):
            attr_name = "xmlns" if p == "" else f"xmlns:{p}"
            if not clone.hasAttribute(attr_name):
                clone.setAttribute(attr_name, uri)

    xml_str = clone.toxml()
    return ET.canonicalize(xml_str, with_comments=False).encode("utf-8")


def _hash_algorithm_for_uri(uri: str, hashes):
    low = (uri or "").lower()
    if "sha512" in low:
        return hashes.SHA512()
    if "sha384" in low:
        return hashes.SHA384()
    if "sha1" in low and "sha128" not in low:
        return hashes.SHA1()
    return hashes.SHA256()


def _verify_saml_signature(
    root: ET.Element,
    idp_cert_pem: str,
    raw_xml_bytes: Optional[bytes] = None,
) -> bool:
    """
    Verifies the XMLDSig signature AND Reference DigestValue integrity of a SAML response
    or assertion using the provided IdP public certificate, defending against XSW and digest spoofing.
    """
    try:
        import hashlib
        import hmac
        import xml.dom.minidom as minidom
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes

        XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
        SAML_ASSERT_NS = "urn:oasis:names:tc:SAML:2.0:assertion"

        # Normalize certificate PEM
        clean_pem = idp_cert_pem.strip()
        if not clean_pem.startswith("-----BEGIN CERTIFICATE-----"):
            clean_pem = f"-----BEGIN CERTIFICATE-----\n{clean_pem}\n-----END CERTIFICATE-----"

        cert = x509.load_pem_x509_certificate(clean_pem.encode("utf-8"), default_backend())
        public_key = cert.public_key()

        xml_payload = raw_xml_bytes if raw_xml_bytes is not None else ET.tostring(root, encoding="utf-8")
        dom = minidom.parseString(xml_payload)
        doc_root = dom.documentElement

        # Index IDs across the entire document and reject duplicate ID attributes (XSW defense)
        id_map: Dict[str, Any] = {}
        all_assertions = []
        queue = [doc_root]
        while queue:
            cur = queue.pop(0)
            if cur.nodeType != cur.ELEMENT_NODE:
                continue
            if cur.localName == "Assertion" and cur.namespaceURI == SAML_ASSERT_NS:
                all_assertions.append(cur)
            for i in range(cur.attributes.length):
                attr = cur.attributes.item(i)
                if attr.localName == "ID" or attr.name == "ID":
                    id_val = attr.value
                    if id_val in id_map:
                        logger.warning("Duplicate XML ID detected in SAML document (potential XSW attack).")
                        return False
                    id_map[id_val] = cur
            for ch in cur.childNodes:
                queue.append(ch)

        if len(all_assertions) != 1:
            logger.warning("SAML signature verification requires exactly one Assertion.")
            return False
        assertion_node = all_assertions[0]

        def _direct_sig(parent_node):
            sigs = [
                ch for ch in parent_node.childNodes
                if ch.nodeType == ch.ELEMENT_NODE and ch.localName == "Signature" and ch.namespaceURI == XMLDSIG_NS
            ]
            if len(sigs) > 1:
                return None, True
            return (sigs[0] if sigs else None), False

        assert_sig, dup_assert_sig = _direct_sig(assertion_node)
        root_sig, dup_root_sig = _direct_sig(doc_root) if assertion_node is not doc_root else (None, False)
        if dup_assert_sig or dup_root_sig:
            logger.warning("Multiple direct ds:Signature elements found on SAML container.")
            return False

        sig_node = assert_sig or root_sig
        if sig_node is None:
            logger.warning("No valid direct ds:Signature element found on SAML Assertion or Response.")
            return False

        def _child_by_name(parent_node, local_name: str, ns: str = XMLDSIG_NS):
            for ch in parent_node.childNodes:
                if ch.nodeType == ch.ELEMENT_NODE and ch.localName == local_name and ch.namespaceURI == ns:
                    return ch
            return None

        signed_info_node = _child_by_name(sig_node, "SignedInfo")
        sig_val_node = _child_by_name(sig_node, "SignatureValue")
        if signed_info_node is None or sig_val_node is None:
            logger.warning("Missing SignatureValue or SignedInfo in SAML response.")
            return False

        sig_val_text = "".join(
            ch.data for ch in sig_val_node.childNodes if ch.nodeType in (ch.TEXT_NODE, ch.CDATA_SECTION_NODE)
        )
        signature = base64.b64decode("".join(sig_val_text.split()))

        c14n_elem = _child_by_name(signed_info_node, "CanonicalizationMethod")
        c14n_algo = c14n_elem.getAttribute("Algorithm") if c14n_elem is not None else ""
        is_exc_c14n = ("xml-exc-c14n" in c14n_algo) or (c14n_algo == "")
        signed_info_bytes = _canonicalize_dom_subtree(signed_info_node, exclusive=is_exc_c14n)

        sig_method_elem = _child_by_name(signed_info_node, "SignatureMethod")
        sig_algo_uri = sig_method_elem.getAttribute("Algorithm") if sig_method_elem is not None else ""
        sig_hash_algo = _hash_algorithm_for_uri(sig_algo_uri, hashes)

        try:
            public_key.verify(signature, signed_info_bytes, padding.PKCS1v15(), sig_hash_algo)
        except Exception as verify_err:
            logger.warning(f"SAML public key cryptographic verification failed: {verify_err}")
            return False

        # Verify Reference elements and DigestValues to prevent post-sign assertion tampering
        references = [
            ch for ch in signed_info_node.childNodes
            if ch.nodeType == ch.ELEMENT_NODE and ch.localName == "Reference" and ch.namespaceURI == XMLDSIG_NS
        ]
        if not references:
            logger.warning("SAML SignedInfo contains no ds:Reference elements.")
            return False

        covered_expected_node = False
        allowed_transforms = {
            "http://www.w3.org/2000/09/xmldsig#enveloped-signature",
            "http://www.w3.org/2001/10/xml-exc-c14n#",
            "http://www.w3.org/2001/10/xml-exc-c14n#WithComments",
            "http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
            "http://www.w3.org/TR/2001/REC-xml-c14n-20010315#WithComments",
        }

        for ref in references:
            uri = ref.getAttribute("URI")
            if uri == "":
                target_node = doc_root
            elif uri.startswith("#"):
                ref_id = uri[1:]
                target_node = id_map.get(ref_id)
                if target_node is None:
                    logger.warning(f"SAML Reference URI '{uri}' does not resolve to a unique element.")
                    return False
            else:
                logger.warning(f"Unsupported SAML Reference URI: '{uri}'")
                return False

            if target_node is assertion_node or target_node is doc_root:
                covered_expected_node = True

            digest_method_elem = _child_by_name(ref, "DigestMethod")
            digest_val_elem = _child_by_name(ref, "DigestValue")
            if digest_method_elem is None or digest_val_elem is None:
                logger.warning("SAML Reference missing DigestMethod or DigestValue.")
                return False

            transforms_node = _child_by_name(ref, "Transforms")
            ref_exc_c14n = True
            remove_enveloped_sig = False
            exc_prefix_list: List[str] = []
            if transforms_node is not None:
                t_nodes = [
                    ch for ch in transforms_node.childNodes
                    if ch.nodeType == ch.ELEMENT_NODE and ch.localName == "Transform" and ch.namespaceURI == XMLDSIG_NS
                ]
                for tn in t_nodes:
                    t_algo = tn.getAttribute("Algorithm")
                    if t_algo not in allowed_transforms:
                        logger.warning(f"Unsupported SAML Reference Transform algorithm: '{t_algo}'")
                        return False
                    if "enveloped-signature" in t_algo:
                        remove_enveloped_sig = True
                    elif "REC-xml-c14n-20010315" in t_algo:
                        ref_exc_c14n = False
                    elif "xml-exc-c14n" in t_algo:
                        ref_exc_c14n = True
                        inc_ns = tn.getElementsByTagNameNS("*", "InclusiveNamespaces")
                        if inc_ns:
                            raw_list = inc_ns[0].getAttribute("PrefixList") or ""
                            exc_prefix_list = [p.strip() for p in raw_list.split() if p.strip()]
            elif sig_node.parentNode is target_node:
                remove_enveloped_sig = True

            # Work on an isolated DOM clone and strip enveloped ds:Signature before digesting
            work_doc = minidom.parseString(xml_payload)
            if uri == "":
                ref_clone = work_doc.documentElement
            else:
                ref_id = uri[1:]
                matches = [
                    el for el in work_doc.getElementsByTagName("*")
                    if el.getAttribute("ID") == ref_id
                ]
                if len(matches) != 1:
                    return False
                ref_clone = matches[0]

            if remove_enveloped_sig:
                for ch in list(ref_clone.childNodes):
                    if ch.nodeType == ch.ELEMENT_NODE and ch.localName == "Signature" and ch.namespaceURI == XMLDSIG_NS:
                        ref_clone.removeChild(ch)

            c14n_ref_bytes = _canonicalize_dom_subtree(
                ref_clone, exclusive=ref_exc_c14n, exc_prefix_list=exc_prefix_list
            )
            digest_algo_uri = digest_method_elem.getAttribute("Algorithm")
            digest_low = (digest_algo_uri or "").lower()
            if "sha512" in digest_low:
                computed_digest = hashlib.sha512(c14n_ref_bytes).digest()
            elif "sha384" in digest_low:
                computed_digest = hashlib.sha384(c14n_ref_bytes).digest()
            elif "sha1" in digest_low and "sha128" not in digest_low:
                computed_digest = hashlib.sha1(c14n_ref_bytes).digest()
            else:
                computed_digest = hashlib.sha256(c14n_ref_bytes).digest()

            computed_b64 = base64.b64encode(computed_digest).decode("ascii")
            expected_raw = "".join(
                ch.data for ch in digest_val_elem.childNodes if ch.nodeType in (ch.TEXT_NODE, ch.CDATA_SECTION_NODE)
            )
            expected_b64 = "".join(expected_raw.split())

            if not hmac.compare_digest(computed_b64, expected_b64):
                logger.warning("SAML Reference DigestValue mismatch (assertion tampering detected).")
                return False

        if not covered_expected_node:
            logger.warning("SAML Signature does not cover the Assertion or Response element.")
            return False

        return True

    except Exception as e:
        logger.warning(f"SAML signature verification notice: {e}")
        return False


def extract_saml_issuer(saml_response_b64: str) -> Optional[str]:
    """Safely peek the unverified Issuer element before signature verification to locate IdP config."""
    try:
        xml_bytes = base64.b64decode(saml_response_b64)
        upper_xml = xml_bytes.upper()
        if b"<!ENTITY" in upper_xml or b"<!DOCTYPE" in upper_xml:
            raise ValueError("XXE security violation: DTD and Entity declarations are prohibited in SAML responses.")
        root = ET.fromstring(xml_bytes)
        issuer = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}Issuer")
        if issuer is not None:
            text = "".join(issuer.itertext()).strip()
            return text or None
        return None
    except ValueError:
        raise
    except Exception:
        return None


def _parse_saml_timestamp(ts_str: str, label: str) -> datetime:
    """Strictly parse an ISO-8601 SAML Conditions timestamp with UTC normalization."""
    try:
        dt = datetime.fromisoformat(ts_str.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as e:
        raise ValueError(f"Invalid SAML Conditions {label} timestamp '{ts_str}': {e}")


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
        upper_xml = xml_bytes.upper()
        if b"<!ENTITY" in upper_xml or b"<!DOCTYPE" in upper_xml:
            raise ValueError("XXE security violation: DTD and Entity declarations are prohibited in SAML responses.")
        root = ET.fromstring(xml_bytes)

        # Parse with comments preserved so any XML comments inside Assertion are detected and rejected
        comment_parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        comment_root = ET.fromstring(xml_bytes, parser=comment_parser)
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
            msg_text = "".join(status_msg.itertext()).strip() if status_msg is not None else val
            raise ValueError(f"IdP returned error status: {msg_text}")

    # 2. Extract Assertion (strictly enforce single assertion to defend against XML Signature Wrapping attacks)
    assertions = root.findall(".//{urn:oasis:names:tc:SAML:2.0:assertion}Assertion")
    if not assertions:
        if root.tag.endswith("Assertion"):
            assertion = root
        else:
            raise ValueError("No SAML Assertion found in response.")
    elif len(assertions) > 1:
        raise ValueError("Multiple assertions found in SAML response (potential XML signature wrapping attack).")
    else:
        assertion = assertions[0]

    # Defend against XML Comment Injection inside Assertion (e.g. alice@corp.com<!--x-->@evil.com)
    comment_assertions = comment_root.findall(".//{urn:oasis:names:tc:SAML:2.0:assertion}Assertion")
    if not comment_assertions and comment_root.tag.endswith("Assertion"):
        comment_assertions = [comment_root]
    for ca in comment_assertions:
        if any(elem.tag is ET.Comment for elem in ca.iter()):
            raise ValueError("XML comments are prohibited inside SAML Assertions (XML comment injection defense).")

    assertion_id = assertion.attrib.get("ID") or root.attrib.get("ID") or ""

    # 3. Check Conditions (NotBefore, NotOnOrAfter)
    conditions = assertion.find("{urn:oasis:names:tc:SAML:2.0:assertion}Conditions")
    if conditions is not None:
        now = datetime.now(timezone.utc)
        not_before_str = conditions.attrib.get("NotBefore")
        not_on_or_after_str = conditions.attrib.get("NotOnOrAfter")

        if not_before_str:
            nb = _parse_saml_timestamp(not_before_str, "NotBefore")
            if now < nb - timedelta(seconds=clock_skew_sec):
                raise ValueError(f"SAML Assertion is not yet valid (NotBefore: {not_before_str})")

        if not_on_or_after_str:
            noa = _parse_saml_timestamp(not_on_or_after_str, "NotOnOrAfter")
            if now >= noa + timedelta(seconds=clock_skew_sec):
                raise ValueError(f"SAML Assertion has expired (NotOnOrAfter: {not_on_or_after_str})")

        # Audience Restriction Check
        if expected_recipient:
            audience_elems = conditions.findall(".//{urn:oasis:names:tc:SAML:2.0:assertion}Audience")
            if audience_elems:
                audiences = ["".join(a.itertext()).strip() for a in audience_elems if "".join(a.itertext()).strip()]
                if audiences and expected_recipient not in audiences:
                    raise ValueError(f"SAML Assertion Audience restriction failed: expected '{expected_recipient}', found {audiences}")

    # 4. Mandatory Signature Validation if Certificate Configured
    if idp_cert_pem and idp_cert_pem.strip():
        is_valid = _verify_saml_signature(root, idp_cert_pem, raw_xml_bytes=xml_bytes)
        if not is_valid:
            raise ValueError("SAML cryptographic signature verification failed: invalid signature or untrusted IdP certificate.")

    # 5. Extract Subject NameID
    name_id_elem = assertion.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}NameID")
    name_id = "".join(name_id_elem.itertext()).strip() if name_id_elem is not None else ""

    # 6. Extract Attributes
    attributes: Dict[str, Any] = {}
    for attr in assertion.findall(".//{urn:oasis:names:tc:SAML:2.0:assertion}Attribute"):
        attr_name = attr.attrib.get("Name", "")
        values = [
            "".join(v.itertext()).strip()
            for v in attr.findall("{urn:oasis:names:tc:SAML:2.0:assertion}AttributeValue")
            if "".join(v.itertext()).strip()
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
        assertion_id=assertion_id,
    )

