import discord
import configparser

class LogHelper:
    def __init__(self, config):
        self.config = config
        self.enabled = config["Logging"].getboolean("Enabled", True)

    async def log(self, event, **kwargs):
        if not self.enabled:
            return
        if event == "invite" and self.config["Logging"].getboolean("LogInvites", True):
            print(self.config["Logging"]["InviteFormat"].format(**kwargs))
        elif event == "remove" and self.config["Logging"].getboolean("LogRemovals", True):
            print(self.config["Logging"]["RemoveFormat"].format(**kwargs))
        elif event == "role" and self.config["Logging"].getboolean("LogRoleChanges", True):
            print(self.config["Logging"]["RoleFormat"].format(**kwargs))
