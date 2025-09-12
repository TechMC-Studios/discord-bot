from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

########################
###### DATA MODEL ######
########################


@dataclass
class AuthorInfo:
    id: str
    username: str
    discord_name: Optional[str] = None


############################
###### PARSERS - API #######
############################


class AuthorParser:

    @staticmethod
    def parse_spigot_author(data: Dict[str, Any]) -> Optional[AuthorInfo]:
        if not isinstance(data, dict):
            return None
        _id = data.get("id")
        # Username keys seen in code: "username" (primary), sometimes "name"
        _username = data.get("username") or data.get("name")
        identities = data.get("identities") or {}
        _discord = None
        if isinstance(identities, dict):
            _discord = identities.get("discord")
        if _id is None or not _username:
            return None
        return AuthorInfo(
            id=str(_id),
            username=str(_username),
            discord_name=str(_discord) if _discord else None,
        )

    @staticmethod
    def parse_spiget_author(data: Dict[str, Any]) -> Optional[AuthorInfo]:
        if not isinstance(data, dict):
            return None
        _id = data.get("id")
        _username = data.get("name") or data.get("username")
        # Attempt to extract discord if present in expanded payloads
        _discord = data.get("discord")
        if not _discord and isinstance(data.get("identities"), dict):
            _discord = data.get("identities", {}).get("discord")
        if not _discord and isinstance(data.get("social"), dict):
            _discord = data.get("social", {}).get("discord")
        if _id is None or not _username:
            return None
        return AuthorInfo(
            id=str(_id),
            username=str(_username),
            discord_name=_discord if _discord else None,
        )

    @staticmethod
    def parse_spiget_search_item(item: Dict[str, Any]) -> Optional[AuthorInfo]:
        """Parse a Spiget search result item into AuthorInfo (id + name)."""
        if not isinstance(item, dict):
            return None
        _id = item.get("id")
        _username = item.get("name") or item.get("username")
        # Search results usually don't include discord, but try common locations
        _discord = item.get("discord")
        if not _discord and isinstance(item.get("identities"), dict):
            _discord = item.get("identities", {}).get("discord")
        if not _discord and isinstance(item.get("social"), dict):
            _discord = item.get("social", {}).get("discord")
        if _id is None or not _username:
            return None
        return AuthorInfo(
            id=str(_id),
            username=str(_username),
            discord_name=_discord if _discord else None,
        )

    @staticmethod
    def parse_spiget_search_list(items: List[Dict[str, Any]]) -> List[AuthorInfo]:
        out: List[AuthorInfo] = []
        if not isinstance(items, list):
            return out
        for it in items:
            ai = AuthorParser.parse_spiget_search_item(it)
            if ai:
                out.append(ai)
        return out
