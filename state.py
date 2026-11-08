import json
import os
import re
import time
from pathlib import Path

import psutil

import cpu
from common import LOGS, run, stamp
import gpu
from logs import APPS, KNOWN, STEAM

STATE = LOGS / "state"
# readings change every run; only flag big moves
READINGS = {"gpu_temp": 8, "vram_used_mb": 500, "cpu_temp": 8, "ram_used_gb": 2, "cpu_load": 25,
            "disk_root_pct": 5, "nvme_temp": 8, "gpu_util": 30, "gpu_power_w": 30, "gpu_mhz": 500,
            "swap_used_gb": 1}

def amd():
    s = gpu.sample()
    if not s:
        return {}, []
    g = {"gpu": gpu.name(), "gpu_temp": s["temp"], "gpu_hotspot": s["hotspot"], "vram_used_mb": s["vram"],
         "vram_total_mb": s["vram_total"], "gpu_power_w": s["watts"], "gpu_util": round(s["util"] or 0),
         "gpu_mhz": round(s["mhz"] or 0)}
    merged = {}
    for pid, mb in gpu.vram_by_pid().items():
        try:
            p = psutil.Process(pid)
            name = Path(p.exe()).name if p.exe() else p.name()
            cmd = " ".join(p.cmdline())
            if m := re.search(r"steamapps/common/([^/]+)", cmd):
                name += f" ({m.group(1)})"
        except (psutil.Error, OSError):
            name = "?"
        merged[name] = merged.get(name, 0) + mb
    return g, sorted(((mb, n) for n, mb in merged.items()), reverse=True)

def proton_versions():
    out = {}
    for d in list((APPS / "common").glob("Proton*")) + list((STEAM / "compatibilitytools.d").glob("*")):
        if "EasyAntiCheat" in d.name:
            continue
        v = d / "version"
        out[d.name] = v.read_text().split()[-1] if v.exists() else "?"
    return out

def failed_units():
    sysu = run(["systemctl", "--failed", "--plain", "--no-legend"]).stdout.split("\n")
    user = run(["systemctl", "--user", "--failed", "--plain", "--no-legend"]).stdout.split("\n")
    return [l.split()[0] for l in sysu if l.strip()] + [l.split()[0] + " (user)" for l in user if l.strip()]

def boot_errors():
    k = run(["journalctl", "-k", "-b", "--no-pager", "-o", "cat"]).stdout.splitlines()
    out = {}
    for label, pat, why in KNOWN:
        n = sum(1 for l in k if re.search(pat, l))
        if n:
            out[label] = n
    n_err = len(run(["journalctl", "-b", "-p", "err", "--no-pager", "-o", "cat", "-q"]).stdout.splitlines())
    return out, n_err

def smart():
    r = run(["smartctl", "-H", "-j", "/dev/nvme0"])
    try:
        st = json.loads(r.stdout).get("smart_status", {})
        return "passed" if st.get("passed") else "FAILED" if "passed" in st else "needs sudo to read"
    except ValueError:
        return "needs sudo to read"

def displays():
    r = run(["niri", "msg", "-j", "outputs"])
    out = []
    try:
        for name, o in json.loads(r.stdout).items():
            m = o["modes"][o["current_mode"]] if o.get("current_mode") is not None else None
            if m:
                out.append(f"{name} {m['width']}x{m['height']}@{m['refresh_rate'] / 1000:.0f}Hz"
                           + (" VRR" if o.get("vrr_enabled") else ""))
    except (ValueError, KeyError, TypeError):
        pass
    return out

def audio_out():
    r = run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"])
    m = re.search(r'node\.description = "([^"]+)"', r.stdout)
    return m.group(1) if m else "?"

def pending_updates():
    try:
        st = json.loads((Path.home() / ".cache/sysupdate/status.json").read_text())
    except (OSError, ValueError):
        return None
    return len(st.get("waiting", [])) + len(st.get("aur", [])) + len(st.get("flatpak_waiting", []))

