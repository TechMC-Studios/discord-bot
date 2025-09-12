from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import aiohttp

from core.config import load_config

logger = logging.getLogger(__name__)


class SpigotService:
    ############################
    ###### INIT & CONFIG #######
    ############################
    def __init__(self):
        cfg = load_config()
        ver_mod = cfg.module("verification")
        mod_api: Dict[str, Any] = (
            (ver_mod.get("spigot", {}) or {}) if isinstance(ver_mod, dict) else {}
        )
        # Base URLs configured in config/verification/spigot.yml
        self.spigot_base_url = str(mod_api.get("spigot", {}).get("base", "")).rstrip(
            "/"
        )
        self.spiget_base_url = str(mod_api.get("spiget", {}).get("base", "")).rstrip(
            "/"
        )

        try:
            self.timeout = aiohttp.ClientTimeout(
                total=float(mod_api.get("timeout_seconds", 10))
            )
        except Exception:
            self.timeout = aiohttp.ClientTimeout(total=10)

    #########################
    ###### HEALTH CHECKS #####
    #########################
    async def check_health_spigot(self) -> bool:
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # Minimal call to validate availability
                url = f"{self.spigot_base_url}listResources&category=1&page=1"
                async with session.get(url) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def check_health_spiget(self) -> bool:
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                url = f"{self.spiget_base_url}/status"
                async with session.get(url) as resp:
                    return resp.status == 200
        except Exception:
            return False

    ################################
    ###### METHODS: SPIGOT API #####
    ################################
    async def spigot_get_author_by_id(
        self, author_id: int | str
    ) -> Tuple[int, Dict[str, Any]]:
        """Get exact author by ID using Spigot simple API (getAuthor)."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                url = f"{self.spigot_base_url}getAuthor&id={author_id}"
                async with session.get(url) as resp:
                    data = await resp.json(content_type=None)
                    return resp.status, data
        except Exception as e:
            return 0, {"error": str(e)}

    async def spigot_find_author_by_name(self, name: str) -> Tuple[int, Dict[str, Any]]:
        """Find exact author by username using Spigot simple API (findAuthor)."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # Name must be exactly matching according to docs
                url = f"{self.spigot_base_url}findAuthor&name={aiohttp.helpers.quote(name, safe='')}"
                async with session.get(url) as resp:
                    data = await resp.json(content_type=None)
                    return resp.status, data
        except Exception as e:
            return 0, {"error": str(e)}

    ############################
    ###### METHODS: SPIGET #####
    ############################
    async def spiget_get_author_by_id(
        self, author_id: int | str
    ) -> Tuple[int, Dict[str, Any]]:
        """Get author by ID using Spiget (/authors/{id})."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                url = f"{self.spiget_base_url}/authors/{author_id}"
                async with session.get(url) as resp:
                    data = await resp.json(content_type=None)
                    return resp.status, data
        except Exception as e:
            return 0, {"error": str(e)}

    async def spiget_search_authors(
        self, query: str, *, size: int = 5, page: int = 1, fields: str | None = None
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """Search authors by name using Spiget search API.

        Parameters map:
        - query: path segment
        - field=name (fixed)
        - size, page, fields as query params
        """
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                q = aiohttp.helpers.quote(query, safe="")
                url = f"{self.spiget_base_url}/search/authors/{q}?field=name&size={int(size)}&page={int(page)}"
                if fields:
                    url += f"&fields={aiohttp.helpers.quote(fields, safe=',')}"
                async with session.get(url) as resp:
                    data = await resp.json(content_type=None)
                    # Spiget returns list
                    if isinstance(data, list):
                        return resp.status, data
                    return resp.status, [data] if data else []
        except Exception as e:
            return 0, [{"error": str(e)}]
