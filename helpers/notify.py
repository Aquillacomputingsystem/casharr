import logging
from emailer import send_email
from sms import send_sms

logger = logging.getLogger("notify")

def send_notification(email=None, mobile=None, discord_member=None, subject="", message=""):
    """Send notification via all enabled channels."""
    sent_any = False

    if email:
        try:
            send_email(email, subject, message)
            logger.info(f"Email sent to {email}")
            sent_any = True
        except Exception as e:
            logger.warning(f"Email failed to {email}: {e}")

    if mobile:
        try:
            send_sms(mobile, message)
            logger.info(f"SMS sent to {mobile}")
            sent_any = True
        except Exception as e:
            logger.warning(f"SMS failed to {mobile}: {e}")

    if discord_member:
        try:
            import main as bot_main
            import asyncio
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(
                discord_member.send(message), loop
            )
            logger.info(f"DM sent to Discord user {discord_member}")
            sent_any = True
        except Exception as e:
            logger.warning(f"Discord DM failed: {e}")

    return sent_any
