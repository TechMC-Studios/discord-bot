from __future__ import annotations

import discord
from typing import Optional

from core.i18n import t


#############################
###### UI - HELP EMBEDS #####
#############################

def build_command_help_embed(
    bot: discord.Client, ctx, cmd: discord.ext.commands.Command
) -> discord.Embed:
    title = t(ctx, "help.title_cmd", name=cmd.name)
    description = cmd.description or t(ctx, "help.no_description")
    embed = discord.Embed(
        title=title, description=description, color=discord.Color.blue()
    )

    # If the command has subcommands (Group), list them
    sub_cmds = getattr(cmd, "commands", None)
    if sub_cmds:
        lines = [
            f"`{c.name}` - {c.description or t(ctx, 'help.no_description')}"
            for c in sub_cmds
        ]
        embed.add_field(
            name=t(ctx, "help.subcommands"),
            value="\n".join(lines) or t(ctx, "help.none"),
            inline=False,
        )

    return embed


#############################
###### UI - HELP INDEX ######
#############################

def build_general_help_embed(bot: discord.Client, ctx) -> discord.Embed:
    title = t(ctx, "help.title")
    description = t(ctx, "help.description")
    embed = discord.Embed(
        title=f"🤖 {title}", description=description, color=discord.Color.blue()
    )

    # Dynamically list commands grouped by cog
    cogs = {}
    for command in bot.commands:
        if getattr(command, "hidden", False):
            continue
        cog_name = command.cog_name or t(ctx, "help.uncategorized")
        cogs.setdefault(cog_name, []).append(command)

    for cog_name, commands_list in sorted(cogs.items(), key=lambda kv: kv[0].lower()):
        # Format each command line: `name` - description
        lines = [
            f"`/{cmd.name}` - {cmd.description or t(ctx, 'help.no_description')}"
            for cmd in sorted(commands_list, key=lambda c: c.name)
        ]
        embed.add_field(
            name=f"{cog_name}",
            value="\n".join(lines) or t(ctx, "help.none"),
            inline=False,
        )

    # Info footer
    embed.set_footer(text=t(ctx, "help.footer_specific"))
    return embed
