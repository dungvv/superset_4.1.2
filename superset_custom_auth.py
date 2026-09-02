"""
Custom Authentication for Superset using External API
This module provides authentication via external API integration
"""

import os
import requests
import logging
from typing import Optional

from flask import current_app, g, has_request_context, session
from flask_appbuilder.security.sqla.models import User

# Import SupersetSecurityManager from Superset
try:
    from superset.security.manager import SupersetSecurityManager
except ImportError:
    # Fallback for older versions
    from flask_appbuilder.security.sqla.manager import (
        SecurityManager as SupersetSecurityManager,
    )

logger = logging.getLogger(__name__)

BASE_URL = "http://10.120.54.43:8088"
CLIENT_ID = os.getenv("EXT_CLIENT_ID")
CLIENT_SECRET = os.getenv("EXT_CLIENT_SECRET")
USERNAME = os.getenv("EXT_USERNAME")
PASSWORD = os.getenv("EXT_PASSWORD")

# Map groupRoleCode from partner API → exact Superset role name (ab_role.name).
ROLE_MAPPING = {
    "ADM": "Admin",
    "ADMIN": "Admin",
    "GRP_ALPHA": "Alpha",
    "ALPHA": "Alpha",
    "GAMMA": "Gamma",
    "PUBLIC": "Public",
}

ALWAYS_INCLUDE_ROLES = ["sql_lab", "Jinja Template"]


