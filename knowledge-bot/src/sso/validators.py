"""
validators.py — Shared Enterprise SSO security validators.

Prevents SSRF, open XSS/script redirects, and cross-tenant corporate domain hijacking.
"""
import ipaddress
import re
import socket
from typing import List, Optional
from urllib.parse import urlparse
import urllib.request

from fastapi import HTTPException
from sqlalchemy.orm import Session


_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
    "metadata",
    "metadata.google.internal",
    "169.254.169.254",
    "redis",
    "db",
    "postgres",
    "postgresql",
    "chromadb",
    "minio",
    "backend",
    "frontend",
    "worker",
}

_BLOCKED_SUFFIXES = (
    ".local",
    ".localhost",
    ".internal",
    ".arpa",
    ".localdomain",
)


class UnsafeSSOUrlError(ValueError):
    """Raised when an SSO/OIDC URL violates scheme or SSRF protections."""


def _check_ip_global(ip_str: str, field_name: str) -> None:
    ip = ipaddress.ip_address(ip_str)
    mapped = getattr(ip, "ipv4_mapped", None)
    check_ips = [ip] + ([mapped] if mapped is not None else [])
    for candidate in check_ips:
        if (
            candidate.is_private
            or candidate.is_loopback
            or candidate.is_link_local
            or candidate.is_multicast
            or candidate.is_reserved
            or candidate.is_unspecified
            or not candidate.is_global
        ):
            raise UnsafeSSOUrlError(f"{field_name} cannot target private, loopback, or metadata IP addresses.")


def validate_external_sso_url(url: str, field_name: str = "SSO URL", resolve_dns: bool = False) -> str:
    """
    Validate that an external IdP / OIDC URL uses http/https cleanly, contains no
    userinfo/control characters, and does not target internal/private infrastructure.
    """
    if not url or not url.strip():
        raise UnsafeSSOUrlError(f"{field_name} cannot be empty.")

    clean_url = url.strip()
    if any(ch in clean_url for ch in ("\r", "\n", "\x00")):
        raise UnsafeSSOUrlError(f"{field_name} contains invalid control characters.")

    parsed = urlparse(clean_url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("https", "http"):
        raise UnsafeSSOUrlError(f"{field_name} must use http:// or https:// scheme (got '{scheme or 'none'}').")

    if parsed.username or parsed.password:
        raise UnsafeSSOUrlError(f"{field_name} cannot contain embedded credentials.")

    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        raise UnsafeSSOUrlError(f"{field_name} must include a valid hostname.")

    if hostname in _BLOCKED_HOSTNAMES or any(hostname.endswith(sfx) for sfx in _BLOCKED_SUFFIXES):
        raise UnsafeSSOUrlError(f"{field_name} cannot target internal or reserved hostnames ('{hostname}').")

    # Reject single-label hosts (Docker service names like 'redis', integer IPs like '2130706433')
    try:
        _check_ip_global(hostname, field_name)
    except UnsafeSSOUrlError as ip_err:
        raise ip_err
    except ValueError:
        if "." not in hostname:
            raise UnsafeSSOUrlError(f"{field_name} must use a public fully-qualified domain name ('{hostname}').")
        tld = hostname.rsplit(".", 1)[-1]
        if not re.fullmatch(r"[a-z]{2,}", tld):
            raise UnsafeSSOUrlError(f"{field_name} has an invalid domain suffix ('{hostname}').")

    if resolve_dns:
        port = parsed.port or (443 if scheme == "https" else 80)
        try:
            addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
            for item in addr_info:
                resolved_ip = item[4][0].split("%")[0]
                _check_ip_global(resolved_ip, field_name)
        except socket.gaierror:
            # DNS may be unavailable in isolated/mocked test environments; urlopen handles network failures.
            pass

    return clean_url


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validates HTTP redirect Location targets against SSRF rules before following."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_external_sso_url(newurl, "OIDC Redirect URL", resolve_dns=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_and_check_corporate_domains(
    raw_domains: Optional[str],
    tenant_id: int,
    db: Session,
    public_domains: set,
) -> List[str]:
    """
    Parse, validate syntax, reject public email domains, and enforce cross-tenant
    domain uniqueness across both Tenants and TenantSSOConfigs.
    """
    if not raw_domains or not raw_domains.strip():
        return []

    domain_list = [d.strip().lower().rstrip(".") for d in raw_domains.split(",") if d.strip()]
    cleaned_domains: List[str] = []

    for d in domain_list:
        if d in public_domains:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Public consumer email domain '{d}' cannot be used for corporate identity "
                    "auto-routing. Please specify a proprietary corporate domain."
                ),
            )
        if (
            not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", d)
            or ".." in d
            or d.startswith(".")
            or d.endswith(".")
            or d.startswith("-")
            or d.endswith("-")
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid domain format: '{d}'. Expected standard hostname format (e.g. 'company.com').",
            )
        if d not in cleaned_domains:
            cleaned_domains.append(d)

    if cleaned_domains:
        from src.models import Tenant, TenantSSOConfig

        domain_set = set(cleaned_domains)
        other_tenants = db.query(Tenant).filter(Tenant.id != tenant_id, Tenant.allowed_domains.isnot(None)).all()
        for other in other_tenants:
            claimed = {x.strip().lower().rstrip(".") for x in (other.allowed_domains or "").split(",") if x.strip()}
            overlap = domain_set & claimed
            if overlap:
                conflict = sorted(overlap)[0]
                raise HTTPException(
                    status_code=409,
                    detail=f"Corporate domain '{conflict}' is already claimed by another organization.",
                )

        other_cfgs = db.query(TenantSSOConfig).filter(
            TenantSSOConfig.tenant_id != tenant_id,
            TenantSSOConfig.allowed_domains.isnot(None),
        ).all()
        for cfg in other_cfgs:
            claimed = {x.strip().lower().rstrip(".") for x in (cfg.allowed_domains or "").split(",") if x.strip()}
            overlap = domain_set & claimed
            if overlap:
                conflict = sorted(overlap)[0]
                raise HTTPException(
                    status_code=409,
                    detail=f"Corporate domain '{conflict}' is already claimed by another organization's SSO config.",
                )

    return cleaned_domains
