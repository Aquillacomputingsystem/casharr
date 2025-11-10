# helpers/sms.py
import os, requests, configparser

CONFIG_PATH = os.path.join("config", "config.ini")
cfg = configparser.ConfigParser()
cfg.read(CONFIG_PATH, encoding="utf-8")

def send_sms(to_number: str, message: str) -> bool:
    """
    Send an SMS via Android SMS Gateway app or any HTTP-based gateway.
    Expected config fields under [SMS]:
        Enabled = true
        GatewayURL = http://phone-ip:port/message
        Token = your_api_token
        From = Casharr (optional)
    """
    if not cfg.has_section("SMS") or not cfg["SMS"].getboolean("Enabled", False):
        return False
    gateway = cfg["SMS"].get("GatewayURL", "").strip()
    token = cfg["SMS"].get("Token", "").strip()
    sender = cfg["SMS"].get("From", "Casharr")

    if not gateway or not token or not to_number:
        print("⚠️ SMS config incomplete — check [SMS] section.")
        return False

    payload = {
        "phone": to_number,
        "message": message,
        "token": token
    }
    try:
        res = requests.post(gateway, data=payload, timeout=10)
        if res.status_code in (200, 201):
            print(f"📲 SMS sent to {to_number}")
            return True
        print(f"⚠️ SMS gateway returned {res.status_code}: {res.text[:100]}")
        return False
    except Exception as e:
        print(f"⚠️ SMS send failed: {e}")
        return False

