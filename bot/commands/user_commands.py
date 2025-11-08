# casharr/bot/commands/user_commands.py
import os, qrcode, discord
from discord import app_commands
from bot import (
    client as bot,
    ADMIN_ROLE, INITIAL_ROLE, TRIAL_ROLE, PAYER_ROLE, LIFETIME_ROLE,
    get_member, plex, send_admin, config
)
from database import is_promo_eligible, has_used_promo, get_referrals, get_referrer

# ────────────────────────────────
# /status COMMAND
# ────────────────────────────────
@bot.tree.command(name="status", description="Check your membership or another member's status.")
async def status(interaction: discord.Interaction, member: discord.Member | None = None):
    requester = interaction.user
    guild = interaction.guild
    admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE)
    target = member or requester
    is_admin = admin_role in requester.roles if admin_role else False

    if member and not is_admin:
        await interaction.response.send_message("❌ You don't have permission to view others.", ephemeral=True)
        return

    record = get_member(target.id)
    if not record:
        await interaction.response.send_message("⚠️ No record found for this member.", ephemeral=True)
        return

    discord_tag = record[1]
    first = record[2]
    last = record[3]
    email = record[4]
    trial_end = record[8]
    paid_until = record[10]
    origin = record[17] if len(record) > 17 else "—"

    # ─────────────────────────────
    # Check Plex status
    # ─────────────────────────────
    plex_status = "❌ Not Invited"
    if email:
        try:
            server_name = plex.plex.friendlyName
            normalized_server_name = server_name.lower().replace(" ", "").replace("-", "")
            plex_user = next((u for u in plex.account.users() if u.email and u.email.lower() == email.lower()), None)

            if plex_user:
                has_access = any(
                    normalized_server_name in str(getattr(s, "name", "")).lower().replace(" ", "").replace("-", "")
                    or normalized_server_name in str(getattr(s, "title", "")).lower().replace(" ", "").replace("-", "")
                    for s in getattr(plex_user, "servers", [])
                )
                plex_status = "✅ Active" if has_access else "🕓 Pending"
            else:
                plex_status = "❌ Not Found"
        except Exception as e:
            plex_status = f"⚠️ Error checking Plex: {type(e).__name__}"

    # ─────────────────────────────
    # Detect Discord role
    # ─────────────────────────────
    role_display = "Unknown"
    for r in [INITIAL_ROLE, TRIAL_ROLE, PAYER_ROLE, ADMIN_ROLE, LIFETIME_ROLE]:
        if discord.utils.get(guild.roles, name=r) in target.roles:
            role_display = r
            break

    if role_display == LIFETIME_ROLE:
        trial_end = "-"
        paid_until = "Never (Lifetime Access)"

    # ─────────────────────────────
    # Promo & referral info
    # ─────────────────────────────
    promo_used = "✅ Used" if has_used_promo(target.id) else "❌ Not Used"
    eligible_promo = "✅ Eligible" if is_promo_eligible(target.id) else "❌ Not Eligible"

    referrer_id = get_referrer(target.id)
    referrals = get_referrals(target.id)
    referral_count = len(referrals)
    is_referrer = bool(record[15]) if len(record) > 15 else False
    referral_paid = "✅ Paid" if (len(record) > 16 and int(record[16]) == 1) else "💸 Awaiting"

    referrer_tag = "-"
    if referrer_id:
        ref_member = guild.get_member(int(referrer_id))
        referrer_tag = ref_member.display_name if ref_member else f"ID {referrer_id}"

    # ─────────────────────────────
    # Build embed
    # ─────────────────────────────
    embed = discord.Embed(title=f"👤 Status for {target.display_name}", color=discord.Color.blurple())
    embed.add_field(name="Discord Tag", value=discord_tag or "-", inline=False)
    embed.add_field(name="Role", value=role_display, inline=True)
    embed.add_field(name="Plex", value=plex_status, inline=True)
    embed.add_field(name="Trial Ends", value=trial_end or "-", inline=True)
    embed.add_field(name="Paid Until", value=paid_until or "-", inline=True)
    embed.add_field(name="Promo Used", value=promo_used, inline=True)
    embed.add_field(name="Promo Eligible", value=eligible_promo, inline=True)
    embed.add_field(name="Origin", value=origin or "-", inline=True)

    # Referral info
    if referrer_tag != "-":
        embed.add_field(name="Referred By", value=referrer_tag, inline=True)
    if is_referrer:
        embed.add_field(name="Referred Members", value=f"{referral_count}", inline=True)
        embed.add_field(name="Referral Status", value=referral_paid, inline=True)

    if is_admin and member:
        embed.add_field(name="First/Last", value=f"{first or '-'} {last or '-'}", inline=False)
        embed.add_field(name="Email", value=email or "-", inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ────────────────────────────────
# /paylink COMMAND
# ────────────────────────────────
@bot.tree.command(name="paylink", description="DM a PayPal payment link for a subscription (1, 3, 6, or 12 months).")
@app_commands.describe(
    months="Subscription length in months (1, 3, 6, or 12)",
    member="(Admins only) Send a payment link to another member"
)
async def paylink(interaction: discord.Interaction, months: int, member: discord.Member | None = None):
    requester = interaction.user
    guild = interaction.guild
    admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE)
    is_admin = admin_role in requester.roles if admin_role else False

    if months not in [1, 3, 6, 12]:
        await interaction.response.send_message("❌ Please choose 1, 3, 6, or 12 months.", ephemeral=True)
        return

    target = member or requester
    if member and not is_admin:
        await interaction.response.send_message("❌ You can’t generate links for others.", ephemeral=True)
        return

    record = get_member(target.id)
    if not record or not record[4]:
        await interaction.response.send_message(
            f"⚠️ No email found for {target.mention}. They must complete onboarding first.",
            ephemeral=True
        )
        return

    # ─────────────────────────────
    # Pricing setup
    # ─────────────────────────────
    cfg = config
    base = cfg["PayPal"].get("PaymentBaseLink", "").rstrip("/")
    currency = cfg["Pricing"].get("DefaultCurrency", "AUD")
    business = cfg["PayPal"].get("BusinessEmail", "")
    ipn_url = cfg["PayPal"].get("IPN_URL", "").rstrip("/")
    domain = cfg["Site"].get("Domain", "").rstrip("/")
    price_key = f"{months}Month" if months == 1 else f"{months}Months"

    # ─────────────────────────────
    # Promo logic
    # ─────────────────────────────
    promo_enabled = cfg.has_section("Promo") and cfg["Promo"].getboolean("Enabled", False)
    eligible_for_promo = promo_enabled and is_promo_eligible(target.id)
    note = ""
    if eligible_for_promo:
        promo_key = f"Discount{months}Month" if months == 1 else f"Discount{months}Months"
        price = cfg["Promo"].get(promo_key, cfg["Pricing"].get(price_key, "0"))
        note = cfg["Promo"].get("Note", "🎁 Special limited-time offer!")
    else:
        price = cfg["Pricing"].get(price_key, "0")

    # ─────────────────────────────
    # Build PayPal link
    # ─────────────────────────────
    notify = ipn_url or (domain + "/paypal/ipn")
    link = (
        f"{base}?cmd=_xclick&business={business}"
        f"&currency_code={currency}&amount={price}"
        f"&item_name={months}%20Month%20Subscription"
        f"&item_number={months}&custom={target.id}"
        f"&notify_url={notify}"
        f"&return={domain}/paypal/thanks&cancel_return={domain}/paypal/cancel"
    )

    # ─────────────────────────────
    # Send DM with embed
    # ─────────────────────────────
    try:
        dm = await target.create_dm()
        embed = discord.Embed(title="💳 PayPal Payment Link", color=discord.Color.gold())
        embed.add_field(name="Duration", value=f"{months} month(s)", inline=True)
        embed.add_field(name="Price", value=f"{price} {currency}", inline=True)
        if eligible_for_promo:
            embed.add_field(name="Promotion", value=note, inline=False)
        embed.add_field(name="Payment Link", value=f"[Click here to pay]({link})", inline=False)
        embed.set_footer(text="Once payment is confirmed, your role will automatically update.")
        await dm.send(embed=embed)

        await interaction.response.send_message(
            f"✅ Payment link sent to {target.mention}'s DMs.",
            ephemeral=True
        )

        log_msg = f"💳 Payment link ({months}m) sent to {target.mention}."
        if eligible_for_promo:
            log_msg += " 🎁 (Promo pricing applied)"
        await send_admin(log_msg)

    except Exception as e:
        await interaction.response.send_message(
            f"⚠️ Couldn’t DM {target.mention}: {e}",
            ephemeral=True
        )

