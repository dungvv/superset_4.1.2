"""
Custom Authentication for Superset using External API
This module provides authentication via external API integration
"""

import os
import requests
import logging
from typing import Optional, Any
from flask import redirect, request, session, url_for
from flask_appbuilder.security.manager import AUTH_OAUTH, AUTH_DB
from flask_appbuilder.security.sqla.models import User
from flask_appbuilder import expose
from werkzeug.security import generate_password_hash

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
CLIENT_ID = "REPORT_FETEK"
CLIENT_SECRET = "CLIENT_S9KbBITFtRyW44m"

USERNAME = "REPORT_FETEK"
PASSWORD = "REPORT_nC9FKmUqNVyPqCe"

LOGIN_ID = "sft_cc_timeout"
LOGIN_PASSWORD = "Com@2025"


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
        print(" URL " + url)
        print(data)
        print(auth)

        print("🔹 Requesting access token...")
        response = requests.post(url, headers=headers, data=data, auth=auth)

        if response.status_code != 200:
            return None

        token_info = response.json()
        access_token = token_info.get("access_token")
        print("✅ Access token retrieved successfully.")
        print(access_token)
        return access_token

    def login_user(self, access_token, username, password):
        """
        Gửi yêu cầu đến /api/v1.0/partner/login với Bearer token.
        """
        url = f"{BASE_URL}/api/v1.0/partner/login"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        payload = {"loginId": username, "password": password}

        print("🔹 Logging in with access token...")
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code != 200:
            raise Exception(f"Login failed: {response.status_code}, {response.text}")

        result = response.json()
        if result.get("responseCode") != "00000":
            raise Exception(f"Login failed: {result}")

        print("✅ Login successful.")
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
        print("Now try login with database authentication")
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
            login_result = self.login_user(token, username, password)
        except:
            print("Login failed")
            return False
        if login_result.get("responseCode") != "00000":
            return False
        user_info = {
            "username": username,
            "email": f"{username}@unitel-report.com",
            "first_name": username,
            "last_name": username,
            "roles": [login_result.get("groupRoleCode")],
        }
        session["external_api_user"] = user_info
        return True

    def get_user_roles(self, user: Optional[User] = None) -> list:
        """
        Get user roles from external API if available
        """
        external_user = session.get("external_api_user", {})
        if external_user:
            roles = external_user.get("roles", [])
            # Map external roles to Superset roles
            superset_roles = []
            for role_name in roles:
                role = self.find_role(role_name)
                if role:
                    superset_roles.append(role)
            return superset_roles if superset_roles else [self.find_role("Public")]
        if user:
            if user.is_anonymous:
                public_role = get_conf().get("AUTH_ROLE_PUBLIC")
                return [self.get_public_role()] if public_role else []
            else:
                return super().get_user_roles(user)
        return [self.find_role("Public")]

    @expose("/login/", methods=["GET", "POST"])
    def login(self):
        """
        Custom login view that supports external API authentication
        """
        if request.method == "POST":
            username = request.form.get("username")
            password = request.form.get("password")

            if username and password:
                user = self.auth_user_db(username, password)
                if user:
                    self.appbuilder.sm.login_user(user)
                    return redirect(self.appbuilder.get_url_for_index)

        return super().login()

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
