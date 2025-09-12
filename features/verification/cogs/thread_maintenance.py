from __future__ import annotations

import logging
from typing import Optional

import discord
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)

from core.config import load_config


class VerificationThreadMaintenance(commands.Cog):
    """Handles verification-related thread maintenance.

    - Deletes threads as soon as they are archived.
    - Performs a periodic cleanup of archived threads (and once on startup).
    """

    ############################
    ###### INIT & CONFIG #######
    ############################

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Load verification settings
        try:
            ver_cfg = load_config().module("verification") or {}
            raw_channel = None
            if isinstance(ver_cfg, dict):
                # Prefer new structure: verification.channels.verification_channel
                raw_channel = (ver_cfg.get("channels", {}) or {}).get(
                    "verification_channel"
                )
                # Fallback to old structure: verification.config.verification_channel
                if raw_channel is None:
                    raw_channel = (ver_cfg.get("config", {}) or {}).get(
                        "verification_channel"
                    )
            # Sanitize to digits only (allows values like "123." as provided)
            self.channel_id: Optional[int] = None
            if raw_channel is not None:
                try:
                    digits = "".join(ch for ch in str(raw_channel) if ch.isdigit())
                    self.channel_id = int(digits) if digits else None
                except Exception:
                    self.channel_id = None
        except Exception:
            self.channel_id = None
        # Start periodic cleanup task
        try:
            self.periodic_cleanup.start()
        except Exception as e:
            logger.error(f"Failed to start periodic thread cleanup: {e}")

    #########################
    ###### LISTENERS ########
    #########################

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        # If a thread has just been archived, delete it
        try:
            if not before.archived and after.archived:
                # Only act for configured verification channel if set
                if self.channel_id is not None:
                    if after.parent is None or after.parent.id != self.channel_id:
                        return
                await self._delete_thread(after)
        except Exception as e:
            logger.debug(f"on_thread_update: failed to process thread archive: {e}")

    async def _delete_thread(self, thread: discord.Thread):
        try:
            await thread.delete()
        except discord.HTTPException as e:
            # Already deleted or other HTTP issue
            logger.error(f"Failed to delete thread {thread.id}: {e}")
        except Exception as e:
            logger.error(
                f"Unexpected error deleting thread {getattr(thread, 'id', 'unknown')}: {e}"
            )

    ######################
    ###### TASKS #########
    ######################

    async def _cleanup_guild(self, guild: discord.Guild):
        # If configured, only cleanup the specified verification channel in this guild
        if self.channel_id is None:
            return
        channel = guild.get_channel(self.channel_id) or self.bot.get_channel(
            self.channel_id
        )
        if channel is None:
            return

        # Public archived threads
        try:
            async for thr in channel.archived_threads(limit=None, private=False):
                await self._delete_thread(thr)
        except Exception:
            pass

        # Private archived threads
        try:
            async for thr in channel.archived_threads(limit=None, private=True):
                await self._delete_thread(thr)
        except Exception:
            pass

    @tasks.loop(minutes=60)
    async def periodic_cleanup(self):
        # Periodic sweep through all guilds
        for guild in list(self.bot.guilds):
            try:
                await self._cleanup_guild(guild)
            except Exception:
                continue

    @periodic_cleanup.before_loop
    async def before_periodic_cleanup(self):
        await self.bot.wait_until_ready()

    #####################
    ###### SETUP ########
    #####################

def setup(bot: commands.Bot):
    bot.add_cog(VerificationThreadMaintenance(bot))
