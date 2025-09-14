from __future__ import annotations

import discord
from core.i18n import t
from core.config import load_config
from datetime import datetime, timezone
from typing import Any
from ..services.author_parser import AuthorInfo


########################
###### UI - PANEL ######
########################

def verification_panel_embed(ctx: Any) -> discord.Embed:
    """Main verification panel embed shown with the persistent Verify button."""
    embed = discord.Embed(
        title=t(ctx, "verification.panel.embed.title"),
        description=t(ctx, "verification.panel.embed.desc"),
        color=discord.Color.magenta(),
    )
    embed.set_footer(text=t(ctx, "verification.panel.embed.footer"))
    return embed


################################
###### UI - SPIGOT FLOW ########
################################

def spigot_link_step1_embed(ctx: Any) -> discord.Embed:
    """Step 1: Set identities visibility to All Visitors."""
    embed = discord.Embed(
        title=t(ctx, "verification.spigot.link_help.step1.title"),
        description=t(ctx, "verification.spigot.link_help.step1.desc"),
        color=discord.Color.gold(),
    )
    embed.set_image(url=t(ctx, "verification.spigot.link_help.image1"))
    return embed


def spigot_link_step2_embed(ctx: Any) -> discord.Embed:
    """Step 2: Fill Discord with Global Discord Name and save."""
    embed = discord.Embed(
        title=t(ctx, "verification.spigot.link_help.step2.title"),
        description=t(ctx, "verification.spigot.link_help.step2.desc"),
        color=discord.Color.gold(),
    )
    embed.set_image(url=t(ctx, "verification.spigot.link_help.image2"))
    return embed


def spigot_link_final_embed(ctx: Any, *, mismatch: bool) -> discord.Embed:
    """Final summary before showing action buttons; includes delay note."""
    key = (
        "verification.spigot.link_help.final.mismatch.desc"
        if mismatch
        else "verification.spigot.link_help.final.not_linked.desc"
    )
    embed = discord.Embed(
        title=t(ctx, "verification.spigot.link_help.final.title"),
        description=(
            t(ctx, key)
            + "\n\n"
            + t(ctx, "verification.spigot.link_help.note_delay")
            + "\n\n"
            + t(ctx, "verification.spigot.link_help.final.tips")
        ),
        color=discord.Color.orange(),
    )
    return embed


# Removed legacy mismatch embed (replaced by details + steps flow)


def spigot_link_details_embed(
    ctx: Any,
    *,
    author: AuthorInfo,
    current_discord: str,
    spigot_discord: str | None,
    mismatch: bool,
) -> discord.Embed:
    """Details card showing current vs Spigot Discord for clarity."""
    embed = discord.Embed(
        title=t(ctx, "verification.spigot.link_help.details.title"),
        color=discord.Color.red() if mismatch else discord.Color.orange(),
    )
    embed.add_field(
        name=t(ctx, "verification.spigot.link_help.details.current_discord"),
        value=f"`{current_discord or '-'}`",
        inline=False,
    )
    spigot_value = (
        f"`{spigot_discord}`"
        if spigot_discord
        else t(ctx, "verification.labels.not_linked")
    )
    embed.add_field(
        name=t(ctx, "verification.spigot.link_help.details.spigot_discord"),
        value=spigot_value,
        inline=False,
    )
    embed.add_field(
        name=t(ctx, "verification.labels.username"),
        value=f"**{author.username}** (ID `{author.id}`)",
        inline=False,
    )
    status_text = (
        t(ctx, "verification.spigot.link_help.details.status.mismatch")
        if mismatch
        else t(ctx, "verification.spigot.link_help.details.status.not_linked")
    )
    embed.set_footer(text=status_text)
    return embed


####################################
###### UI - RESULTS & CARDS ########
####################################

