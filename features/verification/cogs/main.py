from __future__ import annotations

import logging
from typing import Optional
import asyncio

import discord
from discord.ext import bridge, commands
from core.i18n import t
from ..ui import embeds as ui_embeds

from ..services.verification_service import VerificationService
from ..services.spigot_service import SpigotService
from ..ui.views import VerificationViewPanel, NotifyStaffView

from core.config import load_config


logger = logging.getLogger(__name__)


class Verification(commands.Cog):
    """Verification system for resource purchases."""

    def __init__(self, bot: bridge.Bot):
        self.bot = bot
        self.service = VerificationService()
        self.spigot_service = SpigotService()
        # Kick off a startup health check for the verification API
        # Log an error if the external API is not healthy at boot.
        try:
            self.bot.loop.create_task(self._startup_health_check())
        except Exception as e:
            logger.error(f"Failed to schedule verification health check: {e}")

    async def _startup_health_check(self) -> None:
        # Ensure the bot is fully ready before performing external calls
        try:
            await self.bot.wait_until_ready()
            healthy = await self.service.check_health()
            if not healthy:
                logger.error(
                    "Verification feature: external API health check failed at startup."
                )
            else:
                logger.info("Verification feature: external API health check OK.")
        except Exception as e:
            logger.error(
                f"Verification feature: error during startup health check: {e}"
            )

    ######################
    ###### COMMANDS ######
    ######################

    # This only not translate
    @bridge.has_permissions(administrator=True)
    @bridge.bridge_command(name="verify_panel", description="create verify panel")
    async def verify_panel(self, ctx: bridge.BridgeContext):
        # Local TTL helper
        def _ui_ttl(key: str, default: int) -> int:
            try:
                cfg = load_config()
                ver = cfg.module("verification") or {}
                ui = ver.get("ui", {}) if isinstance(ver, dict) else {}
                ttl = ui.get("ttl", {}) if isinstance(ui, dict) else {}
                val = ttl.get(key)
                return int(val) if val is not None else int(default)
            except Exception:
                return int(default)

        # Extra runtime guard so prefix (!verify_panel) also enforces admin perms
        try:
            is_admin = False
            author = getattr(ctx, "author", None) or getattr(ctx, "user", None)
            perms = getattr(
                getattr(author, "guild_permissions", None), "administrator", False
            )
            is_admin = bool(perms)
            if not is_admin:
                await ctx.respond(
                    t(ctx, "verification.errors.not_admin"),
                    ephemeral=True,
                    delete_after=_ui_ttl("admin_error", 8),
                )
                return
        except Exception:
            # If we cannot reliably check, fall back to deny
            await ctx.respond(
                t(ctx, "verification.errors.not_admin"),
                ephemeral=True,
                delete_after=_ui_ttl("admin_error", 8),
            )
            return

        await ctx.defer(ephemeral=True)
        # Post a localized embed with a Verify button
        await ctx.send(
            embed=ui_embeds.verification_panel_embed(ctx),
            view=VerificationViewPanel(ctx),
        )
        await ctx.respond(
            t(ctx, "verification.panel.created"),
            ephemeral=True,
            delete_after=_ui_ttl("admin_success", 5),
        )

    @bridge.has_permissions(administrator=True)
    @bridge.bridge_command(
        name="remove_verify_threads", description="Remove verify threads"
    )
    async def remove_verify_threads(self, ctx: bridge.BridgeContext):
        is_admin = False
        author = getattr(ctx, "author", None) or getattr(ctx, "user", None)
        perms = getattr(
            getattr(author, "guild_permissions", None), "administrator", False
        )
        is_admin = bool(perms)
        if not is_admin:
            await ctx.respond(
                t(ctx, "verification.errors.not_admin"),
                ephemeral=True,
                delete_after=_ui_ttl("admin_error", 8),
            )
            return
        await ctx.defer(ephemeral=True)
        cfg = load_config()
        mod = cfg.module("verification")
        channel_id = mod.get("channels", {}).get("verification_channel", 0)
        channel: TextChannel = ctx.guild.get_channel(channel_id)
        if channel:
            await ctx.respond(
                t(ctx, "verification.remove_verify_threads.success"),
                ephemeral=True,
                delete_after=_ui_ttl("admin_success", 5),
            )
            for thread in channel.threads:
                try:
                    await thread.delete()
                except Exception:
                    pass
        else:
            await ctx.respond(
                t(ctx, "verification.remove_verify_threads.error"),
                ephemeral=True,
                delete_after=_ui_ttl("admin_error", 8),
            )


def setup(bot: bridge.Bot):
    bot.add_cog(Verification(bot))

    #####################
    ###### VIEWS ########
    #####################

    try:
        bot.add_view(VerificationViewPanel())
        bot.add_view(NotifyStaffView())
    except Exception as e:
        logger.error(f"Error adding verification view: {e}")
