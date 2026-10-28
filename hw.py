import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

from common import avg, compare_runs, have, list_runs, print_table, save_run, stamp

GPU_FIELDS = "temperature.gpu,clocks.gr,power.draw,utilization.gpu,memory.used,fan.speed,clocks_event_reasons.active"

def need(tool, pkg):
    if not have(tool):
        raise SystemExit(f"{tool} isn't installed, get it with: sudo pacman -S {pkg}")

def num(v):
    try:
        return float(v)
    except ValueError:
        return None

def gpu_sample():
    r = subprocess.run(["nvidia-smi", f"--query-gpu={GPU_FIELDS}", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True)
    v = [x.strip() for x in r.stdout.split(",")]
    if len(v) < 7:
        return None
    reasons = int(v[6], 16) if v[6].startswith("0x") else 0
    # 0x20 sw thermal, 0x40 hw thermal, 0x4 sw power cap
    return {"temp": num(v[0]), "mhz": num(v[1]), "watts": num(v[2]), "util": num(v[3]),
            "vram": num(v[4]), "fan": num(v[5]), "thermal": bool(reasons & 0x60), "powercap": bool(reasons & 0x4)}

def sampler(samples, stop):
    t0 = time.monotonic()
    while not stop.is_set():
        if s := gpu_sample():
            s["t"] = round(time.monotonic() - t0, 1)
            samples.append(s)
            print(f"\r  {s['t']:5.0f}s  {s['temp']:.0f}°C  {s['mhz']:.0f} MHz  {s['watts']:.0f} W  "
                  f"{s['util']:.0f}% busy  fan {s['fan']:.0f}%   ", end="", flush=True)
        stop.wait(1)

# gpu
GPU_COLS = [("id", "run"), ("note", "note"), ("tool", "tool"), ("score", "score"), ("avg_temp", "avg°C"),
            ("max_temp", "max°C"), ("avg_mhz", "MHz"), ("avg_watts", "W"), ("max_fan", "fan%"),
            ("secs_thermal", "thermal-limited s"), ("max_vram", "VRAM MiB")]
GPU_METRICS = [("score", "score", False, 0.03, True), ("avg_temp", "avg temp", True, 2, False),
               ("max_temp", "max temp", True, 2, False), ("avg_mhz", "clock", False, 30, False),
               ("max_fan", "fan", True, 5, False)]

def gpu_run(args):
    # vkmark's wayland window dies on niri & xcb is vsync-capped, so glmark2 off-screen
    tool = next((t for t in ("glmark2-wayland", "glmark2") if have(t)), None)
    if not tool:
        raise SystemExit("i need glmark2 for this: sudo pacman -S glmark2")
    cmd = [tool, "--off-screen", "-s", "1920x1080"]
    print(f"bench gpu: glmark2 off-screen at 1920x1080 (a few minutes, no window)")
    samples, stop = [], threading.Event()
    th = threading.Thread(target=sampler, args=(samples, stop), daemon=True)
    th.start()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    except KeyboardInterrupt:
        stop.set()
        sys.exit("\naborted, nothing saved")
    stop.set()
    th.join()
    print()
    m = re.search(r"glmark2 Score:\s*(\d+)", r.stdout)
    if not m:
        print(r.stdout[-1500:], r.stderr[-1500:])
        raise SystemExit("glmark2 didn't give a score, its output is above")
    busy = [s for s in samples if (s["util"] or 0) >= 50] or samples
    res = {"id": stamp(), "note": args.note, "tool": tool, "score": int(m.group(1)),
           "avg_temp": avg(s["temp"] for s in busy), "max_temp": max(s["temp"] for s in samples),
           "avg_mhz": round(avg(s["mhz"] for s in busy) or 0), "avg_watts": avg(s["watts"] for s in busy),
           "max_fan": round(max(s["fan"] for s in samples)), "secs_thermal": sum(s["thermal"] for s in samples),
           "max_vram": round(max(s["vram"] for s in samples))}
    path = save_run("gpu", res, {"samples": samples, "output": r.stdout[-4000:]}, [k for k, _ in GPU_COLS])
    print_table([res], GPU_COLS)
    print(f"\nsaved {path}")

# disk
DISK_COLS = [("id", "run"), ("note", "note"), ("path", "tested"), ("seq_read", "seq read MB/s"),
             ("seq_write", "seq write MB/s"), ("rand_read", "4k read IOPS"), ("rand_write", "4k write IOPS"),
             ("max_temp", "max°C"), ("smart", "SMART")]
DISK_METRICS = [("seq_read", "seq read", False, 0.05, True), ("seq_write", "seq write", False, 0.05, True),
                ("rand_read", "4k read", False, 0.08, True), ("rand_write", "4k write", False, 0.08, True)]
JOBS = [("seq_read", "read", "1M", 8), ("seq_write", "write", "1M", 8),
        ("rand_read", "randread", "4k", 32), ("rand_write", "randwrite", "4k", 32)]

def nvme_temp():
    return next((t.current for t in psutil.sensors_temperatures().get("nvme", [])), None)

def disk_run(args):
    need("fio", "fio")
    folder = Path(args.path).expanduser()
    free = psutil.disk_usage(folder).free
    if free < 4 * 2**30:
        raise SystemExit(f"i need 4 GB free in {folder} for this")
    res = {"id": stamp(), "note": args.note, "path": str(folder)}
    temps = []
    print(f"bench disk: 4 tests x {args.seconds}s in {folder} (uses a 1 GB test file & deletes it after)")
    with tempfile.TemporaryDirectory(dir=folder, prefix=".bench-fio-") as tmp:
        f = Path(tmp) / "test"
        for key, rw, bs, qd in JOBS:
            print(f"  {key:11}", end="", flush=True)
            r = subprocess.run(["fio", "--name", key, f"--filename={f}", "--size=1G", f"--rw={rw}", f"--bs={bs}",
                                f"--iodepth={qd}", "--ioengine=libaio", "--direct=1", "--time_based",
                                f"--runtime={args.seconds}", "--output-format=json"],
                               capture_output=True, text=True)
            temps.append(nvme_temp())
            try:
                job = json.loads(r.stdout)["jobs"][0]
            except (ValueError, KeyError, IndexError):
                raise SystemExit(f"fio failed: {r.stderr[-500:]}")
            side = job["read"] if "read" in rw else job["write"]
            res[key] = round(side["bw"] / 1024) if bs == "1M" else round(side["iops"])
            print(f"{res[key]} {'MB/s' if bs == '1M' else 'IOPS'}")
    res["max_temp"] = round(max((t for t in temps if t), default=0)) or None
    from state import smart
    res["smart"] = smart()
    path = save_run("disk", res, {}, [k for k, _ in DISK_COLS])
    print()
    print_table([res], DISK_COLS)
    print(f"\nsaved {path}")

# mem
MEM_COLS = [("id", "run"), ("note", "note"), ("gb", "GB tested"), ("seconds", "s"), ("result", "result"),
            ("score", "score")]
MEM_METRICS = [("score", "score", False, 0.03, True)]

def mem_run(args):
    need("stress-ng", "stress-ng")
    avail = psutil.virtual_memory().available
    gb = round(avail * args.fraction / 2**30, 1)
    workers = 4
    print(f"bench mem: writing & checking {gb} GB of RAM for {args.seconds}s")
    print("  this is a quick check. a real RAM test is memtest86+, it runs at boot")
    with tempfile.TemporaryDirectory() as tmp:
        yml = Path(tmp) / "sn.yaml"
        p = subprocess.Popen(["stress-ng", "--vm", str(workers), "--vm-bytes", f"{int(avail * args.fraction / workers)}",
                              "--vm-method", "all", "--verify", "-t", f"{args.seconds}s", "--metrics-brief",
                              "--yaml", str(yml)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            out, _ = p.communicate()
        except KeyboardInterrupt:
            p.send_signal(signal.SIGINT)
            p.wait()
            sys.exit("\naborted, nothing saved")
        m = re.search(r"bogo-ops-per-second-real-time:\s*([\d.]+)", yml.read_text()) if yml.exists() else None
    fails = re.findall(r"(?i)verif\w* (?:fail|error)[^\n]*|detected \d+ bit errors[^\n]*", out)
    result = "PASS" if p.returncode == 0 and not fails else "FAIL"
    res = {"id": stamp(), "note": args.note, "gb": gb, "seconds": args.seconds, "result": result,
           "score": round(float(m.group(1))) if m else None}
    path = save_run("mem", res, {"errors": fails[:20], "rc": p.returncode}, [k for k, _ in MEM_COLS])
    print_table([res], MEM_COLS)
    if result == "FAIL":
        print("\n  ! found memory errors:\n    " + "\n    ".join(fails[:5] or [f"stress-ng exit code {p.returncode}"]))
        print("  that could be bad RAM or an unstable XMP/overclock. run memtest86+ to be sure before replacing anything")
    print(f"\nsaved {path}")

def add_parser(sub):
    specs = [("gpu", "gpu speed & temps", gpu_run, GPU_COLS, GPU_METRICS),
             ("disk", "drive speed & health", disk_run, DISK_COLS, DISK_METRICS),
             ("mem", "quick RAM check", mem_run, MEM_COLS, MEM_METRICS)]
    for kind, help_, fn, cols, metrics in specs:
        p = sub.add_parser(kind, help=help_)
        s = p.add_subparsers(dest="action")
        s.add_parser("list", help=f"all saved {kind} runs")
        c = s.add_parser("compare", help="compare two runs (default: last two)")
        c.add_argument("runs", nargs="*")
        p.add_argument("--note", default="")
        if kind == "disk":
            p.add_argument("--path", default="~", help="folder on the drive to test (default: home)")
            p.add_argument("--seconds", type=int, default=15, help="per test (default 15)")
        if kind == "mem":
            p.add_argument("--seconds", type=int, default=120)
            p.add_argument("--fraction", type=float, default=0.7, help="share of free RAM to test (default 0.7)")
        p.set_defaults(func=lambda a, k=kind, f=fn, cl=cols, me=metrics:
                       list_runs(k, cl) if a.action == "list" else
                       compare_runs(k, a.runs, cl, me) if a.action == "compare" else f(a))
