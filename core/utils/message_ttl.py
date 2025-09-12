from __future__ import annotations

import asyncio
from typing import Dict, Optional, Union

import discord

# Global task registry keyed by message ID
_TASKS: Dict[int, asyncio.Task] = {}


def _get_message_id(message_or_id: Union[int, discord.Message]) -> int:
    return message_or_id.id if isinstance(message_or_id, discord.Message) else int(message_or_id)


def schedule_followup_delete(
    interaction: discord.Interaction,
    message_or_id: Union[int, discord.Message],
    *,
    delay_seconds: int,
) -> None:
    """
    Schedule deletion of an ephemeral followup message after delay_seconds.

    If there is already a scheduled deletion for this message, it will be cancelled
    and replaced by the new schedule.

    This is intended for ephemeral followups sent via interaction.followup.send(...).
    """
    message_id = _get_message_id(message_or_id)

    # Cancel any existing task for this message
    existing = _TASKS.pop(message_id, None)
    if existing and not existing.done():
        existing.cancel()

    async def _runner():
        try:
            await asyncio.sleep(max(0, int(delay_seconds)))
            await interaction.followup.delete_message(message_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # As a fallback, try deleting the original response (only if that matches)
            try:
                await interaction.delete_original_response()
            except Exception:
                pass
        finally:
            # Ensure we free the task entry once it finishes
            _TASKS.pop(message_id, None)

    task = asyncio.create_task(_runner())
    # Also remove from registry when the task completes, for extra safety
    def _on_done(_t: asyncio.Task) -> None:
        _TASKS.pop(message_id, None)

    task.add_done_callback(_on_done)
    _TASKS[message_id] = task


def reschedule_delete_for_same_message(
    interaction: discord.Interaction,
    *,
    delay_seconds: int,
) -> None:
    """
    Reschedule deletion for the same ephemeral message that triggered this component interaction.

    Use this after editing the message in a component callback to extend its lifetime.
    """
    msg: Optional[discord.Message] = getattr(interaction, "message", None)
    if not msg:
        return
    schedule_followup_delete(interaction, msg.id, delay_seconds=delay_seconds)


def cancel_scheduled_delete(message_or_id: Union[int, discord.Message]) -> None:
    message_id = _get_message_id(message_or_id)
    task = _TASKS.pop(message_id, None)
    if task and not task.done():
        task.cancel()


def clear_all_schedules() -> None:
    for mid, task in list(_TASKS.items()):
        if task and not task.done():
            task.cancel()
        _TASKS.pop(mid, None)
