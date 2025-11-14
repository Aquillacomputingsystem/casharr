# helpers/emailer.py
import smtplib, ssl, os, configparser
from email.message import EmailMessage

def send_email(subject, body, to=None):
    """Send an email using SMTP settings, optionally to a specific address."""
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join("config", "config.ini"))

    if not cfg.has_section("SMTP") or not cfg["SMTP"].getboolean("Enabled", False):
        return False

    host = cfg["SMTP"].get("Server", "smtp.gmail.com")
    user = cfg["SMTP"].get("User")
    pw   = cfg["SMTP"].get("Pass")

    # If no recipient was supplied, fallback to admin
    if not to:
        to = cfg["SMTP"].get("To")

    if not (user and pw and to):
        print("⚠ Missing SMTP user/pass or target email")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.set_content(body)

    ctx = ssl.create_default_context()

    try:
        with smtplib.SMTP_SSL(host, 465, context=ctx) as s:
            s.login(user, pw)
            s.send_message(msg)
        return True
    
    except Exception as e:
        print("❌ SMTP error:", e)
        return False
