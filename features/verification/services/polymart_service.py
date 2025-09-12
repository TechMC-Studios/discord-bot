"""Polymart API service for verification."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple
import asyncio

import aiohttp

from core.config import load_config

logger = logging.getLogger(__name__)


class PolymartService:
    """Service for interacting with Polymart API."""

    ############################
    ###### INIT & CONFIG #######
    ############################
    # TODO: Revisar que este quitado lo de las apis por plugin.
    def __init__(self):
        cfg = load_config()
        ver_mod = cfg.module("verification")
        polymart_cfg = ver_mod.get("polymart", {}) if isinstance(ver_mod, dict) else {}

        # API configuration
        self.api_key = str(polymart_cfg.get("api_key", ""))
        self.base_url = str(polymart_cfg.get("base", "https://api.polymart.org/v1"))

        # API endpoints
        self.generate_url_endpoint = f"{self.base_url}/generateUserVerifyURL"
        self.verify_user_endpoint = f"{self.base_url}/verifyUser/"
        self.get_resource_endpoint = f"{self.base_url}/getResourceUserData/"
        self.status_endpoint = f"{self.base_url}/status"
        self.get_account_info_endpoint = f"{self.base_url}/getAccountInfo/"

        # Timeout configuration
        timeout_seconds = float(polymart_cfg.get("timeout_seconds", 10))
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    #########################
    ###### HEALTH CHECK #####
    #########################
    async def check_health(self) -> bool:
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(self.status_endpoint) as resp:
                    if resp.status != 200:
                        logger.error(
                            f"Polymart status check failed with status {resp.status}"
                        )
                        return False
                    return True
        except Exception as e:
            logger.error(f"Polymart API connection error: {e}")
            return False

    ############################################
    ###### ACTIONS: GENERATE & VERIFY TOKEN #####
    ############################################
    async def generate_verification_url(
        self,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Generate a verification URL for the user.

        Returns:
            Tuple of (success, url, error_message)
        """
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(self.generate_url_endpoint) as resp:
                    if resp.status != 200:
                        logger.error(
                            f"Polymart generate URL failed with status {resp.status}"
                        )
                        return False, None, "Failed to generate verification URL"

                    try:
                        data = await resp.json()
                    except Exception as e:
                        logger.error(f"Failed to parse Polymart response: {e}")
                        return False, None, "Invalid response from Polymart"

                    response = data.get("response", {})
                    if not response.get("success"):
                        error_msg = response.get("message", "Unknown error")
                        logger.error(f"Polymart API error: {error_msg}")
                        return False, None, error_msg

                    url = response.get("result", {}).get("url")
                    if not url:
                        logger.error("No URL in Polymart response")
                        return False, None, "No URL received from Polymart"

                    return True, url, None

        except asyncio.TimeoutError:
            logger.error("Polymart API timeout")
            return False, None, "Request timeout"
        except aiohttp.ClientError as e:
            logger.error(f"Polymart API connection error: {e}")
            return False, None, "Connection error"
        except Exception as e:
            logger.error(f"Unexpected error generating Polymart URL: {e}")
            return False, None, "Unexpected error"

    async def verify_token(
        self, token: str
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """Verify a user token from Polymart.

        Args:
            token: The verification token (without dashes)

        Returns:
            Tuple of (success, user_data, error_message)
        """
        try:
            # Clean the token (remove any dashes)
            clean_token = token.replace("-", "").strip()

            # Accept tokens like XXX-XXX-XXX (9 chars) and XXX-XXX-XXX-<1-3> (10-12 chars) after removing dashes
            if not (9 <= len(clean_token) <= 12):
                return False, None, "Invalid token format"

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    self.verify_user_endpoint, params={"token": clean_token}
                ) as resp:
                    if resp.status != 200:
                        logger.error(
                            f"Polymart verify token failed with status {resp.status}"
                        )
                        return False, None, "Failed to verify token"

                    try:
                        data = await resp.json()
                    except Exception as e:
                        logger.error(f"Failed to parse Polymart response: {e}")
                        return False, None, "Invalid response from Polymart"

                    response = data.get("response", {})
                    if not response.get("success"):
                        error_msg = response.get("message", "Invalid or expired token")
                        logger.warning(f"Token verification failed: {error_msg}")
                        return False, None, error_msg

                    user_data = response.get("result", {}).get("user", {})
                    if not user_data or not user_data.get("id"):
                        logger.error("No user data in Polymart response")
                        return False, None, "No user data received"

                    return True, user_data, None

        except aiohttp.ClientTimeout:
            logger.error("Polymart API timeout")
            return False, None, "Request timeout"
        except aiohttp.ClientError as e:
            logger.error(f"Polymart API connection error: {e}")
            return False, None, "Connection error"
        except Exception as e:
            logger.error(f"Unexpected error verifying token: {e}")
            return False, None, "Unexpected error"

    # Deprecated bulk method removed: views should iterate per resource and call
    # check_resource_purchase() individually. Use get_account_info() to fetch
    # username and profile picture separately.

    ###############################
    ###### ACTIONS: PURCHASES #####
    ###############################
    async def check_resource_purchase(
        self, user_id: str, resource_id: str, resource_api_key: Optional[str] = None
    ) -> Tuple[bool, bool, Optional[Dict[str, Any]], Optional[str]]:

        try:
            api_key = resource_api_key or self.api_key

            if not api_key:
                logger.error("No API key configured for Polymart")
                return False, False, None, "Polymart not configured"

            payload = {
                "api_key": api_key,
                "user_id": user_id,
                "resource_id": resource_id,
            }

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    self.get_resource_endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status != 200:
                        logger.error(
                            f"Polymart purchase check failed with status {resp.status}"
                        )
                        return False, False, None, "Failed to check purchase"

                    try:
                        data = await resp.json()
                    except Exception as e:
                        logger.error(f"Failed to parse Polymart response: {e}")
                        return (False, False, None, "Invalid response from Polymart")

                    response = data.get("response", {})
                    if not response.get("success"):
                        errors = response.get("errors", {})
                        if isinstance(errors, list) and errors:
                            error_msg = "; ".join(str(e) for e in errors)
                        elif isinstance(errors, dict) and errors:
                            error_msg = "; ".join(
                                f"{k}: {v}" for k, v in errors.items()
                            )
                        else:
                            error_msg = response.get(
                                "message", "Failed to check purchase"
                            )
                        # Downgrade to debug to avoid noisy warnings for expected API responses
                        logger.debug(f"Purchase check failed: {error_msg}")
                        return False, False, None, error_msg

                    # Response for getResourceUserData returns a single 'resource' object
                    resource = response.get("resource")
                    if resource and (
                        str(resource.get("id", "")) == str(resource_id)
                        or not resource.get("id")
                    ):
                        purchased = bool(resource.get("purchaseValid", False))
                        meta = {
                            "purchaseTime": resource.get("purchaseTime"),
                            "purchaseStatus": resource.get("purchaseStatus"),
                            "title": resource.get("title"),
                            "owner": False,
                        }
                        if (
                            not purchased
                            and resource.get("purchaseStatus") is None
                            and resource.get("purchaseTime") is None
                        ):
                            meta["owner"] = True
                        return True, purchased, meta, None
                    # If resource missing or doesn't match, treat as not purchased but successful call
                    return True, False, None, None

        except asyncio.TimeoutError:
            logger.error("Polymart API timeout")
            return False, False, None, "Request timeout"
        except aiohttp.ClientError as e:
            logger.error(f"Polymart API connection error: {e}")
            return False, False, None, "Connection error"
        except Exception as e:
            logger.error(f"Unexpected error checking purchase: {e}")
            return False, False, None, "Unexpected error"

    #################################
    ###### ACTION: ACCOUNT INFO #####
    #################################
    async def get_account_info(self, user_id: str) -> Tuple[
        bool,  # Success
        Optional[str],  # Username
        Optional[str],  # Profile picture URL
        Optional[str],  # Error message
    ]:
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(
                    self.get_account_info_endpoint,
                    params={"user_id": user_id},
                ) as resp:
                    if resp.status != 200:
                        logger.error(
                            f"Polymart get account info failed with status {resp.status}"
                        )
                        return False, None, None, "Failed to get account info"

                    try:
                        data = await resp.json()
                    except Exception as e:
                        logger.error(f"Failed to parse Polymart response: {e}")
                        return False, None, None, "Invalid response from Polymart"

                    response = data.get("response", {})
                    if not response.get("success"):
                        errors = response.get("errors", {})
                        if isinstance(errors, list) and errors:
                            error_msg = "; ".join(str(e) for e in errors)
                        elif isinstance(errors, dict) and errors:
                            error_msg = "; ".join(
                                f"{k}: {v}" for k, v in errors.items()
                            )
                        else:
                            error_msg = response.get("message", "Unknown error")
                        return False, None, None, error_msg

                    # For users, the key is likely 'user'; for teams, 'team'. Support both.
                    payload = response.get("user") or response.get("team") or {}
                    username = payload.get("username")
                    profile_picture = payload.get("profilePictureURL")
                    return True, username, profile_picture, None

        except asyncio.TimeoutError:
            logger.error("Polymart API timeout")
            return False, None, None, "Request timeout"
        except aiohttp.ClientError as e:
            logger.error(f"Polymart API connection error: {e}")
            return False, None, None, "Connection error"
        except Exception as e:
            logger.error(f"Unexpected error getting account info: {e}")
            return False, None, None, "Unexpected error"
