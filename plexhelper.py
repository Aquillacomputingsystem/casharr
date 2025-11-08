from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount
import requests
import configparser
import os


class PlexHelper:
    def __init__(self, url, token, libraries):
        self.url = url
        self.token = token
        self.libraries = libraries
        self.plex = PlexServer(url, token)
        self.account = self.plex.myPlexAccount()

        # Load optional Discord webhook for admin logging
        CONFIG_PATH = os.path.join("config", "config.ini")
        self.admin_webhook = None
        if os.path.exists(CONFIG_PATH):
            cfg = configparser.ConfigParser()
            cfg.read(CONFIG_PATH)
            if "Discord" in cfg and "AdminWebhookURL" in cfg["Discord"]:
                self.admin_webhook = cfg["Discord"]["AdminWebhookURL"].strip() or None

    def test_connection(self):
        """Check whether the Plex server is reachable."""
        try:
            self.plex.library.sections()
            return True
        except Exception:
            return False

    # ────────────────────────────────
    # Discord logging helper
    # ────────────────────────────────
    def _discord_log(self, message):
        if not self.admin_webhook:
            return
        try:
            requests.post(self.admin_webhook, json={"content": message}, timeout=5)
        except Exception:
            pass

    # ────────────────────────────────
    # Invite Plex user
    # ────────────────────────────────
    def invite_user(self, email):
        """Send Plex invite by direct API call, restricted to configured libraries."""
        try:
            print(f"🔹 Checking existing invites for {email}")
            existing = [u for u in self.account.users() if u.email == email]
            if existing:
                msg = f"⚠️ {email} already has access or a pending invite."
                print(msg)
                self._discord_log(msg)
                return "already_invited"

            # Find the correct Plex server
            server_name = self.plex.friendlyName
            plex_resource = next(
                (r for r in self.account.resources()
                if r.name == server_name and "server" in r.provides),
                None,
            )
            if not plex_resource:
                msg = f"❌ Could not find Plex server resource for '{server_name}'."
                print(msg)
                self._discord_log(msg)
                return "server_not_found"

            server_id = getattr(plex_resource, "machineIdentifier", None) or getattr(
                plex_resource, "clientIdentifier", None
            )

            # 🔍 Fetch global section IDs from Plex.tv (not local keys)
            sections = []
            r = requests.get(
                f"https://plex.tv/api/servers/{server_id}",
                headers={"X-Plex-Token": self.token},
            )
            if r.status_code == 200:
                xml = r.text
                for name in self.libraries:
                    # match <Section title="Movies" id="111160616">
                    import re
                    match = re.search(
                        rf'id="(\d+)" key="\d+" type="[a-z]+" title="{re.escape(name)}"',
                        xml,
                    )
                    if match:
                        sid = match.group(1)
                        sections.append(sid)
                        print(f"   → Found {name} (global id: {sid})")
                    else:
                        print(f"⚠️ Library '{name}' not found on Plex.tv server list.")
            else:
                print(f"⚠️ Could not retrieve server sections ({r.status_code}).")

            if not sections:
                msg = "❌ No valid libraries found to share."
                print(msg)
                self._discord_log(msg)
                return "no_libraries"

            # --- Correct API call ---
            url = f"https://plex.tv/api/servers/{server_id}/shared_servers"
            headers = {
                "X-Plex-Token": self.token,
                "X-Plex-Client-Identifier": server_id,
                "X-Plex-Platform": "Python",
                "X-Plex-Product": "Casharr",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            }

            # form list with correct ids
            payload = [
                ("shared_server[invited_email]", email),
                ("shared_server[allow_sync]", 1),
                ("shared_server[allow_channels]", 1),
                ("shared_server[allow_camera_upload]", 0),
            ]
            for sid in sections:
                payload.append(("shared_server[library_section_ids][]", sid))

            r = requests.post(url, headers=headers, data=payload)
            if r.status_code in (200, 201):
                msg = f"✅ Plex invite sent to {email} (Libraries: {', '.join(self.libraries)})"
                print(msg)
                self._discord_log(msg)
                return "sent"
            else:
                msg = f"❌ Plex invite failed ({r.status_code}): {r.text}"
                print(msg)
                self._discord_log(msg)
                return f"HTTP {r.status_code}"

        except Exception as e:
            import traceback
            msg = f"❌ Plex invite failed for {email}: {type(e).__name__}: {e}"
            print(msg)
            traceback.print_exc()
            self._discord_log(msg)
            return "failed"

    # ────────────────────────────────
    # Remove Plex user
    # ────────────────────────────────
    def remove_user(self, email):
        """Remove Plex user by direct API call."""
        try:
            user = next((u for u in self.account.users() if u.email == email), None)
            if not user:
                msg = f"⚠️ No Plex user found for {email}."
                print(msg)
                self._discord_log(msg)
                return "not_found"

            server_name = self.plex.friendlyName
            plex_resource = next(
                (r for r in self.account.resources()
                 if r.name == server_name and "server" in r.provides),
                None,
            )
            if not plex_resource:
                msg = f"❌ Could not find Plex server resource for '{server_name}'."
                print(msg)
                self._discord_log(msg)
                return "server_not_found"

            server_id = getattr(plex_resource, "machineIdentifier", None) or getattr(
                plex_resource, "clientIdentifier", None
            )

            # Make DELETE request to revoke share
            url = f"https://plex.tv/api/servers/{server_id}/shared_servers"
            headers = {
                "X-Plex-Token": self.token,
                "X-Plex-Client-Identifier": server_id,
                "X-Plex-Platform": "Python",
                "X-Plex-Product": "Casharr",
                "Accept": "application/json",
            }
            payload = {"shared_server[invited_email]": email}
            r = requests.delete(url, headers=headers, data=payload)

            if r.status_code in (200, 204):
                msg = f"🚫 Removed Plex access for {email}"
                print(msg)
                self._discord_log(msg)
                return "removed"
            else:
                msg = f"❌ Plex remove failed ({r.status_code}): {r.text}"
                print(msg)
                self._discord_log(msg)
                return f"HTTP {r.status_code}"

        except Exception as e:
            import traceback
            msg = f"❌ Plex remove failed for {email}: {type(e).__name__}: {e}"
            print(msg)
            traceback.print_exc()
            self._discord_log(msg)
            return "failed"
