# bot/detail_requests.py
from __future__ import annotations

from typing import Optional

import discord

from bot import bot, get_member, save_member, send_admin
from database import (
    delete_detail_request,
    get_detail_request,
    list_detail_requests,
    save_detail_request_state,
)


DETAIL_STEPS: list[tuple[str, str]] = [
    ("first_name", "What is your **first name**?"),
    ("last_name", "What is your **last name**?"),
    ("email", "What is the **email you use for Plex**?"),
    ("mobile", "What is your **mobile number**?"),
]


def serialize_roles(member: discord.Member) -> str:
    """Return a comma-separated snapshot of the member's roles (excluding @everyone)."""
    if not isinstance(member, discord.Member):
        return ""
    return ", ".join(role.name for role in member.roles if role.name != "@everyone")


async def start_detail_request(member: discord.Member) -> bool:
    """Ensure a DM detail collection flow is active for the given member."""
    if member.bot:
        return False

    record = get_member(member.id)
    tag = f"{member.name}#{member.discriminator}" if member.discriminator else member.name
    origin = record[17] if record and len(record) > 17 and record[17] else "sync"
    first = record[2] if record and len(record) > 2 and record[2] else ""
    last = record[3] if record and len(record) > 3 and record[3] else ""
    email = record[4] if record and len(record) > 4 and record[4] else ""
    mobile = record[5] if record and len(record) > 5 and record[5] else ""

    state = get_detail_request(member.id)
    if state is None:
        state = save_detail_request_state(
            member.id,
            step=0,
            first_name=first,
            last_name=last,
            email=email,
            mobile=mobile,
            origin=origin,
            roles=serialize_roles(member),
            discord_tag=tag,
            intro_sent=0,
        )
    else:
        # Refresh tag and roles snapshot on existing flows
        state = save_detail_request_state(
            member.id,
            first_name=state.get("first_name") or first,
            last_name=state.get("last_name") or last,
            email=state.get("email") or email,
            mobile=state.get("mobile") or mobile,
            origin=state.get("origin") or origin,
            roles=serialize_roles(member),
            discord_tag=tag,
        )

    try:
        dm = await member.create_dm()
    except Exception as exc:
        await send_admin(f"⚠️ Couldn’t DM {member.mention} for details: {exc}")
        return False

    if not state.get("intro_sent"):
        await dm.send(
            "👋 Thanks for helping us update your Casharr profile."
            "\nPlease answer the next few questions. Reply with `skip` to keep the value we already have."
        )
        state = save_detail_request_state(member.id, intro_sent=1)
    else:
        await dm.send("👋 Just a reminder — we still need a few details from you.")

    await _send_current_question(dm, state)
    return True


async def resume_pending_requests():
    """Re-issue prompts for any pending detail requests (used after restarts)."""
    pending = list_detail_requests()
    for state in pending:
        step = int(state.get("step", 0))
        if step >= len(DETAIL_STEPS):
            continue

        user = bot.get_user(int(state["discord_id"]))
        if user is None:
            try:
                user = await bot.fetch_user(int(state["discord_id"]))
            except Exception:
                continue

        try:
            dm = await user.create_dm()
        except Exception:
            continue

        if not state.get("intro_sent"):
            await dm.send(
                "👋 Thanks for your patience — we still need a few quick answers to finish updating your Casharr profile."
            )
            state = save_detail_request_state(state["discord_id"], intro_sent=1)
        else:
            await dm.send("⏳ We’re still waiting on some details. You can reply here whenever you’re ready.")

        await _send_current_question(dm, state)


async def handle_detail_response(message: discord.Message) -> bool:
    """Process a DM reply from a user; returns True if handled."""
    if message.author.bot:
        return False

    state = get_detail_request(message.author.id)
    if not state:
        return False

    step = int(state.get("step", 0))
    if step >= len(DETAIL_STEPS):
        # Already complete but record not cleaned up; tidy.
        delete_detail_request(message.author.id)
        return True

    field, _ = DETAIL_STEPS[step]
    response = message.content.strip()

    if response.lower() != "skip":
        state = save_detail_request_state(message.author.id, **{field: response})

    next_step = step + 1
    state = save_detail_request_state(message.author.id, step=next_step)

    member = _find_member(message.author.id)

    if next_step >= len(DETAIL_STEPS):
        await _finalize_details(message, state, member)
        return True

    target = member or message.author
    dm = target.dm_channel or await target.create_dm()
    await dm.send("✅ Got it!")
    await _send_current_question(dm, state)
    return True


async def _finalize_details(message: discord.Message, state: dict, member: Optional[discord.Member]):
    first = (state.get("first_name") or "").strip()
    last = (state.get("last_name") or "").strip()
    email = (state.get("email") or "").strip()
    mobile = (state.get("mobile") or "").strip()

    if member:
        tag = f"{member.name}#{member.discriminator}" if member.discriminator else member.name
        roles = serialize_roles(member)
        origin = state.get("origin") or "sync"
    else:
        tag = state.get("discord_tag") or message.author.name
        roles = state.get("roles") or ""
        origin = state.get("origin") or "sync"

    save_member(
        message.author.id,
        first,
        last,
        email,
        mobile,
        discord_tag=tag,
        origin=origin,
        roles=roles,
    )

    delete_detail_request(message.author.id)

    await message.channel.send("✅ Thanks! Your details have been updated.")

    email_display = email or "no email supplied"
    if member:
        await send_admin(f"✅ Saved updated details for {member.mention} ({email_display}).")
    else:
        await send_admin(
            f"✅ Saved updated details for `{message.author}` (`{message.author.id}`) ({email_display})."
        )


async def _send_current_question(channel: discord.abc.Messageable, state: dict):
    step = int(state.get("step", 0))
    if step >= len(DETAIL_STEPS):
        return

    field, question = DETAIL_STEPS[step]
    current_value = state.get(field) or ""

    prompt = question
    if current_value:
        prompt += f"\nCurrent value: `{current_value}`\nType `skip` to keep this value."
    else:
        prompt += "\n(Type `skip` to leave this blank.)"

    await channel.send(prompt)


def _find_member(user_id: int) -> Optional[discord.Member]:
    for guild in bot.guilds:
        member = guild.get_member(int(user_id))
        if member:
            return member
    return None

