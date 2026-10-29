import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

import cpu
import hw
from common import LOGS

SENSORS = LOGS / "sensors"
EVERY = 2
IGNORED_APPS = {"431960"}  # wallpaper engine
TS = "%Y-%m-%d %H:%M:%S"
FIELDS = ["time", "vram", "vram_total", "gpu_temp", "gpu_mhz", "gpu_watts", "gpu_util", "fan",
          "gpu_thermal", "cpu_pkg", "cpu_mhz", "cpu_util", "ram_gb", "swap_gb"]

def game_running():
    for p in psutil.process_iter(["cmdline"]):
        args = p.info["cmdline"] or []
        if "SteamLaunch" not in args:
            continue
        app = next((a[6:] for a in args if a.startswith("AppId=")), None)
        if app and app not in IGNORED_APPS:
            return app
    return None

def sample():
    g = hw.gpu_sample() or {}
    pkg, _ = cpu.temps()
    mem, swap = psutil.virtual_memory(), psutil.swap_memory()
    return {"time": datetime.now().strftime(TS), "vram": g.get("vram"), "vram_total": g.get("vram_total"),
            "gpu_temp": g.get("temp"), "gpu_mhz": g.get("mhz"), "gpu_watts": g.get("watts"),
            "gpu_util": g.get("util"), "fan": g.get("fan"), "gpu_thermal": int(g["thermal"]) if g else None,
            "cpu_pkg": pkg, "cpu_mhz": cpu.mhz(), "cpu_util": psutil.cpu_percent(None),
            "ram_gb": round(mem.used / 2**30, 1), "swap_gb": round(swap.used / 2**30, 1)}

def record(appid, live):
    SENSORS.mkdir(parents=True, exist_ok=True)
    path = SENSORS / f"{datetime.now():%Y%m%d-%H%M%S}-{appid}.csv"
    print(f"game {appid} started, recording to {path}", flush=True)
    psutil.cpu_percent(None)  # first call is always 0
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        while game_running() == appid:
            s = sample()
            w.writerow(s)
            f.flush()
            os.fsync(f.fileno())  # survive a hard freeze
            if live:
                fmt = lambda v: "?" if v is None else f"{v:.0f}"
                print(f"\r  vram {fmt(s['vram'])}/{fmt(s['vram_total'])} MiB  gpu {fmt(s['gpu_temp'])}°C  "
                      f"cpu {fmt(s['cpu_pkg'])}°C  ram {s['ram_gb']} GB   ", end="", flush=True)
            time.sleep(EVERY)
    print(("\n" if live else "") + f"game {appid} closed", flush=True)

def cmd_watch(args):
    live = sys.stdout.isatty()
    if live:
        print("waiting for a steam game... (ctrl+c to stop)")
    try:
        while True:
            if app := game_running():
                record(app, live)
            time.sleep(5)
    except KeyboardInterrupt:
        print()

def load(appid, start, end):
    rows = []
    for f in sorted(SENSORS.glob(f"*-{appid}.csv")):
        with f.open(newline="") as fh:
            for r in csv.DictReader(fh):
                # skip a half-written last line after a crash
                if len(r.get("time") or "") != 19 or r.get(FIELDS[-1]) is None:
                    continue
                ts = datetime.strptime(r["time"], TS)
                if start <= ts <= end:
                    rows.append(r)
    return rows

def add_parser(sub):
    p = sub.add_parser("watch", help="record vram/temps while steam games run (the service runs this)")
    p.set_defaults(func=cmd_watch)