def game_running():
    for p in psutil.process_iter(["cmdline"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if "SteamLaunch AppId=" in cmd and "AppId=431960" not in cmd:
            m = re.search(r"steamapps/common/([^/']+)", cmd)
            return m.group(1) if m else re.search(r"AppId=(\d+)", cmd).group(1)
    return None

def collect(note):
    gpu_info, vram = amd()
    temps = psutil.sensors_temperatures()
    pkg, _ = cpu.temps()
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    errs, n_err = boot_errors()
    kernel = os.uname().release
    s = {
        "id": stamp(), "note": note, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kernel": kernel,
        "kernel_reboot_needed": not Path(f"/usr/lib/modules/{kernel}").exists(),
        "gpu_driver": gpu.driver(),
        **gpu_info,
        "vram_top": [f"{n} {mb}MiB" for mb, n in vram[:6]],
        "cpu_temp": pkg, "cpu_load": psutil.cpu_percent(interval=1),
        "cpu_top": [f"{n} {c:.0f}%" for n, c in cpu.top_procs(5, 3)],
        "ram_used_gb": round(vm.used / 2**30, 1), "ram_total_gb": round(vm.total / 2**30, 1),
        "swap_used_gb": round(sw.used / 2**30, 1),
        "disk_root_pct": psutil.disk_usage("/").percent,
        "nvme_temp": next((round(t.current) for t in temps.get("nvme", [])), None),
        "smart": smart(),
        "displays": displays(), "audio_out": audio_out(),
        "proton": proton_versions(),
        "game_running": game_running(),
        "wallpaper_engine": any(p.info["name"] == "linux-wallpaper" or "linux-wallpaperengine" in (p.info["name"] or "")
                                for p in psutil.process_iter(["name"])),
        "failed_units": failed_units(),
        "boot_known_errors": errs, "boot_error_lines": n_err,
        "pending_updates": pending_updates(),
    }
    return s

def report(s):
    ok, bad = "  ok ", "  !  "
    L = [f"system state  {s['time']}" + (f"  ({s['note']})" if s["note"] else ""), ""]
    L.append("drivers")
    L.append((bad if s["kernel_reboot_needed"] else ok) + f"kernel {s['kernel']}"
             + ("  (updated, reboot to use it)" if s["kernel_reboot_needed"] else ""))
    L.append(ok + s.get("gpu_driver", "?"))
    L.append(ok + "proton " + ", ".join(f"{k} {v}" for k, v in s["proton"].items()))
    if "gpu" in s:
        vram_pct = s["vram_used_mb"] / s["vram_total_mb"] * 100
        L += ["", "gpu"]
        L.append((bad if s["gpu_temp"] >= 83 else ok) + f"{s['gpu']}  {s['gpu_temp']:.0f}°C (hotspot {s['gpu_hotspot']:.0f})  {s['gpu_mhz']} MHz  "
                 f"{s['gpu_power_w']:.0f} W  {s['gpu_util']}% busy")
        L.append((bad if vram_pct >= 85 else ok) + f"VRAM {s['vram_used_mb']}/{s['vram_total_mb']} MiB ({vram_pct:.0f}%)"
                 + ("  (almost full, games might freeze)" if vram_pct >= 85 else ""))
        L.append("       top: " + ", ".join(s["vram_top"]))
    L += ["", "cpu / memory"]
    L.append((bad if (s["cpu_temp"] or 0) >= 90 else ok) + f"CPU {s['cpu_temp']:.0f}°C, {s['cpu_load']:.0f}% busy"
             + (("  top: " + ", ".join(s["cpu_top"])) if s["cpu_top"] else ""))
    ram_pct = s["ram_used_gb"] / s["ram_total_gb"] * 100
    L.append((bad if ram_pct >= 90 else ok) + f"RAM {s['ram_used_gb']}/{s['ram_total_gb']} GB, swap {s['swap_used_gb']} GB")
    L += ["", "storage"]
    L.append((bad if s["disk_root_pct"] >= 90 else ok) + f"/ {s['disk_root_pct']:.0f}% full, NVMe {s['nvme_temp']}°C")
    L.append((bad if s["smart"] == "FAILED" else ok) + f"SMART health: {s['smart']}")
    L += ["", "desktop"]
    L.append(ok + "displays " + (", ".join(s["displays"]) or "?"))
    L.append(ok + f"audio out: {s['audio_out']}")
    L.append(ok + f"game running: {s['game_running'] or 'none'}, wallpaper engine: {'on' if s['wallpaper_engine'] else 'off'}")
    L += ["", "health"]
    L.append((bad if s["failed_units"] else ok) + "failed services: " + (", ".join(s["failed_units"]) or "none"))
    known = s["boot_known_errors"]
    L.append((bad if known else ok) + "driver/kernel problems since boot: "
             + (", ".join(f"{k} x{v}" for k, v in known.items()) or "none"))
    L.append(ok + f"{s['boot_error_lines']} error lines in the system log since boot (some is normal)")
    if s["pending_updates"] is not None:
        L.append((bad if s["pending_updates"] else ok) + f"pending updates: {s['pending_updates']}"
                 + ("  (sysupdate review)" if s["pending_updates"] else ""))
    return "\n".join(L) + "\n"

def cmd_state(args):
    if args.action == "compare":
        return cmd_compare(args)
    if args.action == "list":
        for f in sorted(STATE.glob("*.json")):
            d = json.loads(f.read_text())
            print(f"  {d['id']}  {d['note']}")
        return
    s = collect(args.note)
    STATE.mkdir(parents=True, exist_ok=True)
    text = report(s)
    (STATE / f"{s['id']}.json").write_text(json.dumps(s, indent=1))
    (STATE / f"{s['id']}.txt").write_text(text)
    print(text + f"\nsaved {STATE / s['id']}.txt")

def cmd_compare(args):
    files = sorted(STATE.glob("*.json"))
    ids = args.runs or [f.stem for f in files[-2:]]
    if len(ids) != 2:
        raise SystemExit("need two states (bench state list), or at least two saved")
    a, b = (json.loads((STATE / f"{i}.json").read_text()) for i in ids)
    print(f"{a['id']} ({a['note'] or '-'})  ->  {b['id']} ({b['note'] or '-'})\n")
    changed = False
    for k in a.keys() | b.keys():
        if k in ("id", "time", "note", "cpu_top", "boot_error_lines"):
            continue
        x, y = a.get(k), b.get(k)
        if k in READINGS:
            try:
                if abs(float(y) - float(x)) >= READINGS[k]:
                    print(f"  {k:20} {x} -> {y}")
                    changed = True
            except (TypeError, ValueError):
                pass
        elif x != y:
            if isinstance(x, dict) or isinstance(y, dict):
                x, y = x or {}, y or {}
                for kk in sorted(x.keys() | y.keys()):
                    if x.get(kk) != y.get(kk):
                        print(f"  {k + '.' + kk:20} {x.get(kk)} -> {y.get(kk)}")
            elif isinstance(x, list) or isinstance(y, list):
                gone, new = set(x or []) - set(y or []), set(y or []) - set(x or [])
                if k == "vram_top":
                    # only worth showing when VRAM moved
                    if abs(b.get("vram_used_mb", 0) - a.get("vram_used_mb", 0)) >= READINGS["vram_used_mb"]:
                        print(f"  {k:20} {', '.join(y or [])}")
                    continue
                else:
                    for v in sorted(gone):
                        print(f"  {k:20} - {v}")
                    for v in sorted(new):
                        print(f"  {k:20} + {v}")
            else:
                print(f"  {k:20} {x} -> {y}")
            changed = True
    if not changed:
        print("  nothing important changed")

def add_parser(sub):
    p = sub.add_parser("state", help="check everything & save a report")
    s = p.add_subparsers(dest="action")
    s.add_parser("list", help="saved states")
    c = s.add_parser("compare", help="what changed between two states (default: last two)")
    c.add_argument("runs", nargs="*")
    p.add_argument("--note", default="", help="e.g. 'before driver update'")
    p.set_defaults(func=cmd_state)
