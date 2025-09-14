import discord
import re

from core.config import load_config
from core.i18n import t
from core.utils.message_ttl import (
    schedule_followup_delete,
    reschedule_delete_for_same_message,
)
from . import embeds as ui_embeds
from ..services.spigot_service import SpigotService
from ..services.verification_service import VerificationService
from ..services.author_parser import AuthorParser
from ..services.polymart_service import PolymartService

import logging

logger = logging.getLogger(__name__)


######################
###### HELPERS #######
######################
# TTL helpers
def _ui_ttl(key: str, default: int) -> int:
    """Read UI TTL seconds from config with a sensible default."""
    try:
        cfg = load_config()
        ver = cfg.module("verification") or {}
        ui = ver.get("ui", {}) if isinstance(ver, dict) else {}
        ttl = ui.get("ttl", {}) if isinstance(ui, dict) else {}
        val = ttl.get(key)
        return int(val) if val is not None else int(default)
    except Exception:
        return int(default)
# Helpers to reduce duplication across the four Spigot flows
def _current_discord_tag(user: discord.User | discord.Member) -> str:
    """Return the current Discord username used for comparison.

    We intentionally use `user.name` (not global_name) to match the Spigot
    profile's Discord field recommendation.
    """
    try:
        return str(user.name)
    except Exception:
        return str(getattr(user, "name", ""))


async def _assign_roles_from_resources(
    inter: discord.Interaction, resources: list[dict] | None
) -> None:
    try:
        cfg = load_config()
        ver_mod = cfg.module("verification")
        roles_cfg = ver_mod.get("roles", {}) if isinstance(ver_mod, dict) else {}
        plugins_cfg = ver_mod.get("plugins", {}) if isinstance(ver_mod, dict) else {}

        guild = inter.guild
        member = inter.user if hasattr(inter.user, "add_roles") else None
        roles_to_add: list[discord.Role] = []
        if guild and member:
            buyer_role_id = (
                int(roles_cfg.get("buyer", 0)) if isinstance(roles_cfg, dict) else 0
            )
            if buyer_role_id:
                role = guild.get_role(buyer_role_id)
                if role and role not in getattr(member, "roles", []):
                    roles_to_add.append(role)
            if isinstance(resources, list):
                for r in resources:
                    try:
                        slug = str(r.get("slug", "")).strip()
                        plug = (
                            plugins_cfg.get(slug, {})
                            if isinstance(plugins_cfg, dict)
                            else {}
                        )
                        role_id = (
                            int(plug.get("role", 0)) if isinstance(plug, dict) else 0
                        )
                        if role_id:
                            prole = guild.get_role(role_id)
                            if prole and prole not in getattr(member, "roles", []):
                                roles_to_add.append(prole)
                    except Exception:
                        continue
            if roles_to_add:
                unique_roles = []
                seen = set()
                for r in roles_to_add:
                    if r.id not in seen:
                        unique_roles.append(r)
                        seen.add(r.id)
                try:
                    await member.add_roles(
                        *unique_roles,
                        reason="Verification: grant buyer/plugin roles",
                    )
                except Exception:
                    pass
    except Exception:
        pass


async def _unassign_roles_from_old_owner(
    inter: discord.Interaction,
    platform: str,
    platform_user_id: str,
    resources_to_transfer: list[dict] | None,
) -> None:
    """If the platform account is already linked to a different Discord user,
    remove the corresponding plugin roles (and buyer role if left with none)
    from the old member.

    - platform: "spigot" | "polymart"
    - platform_user_id: author id (spigot) or polymart user id
    - resources_to_transfer: list of dicts with at least {slug}
    """
    try:
        guild = inter.guild
        if guild is None:
            return

        # Load role mappings
        cfg = load_config()
        ver_mod = cfg.module("verification")
        plugins_cfg = ver_mod.get("plugins", {}) if isinstance(ver_mod, dict) else {}
        roles_cfg = ver_mod.get("roles", {}) if isinstance(ver_mod, dict) else {}
        buyer_role_id = int(roles_cfg.get("buyer", 0)) if isinstance(roles_cfg, dict) else 0

        # Ask internal API who is currently linked to this platform account
        ver = VerificationService()
        try:
            status, data = await ver.get_user(platform, platform_user_id)
        except Exception:
            return
        if status != 200 or not isinstance(data, dict):
            return

        old_discord_id = (
            str(data.get("discord_id") or data.get("discordId") or data.get("discord"))
            if data
            else None
        )
        if not old_discord_id:
            return

        # Do nothing if it's the same user
        try:
            if str(inter.user.id) == str(int(old_discord_id)):
                return
        except Exception:
            if str(inter.user.id) == str(old_discord_id):
                return

        # Resolve the old member, handle not found
        old_member = guild.get_member(int(old_discord_id)) if str(old_discord_id).isdigit() else None
        if old_member is None:
            try:
                if str(old_discord_id).isdigit():
                    old_member = await guild.fetch_member(int(old_discord_id))
            except Exception:
                old_member = None
        if old_member is None:
            # Not in server; nothing to remove
            return

        # Determine plugin roles to remove based on provided resources
        role_ids_to_remove: list[int] = []
        if isinstance(resources_to_transfer, list):
            for r in resources_to_transfer:
                slug = str(r.get("slug", ""))
                plug = plugins_cfg.get(slug, {}) if isinstance(plugins_cfg, dict) else {}
                rid = int(plug.get("role", 0)) if isinstance(plug, dict) else 0
                if rid:
                    role_ids_to_remove.append(rid)

        roles_to_remove = []
        current_roles = getattr(old_member, "roles", [])
        current_role_ids = {role.id for role in current_roles}
        for rid in role_ids_to_remove:
            if rid in current_role_ids:
                role_obj = guild.get_role(rid)
                if role_obj:
                    roles_to_remove.append(role_obj)

        # Remove plugin roles destined to transfer
        if roles_to_remove:
            try:
                await old_member.remove_roles(
                    *roles_to_remove, reason=f"Verification: reassign {platform} ownership"
                )
            except Exception:
                pass

        # After removal, if old member has no plugin roles, remove buyer role
        try:
            remaining_plugin_role_ids = set()
            for slug, plug in (plugins_cfg.items() if isinstance(plugins_cfg, dict) else []):
                try:
                    rid = int(plug.get("role", 0)) if isinstance(plug, dict) else 0
                    if rid:
                        remaining_plugin_role_ids.add(rid)
                except Exception:
                    continue
            old_member_role_ids = {r.id for r in getattr(old_member, "roles", [])}
            has_any_plugin = any(rid in old_member_role_ids for rid in remaining_plugin_role_ids)
            if not has_any_plugin and buyer_role_id:
                buyer_role = guild.get_role(buyer_role_id)
                if buyer_role and buyer_role in getattr(old_member, "roles", []):
                    try:
                        await old_member.remove_roles(
                            buyer_role, reason="Verification: remove buyer (no plugin roles left)"
                        )
                    except Exception:
                        pass
        except Exception:
            pass
    except Exception:
        pass