class ExternalAPIAuthManager(SupersetSecurityManager):
    """
    Custom Security Manager that authenticates users via External API
    """

    def get_token(self):
        """
        Gửi yêu cầu đến /ewallet/token để lấy access_token.
        """
        url = f"{BASE_URL}/ewallet/token"

        auth = (CLIENT_ID, CLIENT_SECRET)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {"username": USERNAME, "password": PASSWORD, "grant_type": "password"}
        logger.debug("🔹 Requesting access token...")
        response = requests.post(url, headers=headers, data=data, auth=auth)

        if response.status_code != 200:
            return None

        token_info = response.json()
        access_token = token_info.get("access_token")
        logger.debug("✅ Access token retrieved successfully.")
        return access_token

    def partner_login(self, access_token, username, password):
        """
        Gửi yêu cầu đến /api/v1.0/partner/login với Bearer token.

        Đặt tên `partner_login` (không phải login_user) để không đè
        Flask-Login / FAB `login_user` — hàm đó dùng để gắn session đăng nhập.
        """
        url = f"{BASE_URL}/api/v1.0/partner/login"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        payload = {"loginId": username, "password": password}

        logger.debug("🔹 Logging in with access token...")
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code != 200:
            raise Exception(f"Login failed: {response.status_code}, {response.text}")

        result = response.json()
        if result.get("responseCode") != "00000":
            raise Exception(f"Login failed: {result}")

        logger.debug("✅ Login successful.")
        return result

    def __init__(self, appbuilder):
        super().__init__(appbuilder)
        self.external_api_url = os.getenv("EXTERNAL_API_URL", "")
        self.external_api_token = os.getenv("EXTERNAL_API_TOKEN", "")
        self.external_api_timeout = int(os.getenv("EXTERNAL_API_TIMEOUT", "10"))

    def auth_user_oauth(self, userinfo: dict) -> Optional[User]:
        """
        Authenticate user using OAuth userinfo
        This is called when using OAuth providers
        """
        user = self.find_user(
            username=userinfo.get("username") or userinfo.get("email")
        )
        if not user:
            # Try to authenticate via external API
            if self._verify_external_api(
                userinfo.get("username") or userinfo.get("email"), None
            ):
                user = self.add_user(
                    username=userinfo.get("username") or userinfo.get("email"),
                    first_name=userinfo.get("first_name", ""),
                    last_name=userinfo.get("last_name", ""),
                    email=userinfo.get("email", ""),
                    role=self.find_role("Public"),  # Default role
                )
        return user

    def auth_user_db(self, username: str, password: str) -> Optional[User]:
        """
        Authenticate user using database credentials
        This method is called for standard login form
        """
        # First try to authenticate via external API
        if self._verify_external_api(username, password):
            # Check if user exists in Superset database
            user = self.find_user(username=username)
            if not user:
                # Create user if doesn't exist
                user = self.add_user(
                    username=username,
                    first_name=username.split("@")[0] if "@" in username else username,
                    last_name="",
                    email=username if "@" in username else f"{username}@fetek.vn",
                    role=self.find_role("Public"),  # Default role, can be changed
                )
                logger.info(f"Created new user from external API: {username}")
            return user

        # Fallback to database authentication
        logger.debug("Now try login with database authentication")
        return super().auth_user_db(username, password)

    def _verify_external_api(
        self, username: str, password: Optional[str] = None
    ) -> bool:
        """
        Verify user credentials with external API

        Expected API Response Format:
        {
            "success": true,
            "user": {
                "username": "user@example.com",
                "email": "user@example.com",
                "first_name": "First",
                "last_name": "Last",
                "roles": ["Public", "Gamma"]
            }
        }

        Or for token-based authentication:
        {
            "success": true,
            "user": {...}
        }
        """
        token = self.get_token()
        try:
            login_result = self.partner_login(token, username, password)
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False
        if login_result.get("responseCode") != "00000":
            return False
        role_code = (
            login_result.get("groupRoleCode")
            or login_result.get("groupRoleCode")
            or login_result.get("roleCode")
        )
        user_info = {
            "username": username,
            "email": f"{username}@unitel-report.com",
            "first_name": username,
            "last_name": username,
            "roles": [role_code] if role_code else [],
        }
        session["external_api_user"] = user_info
        logger.info(
            "External API login ok for %s, groupRoleCode=%r", username, role_code
        )
        return True

    def _session_external_user(self) -> dict:
        if not has_request_context():
            return {}
        try:
            return session.get("external_api_user") or {}
        except RuntimeError:
            return {}

    def _find_role_ci(self, name: Optional[str]):
        """find_role, case-insensitive, strip whitespace, then ROLE_MAPPING."""
        if not name or not str(name).strip():
            return None
        raw = str(name).strip()
        mapped = (
            ROLE_MAPPING.get(raw)
            or ROLE_MAPPING.get(raw.upper())
            or ROLE_MAPPING.get(raw.lower())
            or raw
        )
        role = self.find_role(mapped)
        if role:
            return role
        target = mapped.lower()
        try:
            for candidate in self.get_all_roles():
                if candidate.name.lower() == target:
                    return candidate
        except Exception:
            logger.debug("get_all_roles() unavailable for case-insensitive lookup")
        logger.warning("Could not map external role %r to a Superset role", name)
        return None

    def _merge_roles(self, *role_lists) -> list:
        merged = {}
        for roles in role_lists:
            for role in roles or []:
                if role is not None:
                    merged[role.id] = role
        return list(merged.values())

    def _db_roles(self, user: Optional[User]) -> list:
        if not user:
            try:
                user = g.user
            except Exception:
                user = None
        if not user or getattr(user, "is_anonymous", True):
            return []
        try:
            return list(super().get_user_roles(user) or [])
        except Exception:
            return list(getattr(user, "roles", None) or [])

    def get_user_roles(self, user: Optional[User] = None) -> list:
        """
        Union of:
          1. roles in ab_user_role (UI / DB)
          2. mapped groupRoleCode from the login session
          3. ALWAYS_INCLUDE_ROLES

        Previously this method *replaced* DB roles whenever the session had
        external_api_user. Mapping miss + ALWAYS_INCLUDE_ROLES meant the user
        kept sql_lab but lost Admin → 403 on dataset PUT.
        """
        if not user:
            try:
                user = g.user
            except Exception:
                user = None

        if user is not None and getattr(user, "is_anonymous", False):
            public_role = current_app.config.get("AUTH_ROLE_PUBLIC")
            return [self.get_public_role()] if public_role else []

        db_roles = self._db_roles(user)

        external_user = self._session_external_user()
        mapped_roles = []
        if external_user:
            raw_roles = [r for r in (external_user.get("roles") or []) if r]
            mapped_roles = [self._find_role_ci(r) for r in raw_roles]
            extras = [self._find_role_ci(r) for r in ALWAYS_INCLUDE_ROLES]
            mapped_roles = self._merge_roles(mapped_roles, extras)

        final = self._merge_roles(db_roles, mapped_roles)
        if not final:
            public = self.find_role("Public")
            return [public] if public else []

        logger.debug(
            "get_user_roles user=%s db=%s session_raw=%s final=%s",
            getattr(user, "username", None),
            [r.name for r in db_roles],
            (external_user or {}).get("roles"),
            [r.name for r in final],
        )
        return final

    """
    Alternative implementation for token-based authentication
    Useful when external API uses JWT tokens
    """

    # def auth_user_db(self, username: str, password: str) -> Optional[User]:
    #     """
    #     Authenticate using token from external API
    #     """
    #     # Get token from external API
    #     token = self._get_token_from_api(username, password)
    #     if token:
    #         # Verify token and get user info
    #         user_info = self._verify_token(token)
    #         if user_info:
    #             user = self.find_user(username=user_info.get('username'))
    #             if not user:
    #                 user = self.add_user(
    #                     username=user_info.get('username'),
    #                     first_name=user_info.get('first_name', ''),
    #                     last_name=user_info.get('last_name', ''),
    #                     email=user_info.get('email', ''),
    #                     role=self.find_role('Public')
    #                 )
    #             # Store token in session
    #             session['external_api_token'] = token
    #             return user

    #     return super().auth_user_db(username, password)

    def _get_token_from_api(self, username: str, password: str) -> Optional[str]:
        """
        Get authentication token from external API
        """
        try:
            response = requests.post(
                f"{self.external_api_url}/auth/token",
                json={"username": username, "password": password},
                headers={"Content-Type": "application/json"},
                timeout=self.external_api_timeout,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("token") or data.get("access_token")
        except Exception as e:
            logger.error(f"Error getting token from API: {str(e)}")

        return None

    def _verify_token(self, token: str) -> Optional[dict]:
        """
        Verify token and get user info from external API
        """
        try:
            response = requests.get(
                f"{self.external_api_url}/auth/me",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=self.external_api_timeout,
            )

            if response.status_code == 200:
                return response.json().get("user")
        except Exception as e:
            logger.error(f"Error verifying token: {str(e)}")

        return None
