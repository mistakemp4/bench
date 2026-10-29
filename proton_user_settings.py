# symlinked into each Proton folder as user_settings.py by `bench proton-log`
import os
from pathlib import Path

ARMED = Path.home() / ".config/bench/proton-log"

app = os.environ.get("SteamGameId") or os.environ.get("SteamAppId") or ""
user_settings = {"PROTON_LOG": "1"} if app and (ARMED / app).exists() else {}