async def _process_spigot_author(
    inter: discord.Interaction,
    parent_inter: discord.Interaction,
    ai,
) -> None:
    """Shared flow once we have an AuthorInfo (ai) from any of the 4 methods."""
    current_discord_tag = _current_discord_tag(inter.user)
    spigot_discord = (ai.discord_name or "").strip()

    if not spigot_discord:
        embeds = [
            ui_embeds.spigot_link_details_embed(
                inter,
                author=ai,
                current_discord=current_discord_tag,
                spigot_discord=None,
                mismatch=False,
            ),
            ui_embeds.spigot_link_step1_embed(inter),
            ui_embeds.spigot_link_step2_embed(inter),
            ui_embeds.spigot_link_final_embed(inter, mismatch=False),
        ]
        await parent_inter.edit_original_response(
            embeds=embeds,
            view=SpigotLinkHelpView(
                inter, author_id=str(ai.id), author_username=ai.username
            ),
        )
        try:
            reschedule_delete_for_same_message(parent_inter, delay_seconds=_ui_ttl("panel_default", 300))
        except Exception:
            pass
        return

    if spigot_discord.lower() != current_discord_tag.lower():
        embeds = [
            ui_embeds.spigot_link_details_embed(
                inter,
                author=ai,
                current_discord=current_discord_tag,
                spigot_discord=spigot_discord,
                mismatch=True,
            ),
            ui_embeds.spigot_link_step1_embed(inter),
            ui_embeds.spigot_link_step2_embed(inter),
            ui_embeds.spigot_link_final_embed(inter, mismatch=True),
        ]
        await parent_inter.edit_original_response(
            embeds=embeds,
            view=SpigotLinkHelpView(
                inter, author_id=str(ai.id), author_username=ai.username
            ),
        )
        try:
            reschedule_delete_for_same_message(
                parent_inter, delay_seconds=_ui_ttl("panel_default", 300)
            )
        except Exception:
            pass
        return

    # If matched, proceed with verification API lookup and role assignment
    ver = VerificationService()
    try:
        u_status, u_data = await ver.get_user("spigot", ai.id)
    except Exception:
        # API likely down now; inform user and disable controls
        down = ui_embeds.verification_api_down_embed(inter)
        await parent_inter.edit_original_response(
            embed=down, view=SpigotVerifyView(inter, disabled=True)
        )
        try:
            reschedule_delete_for_same_message(parent_inter, delay_seconds=_ui_ttl("panel_short", 120))
        except Exception:
            pass
        return
    if u_status == 0:
        down = ui_embeds.verification_api_down_embed(inter)
        await parent_inter.edit_original_response(
            embed=down, view=SpigotVerifyView(inter, disabled=True)
        )
        try:
            reschedule_delete_for_same_message(
                parent_inter, delay_seconds=_ui_ttl("panel_short", 120)
            )
        except Exception:
            pass
        return
    if u_status != 200 or not isinstance(u_data, dict):
        embed = ui_embeds.spigot_not_buyer_embed(inter, ai)
        await parent_inter.edit_original_response(
            embed=embed, view=SpigotVerifyView(inter)
        )
        try:
            reschedule_delete_for_same_message(parent_inter, delay_seconds=_ui_ttl("panel_default", 300))
        except Exception:
            pass
        return

    try:
        await ver.link_discord("spigot", ai.id, inter.user.id)
    except Exception:
        pass

    resources = u_data.get("resources", []) if isinstance(u_data, dict) else []
    # Before granting roles to the current user, remove them from the previously linked owner (if different)
    try:
        await _unassign_roles_from_old_owner(inter, "spigot", str(ai.id), resources)
    except Exception:
        pass
    await _assign_roles_from_resources(inter, resources)

    embed = ui_embeds.spigot_user_resources_embed(inter, ai, resources)
    await parent_inter.edit_original_response(embed=embed, view=None)
    try:
        reschedule_delete_for_same_message(
            parent_inter, delay_seconds=_ui_ttl("panel_default", 300)
        )
    except Exception:
        pass


def _style_from_str(name: str) -> discord.ButtonStyle:
    name = (name or "").strip().lower()
    mapping = {
        "primary": discord.ButtonStyle.primary,
        "secondary": discord.ButtonStyle.secondary,
        "success": discord.ButtonStyle.success,
        "danger": discord.ButtonStyle.danger,
    }
    return mapping.get(name, discord.ButtonStyle.primary)


