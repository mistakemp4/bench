import gzip
import shutil
from datetime import datetime
from pathlib import Path

from common import LOGS

STEAM = Path.home() / ".local/share/Steam"
ARMED = Path.home() / ".config/bench/proton-log"
SAVED = LOGS / "proton"
SETTINGS = Path(__file__).resolve().parent / "proton_user_settings.py"

def proton_dirs():
    dirs = list((STEAM / "steamapps/common").glob("Proton*")) + list((STEAM / "compatibilitytools.d").glob("*"))
    return sorted(d for d in dirs if (d / "proton").is_file())

# returns protons that have their own user_settings.py
def ensure_links():
    own = []
    for d in proton_dirs():
        f = d / "user_settings.py"
        if f.is_symlink() and f.resolve() == SETTINGS:
            continue
        if f.exists():
            own.append(d.name)
            continue
        if f.is_symlink():  # broken link
            f.unlink()
        f.symlink_to(SETTINGS)
    return own

def armed():
    return sorted(p.name for p in ARMED.glob("*")) if ARMED.exists() else []

def arm(appid):
    ARMED.mkdir(parents=True, exist_ok=True)
    (ARMED / appid).touch()

def disarm(appid):
    (ARMED / appid).unlink(missing_ok=True)

# proton deletes the log next launch, so keep a copy
def game_closed(appid, started):
    log = Path.home() / f"steam-{appid}.log"
    saved = None
    if log.exists() and log.stat().st_mtime >= started.timestamp():
        SAVED.mkdir(parents=True, exist_ok=True)
        saved = SAVED / f"{started:%Y%m%d-%H%M%S}-{appid}.log.gz"
        with log.open("rb") as src, gzip.open(saved, "wb") as dst:
            shutil.copyfileobj(src, dst)
    flag = ARMED / appid
    # armed mid-game means it's for the next launch
    if flag.exists() and flag.stat().st_mtime < started.timestamp():
        flag.unlink()
    return saved

def find_saved(appid, start, end):
    for f in sorted(SAVED.glob(f"*-{appid}.log.gz"), reverse=True):
        try:
            ts = datetime.strptime(f.name.split(f"-{appid}")[0], "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        if (start - ts).total_seconds() <= 60 and ts <= end:
            return f
    return None
