from __future__ import annotations

import logging

import discord
from discord.ext import bridge, commands

logger = logging.getLogger(__name__)


class Admin(commands.Cog):
    """Core admin commands."""

    ############################
    ###### INIT & CONFIG #######
    ############################
    def __init__(self, bot: bridge.Bot):
        self.bot = bot


#####################
###### SETUP ########
#####################

def setup(bot: bridge.Bot):
    bot.add_cog(Admin(bot))