class VerifyPlatformButton(discord.ui.Button):
    """Button representing a platform choice (e.g., Spigot, Polymart)."""

    def __init__(
        self,
        platform_key: str,
        platform_name: str,
        *,
        emoji: str | None,
        style: discord.ButtonStyle,
        row: int | None = None,
    ):
        super().__init__(
            label=platform_name,
            emoji=emoji,
            style=style,
            row=row,
        )
        self.platform_key = platform_key

    async def callback(self, interaction: discord.Interaction):
        # BuiltByBit flow: create a private thread and guide the user with i18n

        if self.platform_key == "builtbybit":
            try:
                await interaction.response.defer()

                cfg = load_config()
                ver_mod = cfg.module("verification")

                channels_cfg = ver_mod.get("channels", {})
                parent_channel_id = int(channels_cfg.get("verification_channel", 0))

                # Resolve parent channel
                parent_channel = interaction.client.get_channel(parent_channel_id)

                if parent_channel is None or not isinstance(
                    parent_channel, discord.TextChannel
                ):
                    await interaction.followup.send(
                        content=t(interaction, "verification.errors.channel_not_found"),
                        ephemeral=True,
                        delete_after=_ui_ttl("error_medium", 15),
                    )
                    return

                thread_name = f"verify-{interaction.user.name}"[:90]

                thread = await parent_channel.create_thread(
                    name=thread_name,
                    type=discord.ChannelType.private_thread,
                    auto_archive_duration=60,
                    invitable=False,
                    reason="Verification thread for user",
                )

                # BuiltByBit bot mention from config if available
                bbb_cfg = ver_mod.get("builtbybit", {})
                bbb_bot_id = str(bbb_cfg.get("bot_id", "")).strip().strip(".")
                bbb_bot_mention = (
                    f"<@{bbb_bot_id}>"
                    if bbb_bot_id.isdigit()
                    else t(interaction, "verification.labels.username")
                )

                # Minimal embed from helper: only title and description
                embed = ui_embeds.bbb_thread_instructions_embed(
                    interaction, bbb_bot_mention
                )

                # Send embed with persistent Notify Staff button (localized)
                await thread.send(embed=embed, view=NotifyStaffView(interaction))

                # Now add the user to the private thread so they can view it
                try:
                    await thread.add_user(interaction.user)
                except Exception:
                    pass

                # Ephemeral confirmation with a link button to the thread
                view = discord.ui.View()
                # Build a safe URL to the thread
                thread_url = getattr(
                    thread,
                    "jump_url",
                    f"https://discord.com/channels/{interaction.guild_id}/{thread.parent_id}/{thread.id}",
                )
                view.add_item(
                    discord.ui.Button(
                        label=t(interaction, "verification.bbb.thread.open_button"),
                        style=discord.ButtonStyle.link,
                        url=thread_url,
                    )
                )

                # Edit the original platforms message with a brief embed and link button
                await interaction.edit_original_response(
                    embed=ui_embeds.thread_link_brief_embed(interaction), view=view
                )
                # Reschedule deletion for this same message (extend lifetime)
                try:
                    reschedule_delete_for_same_message(
                        interaction, delay_seconds=_ui_ttl("panel_short", 120)
                    )
                except Exception:
                    pass

                return
            except Exception as e:
                try:
                    await interaction.followup.send(
                        content=str(e), ephemeral=True, delete_after=_ui_ttl("error_short", 10)
                    )
                except Exception:
                    pass
                return

        # Spigot flow: show 4 verification methods via buttons + modals
        if self.platform_key == "spigot":
            try:
                await interaction.response.defer(ephemeral=True)

                # Check internal verification API health; if down, inform and disable UI
                ver = VerificationService()
                is_healthy = await ver.check_health()

                if not is_healthy:
                    down_embed = ui_embeds.verification_api_down_embed(interaction)
                    await interaction.edit_original_response(
                        embed=down_embed,
                        view=SpigotVerifyView(interaction, disabled=True),
                    )
                    try:
                        reschedule_delete_for_same_message(
                            interaction, delay_seconds=_ui_ttl("panel_short", 120)
                        )
                    except Exception:
                        pass
                    return

                embed = ui_embeds.spigot_verification_methods_embed(interaction)
                view = SpigotVerifyView(interaction)

                await interaction.edit_original_response(embed=embed, view=view)
                try:
                    # Extend lifetime to configured default
                    reschedule_delete_for_same_message(
                        interaction, delay_seconds=_ui_ttl("panel_default", 300)
                    )
                except Exception:
                    pass
                return
            except Exception as e:
                try:
                    await interaction.followup.send(
                        content=str(e), ephemeral=True, delete_after=_ui_ttl("error_short")
                    )
                except Exception:
                    pass
                return

        # Polymart flow: generate verification URL and show modal for token
        if self.platform_key == "polymart":
            try:
                await interaction.response.defer(ephemeral=True)

                # Check internal verification API health
                # Generate verification URL from Polymart
                polymart = PolymartService()
                ver = VerificationService()
                is_healthy = await ver.check_health() and await polymart.check_health()

                if not is_healthy:
                    # Delete the original message and show only a brief ephemeral error
                    try:
                        await interaction.delete_original_response()
                    except Exception:
                        try:
                            await interaction.edit_original_response(embeds=[], view=None)
                        except Exception:
                            pass
                    down_embed = ui_embeds.verification_api_down_embed(interaction)
                    await interaction.followup.send(
                        embed=down_embed, ephemeral=True, delete_after=_ui_ttl("error_medium", 15)
                    )
                    return

                success, url, error = await polymart.generate_verification_url()

                if not success:
                    # Delete the original message and show only a brief ephemeral error
                    try:
                        await interaction.delete_original_response()
                    except Exception:
                        try:
                            await interaction.edit_original_response(embeds=[], view=None)
                        except Exception:
                            pass
                    error_embed = discord.Embed(
                        title=t(interaction, "verification.polymart.error.title"),
                        description=t(
                            interaction,
                            "verification.polymart.error.generate_url",
                            error=error or "Unknown error",
                        ),
                        color=discord.Color.red(),
                    )
                    await interaction.followup.send(
                        embed=error_embed, ephemeral=True, delete_after=_ui_ttl("error_medium", 15)
                    )
                    return

                # Show 4-step guide as separate embeds with images; buttons appear once
                step1 = discord.Embed(
                    title=t(interaction, "verification.polymart.embed.step1"),
                    description=t(
                        interaction, "verification.polymart.embed.step1_desc"
                    ),
                    color=discord.Color.blue(),
                )
                step1.set_image(
                    url=(
                        "https://cdn.discordapp.com/attachments/1413195767455289480/1415087159416983712/image.png?ex=68c1ee1d&is=68c09c9d&hm=93b6ff1225f1ef1f056a6a3067397103c42073ba0f412e55dc57ed4682f2b21b&"
                    )
                )
                step1.set_footer(
                    text=t(interaction, "verification.polymart.embed.footer"),
                    icon_url=(
                        interaction.client.user.avatar.url
                        if interaction.client.user.avatar
                        else None
                    ),
                )

                step2 = discord.Embed(
                    title=t(interaction, "verification.polymart.embed.step2"),
                    description=t(
                        interaction, "verification.polymart.embed.step2_desc"
                    ),
                    color=discord.Color.blue(),
                )
                step2.set_image(
                    url=(
                        "https://cdn.discordapp.com/attachments/1413195767455289480/1415087275334701056/image.png?ex=68c1ee39&is=68c09cb9&hm=4de9b7a880fc50c0df855ddd65e57b67d828daea783b5e9b742a83185c85e908&"
                    )
                )
                step2.set_footer(
                    text=t(interaction, "verification.polymart.embed.footer"),
                    icon_url=(
                        interaction.client.user.avatar.url
                        if interaction.client.user.avatar
                        else None
                    ),
                )

                step3 = discord.Embed(
                    title=t(interaction, "verification.polymart.embed.step3"),
                    description=t(
                        interaction, "verification.polymart.embed.step3_desc"
                    ),
                    color=discord.Color.blue(),
                )
                step3.set_image(
                    url=(
                        "https://cdn.discordapp.com/attachments/1413195767455289480/1415087417265750187/image.png?ex=68c1ee5b&is=68c09cdb&hm=f5a776c93d73ad7c28e04452edb9585ab6400c3dbb42e56c11b58290a4bcbe76&"
                    )
                )
                step3.set_footer(
                    text=t(interaction, "verification.polymart.embed.footer"),
                    icon_url=(
                        interaction.client.user.avatar.url
                        if interaction.client.user.avatar
                        else None
                    ),
                )

                step4 = discord.Embed(
                    title=t(interaction, "verification.polymart.embed.step4"),
                    description=t(
                        interaction, "verification.polymart.embed.step4_desc"
                    ),
                    color=discord.Color.blue(),
                )
                step4.set_image(
                    url=(
                        "https://cdn.discordapp.com/attachments/1413195767455289480/1415087525466210477/image.png?ex=68c1ee75&is=68c09cf5&hm=8b030d1cb400e015a9e0a51bf95d816f8ba73aec1414f28edcce25fc02fddfbd&"
                    )
                )
                step4.set_footer(
                    text=t(interaction, "verification.polymart.embed.footer"),
                    icon_url=(
                        interaction.client.user.avatar.url
                        if interaction.client.user.avatar
                        else None
                    ),
                )

                view = PolymartVerifyView(interaction, url)
                await interaction.edit_original_response(
                    embeds=[step1, step2, step3, step4], view=view
                )

                try:
                    reschedule_delete_for_same_message(
                        interaction, delay_seconds=_ui_ttl("panel_default", 300)
                    )
                except Exception:
                    pass

                return
            except Exception as e:
                logger.error(f"Error in Polymart verification flow: {e}")
                try:
                    await interaction.followup.send(
                        content=t(interaction, "verification.errors.generic"),
                        ephemeral=True,
                        delete_after=_ui_ttl("error_short", 10),
                    )
                except Exception:
                    pass
                return

        # Placeholder for other platforms
        if not interaction.response.is_done():
            await interaction.response.send_message(
                t(interaction, "verification.errors.generic"),
                ephemeral=True,
                delete_after=_ui_ttl("error_short", 10),
            )


