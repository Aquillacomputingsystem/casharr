# helpers/emailer.py
import smtplib, ssl, os, configparser
from email.message import EmailMessage

def send_email(subject, body):
    """Send an email notification using SMTP details in config.ini"""
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join("config", "config.ini"))
    if not cfg.has_section("SMTP") or not cfg["SMTP"].getboolean("Enabled", False):
        return
    host = cfg["SMTP"].get("Server", "smtp.gmail.com")
    user = cfg["SMTP"].get("User")
    pw = cfg["SMTP"].get("Pass")
    to_addr = cfg["SMTP"].get("To")
    if not (user and pw and to_addr):
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(body)

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, 465, context=ctx) as s:
        s.login(user, pw)
        s.send_message(msg)

def send_bulk_emails(subject: str, message: str, recipients: list[str]):
    """Send the same email to multiple recipients in one go."""
    for email in recipients:
        try:
            send_email(subject, message, to=email)
        except Exception as e:
            print(f"⚠️ Bulk email failed for {email}: {e}")