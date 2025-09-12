from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import aiohttp

from core.config import load_config


class VerificationService:
    """Service layer to interact with external verification API."""

    ############################
    ###### INIT & CONFIG #######
    ############################
    def __init__(self):
        cfg = load_config()
        # Only read from module-specific config: config/verification/api.yml
        ver_mod = cfg.module("verification")
        mod_api: Dict[str, Any] = (
            (ver_mod.get("api", {}) or {}) if isinstance(ver_mod, dict) else {}
        )

        self.base_url = str(mod_api.get("base_url", ""))
        self.api_key = str(mod_api.get("api_key", ""))
        timeout_total = float(mod_api.get("timeout_seconds", 10))
        self.timeout = aiohttp.ClientTimeout(total=timeout_total)
        # Optional custom User-Agent for all requests
        self.user_agent = str(mod_api.get("user_agent", "")).strip()

    #########################
    ###### HEALTH CHECK #####
    #########################
    async def check_health(self) -> bool:
        try:
            default_headers = {"User-Agent": self.user_agent} if self.user_agent else None
            async with aiohttp.ClientSession(timeout=self.timeout, headers=default_headers) as session:
                async with session.get(f"{self.base_url}/health") as resp:
                    return resp.status == 200
        except Exception:
            return False

    #########################
    ###### HTTP CLIENT ######
    #########################
    async def request(
        self, method: str, endpoint: str, json: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, Dict[str, Any]]:
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        if self.user_agent:
            headers["User-Agent"] = self.user_agent
        url = f"{self.base_url}{endpoint}"
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.request(method, url, headers=headers, json=json) as resp:
                data = await resp.json(content_type=None)
                return resp.status, data

    ###############################
    ###### CONVENIENCE API ########
    ###############################
    async def verify_spigot(
        self, spigot_user_id: str, spigot_username: str, resource_slug: str
    ):
        return await self.request(
            "POST",
            "/verify/spigot",
            json={
                "spigotUserId": spigot_user_id,
                "spigotUsername": spigot_username,
                "resourceSlug": resource_slug,
            },
        )

    async def verify_polymart(
        self, polymart_user_id: str, polymart_username: str, resource_slug: str
    ):
        return await self.request(
            "POST",
            "/verify/polymart",
            json={
                "polymartUserId": polymart_user_id,
                "polymartUsername": polymart_username,
                "resourceSlug": resource_slug,
            },
        )

    async def link_discord(self, platform: str, external_user_id: str, discord_id: int):
        return await self.request(
            "POST",
            f"/users/{platform}/{external_user_id}/discord",
            json={"discordId": str(discord_id)},
        )

    async def list_resources(self):
        return await self.request("GET", "/resources/")

    async def get_user_by_discord(self, platform: str, discord_id: int):
        return await self.request("GET", f"/users/{platform}/discord/{discord_id}")

    async def get_user(self, platform: str, external_user_id: str):
        return await self.request("GET", f"/users/{platform}/{external_user_id}")
