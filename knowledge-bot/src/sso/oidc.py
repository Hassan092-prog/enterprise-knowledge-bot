"""
oidc.py — Enterprise OpenID Connect (OIDC) & OAuth2 Client Engine.

Provides dynamic discovery (.well-known/openid-configuration), authorization code exchange,
user profile resolution, and directory groups extraction across Okta, Microsoft Entra,
Google Workspace, Keycloak, and generic OIDC Identity Providers.
"""

import json
import base64
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, List
import logging

from src.sso.base import SSOUserProfile

logger = logging.getLogger(__name__)

# Discovery Cache: { issuer_url: { "authorization_endpoint": ..., "token_endpoint": ..., ... } }
_OIDC_DISCOVERY_CACHE: Dict[str, Dict[str, str]] = {}


def discover_oidc_endpoints(issuer_url: str) -> Dict[str, str]:
    """
    Fetches and caches the OpenID Connect discovery document (.well-known/openid-configuration).
    """
    clean_issuer = issuer_url.rstrip("/")
    if clean_issuer in _OIDC_DISCOVERY_CACHE:
        return _OIDC_DISCOVERY_CACHE[clean_issuer]

    well_known_url = f"{clean_issuer}/.well-known/openid-configuration"
    req = urllib.request.Request(well_known_url)
    req.add_header("User-Agent", "EnterpriseKnowledgeBot-SSO/2.0")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            endpoints = {
                "authorization_endpoint": data.get("authorization_endpoint", f"{clean_issuer}/v1/authorize"),
                "token_endpoint": data.get("token_endpoint", f"{clean_issuer}/v1/token"),
                "userinfo_endpoint": data.get("userinfo_endpoint", f"{clean_issuer}/v1/userinfo"),
                "jwks_uri": data.get("jwks_uri", ""),
                "issuer": data.get("issuer", clean_issuer),
            }
            _OIDC_DISCOVERY_CACHE[clean_issuer] = endpoints
            return endpoints
    except Exception as e:
        logger.warning(f"OIDC discovery failed for {well_known_url} ({e}). Falling back to convention endpoints.")
        # Fallback to standard RFC endpoints
        fallback = {
            "authorization_endpoint": f"{clean_issuer}/oauth2/v1/authorize",
            "token_endpoint": f"{clean_issuer}/oauth2/v1/token",
            "userinfo_endpoint": f"{clean_issuer}/oauth2/v1/userinfo",
            "jwks_uri": f"{clean_issuer}/oauth2/v1/keys",
            "issuer": clean_issuer,
        }
        _OIDC_DISCOVERY_CACHE[clean_issuer] = fallback
        return fallback


def generate_oidc_authorization_url(
    issuer_url: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: str = "openid email profile groups"
) -> str:
    """Constructs the OIDC authorization redirection URL."""
    endpoints = discover_oidc_endpoints(issuer_url)
    auth_endpoint = endpoints["authorization_endpoint"]

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "state": state,
    }
    separator = "&" if "?" in auth_endpoint else "?"
    return f"{auth_endpoint}{separator}{urllib.parse.urlencode(params)}"


def _decode_jwt_payload_unverified(jwt_token: str) -> Dict[str, Any]:
    """Safely decodes JWT claims payload without signature verification."""
    try:
        parts = jwt_token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1]
            # Add padding
            rem = len(payload_b64) % 4
            if rem > 0:
                payload_b64 += "=" * (4 - rem)
            decoded = base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
            return json.loads(decoded)
    except Exception as e:
        logger.warning(f"Error parsing ID token JWT claims: {e}")
    return {}


def exchange_oidc_code(
    issuer_url: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str
) -> SSOUserProfile:
    """
    Exchanges an authorization code at the OIDC token endpoint, parses claims,
    and returns a normalized SSOUserProfile.
    """
    endpoints = discover_oidc_endpoints(issuer_url)
    token_url = endpoints["token_endpoint"]

    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "EnterpriseKnowledgeBot-SSO/2.0")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_res = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"OIDC token exchange request failed: {e}")
        raise ValueError(f"Failed to exchange OIDC authorization code: {str(e)}")

    access_token = token_res.get("access_token")
    id_token = token_res.get("id_token")

    claims: Dict[str, Any] = {}
    if id_token:
        claims.update(_decode_jwt_payload_unverified(id_token))

    # Fetch UserInfo if available
    userinfo_endpoint = endpoints.get("userinfo_endpoint")
    if access_token and userinfo_endpoint:
        try:
            u_req = urllib.request.Request(userinfo_endpoint)
            u_req.add_header("Authorization", f"Bearer {access_token}")
            u_req.add_header("Accept", "application/json")
            u_req.add_header("User-Agent", "EnterpriseKnowledgeBot-SSO/2.0")
            with urllib.request.urlopen(u_req, timeout=10) as u_resp:
                userinfo_data = json.loads(u_resp.read().decode("utf-8"))
                claims.update(userinfo_data)
        except Exception as ue:
            logger.warning(f"OIDC userinfo fetch warning: {ue}")

    # Extract email
    email = claims.get("email") or claims.get("upn") or claims.get("preferred_username")
    if not email:
        raise ValueError("OIDC identity payload did not contain a valid email address.")
    email = str(email).lower().strip()

    # Extract name
    name = claims.get("name") or claims.get("displayName")
    if not name:
        given = claims.get("given_name", "")
        family = claims.get("family_name", "")
        if given or family:
            name = f"{given} {family}".strip()
    if not name:
        name = email.split("@")[0].title()

    oauth_id = str(claims.get("sub") or email)

    # Extract Directory Groups
    groups: List[str] = []
    group_claims = ["groups", "roles", "memberOf", "wids"]
    for gc in group_claims:
        if gc in claims:
            val = claims[gc]
            if isinstance(val, list):
                groups.extend([str(g).strip() for g in val if g])
            elif isinstance(val, str):
                groups.extend([g.strip() for g in val.split(",") if g.strip()])

    return SSOUserProfile(
        email=email,
        name=name,
        oauth_id=oauth_id,
        provider="oidc",
        groups=list(dict.fromkeys(groups)),
        raw_attributes=claims,
        avatar_url=claims.get("picture"),
    )

