import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from common import avg, compare_runs, list_runs, print_table, save_run, stamp

METHOD = "matrixprod"  # fixed so runs compare
HOT = 90.0
FIELDS = ["id", "note", "duration", "idle_pkg", "load_pkg", "max_pkg", "max_core",
          "load_mhz", "score", "secs_hot", "throttle_events", "cooldown_drop", "room"]
COLS = [("id", "run"), ("note", "note"), ("idle_pkg", "idle°C"), ("load_pkg", "load°C"),
        ("max_pkg", "max°C"), ("load_mhz", "MHz"), ("score", "score"), ("secs_hot", f"≥{HOT:.0f}°C s"),
        ("throttle_events", "throttle"), ("cooldown_drop", "cool -°C"), ("room", "room°C")]
METRICS = [("load_pkg", "load temp", True, 1.5, False), ("max_pkg", "max temp", True, 1.5, False),
           ("load_mhz", "clock", False, 50, False), ("score", "score", False, 0.02, True),
           ("cooldown_drop", "cooldown drop", False, 2.0, False)]

def temps():
    t = psutil.sensors_temperatures()
    if "k10temp" in t:  # amd: Tctl = package, Tccd = per chiplet
        s = t["k10temp"]
        pkg = next((x.current for x in s if x.label == "Tctl"), None)
        core = max((x.current for x in s if x.label.startswith("Tccd")), default=None)
        return pkg, core
    cores = t.get("coretemp", [])
    pkg = next((s.current for s in cores if s.label.startswith("Package")), None)
    core = max((s.current for s in cores if s.label.startswith("Core")), default=None)
    return pkg, core

def mhz():
    f = psutil.cpu_freq(percpu=True)
    return round(sum(c.current for c in f) / len(f)) if f else None

def throttle_count():
    n = 0
    for f in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/thermal_throttle/*_throttle_count"):
        try:
            n += int(f.read_text())
        except (OSError, ValueError):
            pass
    return n

def top_procs(n=5, min_pct=5):
    procs = list(psutil.process_iter(["name"]))
    for p in procs:
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(1)
    top = []
    for p in procs:
        try:
            top.append((p.cpu_percent(None), p.info["name"]))
        except psutil.Error:
            pass
    return [(name, pct) for pct, name in sorted(top, reverse=True)[:n] if pct > min_pct]

def busy_check():
    usage = psutil.cpu_percent(interval=3)
    if usage < 15:
        return None
    return usage, [f"{n} {c:.0f}%" for n, c in top_procs()]

def phase(name, secs, t0, samples):
    fmt = lambda v: f"{v:.0f}" if v is not None else "?"
    end = time.monotonic() + secs
    while time.monotonic() < end:
        pkg, core = temps()
        s = {"t": round(time.monotonic() - t0, 1), "phase": name, "pkg": pkg, "core": core, "mhz": mhz()}
        samples.append(s)
        print(f"\r  {name:8} {s['t']:6.0f}s  pkg {fmt(pkg)}°C  hottest core {fmt(core)}°C  "
              f"{s['mhz']} MHz   ", end="", flush=True)
        time.sleep(1)
    print()

def cmd_run(args):
    if b := busy_check():
        print(f"the cpu is already {b[0]:.0f}% busy ({', '.join(b[1]) or 'not sure what'}), results would be off.")
        print("close it or wait a bit. --force runs anyway")
        if not args.force:
            sys.exit(1)

    run_id = stamp()
    samples, t0 = [], time.monotonic()
    throttle_start = throttle_count()
    print(f"bench cpu: {args.idle}s idle, {args.duration}s full load ({METHOD}), {args.cooldown}s cooldown")

    phase("idle", args.idle, t0, samples)
    with tempfile.TemporaryDirectory() as tmp:
        yml = Path(tmp) / "sn.yaml"
        sn = subprocess.Popen(["stress-ng", "--cpu", "0", "--cpu-method", METHOD, "-t", f"{args.duration}s",
                               "--metrics-brief", "--yaml", str(yml)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            phase("load", args.duration, t0, samples)
            sn.wait(timeout=30)
        except KeyboardInterrupt:
            sn.send_signal(signal.SIGINT)
            sn.wait()
            sys.exit("\naborted, nothing saved")
        m = re.search(r"bogo-ops-per-second-real-time:\s*([\d.]+)", yml.read_text()) if yml.exists() else None
    phase("cooldown", args.cooldown, t0, samples)

    load = [s for s in samples if s["phase"] == "load"]
    steady = load[len(load) // 2:]  # second half, after warm-up
    cool = [s for s in samples if s["phase"] == "cooldown"]
    res = {
        "id": run_id, "note": args.note, "duration": args.duration,
        "idle_pkg": avg(s["pkg"] for s in samples if s["phase"] == "idle"),
        "load_pkg": avg(s["pkg"] for s in steady),
        "max_pkg": max((s["pkg"] for s in load if s["pkg"]), default=None),
        "max_core": max((s["core"] for s in load if s["core"]), default=None),
        "load_mhz": round(avg(s["mhz"] for s in steady) or 0),
        "score": round(float(m.group(1))) if m else None,
        "secs_hot": sum(1 for s in load if (s["pkg"] or 0) >= HOT),
        "throttle_events": throttle_count() - throttle_start,
        "cooldown_drop": round(load[-1]["pkg"] - cool[-1]["pkg"], 1)
                         if load and cool and load[-1]["pkg"] is not None and cool[-1]["pkg"] is not None else None,
        "room": args.room,
    }
    detail = {"cpu": cpu_model(), "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
              "method": METHOD, "samples": samples}
    path = save_run("cpu", res, detail, FIELDS)
    print_table([res], COLS)
    print(f"\nsaved {path}")

def cpu_model():
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return None

def cmd_list(args):
    list_runs("cpu", COLS)

def cmd_compare(args):
    a, b = compare_runs("cpu", args.runs, COLS, METRICS)
    try:
        room = float(b["room"]) - float(a["room"])
        if abs(room) >= 2:
            print(f"\n  heads up: the room was {room:+.1f}°C different, temps move about that much too")
    except ValueError:
        pass

def add_parser(sub):
    p = sub.add_parser("cpu", help="cpu temps & speed under full load")
    s = p.add_subparsers(dest="action")
    s.add_parser("list", help="all saved cpu runs")
    c = s.add_parser("compare", help="compare two runs (default: last two)")
    c.add_argument("runs", nargs="*")
    p.add_argument("--note", default="", help="e.g. 'before repaste'")
    p.add_argument("--duration", type=int, default=300, help="load seconds (default 300)")
    p.add_argument("--idle", type=int, default=30)
    p.add_argument("--cooldown", type=int, default=60)
    p.add_argument("--room", type=float, help="room temp in °C, if you know it")
    p.add_argument("--force", action="store_true", help="run even if CPU is busy")
    p.set_defaults(func=lambda a: {"list": cmd_list, "compare": cmd_compare}.get(a.action, cmd_run)(a))