#############################
###### VIEWS - PLATFORMS ####
#############################
class PlatformsView(discord.ui.View):
    """View listing platforms for a selected plugin and a Notify Staff button."""

    def __init__(self, ctx: discord.Interaction | object | None = None):
        super().__init__(timeout=None)

        self._ctx = ctx
        cfg = load_config()
        ver_mod = cfg.module("verification")
        # Note: config file uses key 'plataforms'
        platforms_cfg = ver_mod.get("plataforms", {}) or {}

        max_per_row = 5
        for idx, (pkey, pdata) in enumerate(platforms_cfg.items()):
            name = str(pdata.get("name", pkey))
            emoji = pdata.get("emoji")
            btn_color = str(pdata.get("btn_color", "secondary"))
            style = _style_from_str(btn_color)
            row = idx // max_per_row
            self.add_item(
                VerifyPlatformButton(
                    platform_key=pkey,
                    platform_name=name,
                    emoji=emoji,
                    style=style,
                    row=row,
                )
            )

        # Add a row-1 "Notify Staff" button that creates a private thread and links back
        notify_label = (
            t(ctx, "verification.platforms.notify_staff.button")
            if ctx
            else "Notify Staff"
        )
        notify_btn = discord.ui.Button(
            label=notify_label,
            style=discord.ButtonStyle.danger,
            custom_id="verification:platforms:notify_staff",
            emoji="🆘",
            row=1,
        )

        async def on_notify(inter: discord.Interaction):
            # Build a confirmation step to avoid accidental clicks
            if not inter.response.is_done():
                await inter.response.defer(ephemeral=True)

            async def create_help_thread():
                # Resolve config
                cfg_l = load_config()
                ver_mod_l = cfg_l.module("verification")
                channels_cfg = ver_mod_l.get("channels", {})
                parent_channel_id = int(channels_cfg.get("verification_channel", 0))
                staff_role_id = int(channels_cfg.get("staff_role", 0))

                parent_channel = inter.client.get_channel(parent_channel_id)
                if parent_channel is None or not isinstance(
                    parent_channel, discord.TextChannel
                ):
                    await inter.followup.send(
                        content=t(inter, "verification.errors.channel_not_found"),
                        ephemeral=True,
                        delete_after=_ui_ttl("error_medium", 15),
                    )
                    return

                thread_name = f"verify-{inter.user.name}"[:90]
                try:
                    thread = await parent_channel.create_thread(
                        name=thread_name,
                        type=discord.ChannelType.private_thread,
                        auto_archive_duration=60,
                        invitable=False,
                        reason="Verification thread (Notify Staff)",
                    )
                except Exception as e:
                    await inter.followup.send(
                        content=str(e), ephemeral=True, delete_after=_ui_ttl("error_short", 10)
                    )
                    return

                # Mention staff role and user in the thread with a brief message
                role_mention = f"<@&{staff_role_id}>" if staff_role_id else ""
                content = (
                    t(
                        inter,
                        "verification.platforms.notify_staff.content.with_role",
                        role=role_mention,
                        user=inter.user.mention,
                    )
                    if role_mention
                    else t(
                        inter,
                        "verification.platforms.notify_staff.content.no_role",
                        user=inter.user.mention,
                    )
                )
                try:
                    await thread.send(
                        content,
                        allowed_mentions=discord.AllowedMentions(
                            everyone=False, users=True, roles=True
                        ),
                    )
                except Exception:
                    pass

                # Add the user to the thread
                try:
                    await thread.add_user(inter.user)
                except Exception:
                    pass

                # Edit original ephemeral message to show link to the thread
                link_view = discord.ui.View()
                thread_url = getattr(
                    thread,
                    "jump_url",
                    f"https://discord.com/channels/{inter.guild_id}/{thread.parent_id}/{thread.id}",
                )
                link_view.add_item(
                    discord.ui.Button(
                        label=t(inter, "verification.bbb.thread.open_button"),
                        style=discord.ButtonStyle.link,
                        url=thread_url,
                    )
                )
                await inter.edit_original_response(
                    embed=ui_embeds.thread_link_brief_embed(inter),
                    view=link_view,
                )
                try:
                    reschedule_delete_for_same_message(
                        inter, delay_seconds=_ui_ttl("link_thread", 180)
                    )
                except Exception:
                    pass

            # Confirmation view
            confirm_view = discord.ui.View()
            yes_btn = discord.ui.Button(
                label=t(inter, "verification.platforms.notify_staff.confirm.yes"),
                style=discord.ButtonStyle.danger,
                custom_id="verification:platforms:notify_confirm_yes",
            )
            no_btn = discord.ui.Button(
                label=t(inter, "verification.platforms.notify_staff.confirm.no"),
                style=discord.ButtonStyle.secondary,
                custom_id="verification:platforms:notify_confirm_no",
            )

            async def on_yes(_i: discord.Interaction):
                # Acknowledge this button press without sending a new message
                if not _i.response.is_done():
                    await _i.response.defer()
                # Disable confirm buttons to prevent double clicks
                yes_btn.disabled = True
                no_btn.disabled = True
                try:
                    await inter.edit_original_response(view=confirm_view)
                except Exception:
                    pass
                await create_help_thread()

            async def on_no(_i: discord.Interaction):
                # Acknowledge this button press and disable confirm buttons
                if not _i.response.is_done():
                    await _i.response.defer()
                yes_btn.disabled = True
                no_btn.disabled = True
                try:
                    await inter.edit_original_response(view=confirm_view)
                except Exception:
                    pass
                # Restore original platforms selection view
                try:
                    await inter.edit_original_response(
                        embed=ui_embeds.select_platform_only_embed(inter),
                        view=PlatformsView(inter),
                    )
                except Exception:
                    pass
                try:
                    reschedule_delete_for_same_message(
                        inter, delay_seconds=_ui_ttl("link_thread", 180)
                    )
                except Exception:
                    pass

            yes_btn.callback = on_yes
            no_btn.callback = on_no
            confirm_view.add_item(yes_btn)
            confirm_view.add_item(no_btn)

            # Show confirmation prompt
            try:
                embed = discord.Embed(
                    title=t(inter, "verification.platforms.notify_staff.confirm.title"),
                    description=t(
                        inter, "verification.platforms.notify_staff.confirm.desc"
                    ),
                    color=discord.Color.red(),
                )
                await inter.edit_original_response(embed=embed, view=confirm_view)
            except Exception:
                # Fallback: send as followup
                await inter.followup.send(
                    t(inter, "verification.platforms.notify_staff.confirm.desc"),
                    view=confirm_view,
                    ephemeral=True,
                )

        notify_btn.callback = on_notify
        self.add_item(notify_btn)