# ────────────────────────────────
# /referral COMMAND (channel-restricted + DM delivery)
# ────────────────────────────────
@bot.tree.command(name="referral", description="Generate your personal one-time referral invite (sent via DM).")
async def referral(interaction: discord.Interaction):
    """Allow members to request their referral link only in the designated channel, then DM it to them."""
    user = interaction.user
    guild = interaction.guild or bot.guilds[0]

    # Restrict to a specific channel
    allowed_channel_id = int(config["Discord"].get("ReferralChannelID", "0"))
    if allowed_channel_id and interaction.channel.id != allowed_channel_id:
        await interaction.response.send_message(
            f"❌ This command can only be used in <#{allowed_channel_id}>.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    # Check for existing valid invite
    existing_invites = await guild.invites()
    existing = next((i for i in existing_invites if i.inviter and i.inviter.id == user.id), None)

    if existing:
        invite_url = existing.url
    else:
        # Default to first text channel if not specified
        target_channel = guild.get_channel(allowed_channel_id) or guild.text_channels[0]
        invite = await target_channel.create_invite(
            max_uses=1,
            unique=True,
            reason=f"Referral invite by {user.name} ({user.id})"
        )
        invite_url = invite.url

    # Generate QR for the invite link
    os.makedirs("exports", exist_ok=True)
    qr_path = f"exports/referral_{user.id}.png"
    qrcode.make(invite_url).save(qr_path)

    embed = discord.Embed(
        title="🤝 Your Casharr Referral Invite",
        description=(
            f"Here’s your personal one-time referral invite! "
            f"Share this with friends — when they join and subscribe, you’ll earn bonus days.\n\n"
            f"**Invite Link:** [Click to Join]({invite_url})"
        ),
        color=discord.Color.green(),
    )
    embed.set_footer(text="Each invite is tracked automatically for referral rewards.")
    file = discord.File(qr_path, filename=f"referral_{user.id}.png")
    embed.set_image(url=f"attachment://referral_{user.id}.png")

    # Send via DM
    try:
        dm = await user.create_dm()
        await dm.send(embed=embed, file=file)
        await interaction.followup.send("✅ Check your DMs for your personal referral invite!", ephemeral=True)
        await send_admin(f"🔗 Referral invite generated for {user.mention}: {invite_url}")
    except Exception as e:
        await interaction.followup.send(
            f"⚠️ I couldn’t DM you ({type(e).__name__}). Please check your privacy settings.",
            ephemeral=True
        )
