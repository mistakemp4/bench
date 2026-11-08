import re
from functools import cache
from pathlib import Path

from common import run

@cache
def device():
    for d in sorted(Path("/sys/class/drm").iterdir()):
        dev = d / "device"
        if not re.fullmatch(r"card\d+", d.name):
            continue
        try:
            if (dev / "vendor").read_text().strip() == "0x1002" and (dev / "gpu_busy_percent").exists():
                return dev
        except OSError:
            continue
    return None

@cache
def hwmon():
    dev = device()
    return next((dev / "hwmon").glob("hwmon*"), None) if dev else None

def read(path, scale=1):
    try:
        return int(path.read_text()) / scale
    except (OSError, ValueError):
        return None

def sample():
    dev, hw = device(), hwmon()
    if not dev or not hw:
        return None
    vram = read(dev / "mem_info_vram_used", 2**20)
    if vram is None:  # gpu not answering
        return None
    hot = read(hw / "temp2_input", 1000)
    crit = read(hw / "temp2_crit", 1000) or 110
    watts = read(hw / "power1_average", 1e6) or read(hw / "power1_input", 1e6)
    cap = read(hw / "power1_cap", 1e6)
    pwm, pwm_max = read(hw / "pwm1"), read(hw / "pwm1_max") or 255
    return {"temp": read(hw / "temp1_input", 1000), "hotspot": hot, "mhz": read(hw / "freq1_input", 1e6),
            "watts": watts, "util": read(dev / "gpu_busy_percent"),
            "vram": round(vram), "vram_total": round(read(dev / "mem_info_vram_total", 2**20) or 0),
            "fan": None if pwm is None else round(pwm / pwm_max * 100),
            # sysfs has no throttle flags: hotspot near its limit, power at the cap
            "thermal": hot is not None and hot >= crit - 10,
            "powercap": bool(watts and cap and watts >= 0.98 * cap)}

def name():
    dev = device()
    if not dev:
        return "?"
    out = run(["lspci", "-mm", "-s", dev.resolve().name]).stdout
    fields = re.findall(r'"([^"]*)"', out)
    model = fields[2] if len(fields) > 2 else "?"
    m = re.search(r"\[(.+)\]", model)
    return m.group(1) if m else model

def driver():
    v = run(["pacman", "-Q", "mesa"]).stdout.split()
    return "mesa " + (v[1].split(":")[-1].split("-")[0] if len(v) > 1 else "?")

def vram_by_pid():
    # each drm client lists its vram in fdinfo; count each client once
    seen, per = set(), {}
    for fd in Path("/proc").glob("[0-9]*/fdinfo/*"):
        try:
            t = fd.read_text()
        except OSError:
            continue
        if "drm-driver:\tamdgpu" not in t:
            continue
        f = dict(re.findall(r"^(drm-[\w-]+):\s+(\d+)", t, re.M))
        pid = int(fd.parts[2])
        if (pid, f.get("drm-client-id")) in seen:
            continue
        seen.add((pid, f.get("drm-client-id")))
        kib = f.get("drm-total-vram") or f.get("drm-memory-vram")
        if kib:
            per[pid] = per.get(pid, 0) + int(kib) // 1024
    return per
