from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

import discord

logger = logging.getLogger(__name__)

# Language files directory: lang/<locale>/(messages.json|<domain>.json)
_LANG_DIR = Path(__file__).resolve().parent.parent / "lang"
# Cache structure: { (locale, domain): { key: value } }
_CACHE: Dict[Tuple[str, Optional[str]], Dict[str, str]] = {}

DEFAULT_LOCALE = "en"


def _load_bundle(locale: str, domain: Optional[str]) -> Dict[str, str]:
    key = (locale, domain)
    if key in _CACHE:
        return _CACHE[key]

    # Domain file first, then global messages.json
    data: Dict[str, str] = {}
    try:
        if domain:
            domain_path = _LANG_DIR / locale / f"{domain}.json"
            if domain_path.exists():
                data.update(json.loads(domain_path.read_text(encoding="utf-8")))
        global_path = _LANG_DIR / locale / "messages.json"
        if global_path.exists():
            # Global is fallback; don't overwrite domain keys
            global_data = json.loads(global_path.read_text(encoding="utf-8"))
            for k, v in global_data.items():
                data.setdefault(k, v)
    except Exception as e:
        logger.error(
            "Failed to load locale bundle '%s' (domain=%s): %s", locale, domain, e
        )

    _CACHE[key] = data
    return data


def _locale_chain(locale: Optional[str]) -> Iterable[str]:
    # Normalize like 'es-ES' -> ('es-ES', 'es', 'en')
    if locale:
        loc = locale.replace("_", "-")
        yield loc
        if "-" in loc:
            yield loc.split("-", 1)[0]
        else:
            yield loc
    yield DEFAULT_LOCALE


def _resolve(locale: Optional[str], key: str) -> Optional[str]:
    # Optional domain if key contains a dot: domain.key
    domain: Optional[str] = None
    if "." in key:
        domain = key.split(".", 1)[0]

    for loc in _locale_chain(locale):
        bundle = _load_bundle(loc, domain)
        if key in bundle:
            return bundle[key]
        # Also try without domain prefix as a last resort (for legacy keys)
        if domain:
            undomain_key = key.split(".", 1)[1]
            if undomain_key in bundle:
                return bundle[undomain_key]
    return None


def get_locale_from_ctx(ctx: Any) -> Optional[str]:
    # Prefer interaction locale for slash commands
    if isinstance(ctx, discord.Interaction):
        interaction = ctx
    else:
        interaction = getattr(ctx, "interaction", None)
    if interaction and isinstance(interaction, discord.Interaction):
        # Try user locale first, then command locale
        return getattr(interaction, "user_locale", None) or getattr(
            interaction, "locale", None
        )
    # Fallbacks: try guild preferred locale if available
    guild = getattr(ctx, "guild", None)
    if guild is not None:
        return getattr(guild, "preferred_locale", None)
    return None


def t(ctx: Any, key: str, **kwargs: Any) -> str:
    """Translate a key using the locale from the context, with fallback to English.

    Usage: t(ctx, "ping.response", ms=123)
    Supports domain bundles: lang/<locale>/<domain>.json
    """
    locale = get_locale_from_ctx(ctx)
    template = _resolve(locale, key) or key
    try:
        return template.format(**kwargs)
    except Exception:
        # If formatting fails, return raw template to avoid crashing commands
        return template