########################
###### VIEWS - PANEL ###
########################
class VerificationViewPanel(discord.ui.View):
    def __init__(self, ctx: discord.Interaction | object | None = None):
        super().__init__(timeout=None)
        # Localize the Verify button label using provided context
        try:
            for child in self.children:
                if (
                    isinstance(child, discord.ui.Button)
                    and child.custom_id == "verification:btn:verify"
                ):
                    if ctx is not None:
                        child.label = t(ctx, "verification.panel.button.verify")
        except Exception:
            pass

    @discord.ui.button(
        label="Verify",
        style=discord.ButtonStyle.success,
        custom_id="verification:btn:verify",
        emoji="<a:verified:1253145469610229890>",
    )
    async def verify(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = ui_embeds.select_platform_only_embed(interaction)

        msg = await interaction.followup.send(
            embed=embed,
            view=PlatformsView(interaction),
            ephemeral=True,
            # We self-manage deletion so we can extend it later upon edits
            # (do not use delete_after here)
        )
        # Schedule deletion of the platforms panel; can be extended by future edits
        try:
            schedule_followup_delete(
                interaction, message_or_id=msg.id, delay_seconds=_ui_ttl("panel_default", 300)
            )
        except Exception:
            pass


class NotifyStaffView(discord.ui.View):
    """Persistent view with a red 'Notify Staff' button that pings staff when pressed."""

    def __init__(self, ctx: discord.Interaction | object | None = None):
        super().__init__(timeout=None)
        # Localize the button label using the provided context
        try:
            for child in self.children:
                if (
                    isinstance(child, discord.ui.Button)
                    and child.custom_id == "verify:btn:notify_staff"
                ):
                    if ctx is not None:
                        child.label = t(ctx, "verification.bbb.notify.button")
        except Exception:
            pass

    @discord.ui.button(
        label="Notify Staff",
        style=discord.ButtonStyle.danger,
        custom_id="verify:btn:notify_staff",
        emoji="🚨",
    )
    async def notify_staff(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        cfg = load_config()
        ver_mod = cfg.module("verification")
        channels_cfg = ver_mod.get("channels", {})
        staff_role_id = int(channels_cfg.get("staff_role", 0))
        staff_channel_id = int(channels_cfg.get("staff_channel", 0))

        role_mention = f"<@&{staff_role_id}>" if staff_role_id else None

        # Prefer pinging in the current thread (localized content)
        content = (
            t(
                interaction,
                "verification.bbb.notify.content.with_role",
                role=role_mention,
                user=interaction.user.mention,
            )
            if role_mention
            else t(
                interaction,
                "verification.bbb.notify.content.no_role",
                user=interaction.user.mention,
            )
        )
        try:
            await interaction.response.send_message(
                content,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, users=True, roles=True
                ),
            )
        except Exception:
            # Fallback: post to a configured staff channel if available
            if staff_channel_id:
                ch = interaction.client.get_channel(staff_channel_id)
                if ch:
                    try:
                        await ch.send(
                            t(
                                interaction,
                                "verification.bbb.notify.fallback",
                                role=role_mention or "",
                                user=interaction.user.mention,
                                channel=getattr(
                                    interaction.channel, "mention", "#channel"
                                ),
                            )
                        )
                    except Exception:
                        pass
        # No ephemeral here; message should be visible to staff in the thread


class SpigotLinkHelpView(discord.ui.View):
    """View showing helpful links, a retry button (without re-asking ID), and a clear button."""

    def __init__(
        self,
        ctx: discord.Interaction | object | None = None,
        *,
        author_id: str | None = None,
        author_username: str | None = None,
    ):
        super().__init__(timeout=None)
        self._ctx = ctx
        self._author_id = str(author_id) if author_id else None
        self._author_username = author_username or None

        # Link to Personal Details (identities visibility)
        self.add_item(
            discord.ui.Button(
                label=(
                    t(ctx, "verification.spigot.link_help.buttons.personal_details")
                    if ctx
                    else "Personal Details"
                ),
                style=discord.ButtonStyle.link,
                url=(
                    t(ctx, "verification.spigot.link_help.links.personal_details")
                    if ctx
                    else "https://www.spigotmc.org/account/privacy#personal_details"
                ),
                row=0,
            )
        )

        # Link to Contact Details (Discord field)
        self.add_item(
            discord.ui.Button(
                label=(
                    t(ctx, "verification.spigot.link_help.buttons.contact_details")
                    if ctx
                    else "Contact Details"
                ),
                style=discord.ButtonStyle.link,
                url=(
                    t(ctx, "verification.spigot.link_help.links.contact_details")
                    if ctx
                    else "https://www.spigotmc.org/account/contact-details"
                ),
                row=0,
            )
        )

        # Retry button (reuses stored author ID)
        retry_label = (
            t(ctx, "verification.spigot.link_help.buttons.retry") if ctx else "Retry"
        )
        retry_btn = discord.ui.Button(
            label=retry_label,
            style=discord.ButtonStyle.primary,
            custom_id="spigot:btn:retry",
            row=1,
        )

        async def on_retry(inter: discord.Interaction):
            # Re-check the same author ID if available, otherwise fall back to modal
            if not inter.response.is_done():
                await inter.response.defer(ephemeral=True)

            if not self._author_id:
                await inter.followup.send(
                    t(inter, "verification.spigot.errors.invalid_id"),
                    ephemeral=True,
                    delete_after=_ui_ttl("error_short", 10),
                )
                return

            service = SpigotService()
            status, data = await service.spigot_get_author_by_id(self._author_id)
            ai = AuthorParser.parse_spigot_author(data)
            if status != 200 or not ai:
                await inter.followup.send(
                    t(inter, "verification.spigot.errors.not_found"),
                    ephemeral=True,
                    delete_after=_ui_ttl("error_short", 10),
                )
                return

            current_discord_tag = _current_discord_tag(inter.user)
            spigot_discord = (ai.discord_name or "").strip()
            if not spigot_discord:
                embeds = [
                    ui_embeds.spigot_link_step1_embed(inter),
                    ui_embeds.spigot_link_step2_embed(inter),
                    ui_embeds.spigot_link_final_embed(inter, mismatch=False),
                ]
                await self._edit_parent(inter, embeds=embeds)
                return
            if spigot_discord.lower() != current_discord_tag.lower():
                embeds = [
                    ui_embeds.spigot_link_step1_embed(inter),
                    ui_embeds.spigot_link_step2_embed(inter),
                    ui_embeds.spigot_link_final_embed(inter, mismatch=True),
                ]
                await self._edit_parent(inter, embeds=embeds)
                return

            # If matched now, continue with verification API flow
            ver = VerificationService()
            u_status, u_data = await ver.get_user("spigot", ai.id)
            if u_status != 200 or not isinstance(u_data, dict):
                embed = ui_embeds.spigot_not_buyer_embed(inter, ai)
                await self._edit_parent(inter, embed=embed)
                return

            # Attempt to link Discord and assign roles as in main flow
            try:
                await ver.link_discord("spigot", ai.id, inter.user.id)
            except Exception:
                pass

            resources = u_data.get("resources", []) if isinstance(u_data, dict) else []
            try:
                cfg = load_config()
                ver_mod = cfg.module("verification")
                roles_cfg = (
                    ver_mod.get("roles", {}) if isinstance(ver_mod, dict) else {}
                )
                plugins_cfg = (
                    ver_mod.get("plugins", {}) if isinstance(ver_mod, dict) else {}
                )

                guild = inter.guild
                member = inter.user if hasattr(inter.user, "add_roles") else None
                roles_to_add: list[discord.Role] = []
                if guild and member:
                    buyer_role_id = (
                        int(roles_cfg.get("buyer", 0))
                        if isinstance(roles_cfg, dict)
                        else 0
                    )
                    if buyer_role_id:
                        role = guild.get_role(buyer_role_id)
                        if role and role not in getattr(member, "roles", []):
                            roles_to_add.append(role)
                    if isinstance(resources, list):
                        for r in resources:
                            try:
                                slug = str(r.get("slug", "")).strip()
                                plug = (
                                    plugins_cfg.get(slug, {})
                                    if isinstance(plugins_cfg, dict)
                                    else {}
                                )
                                role_id = (
                                    int(plug.get("role", 0))
                                    if isinstance(plug, dict)
                                    else 0
                                )
                                if role_id:
                                    prole = guild.get_role(role_id)
                                    if prole and prole not in getattr(
                                        member, "roles", []
                                    ):
                                        roles_to_add.append(prole)
                            except Exception:
                                continue
                    if roles_to_add:
                        unique_roles = []
                        seen = set()
                        for r in roles_to_add:
                            if r.id not in seen:
                                unique_roles.append(r)
                                seen.add(r.id)
                        try:
                            await member.add_roles(
                                *unique_roles,
                                reason="Verification: grant buyer/plugin roles",
                            )
                        except Exception:
                            pass
            except Exception:
                pass

            embed = ui_embeds.spigot_user_resources_embed(inter, ai, resources)
            await self._edit_parent(inter, embed=embed)

        retry_btn.callback = on_retry
        self.add_item(retry_btn)

        # Clear button (red) to remove embeds and go back to methods
        clear_btn = discord.ui.Button(
            label=t(ctx, "verification.spigot.search.cancel") if ctx else "Clear",
            style=discord.ButtonStyle.danger,
            custom_id="spigot:btn:clear",
            row=1,
        )

        async def on_clear(inter: discord.Interaction):
            if not inter.response.is_done():
                await inter.response.defer(ephemeral=True)
            # Clear all embeds and remove view
            try:
                await inter.edit_original_response(
                    content=t(inter, "verification.spigot.link_help.cleared"),
                    embeds=[],
                    view=None,
                )
            except Exception:
                # Fallback: minimal content-only edit
                await inter.edit_original_response(content="Cleared.", view=None)

        clear_btn.callback = on_clear
        self.add_item(clear_btn)

    async def _edit_parent(
        self,
        interaction: discord.Interaction,
        *,
        embed: discord.Embed | None = None,
        embeds: list[discord.Embed] | None = None,
        view: discord.ui.View | None = None,
    ) -> None:
        if embeds is not None:
            await interaction.edit_original_response(embeds=embeds, view=view or self)
        elif embed is not None:
            await interaction.edit_original_response(embed=embed, view=view or self)
        try:
            reschedule_delete_for_same_message(
                interaction, delay_seconds=_ui_ttl("panel_default", 300)
            )
        except Exception:
            pass


class SpigotIdModal(discord.ui.Modal):
    """Modal to verify by Spigot account ID."""

    def __init__(self, parent_interaction: discord.Interaction):
        super().__init__(
            title=t(parent_interaction, "verification.spigot.modals.id.title")
        )
        self.parent_interaction = parent_interaction
        self.spigot_id = discord.ui.InputText(
            label=t(parent_interaction, "verification.labels.user_id"),
            placeholder="783167",
            required=True,
            max_length=12,
        )
        self.add_item(self.spigot_id)

    async def callback(self, interaction: discord.Interaction):
        # Ack the modal so it closes immediately
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        service = SpigotService()
        author_id = (str(self.spigot_id.value) or "").strip()
        if not author_id.isdigit():
            await interaction.followup.send(
                t(interaction, "verification.spigot.errors.invalid_id"),
                ephemeral=True,
                delete_after=_ui_ttl("error_short", 10),
            )
            return

        status, data = await service.spigot_get_author_by_id(author_id)
        ai = AuthorParser.parse_spigot_author(data)
        if status != 200 or not ai:
            await interaction.followup.send(
                t(interaction, "verification.spigot.errors.not_found"),
                ephemeral=True,
                delete_after=_ui_ttl("error_short", 10),
            )
            return
        # Shared path once we parsed the AuthorInfo
        await _process_spigot_author(interaction, self.parent_interaction, ai)


class SpigotUrlModal(discord.ui.Modal):
    """Modal to verify by Spigot profile URL."""

    def __init__(self, parent_interaction: discord.Interaction):
        super().__init__(
            title=t(parent_interaction, "verification.spigot.modals.url.title")
        )
        self.parent_interaction = parent_interaction
        self.profile_url = discord.ui.InputText(
            label=t(parent_interaction, "verification.spigot.labels.profile_url"),
            placeholder="https://www.spigotmc.org/members/md_5.1/",
            required=True,
            max_length=200,
        )
        self.add_item(self.profile_url)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        raw = (str(self.profile_url.value) or "").strip()
        # Expected format: https://www.spigotmc.org/members/<name>.<id>/
        m = re.match(
            r"^https?://(www\.)?spigotmc\.org/members/([A-Za-z0-9_\-\.]+)\.(\d+)(/)?$",
            raw,
        )
        if not m:
            await interaction.followup.send(
                t(interaction, "verification.spigot.errors.invalid_url"),
                ephemeral=True,
                delete_after=_ui_ttl("error_short", 10),
            )
            return
        name, author_id = m.group(2), m.group(3)
        service = SpigotService()
        status, data = await service.spigot_get_author_by_id(author_id)
        ai = AuthorParser.parse_spigot_author(data)
        if status != 200 or not ai:
            await interaction.followup.send(
                t(interaction, "verification.spigot.errors.not_found"),
                ephemeral=True,
                delete_after=_ui_ttl("error_short", 10),
            )
            return
        await _process_spigot_author(interaction, self.parent_interaction, ai)


class SpigotExactNameModal(discord.ui.Modal):
    """Modal to verify by exact Spigot username."""

    def __init__(self, parent_interaction: discord.Interaction):
        super().__init__(
            title=t(parent_interaction, "verification.spigot.modals.exact.title")
        )
        self.parent_interaction = parent_interaction
        self.username = discord.ui.InputText(
            label=t(parent_interaction, "verification.labels.username"),
            placeholder="Exact Spigot username",
            required=True,
            max_length=32,
        )
        self.add_item(self.username)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        name = (str(self.username.value) or "").strip()
        if not name:
            await interaction.followup.send(
                t(interaction, "verification.spigot.errors.invalid_name"),
                ephemeral=True,
                delete_after=_ui_ttl("error_short", 10),
            )
            return
        service = SpigotService()
        status, data = await service.spigot_find_author_by_name(name)
        ai = AuthorParser.parse_spigot_author(data)
        if status != 200 or not ai:
            await interaction.followup.send(
                t(interaction, "verification.spigot.errors.not_found"),
                ephemeral=True,
                delete_after=10,
            )
            return
        await _process_spigot_author(interaction, self.parent_interaction, ai)


class SpigotSearchResultsView(discord.ui.View):
    def __init__(
        self,
        parent_interaction: discord.Interaction,
        options: list[discord.SelectOption],
        *,
        page_size: int = 25,
    ):
        # 300s timeout per request
        super().__init__(timeout=300)
        self.parent_interaction = parent_interaction
        self._all_options: list[discord.SelectOption] = options
        self._page_size = max(1, min(25, page_size))
        self._page = 0

        # Build initial controls
        self._rebuild_children()
        # Ensure the ephemeral message is deleted after 300s unless extended again
        try:
            reschedule_delete_for_same_message(
                self.parent_interaction, delay_seconds=300
            )
        except Exception:
            pass

    def _slice_for_page(self) -> list[discord.SelectOption]:
        start = self._page * self._page_size
        end = start + self._page_size
        return self._all_options[start:end]

    def _rebuild_children(self) -> None:
        # Clear current components
        self.clear_items()

        # Select menu with current page options
        select = discord.ui.Select(
            placeholder=t(
                self.parent_interaction, "verification.spigot.search.select_placeholder"
            ),
            min_values=1,
            max_values=1,
            options=self._slice_for_page(),
            custom_id="spigot:search:select",
            row=0,
        )

        async def on_select(inter: discord.Interaction):
            value = select.values[0]
            service = SpigotService()
            # Ensure we defer the component interaction to enable followups
            if not inter.response.is_done():
                await inter.response.defer(ephemeral=True)
            status, data = await service.spiget_get_author_by_id(value)
            ai = AuthorParser.parse_spiget_author(data)
            if status != 200 or not ai:
                await inter.followup.send(
                    t(inter, "verification.spigot.errors.not_found"),
                    ephemeral=True,
                    delete_after=_ui_ttl("error_short", 10),
                )
                return
            await _process_spigot_author(inter, self.parent_interaction, ai)

        select.callback = on_select
        self.add_item(select)

        # Navigation buttons
        total_pages = (len(self._all_options) - 1) // self._page_size + 1

        prev_btn = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label=t(self.parent_interaction, "verification.spigot.search.prev"),
            emoji="⬅️",
            row=1,
            disabled=self._page <= 0,
        )

        next_btn = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label=t(self.parent_interaction, "verification.spigot.search.next"),
            emoji="➡️",
            row=1,
            disabled=self._page >= total_pages - 1,
        )

        cancel_btn = discord.ui.Button(
            style=discord.ButtonStyle.danger,
            label=t(self.parent_interaction, "verification.spigot.search.cancel"),
            emoji="❌",
            row=1,
        )

        async def on_prev(inter: discord.Interaction):
            await inter.response.defer(ephemeral=True)
            self._page = max(0, self._page - 1)
            self._rebuild_children()
            await self.parent_interaction.edit_original_response(view=self)
            try:
                reschedule_delete_for_same_message(
                    self.parent_interaction, delay_seconds=300
                )
            except Exception:
                pass

        async def on_next(inter: discord.Interaction):
            await inter.response.defer(ephemeral=True)
            self._page = min(total_pages - 1, self._page + 1)
            self._rebuild_children()
            await self.parent_interaction.edit_original_response(view=self)
            try:
                reschedule_delete_for_same_message(
                    self.parent_interaction, delay_seconds=300
                )
            except Exception:
                pass

        async def on_cancel(inter: discord.Interaction):
            await inter.response.defer(ephemeral=True)
            # Return to the methods view
            embed = ui_embeds.spigot_verification_methods_embed(inter)
            await self.parent_interaction.edit_original_response(
                embed=embed, view=SpigotVerifyView(inter)
            )
            try:
                reschedule_delete_for_same_message(
                    self.parent_interaction, delay_seconds=300
                )
            except Exception:
                pass

        prev_btn.callback = on_prev
        next_btn.callback = on_next
        cancel_btn.callback = on_cancel

        self.add_item(prev_btn)
        self.add_item(next_btn)
        self.add_item(cancel_btn)


