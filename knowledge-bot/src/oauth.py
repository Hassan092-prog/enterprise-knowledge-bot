import os
import json
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any
from src.logger import get_logger

logger = get_logger(__name__)

# OAuth Provider Credentials from Environment
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")

MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET", "")
MICROSOFT_TENANT_ID = os.getenv("MICROSOFT_TENANT_ID", "common")


def _get_google_creds():
    return os.getenv("GOOGLE_CLIENT_ID") or GOOGLE_CLIENT_ID, os.getenv("GOOGLE_CLIENT_SECRET") or GOOGLE_CLIENT_SECRET


def _get_github_creds():
    return os.getenv("GITHUB_CLIENT_ID") or GITHUB_CLIENT_ID, os.getenv("GITHUB_CLIENT_SECRET") or GITHUB_CLIENT_SECRET


def _get_microsoft_creds():
    cid = os.getenv("MICROSOFT_CLIENT_ID") or MICROSOFT_CLIENT_ID
    csec = os.getenv("MICROSOFT_CLIENT_SECRET") or MICROSOFT_CLIENT_SECRET
    tid = os.getenv("MICROSOFT_TENANT_ID") or MICROSOFT_TENANT_ID or "common"
    return cid, csec, tid


def get_available_oauth_providers() -> Dict[str, bool]:
    """Returns availability status for configured OAuth providers."""
    g_id, g_sec = _get_google_creds()
    gh_id, gh_sec = _get_github_creds()
    ms_id, ms_sec, _ = _get_microsoft_creds()
    return {
        "google": bool(g_id and g_sec),
        "github": bool(gh_id and gh_sec),
        "microsoft": bool(ms_id and ms_sec),
    }


def generate_oauth_authorization_url(provider: str, redirect_uri: str, state: Optional[str] = None) -> str:
    """Constructs the provider-specific OAuth2 authorization URL."""
    prov = provider.lower().strip()
    state_val = state or f"{prov}_oauth_session"

    if prov == "google":
        client_id, _ = _get_google_creds()
        if not client_id:
            raise ValueError("Google OAuth is not configured. Please set GOOGLE_CLIENT_ID in your environment.")
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "select_account",
            "state": state_val,
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

    elif prov == "github":
        client_id, _ = _get_github_creds()
        if not client_id:
            raise ValueError("GitHub OAuth is not configured. Please set GITHUB_CLIENT_ID in your environment.")
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state_val,
        }
        return f"https://github.com/login/oauth/authorize?{urllib.parse.urlencode(params)}"

    elif prov == "microsoft":
        client_id, _, tenant_id = _get_microsoft_creds()
        if not client_id:
            raise ValueError("Microsoft OAuth is not configured. Please set MICROSOFT_CLIENT_ID in your environment.")
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid profile email User.Read",
            "state": state_val,
        }
        return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?{urllib.parse.urlencode(params)}"

    else:
        raise ValueError(f"Unsupported OAuth provider: '{provider}'")


def exchange_oauth_code(provider: str, code: str, redirect_uri: str) -> Dict[str, Any]:
    """
    Exchanges an OAuth authorization code for verified user identity profile.
    Returns standardized dict: { email, name, oauth_id, avatar_url, provider }
    """
    prov = provider.lower().strip()

    if prov == "google":
        return _exchange_google_code(code, redirect_uri)
    elif prov == "github":
        return _exchange_github_code(code, redirect_uri)
    elif prov == "microsoft":
        return _exchange_microsoft_code(code, redirect_uri)
    else:
        raise ValueError(f"Unsupported OAuth provider: '{provider}'")


