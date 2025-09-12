from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple, TypedDict


class NormalizedAuthor(TypedDict, total=False):
    id: int
    username: str
    discord: Optional[str]
    avatar: Optional[str]
    source: str  # "spigot" | "spiget"
    raw: Dict[str, Any]


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return None


# ---------------- Spigot (simple API) ----------------


def normalize_spigot_author(data: Dict[str, Any]) -> NormalizedAuthor:
    """Normalize a Spigot simple API author payload (getAuthor/findAuthor).

    Expected fields:
    - id: str|int
    - username: str
    - identities.discord: str (optional)
    - avatar: str (optional)
    """
    author_id = _to_int(data.get("id"))
    username = str(data.get("username", ""))
    identities = data.get("identities") or {}
    discord = None
    if isinstance(identities, dict):
        discord_val = identities.get("discord")
        if isinstance(discord_val, str) and discord_val.strip():
            discord = discord_val.strip()

    avatar = data.get("avatar") if isinstance(data.get("avatar"), str) else None

    return NormalizedAuthor(
        id=author_id if author_id is not None else -1,
        username=username,
        discord=discord,
        avatar=avatar,
        source="spigot",
        raw=data,
    )


# ---------------- Spiget ----------------


def normalize_spiget_author(data: Dict[str, Any]) -> NormalizedAuthor:
    """Normalize a Spiget author payload (/authors/{id} or search item).

    Expected fields:
    - id: int
    - name: str -> maps to username
    - identities.discord: str (optional)
    - icon.url: str (optional) -> maps to avatar
    """
    author_id = _to_int(data.get("id"))
    username = str(data.get("name", ""))

    identities = data.get("identities") or {}
    discord = None
    if isinstance(identities, dict):
        discord_val = identities.get("discord")
        if isinstance(discord_val, str) and discord_val.strip():
            discord = discord_val.strip()

    icon = data.get("icon") or {}
    avatar = None
    if isinstance(icon, dict):
        if isinstance(icon.get("url"), str):
            avatar = icon["url"]

    return NormalizedAuthor(
        id=author_id if author_id is not None else -1,
        username=username,
        discord=discord,
        avatar=avatar,
        source="spiget",
        raw=data,
    )


def normalize_spiget_search_results(
    items: Iterable[Dict[str, Any]],
) -> List[NormalizedAuthor]:
    """Normalize a list returned by Spiget search /search/authors/{query}."""
    result: List[NormalizedAuthor] = []
    for item in items:
        if isinstance(item, dict):
            result.append(normalize_spiget_author(item))
    return result


def normalize_author(data: Dict[str, Any], source: str) -> NormalizedAuthor:
    """Normalize any author payload by source name.

    source: "spiget" or "spigot" (case-insensitive). Defaults to spigot otherwise.
    """
    src = (source or "spigot").lower()
    if src == "spiget":
        return normalize_spiget_author(data)
    return normalize_spigot_author(data)


# ---------------- Convenience extractors ----------------


def extract_discord(author: Dict[str, Any]) -> Optional[str]:
    """Attempt to extract a discord handle from either Spigot or Spiget payloads."""
    # Try spigot identities
    identities = author.get("identities")
    if isinstance(identities, dict):
        val = identities.get("discord")
        if isinstance(val, str) and val.strip():
            return val.strip()

    # Try spiget under the same path (identities.discord)
    return None


def extract_name(author: Dict[str, Any]) -> str:
    """Extract username (Spigot: username, Spiget: name)."""
    name = author.get("username")
    if isinstance(name, str) and name:
        return name
    name = author.get("name")
    return str(name) if isinstance(name, str) else ""


def extract_id(author: Dict[str, Any]) -> Optional[int]:
    """Extract numeric id (both APIs use 'id')."""
    return _to_int(author.get("id"))


def as_tuple(normalized: NormalizedAuthor) -> Tuple[Optional[int], str, Optional[str]]:
    """Return (id, username, discord) from a NormalizedAuthor.

    Useful to pass around minimal data for verification steps.
    """
    return (
        normalized.get("id"),
        normalized.get("username", ""),
        normalized.get("discord"),
    )
