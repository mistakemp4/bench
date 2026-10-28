import csv
import json
import subprocess
import time
from pathlib import Path

LOGS = Path.home() / "logs"

def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", f"{cmd[0]}: not installed")

def have(tool):
    return run(["which", tool]).returncode == 0

def stamp():
    return time.strftime("%Y%m%d-%H%M%S")

def avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None

def cell(v):
    return "" if v in (None, "") else str(v)

def print_table(rows, cols):
    cells = [[h for _, h in cols]] + [[cell(r.get(k)) for k, _ in cols] for r in rows]
    widths = [max(len(c[i]) for c in cells) for i in range(len(cols))]
    for c in cells:
        print("  ".join(v.ljust(w) for v, w in zip(c, widths)).rstrip())

def save_run(kind, res, detail, fields):
    d = LOGS / "bench" / kind
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{res['id']}.json"
    path.write_text(json.dumps({**res, **detail}, indent=1))
    summary = d / "summary.csv"
    new = not summary.exists()
    with summary.open("a", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(res)
    return path

def load_runs(kind):
    summary = LOGS / "bench" / kind / "summary.csv"
    if not summary.exists():
        return []
    with summary.open() as f:
        return list(csv.DictReader(f))

def list_runs(kind, cols):
    runs = load_runs(kind)
    if not runs:
        print(f"no {kind} runs yet, try: bench {kind} --note 'baseline'")
        return
    print_table(runs, cols)

# metrics: (key, label, lower_is_better, noise, noise_is_fraction)
def compare_runs(kind, ids, cols, metrics):
    runs = {r["id"]: r for r in load_runs(kind)}
    ids = ids or list(runs)[-2:]
    if len(ids) != 2 or any(i not in runs for i in ids):
        raise SystemExit(f"need two {kind} run ids (see bench {kind} list), or at least two runs")
    a, b = runs[ids[0]], runs[ids[1]]
    print_table([a, b], cols)
    print()
    for key, label, lower, noise, frac in metrics:
        try:
            x, y = float(a[key]), float(b[key])
        except (KeyError, ValueError):
            continue
        d = y - x
        tol = noise * abs(x) if frac else noise
        verdict = "same (noise)" if abs(d) <= tol else "better" if (d < 0) == lower else "worse"
        print(f"  {label:14} {d:+10.1f}  {verdict}")
    return a, b