def _exchange_google_code(code: str, redirect_uri: str) -> Dict[str, Any]:
    """Exchange code with Google OAuth2."""
    client_id, client_secret = _get_google_creds()
    token_url = "https://oauth2.googleapis.com/token"
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Google token exchange failed: {e}")
        raise ValueError(f"Failed to exchange Google OAuth code: {str(e)}")

    access_token = token_data.get("access_token")
    if not access_token:
        raise ValueError("Google did not return an access token.")

    # Fetch user profile
    userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
    user_req = urllib.request.Request(userinfo_url)
    user_req.add_header("Authorization", f"Bearer {access_token}")

    try:
        with urllib.request.urlopen(user_req, timeout=15) as user_resp:
            profile = json.loads(user_resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Google userinfo request failed: {e}")
        raise ValueError(f"Failed to fetch Google profile: {str(e)}")

    email = profile.get("email")
    if not email:
        raise ValueError("Google profile did not contain a valid email address.")
    email_verified = profile.get("email_verified")
    if email_verified is not True and str(email_verified or "").strip().lower() != "true":
        raise ValueError("Google account email address is not verified.")

    return {
        "email": email.lower().strip(),
        "name": profile.get("name") or email.split("@")[0],
        "oauth_id": str(profile.get("sub")),
        "avatar_url": profile.get("picture"),
        "provider": "google",
    }


def _exchange_github_code(code: str, redirect_uri: str) -> Dict[str, Any]:
    """Exchange code with GitHub OAuth."""
    client_id, client_secret = _get_github_creds()
    token_url = "https://github.com/login/oauth/access_token"
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=data, method="POST")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"GitHub token exchange failed: {e}")
        raise ValueError(f"Failed to exchange GitHub OAuth code: {str(e)}")

    access_token = token_data.get("access_token")
    if not access_token:
        raise ValueError("GitHub did not return an access token.")

    # Fetch user profile
    user_req = urllib.request.Request("https://api.github.com/user")
    user_req.add_header("Authorization", f"Bearer {access_token}")
    user_req.add_header("User-Agent", "EnterpriseKnowledgeBot")

    try:
        with urllib.request.urlopen(user_req, timeout=15) as user_resp:
            profile = json.loads(user_resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"GitHub user profile request failed: {e}")
        raise ValueError(f"Failed to fetch GitHub profile: {str(e)}")

    # Always verify email ownership via GitHub /user/emails endpoint
    emails_req = urllib.request.Request("https://api.github.com/user/emails")
    emails_req.add_header("Authorization", f"Bearer {access_token}")
    emails_req.add_header("User-Agent", "EnterpriseKnowledgeBot")
    verified_emails = []
    primary_verified_email = None
    try:
        with urllib.request.urlopen(emails_req, timeout=15) as em_resp:
            emails_list = json.loads(em_resp.read().decode("utf-8"))
            for em in emails_list:
                if em.get("verified") and em.get("email"):
                    verified_emails.append(em.get("email"))
                    if em.get("primary") and not primary_verified_email:
                        primary_verified_email = em.get("email")
    except Exception as e:
        raise ValueError(f"Failed to verify GitHub account email addresses: {e}")

    profile_email = profile.get("email")
    if primary_verified_email:
        email = primary_verified_email
    elif profile_email and profile_email in verified_emails:
        email = profile_email
    elif verified_emails:
        email = verified_emails[0]
    else:
        raise ValueError("GitHub account does not have a verified email address.")

    return {
        "email": email.lower().strip(),
        "name": profile.get("name") or profile.get("login"),
        "oauth_id": str(profile.get("id")),
        "avatar_url": profile.get("avatar_url"),
        "provider": "github",
    }


def _exchange_microsoft_code(code: str, redirect_uri: str) -> Dict[str, Any]:
    """Exchange code with Microsoft Entra / 365 OAuth."""
    client_id, client_secret, tenant_id = _get_microsoft_creds()
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Microsoft token exchange failed: {e}")
        raise ValueError(f"Failed to exchange Microsoft OAuth code: {str(e)}")

    access_token = token_data.get("access_token")
    if not access_token:
        raise ValueError("Microsoft did not return an access token.")

    # Fetch Microsoft Graph Me
    me_req = urllib.request.Request("https://graph.microsoft.com/v1.0/me")
    me_req.add_header("Authorization", f"Bearer {access_token}")

    try:
        with urllib.request.urlopen(me_req, timeout=15) as me_resp:
            profile = json.loads(me_resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Microsoft Graph request failed: {e}")
        raise ValueError(f"Failed to fetch Microsoft profile: {str(e)}")

    email = profile.get("mail") or profile.get("userPrincipalName")
    if not email:
        raise ValueError("Microsoft profile did not contain an email address.")

    return {
        "email": email.lower().strip(),
        "name": profile.get("displayName") or email.split("@")[0],
        "oauth_id": str(profile.get("id")),
        "avatar_url": None,
        "provider": "microsoft",
    }