class SpigotSearchModal(discord.ui.Modal):
    def __init__(self, parent_interaction: discord.Interaction):
        super().__init__(
            title=t(parent_interaction, "verification.spigot.modals.search.title")
        )
        self.parent_interaction = parent_interaction
        self.query = discord.ui.InputText(
            label=t(parent_interaction, "verification.spigot.modals.search.label"),
            placeholder="Type a Spigot username",
            required=True,
            max_length=32,
        )
        self.add_item(self.query)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        q = (str(self.query.value) or "").strip()
        if not q:
            await interaction.followup.send(
                t(interaction, "verification.spigot.errors.invalid_name"),
                ephemeral=True,
                delete_after=_ui_ttl("error_short", 10),
            )
            return
        service = SpigotService()
        status, results = await service.spiget_search_authors(q, size=100)
        if status != 200 or not isinstance(results, list) or not results:
            await interaction.followup.send(
                t(interaction, "verification.spigot.errors.not_found"),
                ephemeral=True,
                delete_after=_ui_ttl("error_short", 10),
            )
            return
        options: list[discord.SelectOption] = []
        authors = AuthorParser.parse_spiget_search_list(results)
        for ai in authors:
            try:
                options.append(
                    discord.SelectOption(
                        label=f"👤 {ai.username}",
                        value=ai.id,
                        description=f"ID: {ai.id}"
                        + (f" | Discord: {ai.discord_name}" if ai.discord_name else ""),
                    )
                )
            except Exception:
                continue
        # Show how many we are displaying out of the maximum requested (100)
        embed = ui_embeds.spigot_search_results_embed(
            interaction, shown=len(results), max_shown=100
        )
        await self.parent_interaction.edit_original_response(
            embed=embed,
            view=SpigotSearchResultsView(self.parent_interaction, options),
        )
        try:
            reschedule_delete_for_same_message(
                self.parent_interaction, delay_seconds=300
            )
        except Exception:
            pass


