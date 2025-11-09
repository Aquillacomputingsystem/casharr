# bot/detail_requests.py
from __future__ import annotations

from typing import Optional

import asyncio
import discord

from bot import (
    bot,
    get_member,
    save_member,
    send_admin,
    check_and_upgrade_after_invite,
    TRIAL_DAYS,
    plex,
    start_trial,
)
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


def _default_intro(context: str) -> str:
    context = (context or "").strip().lower()
    if context == "onboarding":
        return (
            "👋 Welcome to Casharr! Let's finish setting up your access."
            "\nPlease answer the next few questions. You can reply with `skip` to leave an answer blank."
        )
    return (
        "👋 Thanks for helping us update your Casharr profile."
        "\nPlease answer the next few questions. Reply with `skip` to keep the value we already have."
    )


def _default_reminder(context: str) -> str:
    context = (context or "").strip().lower()
    if context == "onboarding":
        return (
            "⏳ We still need a few quick details to finish activating your access."
            " Reply here whenever you're ready."
        )
    return "👋 Just a reminder — we still need a few details from you."


def serialize_roles(member: discord.Member) -> str:
    """Return a comma-separated snapshot of the member's roles (excluding @everyone)."""
    if not isinstance(member, discord.Member):
        return ""
    return ", ".join(role.name for role in member.roles if role.name != "@everyone")


async def start_detail_request(
    member: discord.Member,
    *,
    context: str = "backfill",
    intro_message: Optional[str] = None,
    resume_message: Optional[str] = None,
    referrer_id: Optional[str] = None,
) -> bool:
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
    roles_snapshot = serialize_roles(member)

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
            roles=roles_snapshot,
            discord_tag=tag,
            intro_sent=0,
            context=context,
            referrer_id=referrer_id or "",
        )
    else:
        updates = {
            "first_name": state.get("first_name") or first,
            "last_name": state.get("last_name") or last,
            "email": state.get("email") or email,
            "mobile": state.get("mobile") or mobile,
            "origin": state.get("origin") or origin,
            "roles": roles_snapshot,
            "discord_tag": tag,
        }
        desired_context = context or state.get("context") or "backfill"
        if desired_context and desired_context != state.get("context"):
            updates["context"] = desired_context
        if referrer_id:
            updates["referrer_id"] = referrer_id
        state = save_detail_request_state(member.id, **updates)

    try:
        dm = await member.create_dm()
    except Exception as exc:
        await send_admin(f"⚠️ Couldn’t DM {member.mention} for details: {exc}")
        return False

    context_value = (state.get("context") or context or "backfill").strip().lower()

    if not state.get("intro_sent"):
        message = intro_message or _default_intro(context_value)
        if message:
            await dm.send(message)
        state = save_detail_request_state(member.id, intro_sent=1)
    else:
        reminder = resume_message or _default_reminder(context_value)
        if reminder:
            await dm.send(reminder)

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

        context_value = (state.get("context") or "backfill").strip().lower()

        if not state.get("intro_sent"):
            await dm.send(_default_intro(context_value))
            state = save_detail_request_state(state["discord_id"], intro_sent=1)
        else:
            await dm.send(_default_reminder(context_value))

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
    context_value = (state.get("context") or "backfill").strip().lower()
    referrer_id = (state.get("referrer_id") or "").strip()

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

    if context_value == "onboarding":
        await _complete_onboarding(message, member, email, referrer_id)
        return

    await message.channel.send("✅ Thanks! Your details have been updated.")

    email_display = email or "no email supplied"
    if member:
        await send_admin(f"✅ Saved updated details for {member.mention} ({email_display}).")
    else:
        await send_admin(
            f"✅ Saved updated details for `{message.author}` (`{message.author.id}`) ({email_display})."
        )


async def _complete_onboarding(
    message: discord.Message,
    member: Optional[discord.Member],
    email: str,
    referrer_id: str,
):
    channel = message.channel
    email_display = email or "no email supplied"

    if referrer_id:
        referrer_text = referrer_id
        if referrer_id.isdigit():
            referrer_text = f"<@{referrer_id}>"
        await channel.send(
            "🎁 You joined via a referral! "
            f"{referrer_text} will receive bonus days when you subscribe."
        )

    if not member:
        await channel.send(
            "✅ Thanks! Your details have been saved. An admin will finish setting up your access shortly."
        )
        await send_admin(
            "⚠️ Completed onboarding questionnaire for "
            f"`{message.author}` (`{message.author.id}`), but they are no longer in the server. "
            f"Email: {email_display}."
        )
        return

    invite_sent = False
    invite_error: Optional[str] = None

    if email:
        if plex is not None:
            try:
                plex.invite_user(email)
                invite_sent = True
            except Exception as exc:
                invite_error = f"{type(exc).__name__}: {exc}"
                await send_admin(
                    f"⚠️ Couldn’t send Plex invite to {email} for {member.mention}: {exc}"
                )
        else:
            invite_error = "Plex connection unavailable"
            await send_admin(
                f"⚠️ Plex connection unavailable — unable to invite {member.mention} ({email})."
            )
    else:
        invite_error = "missing email"

    if email and plex is not None:
        try:
            await asyncio.sleep(5)
            await check_and_upgrade_after_invite(member, email)
        except Exception as exc:
            await send_admin(
                f"⚠️ Failed to verify Plex access for {member.mention} ({email}): {exc}"
            )

    trial_started = False
    if email:
        try:
            start_trial(member.id, TRIAL_DAYS)
            trial_started = True
        except Exception as exc:
            await send_admin(
                f"⚠️ Couldn’t start trial for {member.mention} ({email}): {exc}"
            )
    else:
        await send_admin(
            f"⚠️ {member.mention} completed onboarding without providing an email address."
        )

    summary_lines = ["✅ Thanks! Your details have been saved."]
    if invite_sent:
        summary_lines.append("📨 We've sent a Plex invite to your email.")
    elif invite_error == "missing email":
        summary_lines.append(
            "⚠️ We still need your Plex email to finish the setup. Reply with it here whenever you're ready."
        )
    else:
        summary_lines.append(
            "⚠️ We couldn't automatically send your Plex invite. An admin will follow up shortly."
        )

    if trial_started:
        summary_lines.append(f"🧪 Your {TRIAL_DAYS}-day trial has started. Enjoy!")

    await channel.send("\n".join(summary_lines))

    admin_notes = []
    if invite_sent:
        admin_notes.append("Plex invite sent")
    elif invite_error:
        admin_notes.append(f"Plex invite issue: {invite_error}")
    if trial_started:
        admin_notes.append(f"{TRIAL_DAYS}-day trial started")
    if referrer_id:
        mention = f"<@{referrer_id}>" if referrer_id.isdigit() else referrer_id
        admin_notes.append(f"Referral: {mention}")

    note_text = "; ".join(admin_notes) if admin_notes else "details saved"
    await send_admin(
        f"✅ Onboarding details complete for {member.mention} ({email_display}). {note_text}."
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

