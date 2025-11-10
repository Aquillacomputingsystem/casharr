import asyncio
import discord, shutil, os, configparser, json
from discord import app_commands
from datetime import datetime, timezone, timedelta
from bot import (
    bot, ADMIN_ROLE, INITIAL_ROLE, TRIAL_ROLE, PAYER_ROLE, LIFETIME_ROLE, send_admin,
    get_member, save_member, get_all_members, pay_page, DB_PATH, EXPORTS_DIR, plex, config
)
from database import is_promo_eligible, has_used_promo

# ───────────────────────────────
# Persistent pending DM tracking
# ───────────────────────────────
PENDING_FILE = "data/pending_details.json"
os.makedirs("data", exist_ok=True)
if not os.path.exists(PENDING_FILE):
    with open(PENDING_FILE, "w") as f:
        json.dump({}, f)

def load_pending():
    try:
        with open(PENDING_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_pending(data):
    with open(PENDING_FILE, "w") as f:
        json.dump(data, f, indent=2)

def _serialize_roles(member: discord.Member) -> str:
    return ", ".join(role.name for role in member.roles if role.name != "@everyone")

def _needs_contact(record) -> bool:
    if not record:
        return True
    for idx in (2, 3, 4, 5):  # first_name, last_name, email, mobile
        value = record[idx] if len(record) > idx else None
        if not value or not str(value).strip():
            return True
    return False


async def _collect_member_details(member: discord.Member, resume_stage: int = 0):
    """Interactively collect missing details from a member via DM (persistent)."""
    record = get_member(member.id)
    first = record[2] if record and len(record) > 2 else ""
    last = record[3] if record and len(record) > 3 else ""
    email = record[4] if record and len(record) > 4 else ""
    mobile = record[5] if record and len(record) > 5 else ""

    try:
        dm = await member.create_dm()
    except Exception as e:
        await send_admin(f"⚠️ Couldn’t DM {member.mention} for details: {e}")
        return False

    await dm.send(
        "👋 Thanks for helping update your Casharr profile."
        "\nYou can reply anytime — this chat stays open until all details are received."
        "\nReply with `skip` to keep any existing value."
    )

    def check(message: discord.Message) -> bool:
        return message.author == member and isinstance(message.channel, discord.DMChannel)

    questions = [
        ("first_name", "What is your **first name**?", first),
        ("last_name", "What is your **last name**?", last),
        ("email", "What is the **email you use for Plex**?", email),
        ("mobile", "What is your **mobile number**?", mobile),
    ]
    answers: dict[str, str] = {}

    # Load pending progress
    pending = load_pending()
    stage = resume_stage
    pending[str(member.id)] = stage
    save_pending(pending)

    while stage < len(questions):
        key, question, current = questions[stage]
        prompt = question
        if current:
            prompt += f"\nCurrent: `{current}`\nType `skip` to keep it."
        else:
            prompt += "\n(Type `skip` to leave blank.)"
        await dm.send(prompt)

        reply = await bot.wait_for("message", check=check)
        response = reply.content.strip()
        if response.lower() == "skip":
            answers[key] = current or ""
        else:
            answers[key] = response

        stage += 1
        pending[str(member.id)] = stage
        save_pending(pending)

    cleaned_first = answers.get("first_name", first).strip()
    cleaned_last = answers.get("last_name", last).strip()
    cleaned_email = answers.get("email", email).strip()
    cleaned_mobile = answers.get("mobile", mobile).strip()

    tag = f"{member.name}#{member.discriminator}" if member.discriminator else member.name
    origin = record[17] if record and len(record) > 17 and record[17] else "sync"
    roles_snapshot = _serialize_roles(member)

    save_member(
        member.id,
        cleaned_first,
        cleaned_last,
        cleaned_email,
        cleaned_mobile,
        discord_tag=tag,
        origin=origin,
        roles=roles_snapshot,
    )

    await dm.send("✅ Thanks! Your details have been updated and saved.")
    await send_admin(f"✅ Saved updated details for {member.mention} ({cleaned_email or 'no email supplied'}).")

    # Remove from pending
    pending.pop(str(member.id), None)
    save_pending(pending)
    return True

# ───────────────────────────────
# /request_details (persistent)
# ───────────────────────────────
@bot.tree.command(name="request_details", description="Admins only: DM members to request missing details (persistent).")
async def request_details(interaction: discord.Interaction):
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
    if admin_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don’t have permission.", ephemeral=True)
        return

    await interaction.response.send_message("📨 Checking for members missing details...", ephemeral=True)

    started = 0
    for member in interaction.guild.members:
        if member.bot:
            continue
        if admin_role and admin_role in member.roles:
            continue

        record = get_member(member.id)
        if not _needs_contact(record):
            continue

        tag = f"{member.name}#{member.discriminator}" if member.discriminator else member.name
        origin = record[17] if record and len(record) > 17 and record[17] else "sync"
        roles_snapshot = _serialize_roles(member)
        existing_first = record[2] if record and len(record) > 2 else ""
        existing_last = record[3] if record and len(record) > 3 else ""
        existing_email = record[4] if record and len(record) > 4 else ""
        existing_mobile = record[5] if record and len(record) > 5 else ""

        save_member(
            member.id,
            existing_first,
            existing_last,
            existing_email,
            existing_mobile,
            discord_tag=tag,
            origin=origin,
            roles=roles_snapshot,
        )

        asyncio.create_task(_collect_member_details(member))
        started += 1

    if started == 0:
        await interaction.followup.send("✅ Everyone already has full details on file.", ephemeral=True)
        return

    await interaction.followup.send(
        f"✅ Started persistent detail collection with {started} member(s). They can reply anytime in DM.",
        ephemeral=True,
    )
    await send_admin(f"📬 Persistent detail collection started for {started} member(s).")



def _serialize_roles(member: discord.Member) -> str:
    """Return a comma-separated snapshot of the member's roles (excluding @everyone)."""
    return ", ".join(role.name for role in member.roles if role.name != "@everyone")


def _needs_contact(record) -> bool:
    """Determine whether a database record is missing required contact info."""
    if not record:
        return True

    for idx in (2, 3, 4, 5):  # first_name, last_name, email, mobile
        value = record[idx] if len(record) > idx else None
        if not value or not str(value).strip():
            return True
    return False


async def _collect_member_details(member: discord.Member) -> bool:
    """Interactively collect missing details from a member via DM."""
    record = get_member(member.id)
    first = record[2] if record and len(record) > 2 else ""
    last = record[3] if record and len(record) > 3 else ""
    email = record[4] if record and len(record) > 4 else ""
    mobile = record[5] if record and len(record) > 5 else ""

    try:
        dm = await member.create_dm()
    except Exception as e:
        await send_admin(f"⚠️ Couldn’t DM {member.mention} for details: {e}")
        return False

    await dm.send(
        "👋 Thanks for helping us update your Casharr profile."
        "\nPlease answer the next few questions. Reply with `skip` to keep the value we already have."
    )

    def check(message: discord.Message) -> bool:
        return message.author == member and isinstance(message.channel, discord.DMChannel)

    questions = [
        ("first_name", "What is your **first name**?", first),
        ("last_name", "What is your **last name**?", last),
        ("email", "What is the **email you use for Plex**?", email),
        ("mobile", "What is your **mobile number**?", mobile),
    ]

    answers: dict[str, str] = {}

    for key, question, current in questions:
        prompt = question
        if current:
            prompt += f"\nCurrent value: `{current}`\nType `skip` to keep this value."
        else:
            prompt += "\n(Type `skip` to leave this blank.)"

        await dm.send(prompt)

        try:
            reply = await bot.wait_for("message", check=check)
        except asyncio.TimeoutError:
            await dm.send("⏳ No worries — we’ll try again later. Feel free to DM an admin when you’re ready.")
            await send_admin(f"⏳ Timed out waiting for details from {member.mention}.")
            return False

        response = reply.content.strip()
        if response.lower() == "skip":
            answers[key] = current or ""
        else:
            answers[key] = response

    cleaned_first = answers["first_name"].strip()
    cleaned_last = answers["last_name"].strip()
    cleaned_email = answers["email"].strip()
    cleaned_mobile = answers["mobile"].strip()

    tag = f"{member.name}#{member.discriminator}" if member.discriminator else member.name
    origin = record[17] if record and len(record) > 17 and record[17] else "sync"
    roles_snapshot = _serialize_roles(member)

    save_member(
        member.id,
        cleaned_first,
        cleaned_last,
        cleaned_email,
        cleaned_mobile,
        discord_tag=tag,
        origin=origin,
        roles=roles_snapshot,
    )

    await dm.send("✅ Thanks! Your details have been updated.")
    await send_admin(f"✅ Saved updated details for {member.mention} ({cleaned_email or 'no email supplied'}).")
    return True

# ────────────────────────────────
# /sync_members COMMAND
# ────────────────────────────────
@bot.tree.command(name="sync_members", description="Admins only: Sync existing members into the database.")
async def sync_members(interaction: discord.Interaction):
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
    if admin_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don’t have permission to do this.", ephemeral=True)
        return

    count_new = 0
    count_backfill = 0
    roles_updated = 0
    for member in interaction.guild.members:
        if member.bot:
            continue
        record = get_member(member.id)
        tag = f"{member.name}#{member.discriminator}" if member.discriminator else member.name
        roles_snapshot = _serialize_roles(member)
        origin = record[17] if record and len(record) > 17 and record[17] else "sync"

        if not record:
            save_member(member.id, "", "", "", "", discord_tag=tag, origin=origin, roles=roles_snapshot)
            count_new += 1
            roles_updated += 1
            continue

        stored_roles = (record[18] if len(record) > 18 else None) or ""
        save_member(
            member.id,
            record[2] or "",
            record[3] or "",
            record[4] or "",
            record[5] or "",
            discord_tag=tag,
            origin=origin,
            roles=roles_snapshot,
        )

        if not record[1]:
            count_backfill += 1

        if roles_snapshot != stored_roles:
            roles_updated += 1

    await interaction.response.send_message(
        f"✅ Synced {count_new} new members; backfilled tags for {count_backfill} member(s);"
        f" captured roles for {roles_updated} member(s).",
        ephemeral=True
    )
    await send_admin(
        f"🔄 Sync complete — {count_new} new member(s), {count_backfill} tag backfill(s),"
        f" {roles_updated} role snapshot(s) updated."
    )

# ────────────────────────────────
# /request_details COMMAND
# ────────────────────────────────
@bot.tree.command(name="request_details", description="Admins only: DM members to request missing details.")
async def request_details(interaction: discord.Interaction):
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
    if admin_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don’t have permission to do this.", ephemeral=True)
        return

    await interaction.response.send_message("📨 Checking for members missing details...", ephemeral=True)

    started = 0
    for member in interaction.guild.members:
        if member.bot:
            continue

        # Skip admins — they don't need to be in the member detail workflow.
        if admin_role and admin_role in member.roles:
            continue

        record = get_member(member.id)
        if not _needs_contact(record):
            continue

        tag = f"{member.name}#{member.discriminator}" if member.discriminator else member.name
        origin = record[17] if record and len(record) > 17 and record[17] else "sync"
        roles_snapshot = _serialize_roles(member)

        # Ensure we have at least a placeholder record with the latest tag/roles
        existing_first = record[2] if record and len(record) > 2 else ""
        existing_last = record[3] if record and len(record) > 3 else ""
        existing_email = record[4] if record and len(record) > 4 else ""
        existing_mobile = record[5] if record and len(record) > 5 else ""

        save_member(
            member.id,
            existing_first or "",
            existing_last or "",
            existing_email or "",
            existing_mobile or "",
            discord_tag=tag,
            origin=origin,
            roles=roles_snapshot,
        )

        asyncio.create_task(_collect_member_details(member))
        started += 1

    if started == 0:
        await interaction.followup.send("✅ Everyone already has full details on file.", ephemeral=True)
        return

    await interaction.followup.send(
        f"✅ Started detail collection with {started} member(s). They'll receive prompts via DM.",
        ephemeral=True,
    )
    await send_admin(f"📬 Detail collection started for {started} member(s).")

# ────────────────────────────────
# /renew_all COMMAND
# ────────────────────────────────
@bot.tree.command(name="renew_all", description="Admins only: Ask all trial and payer members to renew.")
async def renew_all(interaction: discord.Interaction):
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
    if admin_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don’t have permission to do this.", ephemeral=True)
        return

    await interaction.response.send_message("🔁 Sending renewal messages...", ephemeral=True)
    guild = interaction.guild
    sent = 0

    # ✅ Load config for pricing and promo
    cfg = config
    promo_enabled = cfg.has_section("Promo") and cfg["Promo"].getboolean("Enabled", False)

    for member in guild.members:
        if member.bot:
            continue
        # Target users in trial or paid roles
        if discord.utils.get(member.roles, name=TRIAL_ROLE) or discord.utils.get(member.roles, name=PAYER_ROLE):
            try:
                eligible_for_promo = promo_enabled and is_promo_eligible(member.id)
                note = ""
                if eligible_for_promo:
                    # Apply promo prices
                    m1 = cfg["Promo"].get("Discount1Month", cfg["Pricing"]["1Month"])
                    m3 = cfg["Promo"].get("Discount3Months", cfg["Pricing"]["3Months"])
                    m6 = cfg["Promo"].get("Discount6Months", cfg["Pricing"]["6Months"])
                    m12 = cfg["Promo"].get("Discount12Months", cfg["Pricing"]["12Months"])
                    note = cfg["Promo"].get("Note", "🎁 Special limited-time offer for returning members!")
                else:
                    # Standard prices
                    m1 = cfg["Pricing"]["1Month"]
                    m3 = cfg["Pricing"]["3Months"]
                    m6 = cfg["Pricing"]["6Months"]
                    m12 = cfg["Pricing"]["12Months"]

                dm = await member.create_dm()
                msg = (
                    f"👋 Hi {member.display_name}, your access will expire soon.\n"
                    f"💳 1m: {m1} AUD → {pay_page(member.id, '1')}\n"
                    f"3m: {m3} AUD → {pay_page(member.id, '3')}\n"
                    f"6m: {m6} AUD → {pay_page(member.id, '6')}\n"
                    f"12m: {m12} AUD → {pay_page(member.id, '12')}"
                )
                if note:
                    msg += f"\n\n{note}"

                await dm.send(msg)
                sent += 1
            except Exception as e:
                print(f"⚠️ Couldn’t message {member.name}: {e}")

    await send_admin(f"💬 Renewal messages sent to {sent} member(s).")

# ────────────────────────────────
# /backup_db COMMAND
# ────────────────────────────────
@bot.tree.command(name="backup_db", description="Admins only: Create a backup of members.db into /exports.")
async def backup_db(interaction: discord.Interaction):
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
    if admin_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don’t have permission.", ephemeral=True)
        return

    if not os.path.exists(DB_PATH):
        await interaction.response.send_message("⚠️ Database not found!", ephemeral=True)
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = os.path.join(EXPORTS_DIR, f"members_backup_{timestamp}.db")
    shutil.copy2(DB_PATH, backup_path)

    await interaction.response.send_message("✅ Database backup created.", ephemeral=True)
    await send_admin(f"💾 Database backup created: `{backup_path}`")


# ────────────────────────────────
# /add_member COMMAND
# ────────────────────────────────
@bot.tree.command(name="add_member", description="Admins only: manually add or update a member in the database.")
@app_commands.describe(
    discord_id="Discord user ID (numbers only)",
    discord_tag="Discord tag (e.g. user#1234)",
    first_name="Member's first name",
    last_name="Member's last name",
    email="Plex or contact email",
    mobile="Mobile number"
)
async def add_member(
    interaction: discord.Interaction,
    discord_id: str,
    discord_tag: str,
    first_name: str = "",
    last_name: str = "",
    email: str = "",
    mobile: str = ""
):
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
    if admin_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don’t have permission.", ephemeral=True)
        return

    try:
        save_member(discord_id, first_name, last_name, email, mobile, discord_tag)
        embed = discord.Embed(title="✅ Member Added / Updated", color=discord.Color.green())
        embed.add_field(name="Discord ID", value=discord_id, inline=False)
        embed.add_field(name="Discord Tag", value=discord_tag or "-", inline=True)
        embed.add_field(name="First Name", value=first_name or "-", inline=True)
        embed.add_field(name="Last Name", value=last_name or "-", inline=True)
        embed.add_field(name="Email", value=email or "-", inline=True)
        embed.add_field(name="Mobile", value=mobile or "-", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await send_admin(f"🗂️ Manually added/updated member: **{discord_tag}** (`{discord_id}`)")
    except Exception as e:
        await interaction.response.send_message(f"⚠️ Failed to add/update member: {e}", ephemeral=True)


# ────────────────────────────────
# /set_mode COMMAND (Auto / Manual)
# ────────────────────────────────
@bot.tree.command(name="set_mode", description="Admins only: Switch between Manual or Auto enforcement mode.")
@app_commands.describe(mode="Choose 'Manual' or 'Auto'")
async def set_mode(interaction: discord.Interaction, mode: str):
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
    if admin_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don’t have permission.", ephemeral=True)
        return

    mode = mode.capitalize()
    if mode not in ["Manual", "Auto"]:
        await interaction.response.send_message("❌ Mode must be 'Manual' or 'Auto'.", ephemeral=True)
        return

    CONFIG_PATH = os.path.join("config", "config.ini")
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)

    if "AccessMode" not in config:
        config["AccessMode"] = {}
    config["AccessMode"]["Mode"] = mode

    with open(CONFIG_PATH, "w") as f:
        config.write(f)

    await interaction.response.send_message(f"✅ Access mode set to **{mode}**.", ephemeral=True)
    await send_admin(f"🔧 Access mode changed to **{mode}** by {interaction.user.mention}.")


# ────────────────────────────────
# /view_skips COMMAND
# ────────────────────────────────
@bot.tree.command(name="view_skips", description="Admins only: View members currently deferred (skip list).")
async def view_skips(interaction: discord.Interaction):
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
    if admin_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don’t have permission.", ephemeral=True)
        return

    skip_file = os.path.join("data", "skip_deferrals.json")
    if not os.path.exists(skip_file):
        await interaction.response.send_message("✅ No skip file found — no members deferred.", ephemeral=True)
        return

    try:
        with open(skip_file, "r") as f:
            skips = json.load(f)
    except Exception as e:
        await interaction.response.send_message(f"⚠️ Failed to read skip file: {e}", ephemeral=True)
        return

    if not skips:
        await interaction.response.send_message("✅ No members currently deferred.", ephemeral=True)
        return

    now = datetime.now(timezone.utc)
    lines = []
    for discord_id, ts in skips.items():
        try:
            last_skip = datetime.fromisoformat(ts)
            expires = last_skip + timedelta(days=7)
            member = interaction.guild.get_member(int(discord_id))
            name = member.display_name if member else f"UserID {discord_id}"
            lines.append(f"• **{name}** — expires <t:{int(expires.timestamp())}:R> ({expires.date()})")
        except Exception:
            continue

    msg = "\n".join(lines)
    embed = discord.Embed(
        title="🕓 Deferred Members (Skip List)",
        description=msg or "✅ No members currently deferred.",
        color=discord.Color.orange()
    )
    embed.set_footer(text=f"Total deferred: {len(lines)}")
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await send_admin(f"📋 {interaction.user.mention} viewed the skip list ({len(lines)} member(s)).")


# ────────────────────────────────
# /mark_paid COMMAND
# ────────────────────────────────
@bot.tree.command(name="mark_paid", description="Admins only: manually mark a member as paid for X months.")
@app_commands.describe(
    member="Discord member to mark as paid",
    months="Number of months to extend access (default 1)"
)
async def mark_paid(interaction: discord.Interaction, member: discord.Member, months: int = 1):
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
    if admin_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don’t have permission.", ephemeral=True)
        return

    from database import update_payment, clear_trial_after_payment

    try:
        update_payment(member.id, months)
        clear_trial_after_payment(member.id)

        payer_role = discord.utils.get(interaction.guild.roles, name=PAYER_ROLE)
        trial_role = discord.utils.get(interaction.guild.roles, name=TRIAL_ROLE)

        if trial_role in member.roles:
            await member.remove_roles(trial_role)
        if payer_role and payer_role not in member.roles:
            await member.add_roles(payer_role)

        await interaction.response.send_message(
            f"✅ {member.display_name} marked as paid for {months} month(s).",
            ephemeral=True
        )
        await send_admin(f"💰 {member.mention} manually marked as paid ({months}m).")

    except Exception as e:
        await interaction.response.send_message(f"⚠️ Failed to mark as paid: {e}", ephemeral=True)
        await send_admin(f"⚠️ Failed to manually mark {member.mention} as paid: {e}")


# ────────────────────────────────
# /mark_lifetime COMMAND
# ────────────────────────────────
@bot.tree.command(name="mark_lifetime", description="Admins only: Grant a member permanent lifetime access.")
@app_commands.describe(member="The Discord member to grant Lifetime access to.")
async def mark_lifetime(interaction: discord.Interaction, member: discord.Member):
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
    if admin_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don’t have permission to do this.", ephemeral=True)
        return

    lifetime_role = discord.utils.get(interaction.guild.roles, name=LIFETIME_ROLE)
    if not lifetime_role:
        await interaction.response.send_message("⚠️ Lifetime role not found! Please create it in Discord.", ephemeral=True)
        return

    await member.add_roles(lifetime_role)

    # Remove trial/payer roles
    trial_role = discord.utils.get(interaction.guild.roles, name=TRIAL_ROLE)
    payer_role = discord.utils.get(interaction.guild.roles, name=PAYER_ROLE)
    if trial_role in member.roles:
        await member.remove_roles(trial_role)
    if payer_role in member.roles:
        await member.remove_roles(payer_role)

    # Plex invite check
    record = get_member(member.id)
    if record and record[4]:
        email = record[4]
        try:
            server_name = plex.plex.friendlyName
            normalized_server_name = server_name.lower().replace(" ", "").replace("-", "")
            plex_user = next((u for u in plex.account.users() if u.email and u.email.lower() == email.lower()), None)
            has_access = False

            if plex_user:
                for s in plex_user.servers:
                    s_str = str(s).lower().replace(" ", "").replace("-", "")
                    s_name = str(getattr(s, "name", "")).lower().replace(" ", "").replace("-", "")
                    if normalized_server_name in s_str or normalized_server_name in s_name:
                        has_access = True
                        break

            if has_access:
                await send_admin(f"🏅 {member.mention} marked as Lifetime — already has Plex access.")
                await interaction.response.send_message(
                    f"🏅 {member.display_name} granted **Lifetime Access** (Plex already active).",
                    ephemeral=True
                )
            else:
                result = plex.invite_user(email)
                if result == "sent":
                    await send_admin(f"🏅 {member.mention} marked as Lifetime — Plex invite sent to {email}.")
                    await interaction.response.send_message(
                        f"🏅 {member.display_name} granted **Lifetime Access** — Plex invite sent to {email}.",
                        ephemeral=True
                    )
                elif result == "already_invited":
                    await send_admin(f"🏅 {member.mention} marked as Lifetime — Plex invite already pending for {email}.")
                    await interaction.response.send_message(
                        f"🏅 {member.display_name} granted **Lifetime Access** — Plex invite already pending for {email}.",
                        ephemeral=True
                    )
                else:
                    await send_admin(f"⚠️ {member.mention} marked as Lifetime but Plex invite failed for {email}.")
                    await interaction.response.send_message(
                        f"⚠️ Lifetime role granted, but Plex invite failed for {email}.",
                        ephemeral=True
                    )
        except Exception as e:
            await interaction.response.send_message(
                f"⚠️ Lifetime role granted, but Plex check failed: {type(e).__name__}",
                ephemeral=True
            )
            await send_admin(f"⚠️ Plex verification failed for {member.mention}: {type(e).__name__}: {e}")
    else:
        await interaction.response.send_message(
            f"🏅 {member.display_name} granted **Lifetime Access**, but no email found in database. Add manually if needed.",
            ephemeral=True
        )
        await send_admin(f"🏅 {member.mention} granted **Lifetime Access**, but no email found in DB.")

# ────────────────────────────────
# /dm_all (Safe + Anti-Spam)
# ────────────────────────────────
import asyncio

@bot.tree.command(name="dm_all", description="Admins only: Safely DM all human members with optional embed formatting.")
@app_commands.describe(
    title="Embed title (optional)",
    body="Main message content (required)",
    image_url="Optional image to include in the message",
    footer="Optional footer text"
)
async def dm_all(
    interaction: discord.Interaction,
    body: str,
    title: str = "",
    image_url: str = "",
    footer: str = ""
):
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
    if admin_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don’t have permission to do this.", ephemeral=True)
        return

    guild = interaction.guild
    sent = 0
    failed = 0

    await interaction.response.send_message("📨 Sending messages safely (this may take a while)...", ephemeral=True)

    # Prepare embed if required
    embed = None
    if title or image_url or footer:
        embed = discord.Embed(
            title=title or "📢 Announcement",
            description=body,
            color=discord.Color.blurple()
        )
        if image_url:
            embed.set_image(url=image_url)
        if footer:
            embed.set_footer(text=footer)

    for member in guild.members:
        if member.bot:
            continue
        try:
            dm = await member.create_dm()
            if embed:
                await dm.send(embed=embed)
            else:
                await dm.send(body)
            sent += 1
            await asyncio.sleep(1.5)  # ⏳ Prevent rate limits
        except discord.HTTPException as e:
            if e.status == 429:
                print("⏰ Rate limit hit. Waiting 10 seconds...")
                await asyncio.sleep(10)
            else:
                print(f"⚠️ Couldn’t DM {member.name}: {e}")
                failed += 1
        except Exception as e:
            print(f"⚠️ Couldn’t DM {member.name}: {e}")
            failed += 1

    await send_admin(f"📢 Broadcast safely sent to {sent} members ({failed} failed).")
    await interaction.followup.send(f"✅ Sent to {sent} members. ⚠️ {failed} failed.", ephemeral=True)

# ────────────────────────────────
# /maintenance COMMAND
# ────────────────────────────────
@bot.tree.command(name="maintenance", description="Admins only: cleanup expired data and compact DB.")
async def maintenance(interaction: discord.Interaction):
    """Remove expired members, compact DB, and archive logs."""
    import sqlite3, shutil, datetime
    from database import DB_PATH
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
    if admin_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don’t have permission.", ephemeral=True)
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM members WHERE paid_until IS NULL AND trial_end IS NULL")
    conn.execute("VACUUM")
    conn.close()

    os.makedirs("exports", exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    shutil.make_archive(f"exports/logs_backup_{stamp}", "zip", "logs")

    await interaction.response.send_message("🧹 Maintenance complete — cleaned DB and archived logs.", ephemeral=True)