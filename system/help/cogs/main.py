"""Custom help command module (system-level)."""

import discord
from discord.ext import bridge, commands

from core.i18n import t
from system.help.ui.embed import (
    build_command_help_embed,
    build_general_help_embed,
)


class HelpCog(commands.Cog):
    """Custom help command implementation."""

    ############################
    ###### INIT & CONFIG #######
    ############################
    def __init__(self, bot: bridge.Bot):
        self.bot = bot


#####################
###### SETUP ########
#####################

def setup(bot: bridge.Bot):
    bot.add_cog(HelpCog(bot))
