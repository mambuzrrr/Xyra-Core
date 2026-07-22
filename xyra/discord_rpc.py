import time

from xyra.app_constants import (
    APP_NAME,
    APP_REPOSITORY_URL,
    APP_VERSION,
    DISCORD_APP_ID,
    DISCORD_LARGE_IMAGE_KEY,
    DISCORD_SMALL_IMAGE_KEY,
)

try:
    from pypresence import Presence
except Exception:
    Presence = None


class DiscordRichPresence:
    def __init__(self):
        self.rpc = None
        self.started_at = int(time.time())
        self.enabled = Presence is not None

    def connect(self):
        if not self.enabled or self.rpc is not None:
            return
        try:
            rpc = Presence(DISCORD_APP_ID)
            rpc.connect()
            self.rpc = rpc
            self.update("Idle in dashboard", APP_VERSION)
        except Exception:
            self.rpc = None
            self.enabled = False

    def update(self, state: str = "Browsing remote files", details: str | None = None):
        if not self.enabled:
            return
        if self.rpc is None:
            self.connect()
            if self.rpc is None:
                return
        try:
            self.rpc.update(
                details=details or APP_VERSION,
                state=state,
                start=self.started_at,
                large_image=DISCORD_LARGE_IMAGE_KEY,
                large_text=APP_NAME,
                small_image=DISCORD_SMALL_IMAGE_KEY,
                small_text="Linux / VPS dashboard",
                buttons=[
                    {
                        "label": "Get Xyra on GitHub",
                        "url": APP_REPOSITORY_URL,
                    }
                ],
            )
        except Exception:
            self.close()
            self.enabled = False

    def close(self):
        if self.rpc is None:
            return
        try:
            self.rpc.close()
        except Exception:
            pass
        self.rpc = None