class SpigotVerifyView(discord.ui.View):
    def __init__(self, ctx: discord.Interaction | object, disabled: bool = False):
        super().__init__(timeout=None)
        self._ctx = ctx
        self._disabled = disabled
        # Localize button labels using the provided context
        try:
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    if child.custom_id == "spigot:btn:id":
                        child.label = t(self._ctx, "verification.spigot.buttons.by_id")
                    elif child.custom_id == "spigot:btn:url":
                        child.label = t(self._ctx, "verification.spigot.buttons.by_url")
                    elif child.custom_id == "spigot:btn:exact":
                        child.label = t(self._ctx, "verification.spigot.buttons.exact")
                    elif child.custom_id == "spigot:btn:search":
                        child.label = t(self._ctx, "verification.spigot.buttons.search")
                    # If API is down, disable all buttons to prevent attempts
                    child.disabled = bool(self._disabled)
        except Exception:
            pass

    @discord.ui.button(
        label="By URL",
        style=discord.ButtonStyle.success,
        custom_id="spigot:btn:url",
        emoji="🔗",
        row=0,
    )
    async def by_url(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(SpigotUrlModal(interaction))
        try:
            reschedule_delete_for_same_message(
                interaction, delay_seconds=_ui_ttl("panel_default", 300)
            )
        except Exception:
            pass

    @discord.ui.button(
        label="Exact name",
        style=discord.ButtonStyle.success,
        custom_id="spigot:btn:exact",
        emoji="🟰",
        row=0,
    )
    async def by_exact_name(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        await interaction.response.send_modal(SpigotExactNameModal(interaction))
        try:
            reschedule_delete_for_same_message(
                interaction, delay_seconds=_ui_ttl("panel_default", 300)
            )
        except Exception:
            pass

    @discord.ui.button(
        label="By ID",
        style=discord.ButtonStyle.success,
        custom_id="spigot:btn:id",
        emoji="#️⃣",
        row=0,
    )
    async def by_id(self, button: discord.ui.Button, interaction: discord.Interaction):
        # Open modal for ID input
        await interaction.response.send_modal(SpigotIdModal(interaction))
        try:
            reschedule_delete_for_same_message(
                interaction, delay_seconds=_ui_ttl("panel_default", 300)
            )
        except Exception:
            pass

    @discord.ui.button(
        label="Search name",
        style=discord.ButtonStyle.success,
        custom_id="spigot:btn:search",
        emoji="🔎",
        row=0,
    )
    async def search_name(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        await interaction.response.send_modal(SpigotSearchModal(interaction))
        try:
            reschedule_delete_for_same_message(
                interaction, delay_seconds=_ui_ttl("panel_default", 300)
            )
        except Exception:
            pass


class PolymartVerifyView(discord.ui.View):
    """View for Polymart verification with link and verify buttons."""

    def __init__(self, ctx: discord.Interaction, verification_url: str):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.verification_url = verification_url

        # Add link button to Polymart verification page
        link_btn = discord.ui.Button(
            label=t(ctx, "verification.polymart.button.link"),
            style=discord.ButtonStyle.link,
            url=verification_url,
            emoji="🔗",
        )
        self.add_item(link_btn)

        # Add verify button to open modal
        verify_btn = discord.ui.Button(
            label=t(ctx, "verification.polymart.button.verify"),
            style=discord.ButtonStyle.success,
            custom_id="polymart:btn:verify",
            emoji="✅",
        )
        verify_btn.callback = self.on_verify
        self.add_item(verify_btn)

    async def on_verify(self, interaction: discord.Interaction):
        """Open modal for token input."""
        modal = PolymartTokenModal(self.ctx)
        await interaction.response.send_modal(modal)


class PolymartTokenModal(discord.ui.Modal):
    """Modal for entering Polymart verification token."""

    def __init__(self, parent_ctx: discord.Interaction):
        super().__init__(
            title=t(parent_ctx, "verification.polymart.modal.title"), timeout=300
        )
        self.parent_ctx = parent_ctx

        # Add token input field
        self.token_input = discord.ui.InputText(
            label=t(parent_ctx, "verification.polymart.modal.label"),
            placeholder="XXX-XXX-XXX",
            required=True,
            min_length=11,
            max_length=15,
            style=discord.InputTextStyle.short,
        )
        self.add_item(self.token_input)

    async def callback(self, interaction: discord.Interaction):
        """Process the verification token."""
        token = self.token_input.value.strip()

        # Validate token format
        # Validate token format using segment rules to be more robust than regex
        def _valid_polymart_token(tok: str) -> bool:
            tok = tok.strip()
            parts = tok.split("-")
            if len(parts) not in (3, 4):
                return False
            # All parts must be alphanumeric
            if not all(p.isalnum() for p in parts):
                return False
            # First three segments must be exactly 3 chars
            if not all(len(p) == 3 for p in parts[:3]):
                return False
            # Optional 4th segment must be 1-3 chars if present
            if len(parts) == 4 and not (1 <= len(parts[3]) <= 3):
                return False
            # After removing dashes, total length must be between 9 and 12
            clean = "".join(parts)
            return 9 <= len(clean) <= 12 and clean.isalnum()

        if not _valid_polymart_token(token):
            # Keep the tutorial embeds; just show a brief ephemeral error
            await interaction.response.send_message(
                embed=discord.Embed(
                    title=t(interaction, "verification.polymart.error.title"),
                    description=t(
                        interaction, "verification.polymart.error.invalid_format"
                    ),
                    color=discord.Color.red(),
                ),
                ephemeral=True,
                delete_after=_ui_ttl("error_short", 10),
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Verify token with Polymart
        polymart = PolymartService()
        success, user_data, error = await polymart.verify_token(token)

        if not success:
            # Remove the original tutorial message so only a brief error remains
            try:
                await self.parent_ctx.delete_original_response()
            except Exception:
                try:
                    await self.parent_ctx.edit_original_response(embeds=[], view=None)
                except Exception:
                    pass
            await interaction.followup.send(
                embed=discord.Embed(
                    title=t(interaction, "verification.polymart.error.title"),
                    description=t(
                        interaction,
                        "verification.polymart.error.token_verify",
                        error=error or "Unknown error",
                    ),
                    color=discord.Color.red(),
                ),
                ephemeral=True,
                delete_after=_ui_ttl("error_medium", 15),
            )
            return

        # Get user ID from Polymart response
        polymart_user_id = str(user_data.get("id", ""))

        if not polymart_user_id:
            # Remove the original tutorial message so only a brief error remains
            try:
                await self.parent_ctx.delete_original_response()
            except Exception:
                try:
                    await self.parent_ctx.edit_original_response(embeds=[], view=None)
                except Exception:
                    pass
            await interaction.followup.send(
                embed=discord.Embed(
                    title=t(interaction, "verification.polymart.error.title"),
                    description=t(
                        interaction, "verification.polymart.error.no_user_data"
                    ),
                    color=discord.Color.red(),
                ),
                ephemeral=True,
                delete_after=_ui_ttl("error_medium", 15),
            )
            return

        # Get configured plugins to check purchases
        cfg = load_config()
        ver_mod = cfg.module("verification")
        plugins_cfg = ver_mod.get("plugins", {}) if isinstance(ver_mod, dict) else {}

        # Fetch Polymart account info (username, picture)
        acc_ok, polymart_username, profile_picture, acc_err = (
            await polymart.get_account_info(polymart_user_id)
        )
        if not polymart_username:
            polymart_username = "Unknown"

        # Check purchases per configured plugin (per-resource verification)
        purchased_resources: list[dict] = []
        for plugin_slug, plugin_data in plugins_cfg.items():
            if not isinstance(plugin_data, dict):
                continue
            polymart_id = plugin_data.get("polymart_id")
            if not polymart_id:
                continue
            api_key = plugin_data.get("polymart_api_key")
            ok, purchased, meta, perr = await polymart.check_resource_purchase(
                polymart_user_id, str(polymart_id), api_key
            )
            if ok and purchased:
                purchased_resources.append(
                    {
                        "slug": plugin_slug,
                        "name": plugin_data.get("name", plugin_slug),
                        "meta": meta,
                    }
                )

        # If no purchases found
        if not purchased_resources:

            # Remove the original tutorial message so only a brief error remains
            try:
                await self.parent_ctx.delete_original_response()
            except Exception:
                try:
                    await self.parent_ctx.edit_original_response(embeds=[], view=None)
                except Exception:
                    pass

            await interaction.followup.send(
                embed=discord.Embed(
                    title=t(interaction, "verification.polymart.no_purchases.title"),
                    description=t(
                        interaction,
                        "verification.polymart.no_purchases.description",
                        username=polymart_username,
                    ),
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
                delete_after=_ui_ttl("success", 30),
            )
            return

        # Register with verification API (only resources marked as purchased)
        ver = VerificationService()
        verified_resources: list[dict] = []

        for res in purchased_resources:
            try:
                status, data = await ver.verify_polymart(
                    polymart_user_id, polymart_username, res["slug"]
                )
                if status in [200, 409]:  # 409 is duplicate, acceptable
                    verified_resources.append(
                        {"slug": res["slug"], "name": res["name"]}
                    )
                else:
                    logger.warning(
                        f"Failed to register Polymart purchase for {res['slug']}: status={status}, data={data}"
                    )
            except Exception as e:
                logger.error(
                    f"Error registering Polymart purchase for {res['slug']}: {e}"
                )

        # If none registered successfully, stop here without linking or assigning roles
        if not verified_resources:
            # Remove the original tutorial message so only a brief error remains
            try:
                await self.parent_ctx.delete_original_response()
            except Exception:
                try:
                    await self.parent_ctx.edit_original_response(embeds=[], view=None)
                except Exception:
                    pass
            await interaction.followup.send(
                embed=discord.Embed(
                    title=t(interaction, "verification.polymart.error.title"),
                    description=t(
                        interaction,
                        "verification.polymart.error.token_verify",
                        error="Registration failed for all purchases",
                    ),
                    color=discord.Color.red(),
                ),
                ephemeral=True,
                delete_after=_ui_ttl("warning", 20),
            )
            return

        # Link Discord account only after at least one successful registration
        try:
            await ver.link_discord("polymart", polymart_user_id, interaction.user.id)
        except Exception as e:
            logger.error(f"Error linking Discord account: {e}")

        # Before granting roles to the current user, remove them from the previously linked owner (if different)
        try:
            await _unassign_roles_from_old_owner(
                interaction, "polymart", polymart_user_id, verified_resources
            )
        except Exception:
            pass

        # Assign roles only for verified resources
        await _assign_roles_from_resources(interaction, verified_resources)

        # Success message built from verified resources (prepend plugin emoji)
        # Load plugins config to access emojis
        cfg = load_config()
        ver_mod = cfg.module("verification")
        plugins_cfg = ver_mod.get("plugins", {}) if isinstance(ver_mod, dict) else {}

        def _emoji_for_slug(slug: str) -> str:
            try:
                plug = (
                    plugins_cfg.get(slug, {}) if isinstance(plugins_cfg, dict) else {}
                )
                return str(plug.get("emoji", "")).strip() or ""
            except Exception:
                return ""

        def _line_for_resource(r: dict) -> str:
            emoji = _emoji_for_slug(r.get("slug", ""))
            name = str(r.get("name", ""))
            if emoji:
                return f"{emoji} **{name}**"
            return f"• **{name}**"

        resource_list = "\n".join([_line_for_resource(r) for r in verified_resources])

        success_embed = discord.Embed(
            title=t(interaction, "verification.polymart.success.title"),
            description=t(
                interaction,
                "verification.polymart.success.description",
                username=polymart_username,
                resources=resource_list,
            ),
            color=discord.Color.green(),
        )
        success_embed.set_footer(
            text=t(interaction, "verification.polymart.success.footer"),
            icon_url=(
                interaction.client.user.avatar.url
                if interaction.client.user.avatar
                else None
            ),
        )

        await interaction.followup.send(
            embed=success_embed, ephemeral=True, delete_after=_ui_ttl("success", 30)
        )

        # Update the parent message to show completion
        try:
            complete_embed = discord.Embed(
                title=t(self.parent_ctx, "verification.polymart.complete.title"),
                description=t(
                    self.parent_ctx,
                    "verification.polymart.complete.description",
                    username=polymart_username,
                ),
                color=discord.Color.green(),
            )
            await self.parent_ctx.edit_original_response(
                embed=complete_embed, view=None
            )
            try:
                # Schedule deletion of the parent message after configured success TTL
                reschedule_delete_for_same_message(
                    self.parent_ctx, delay_seconds=_ui_ttl("success", 30)
                )
            except Exception:
                pass
        except Exception:
            pass