def spigot_user_resources_embed(
    ctx: Any, author: AuthorInfo, resources: list[dict]
) -> discord.Embed:
    """Embed showing the user's verified resources from the verification API."""
    embed = discord.Embed(
        title=t(ctx, "verification.spigot.result.title"),
        description=t(
            ctx,
            "verification.spigot.result.desc",
            username=author.username,
            id=author.id,
        ),
        color=discord.Color.green(),
    )
    # Basic fields
    embed.add_field(
        name=t(ctx, "verification.labels.username"),
        value=f"**{author.username}**",
        inline=True,
    )
    embed.add_field(
        name=t(ctx, "verification.labels.user_id"), value=f"`{author.id}`", inline=True
    )
    if author.discord_name:
        embed.add_field(
            name=t(ctx, "verification.labels.discord_id"),
            value=f"`{author.discord_name}`",
            inline=True,
        )
    # Resources list (pretty with emoji and Discord timestamps)
    if resources:
        cfg = load_config()
        ver_mod = cfg.module("verification")
        plugins_cfg = (
            (ver_mod.get("plugins", {}) or {}) if isinstance(ver_mod, dict) else {}
        )
        lines: list[str] = []
        for r in resources:
            slug = str(r.get("slug", "?")).strip()
            plug = plugins_cfg.get(slug, {}) if isinstance(plugins_cfg, dict) else {}
            emoji = str(plug.get("emoji", "")).strip() if isinstance(plug, dict) else ""
            display_name = (
                str(plug.get("name", slug)) if isinstance(plug, dict) else slug
            )
            verified_at_raw = r.get("verified_at")
            ts = None
            if isinstance(verified_at_raw, str) and verified_at_raw:
                try:
                    # Support ISO8601 with or without Z
                    iso = verified_at_raw.strip()
                    if iso.endswith("Z"):
                        dt_obj = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                    else:
                        dt_obj = datetime.fromisoformat(iso)
                    ts = int(
                        dt_obj.replace(tzinfo=dt_obj.tzinfo or timezone.utc).timestamp()
                    )
                except Exception:
                    ts = None
            ts_str = f"<t:{ts}:R>" if ts else ""
            prefix = f"{emoji} " if emoji else ""
            line = f"{prefix}**{display_name}**" + (f" — ✓ {ts_str}" if ts_str else "")
            lines.append(line)
        value = "\n".join(lines)[:1000] or "-"
        embed.add_field(
            name=t(ctx, "verification.labels.verified_resources"),
            value=value,
            inline=False,
        )
    else:
        embed.add_field(
            name=t(ctx, "verification.labels.verified_resources"),
            value=t(ctx, "verification.labels.none"),
            inline=False,
        )
    return embed


def spigot_not_buyer_embed(ctx: Any, author: AuthorInfo) -> discord.Embed:
    """Shown when the verification API has no user/purchases for this Spigot ID."""
    embed = discord.Embed(
        title=t(ctx, "verification.spigot.result.title"),
        description=t(
            ctx,
            "verification.spigot.not_buyer.desc",
            username=author.username,
            id=author.id,
        ),
        color=discord.Color.orange(),
    )
    if author.discord_name:
        embed.add_field(
            name=t(ctx, "verification.labels.discord_id"),
            value=f"`{author.discord_name}`",
            inline=True,
        )
    return embed


# Removed legacy not-linked embed (replaced by details + steps flow)


def select_platform_only_embed(ctx: Any) -> discord.Embed:
    """Embed for selecting platform (no plugin chosen)."""
    embed = discord.Embed(
        title=t(ctx, "verification.ui.select_platform.title"),
        description=t(ctx, "verification.ui.select_platform.only_desc"),
        color=discord.Color.magenta(),
    )
    return embed


