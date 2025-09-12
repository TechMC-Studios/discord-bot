from __future__ import annotations

import logging
from discord.ext import bridge, commands
import discord
from core.i18n import t
from core.config import load_config

# TODO: Hacer que si una persona abre un hilo pero el hilo tiene una etiqueta distinta al plugin que tiene comprado, no aplicar el tag de prioridad.

logger = logging.getLogger(__name__)


class SupportForums(commands.Cog):
    """Support forums cog."""

    ############################
    ###### INIT & CONFIG #######
    ############################

    def __init__(self, bot: bridge.Bot):
        self.bot = bot
        self.cfg = load_config()
        self.mod_cfg = self.cfg.module("forums")
        self.support_cfg = self.mod_cfg.get("support", {})
        self.support_channel_id = int(self.support_cfg.get("channel_id", "0"))
        self.tag_priority_id = int(self.support_cfg.get("tag_priority_id", "0"))
        self.mod_cfg_verify = self.cfg.module("verification")
        self.roles_cfg = self.mod_cfg_verify.get("roles", {})
        self.buyer_role_id = int(self.roles_cfg.get("buyer", "0"))

    ######################
    ###### COMMANDS ######
    ######################

    @bridge.bridge_command(
        name="priority_tag", description="Set priority tag if has buyer role"
    )
    async def set_priority_tag(self, ctx: bridge.BridgeContext):
        try:
            if getattr(ctx, "message", None) is not None:
                await ctx.message.delete(delay=1)
        except Exception:
            pass

        await ctx.defer(ephemeral=True)

        thread = ctx.channel
        if not isinstance(thread, discord.Thread):
            await ctx.respond(
                t(ctx, "forums.support.priority_tag.error_not_thread"),
                ephemeral=True,
                delete_after=5,
            )
            return

        if thread.parent_id != self.support_channel_id:
            await ctx.respond(
                t(ctx, "forums.support.priority_tag.error_wrong_channel"),
                ephemeral=True,
                delete_after=5,
            )
            return

        buyer_role = ctx.guild.get_role(self.buyer_role_id)
        if buyer_role is None:
            await ctx.respond(
                t(ctx, "forums.support.priority_tag.error_buyer_role_missing"),
                ephemeral=True,
                delete_after=5,
            )
            return
        if buyer_role not in ctx.author.roles:
            await ctx.respond(
                t(ctx, "forums.support.priority_tag.error_not_buyer"),
                ephemeral=True,
                delete_after=5,
            )
            return

        if thread.owner_id != ctx.author.id:
            await ctx.respond(
                t(ctx, "forums.support.priority_tag.error_not_owner"),
                ephemeral=True,
                delete_after=5,
            )
            return

        tag = thread.parent.get_tag(self.tag_priority_id)
        if tag is None:
            await ctx.respond(
                t(ctx, "forums.support.priority_tag.error_tag_not_found"),
                ephemeral=True,
                delete_after=5,
            )
            return
        tags = list(thread.applied_tags or [])
        if tag in tags:
            await ctx.respond(
                t(ctx, "forums.support.priority_tag.error_already_tagged"),
                ephemeral=True,
                delete_after=5,
            )
            return
        tags.append(tag)

        try:
            await thread.edit(applied_tags=tags)
        except Exception as e:
            logger.error("Failed to apply priority tag to support thread: %s", e)
            await ctx.respond(
                t(ctx, "forums.support.priority_tag.error_apply_failed"),
                ephemeral=True,
                delete_after=5,
            )
            return

        await ctx.respond(
            t(ctx, "forums.support.priority_tag.success"),
            ephemeral=True,
            delete_after=5,
        )

    #######################
    ###### LISTENERS ######
    #######################

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if thread.parent_id != self.support_channel_id:
            logger.debug(
                "Support thread created in non-support channel. Channel id %s not found",
                self.support_channel_id,
            )
            return

        buyer_role = thread.guild.get_role(self.buyer_role_id)
        if buyer_role is None:
            logger.warning(
                "Buyer role not found. Role id %s not found",
                self.buyer_role_id,
            )
            return

        if buyer_role not in thread.owner.roles:
            return

        tag = thread.parent.get_tag(self.tag_priority_id)
        if tag is None:
            logger.warning(
                "Support thread created without priority tag. Tag id %s not found",
                self.tag_priority_id,
            )
            return
        tags = list(thread.applied_tags or [])
        if tag in tags:
            return
        tags.append(tag)

        try:
            await thread.edit(applied_tags=tags)
        except Exception as e:
            logger.error("Failed to apply priority tag to support thread: %s", e)
            return


def setup(bot: bridge.Bot):
    bot.add_cog(SupportForums(bot))
