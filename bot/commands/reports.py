# casharr/bot/commands/reports.py
import os
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
import discord
from discord import app_commands
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

from bot import (
    bot, ADMIN_ROLE, get_all_members, parse_iso, EXPORTS_DIR, send_admin
)

@bot.tree.command(name="report", description="Admins only: Generate a detailed report (PDF + XML) in /exports.")
async def report(interaction: discord.Interaction):
    admin_role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
    if admin_role not in interaction.user.roles:
        await interaction.response.send_message("❌ You don’t have permission.", ephemeral=True)
        return

    rows = get_all_members()
    if not rows:
        await interaction.response.send_message("⚠️ No members found in database.", ephemeral=True)
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # PDF Report
    pdf_path = os.path.join(EXPORTS_DIR, f"members_report_{timestamp}.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("Casharr Member Report", styles["Heading1"]),
        Spacer(1, 12),
        Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles["Normal"]),
        Spacer(1, 12)
    ]

    # Summary stats
    now = datetime.now(timezone.utc)
    total = len(rows)
    trials = sum(1 for r in rows if parse_iso(r[8]) and parse_iso(r[8]) > now)
    payers = sum(1 for r in rows if parse_iso(r[10]) and parse_iso(r[10]) > now)
    expired = sum(
        1 for r in rows
        if (parse_iso(r[8]) and parse_iso(r[8]) < now) or (parse_iso(r[10]) and parse_iso(r[10]) < now)
    )
    elements += [
        Paragraph(f"Total Members: <b>{total}</b>", styles["Normal"]),
        Paragraph(f"Active Trials: <b>{trials}</b>", styles["Normal"]),
        Paragraph(f"Active Payers: <b>{payers}</b>", styles["Normal"]),
        Paragraph(f"Expired (trial/subscription): <b>{expired}</b>", styles["Normal"]),
        Spacer(1, 10),
        Paragraph("Details", styles["Heading2"]),
        Spacer(1, 6)
    ]

    # ✅ Add Referrer column to PDF data
    data = [
        ["Discord ID", "Discord Tag", "First Name", "Last Name", "Email",
         "Mobile", "Trial End", "Paid Until", "Referrer"]
    ]
    for r in rows:
        data.append([
            str(r[0]) or "-",   # Discord ID
            r[1] or "-",        # Discord Tag
            r[2] or "-",        # First Name
            r[3] or "-",        # Last Name
            r[4] or "-",        # Email
            r[5] or "-",        # Mobile
            r[8] or "-",        # Trial End
            r[10] or "-",       # Paid Until
            r[14] or "-"        # ✅ Referrer ID
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.gray),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    elements.append(table)
    doc.build(elements)

    # XML Export
    xml_path = os.path.join(EXPORTS_DIR, f"members_report_{timestamp}.xml")
    root = ET.Element("MembersReport")
    meta = ET.SubElement(root, "Summary")
    ET.SubElement(meta, "GeneratedAt").text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ET.SubElement(meta, "TotalMembers").text = str(total)
    ET.SubElement(meta, "ActiveTrials").text = str(trials)
    ET.SubElement(meta, "ActivePayers").text = str(payers)
    ET.SubElement(meta, "Expired").text = str(expired)

    members = ET.SubElement(root, "Members")
    tags = [
        "DiscordID", "DiscordTag", "First", "Last", "Email", "Mobile",
        "Invite", "TrialStart", "TrialEnd", "HadTrial",
        "PaidUntil", "TrialReminderSentAt", "PaidReminderSentAt",
        "UsedPromo", "ReferrerID"  # ✅ Added UsedPromo + ReferrerID fields
    ]
    for r in rows:
        m = ET.SubElement(members, "Member")
        for i, tag in enumerate(tags):
            ET.SubElement(m, tag).text = str(r[i]) if i < len(r) and r[i] else ""

    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)

    await interaction.response.send_message("✅ Report exported to `/exports/`.", ephemeral=True)
    await send_admin(f"📊 Report generated:\n• PDF: `{pdf_path}`\n• XML: `{xml_path}`")
