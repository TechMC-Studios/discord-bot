#!/usr/bin/env python3
"""Main bot runner with auto-loading of cogs."""

import asyncio
import logging
import os
from pathlib import Path
import contextlib
import signal

import discord
from discord.ext import bridge
from dotenv import load_dotenv

from core.config import load_config
from core.logging_setup import setup_logging

# Load environment variables
load_dotenv()

# Load configuration
config = load_config()

# Setup logging
setup_logging(config.log_level)
logger = logging.getLogger(__name__)


class TechMCBot(bridge.Bot):
    """Main bot class with auto-loading capabilities."""

    def __init__(self):
        intents = discord.Intents.all()

        print(config.guild_ids)
        super().__init__(
            command_prefix=config.command_prefix,
            help_command=None,
            intents=intents,
        )
        # Guard to ensure extensions load once
        self._extensions_loaded = False

        @self.user_command(name="Account Creation Date")
        async def account_creation_date(
            ctx: bridge.BridgeContext, member: discord.Member
        ):  # user commands take the member as the second argument
            await ctx.respond(
                f"{member.name}'s account was created on {member.created_at}"
            )

    async def load_cogs(self):
        """Load all cogs from modular directories (features and system).

        Supports:
        - features/<feature>/cog.py
        - features/<feature>/cogs/*.py
        - system/**/cog.py
        - system/**/cogs/*.py
        Feature toggles can be set in config.yml under 'features'.
        """
        base_dir = Path(__file__).parent
        targets = [
            (base_dir / "features", "features", True),
            (base_dir / "system", "system", False),
        ]

        modules_to_load: set[str] = set()
        packages_with_cogs: set[tuple[str, str]] = set()  # (root_pkg, subpkg)

        for root, pkg, is_feature_pkg in targets:
            if not root.exists():
                continue

            # Patterns to search
            patterns = ["**/cogs/*.py", "**/cog.py"]
            for pattern in patterns:
                for file in root.glob(pattern):
                    if file.name.startswith("_") or file.name == "__init__.py":
                        continue
                    rel = file.relative_to(base_dir).with_suffix("")
                    parts = rel.parts
                    # parts example: ('features','tickets','cogs','main') or ('system','help','cog')
                    if len(parts) >= 2:
                        root_pkg = parts[0]  # 'features' | 'system'
                        subpkg = parts[1]
                        if is_feature_pkg and not config.is_feature_enabled(subpkg):
                            continue
                        # if this is a cogs module, mark package as having cogs
                        if len(parts) >= 3 and parts[2] == "cogs":
                            packages_with_cogs.add((root_pkg, subpkg))
                        # if root cog.py and package has cogs, skip to avoid duplicate
                        if (
                            parts[-1] == "cog"
                            and (root_pkg, subpkg) in packages_with_cogs
                        ):
                            continue
                    module = ".".join(parts)
                    modules_to_load.add(module)

        for module in sorted(modules_to_load):
            try:
                self.load_extension(module)
                logger.info(f"Loaded extension: {module}")
            except Exception as e:
                logger.error(f"Failed to load extension {module}: {e}")

    async def on_ready(self):
        """Called when the bot is ready."""
        logger.info(f"Bot is ready! Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guilds")

        # Set presence
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"studios.techmc.es",
            )
        )


async def main():
    """Main entry point."""
    bot = TechMCBot()

    # Register clean shutdown on SIGINT/SIGTERM so Discord disconnects immediately
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(bot.close()))
            except NotImplementedError:
                # Some platforms (e.g., Windows) may not support this
                pass
    except RuntimeError:
        # Fallback if no running loop yet; not expected under asyncio.run
        pass

    # Read token exclusively from config.yml
    token = str(config.get("token", "") or "").strip()
    if not token:
        logger.error("No token configured in config.yml (key: 'token').")
        return

    try:
        # Load extensions before connecting so they are ready for events
        if not bot._extensions_loaded:
            await bot.load_cogs()
            bot._extensions_loaded = True
        await bot.start(token)
    except discord.LoginFailure:
        logger.error("Invalid bot token!")
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutdown requested by user")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
    finally:
        if not bot.is_closed():
            with contextlib.suppress(Exception):
                await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
