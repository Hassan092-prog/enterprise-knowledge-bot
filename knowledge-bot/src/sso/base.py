"""
base.py — Core data structures and interfaces for Enterprise Single Sign-On (SSO).
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class SSOUserProfile:
    """Standardized user identity profile returned by any IdP (SAML / OIDC / OAuth2)."""
    email: str
    name: str
    oauth_id: str
    provider: str  # 'saml', 'oidc', 'okta', 'google', 'microsoft', 'github'
    tenant_id: Optional[int] = None
    groups: List[str] = field(default_factory=list)
    raw_attributes: Dict[str, Any] = field(default_factory=dict)
    avatar_url: Optional[str] = None
    assertion_id: Optional[str] = None


class RoleMappingEngine:
    """
    Evaluates corporate directory groups against tenant role mappings
    to determine application RBAC privilege tier ('user', 'editor', 'admin').
    """

    ROLE_PRIORITY = {
        "user": 1,
        "editor": 2,
        "admin": 3,
        "superadmin": 4,
    }

    @classmethod
    def resolve_role(
        cls,
        directory_groups: List[str],
        role_mapping_json: Optional[str],
        default_role: str = "user"
    ) -> str:
        """
        Maps directory groups (e.g. ['IT-Security', 'All-Employees']) to an application role.
        Selects the highest privilege role if the user belongs to multiple mapped groups.
        """
        if not role_mapping_json or not role_mapping_json.strip():
            return default_role if default_role in cls.ROLE_PRIORITY else "user"

        try:
            mapping = json.loads(role_mapping_json)
            if not isinstance(mapping, dict):
                return default_role
        except Exception as e:
            logger.warning(f"Failed to parse role_mapping_json: {e}")
            return default_role

        resolved_role = default_role
        highest_priority = cls.ROLE_PRIORITY.get(resolved_role, 1)

        # Normalize directory groups for case-insensitive matching
        group_set = {g.strip().lower() for g in directory_groups if g and g.strip()}

        for map_group, map_role in mapping.items():
            if not map_group or not map_role:
                continue
            
            clean_map_group = map_group.strip().lower()
            clean_map_role = map_role.strip().lower()

            if clean_map_group in group_set:
                prio = cls.ROLE_PRIORITY.get(clean_map_role, 1)
                # Group mapping can grant up to 'admin'; 'superadmin' is strictly tenant owner
                if prio > highest_priority and clean_map_role in ("user", "editor", "admin"):
                    highest_priority = prio
                    resolved_role = clean_map_role

        return resolved_role