def bbb_thread_instructions_embed(ctx: Any, bot_mention: str) -> discord.Embed:
    """Minimal BBB thread embed with instructions only."""
    embed = discord.Embed(
        title=t(ctx, "verification.bbb.thread.title"),
        description=(
            t(ctx, "verification.bbb.thread.desc", bot=bot_mention)
            + "\n\n"
            + t(ctx, "verification.bbb.thread.link_line")
            + "\n\n"
            + ""
            + t(ctx, "verification.bbb.thread.image.caption")
        ),
        color=discord.Color.magenta(),
    )
    embed.set_author(name=t(ctx, "verification.bbb.thread.author"))
    embed.set_footer(text=t(ctx, "verification.bbb.thread.footer"))
    # Add a helpful example image showing how to run the command
    embed.set_image(
        url=(
            "https://media.discordapp.net/attachments/1413195767455289480/1413811571536302080/image.png?"
            "ex=68bd4a22&is=68bbf8a2&hm=4b73945494423a34d205c4f49006a2b342661f51860bb9da15c0723524b130c9&=&format=webp&quality=lossless"
        )
    )
    return embed

#############################
###### UI - LINKS & CTAs ####
#############################

def thread_link_brief_embed(ctx: Any) -> discord.Embed:
    """Brief ephemeral embed prompting the user to open the created thread."""
    embed = discord.Embed(
        title=t(ctx, "verification.bbb.thread.link_embed.title"),
        description=t(ctx, "verification.bbb.thread.link_embed.desc"),
        color=discord.Color.magenta(),
    )
    return embed


def spigot_verification_methods_embed(ctx: Any) -> discord.Embed:
    """Embed explaining the Spigot verification options."""
    embed = discord.Embed(
        title=t(ctx, "verification.spigot.ui.title"),
        description=t(ctx, "verification.spigot.ui.desc"),
        color=discord.Color.magenta(),
    )
    # Order: URL, Exact, ID, Search
    embed.add_field(
        name=t(ctx, "verification.spigot.ui.method_url.title"),
        value=t(ctx, "verification.spigot.ui.method_url.desc"),
        inline=False,
    )
    embed.add_field(
        name=t(ctx, "verification.spigot.ui.method_exact.title"),
        value=t(ctx, "verification.spigot.ui.method_exact.desc"),
        inline=False,
    )
    embed.add_field(
        name=t(ctx, "verification.spigot.ui.method_id.title"),
        value=t(ctx, "verification.spigot.ui.method_id.desc"),
        inline=False,
    )
    embed.add_field(
        name=t(ctx, "verification.spigot.ui.method_search.title"),
        value=t(ctx, "verification.spigot.ui.method_search.desc"),
        inline=False,
    )
    embed.set_footer(text=t(ctx, "verification.spigot.ui.footer"))
    return embed


def spigot_result_embed(ctx: Any, author: AuthorInfo) -> discord.Embed:
    embed = discord.Embed(
        title=t(ctx, "verification.spigot.result.title"),
        description=t(
            ctx,
            "verification.spigot.result.desc",
            username=author.username,
            id=author.id,
        ),
        color=discord.Color.magenta(),
    )
    embed.add_field(
        name=t(ctx, "verification.labels.username"),
        value=f"**{author.username}**",
        inline=True,
    )
    embed.add_field(
        name=t(ctx, "verification.labels.user_id"), value=f"`{author.id}`", inline=True
    )
    if author.discord_name:
        embed.add_field(
            name=t(ctx, "verification.labels.discord_id"),
            value=f"`{author.discord_name}`",
            inline=True,
        )
    return embed


def spigot_search_results_embed(
    ctx: Any, *, shown: int, max_shown: int
) -> discord.Embed:
    embed = discord.Embed(
        title=t(ctx, "verification.spigot.search.title"),
        description=t(
            ctx,
            "verification.spigot.search.desc_max",
            shown=shown,
            max=max_shown,
        ),
        color=discord.Color.magenta(),
    )
    return embed


def verification_api_down_embed(ctx: Any) -> discord.Embed:
    """Embed shown when the internal verification API is unavailable.

    This should be displayed alongside disabled UI controls so the user
    understands that verification is temporarily unavailable.
    """
    embed = discord.Embed(
        title=t(ctx, "verification.api.down.title"),
        description=t(ctx, "verification.api.down.desc"),
        color=discord.Color.red(),
    )
    embed.set_footer(text=t(ctx, "verification.api.down.footer"))
    return embed
