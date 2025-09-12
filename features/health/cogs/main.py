from __future__ import annotations

import discord
from discord.ext import bridge, commands
import os
import time
import platform
from datetime import timedelta
from core.config import load_config

try:
    import resource  # Unix only, for memory usage
except Exception:  # pragma: no cover
    resource = None  # type: ignore
from core.i18n import t


class Health(commands.Cog):
    """Health check commands: works with both prefix and slash."""

    def __init__(self, bot: bridge.Bot):
        self.bot = bot
        self._start_monotonic = time.monotonic()
        # Optional module settings from config/health.yml
        try:
            self.settings = load_config().module("health")
        except Exception:
            self.settings = {}

    ######################
    ###### COMMANDS ######
    ######################

    @bridge.bridge_command(name="status", description="Bot status")
    async def status(self, ctx: bridge.BridgeContext):
        await ctx.respond(t(ctx, "health.ok"))

    @bridge.bridge_command(name="ping", description="Show bot latency")
    async def ping(self, ctx: bridge.BridgeContext):
        latency_ms = (
            round(self.bot.latency * 1000, 2) if self.bot.latency is not None else 0.0
        )
        await ctx.respond(t(ctx, "ping.response", ms=latency_ms))

    #####################
    ###### SETUP #######
    #####################


def setup(bot: bridge.Bot):
    bot.add_cog(Health(bot))
