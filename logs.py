import re
import shutil
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from common import LOGS, run

STEAM = Path.home() / ".local/share/Steam"
APPS = STEAM / "steamapps"
TS = "%Y-%m-%d %H:%M:%S"
LINE_TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]")
MAX_COPY = 20 * 1024 * 1024
GAME_FILE_EXT = {".log", ".txt", ".dmp", ".mdmp", ".json", ".ini", ".cfg"}

# kernel/journal patterns worth calling out
KNOWN = [
    ("NVRM", r"NVRM(?!: loading)|Failed to allocate NVKMS memory",
     "nvidia driver errors. usually means VRAM ran out"),
    ("Xid", r"NVRM: Xid", "the gpu crashed (Xid). driver bug, too hot or a bad overclock"),
    ("OOM", r"Out of memory|oom-kill", "RAM ran out & something got killed"),
    ("segfault", r"segfault at", "something crashed (segfault)"),
    ("GPU hang", r"GPU has fallen off the bus|timeout waiting", "the gpu stopped responding"),
]

def manifests():
    out = []
    for m in APPS.glob("appmanifest_*.acf"):
        t = m.read_text(errors="replace")
        f = dict(re.findall(r'^\s*"(appid|name|installdir)"\s+"([^"]*)"', t, re.M))
        if "appid" in f:
            out.append(f)
    return out

def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())

def find_game(query):
    games = [g for g in manifests() if not norm(g["name"]).startswith(("proton", "steamlinuxruntime", "steamworks"))]
    if query.isdigit():
        hit = [g for g in games if g["appid"] == query]
    else:
        q = norm(query)
        # name or install folder (P5R, P3P...)
        keys = lambda g: (norm(g["name"]), norm(g.get("installdir", "")))
        hit = [g for g in games if q in keys(g)] or [g for g in games if any(q in k for k in keys(g))]
    if len(hit) == 1:
        return hit[0]
    if not hit:
        raise SystemExit(f"i can't find an installed game called '{query}'")
    raise SystemExit("which one?\n" + "\n".join(f"  {g['appid']:>8}  {g['name']}" for g in hit))

def sessions(appid):
    pat_add = re.compile(rf"AppID {appid} adding PID \d+ as a tracked process(?: \"(.*)\")?$")
    pat_end = re.compile(rf"AppID {appid} no longer tracking PID \d+, exit code (-?\d+)")
    out, cur = [], None
    for name in ("gameprocess_log.previous.txt", "gameprocess_log.txt"):
        f = STEAM / "logs" / name
        if not f.exists():
            continue
        for line in f.read_text(errors="replace").splitlines():
            m = LINE_TS.match(line)
            if not m:
                continue
            ts = datetime.strptime(m.group(1), TS)
            if (a := pat_add.search(line)) and a.group(1) and "SteamLaunch" in a.group(1):
                if cur:
                    out.append(cur)
                cur = {"start": ts, "end": None, "cmd": a.group(1), "exits": []}
            elif cur and (e := pat_end.search(line)):
                cur["end"] = ts
                cur["exits"].append(int(e.group(1)))
    if cur:
        out.append(cur)
    # dedupe if previous/current overlap
    seen, uniq = set(), []
    for s in out:
        if s["start"] not in seen:
            seen.add(s["start"])
            uniq.append(s)
    return uniq

def launch_options(appid):
    for cfg in (STEAM / "userdata").glob("*/config/localconfig.vdf"):
        t = cfg.read_text(errors="replace")
        m = re.search(rf'\n(\t+)"{appid}"\n\1\{{(.*?)\n\1\}}', t, re.S)
        if m and (lo := re.search(r'"LaunchOptions"\s+"((?:[^"\\]|\\.)*)"', m.group(2))):
            return lo.group(1)
    return ""

def proton_from_cmd(cmd):
    m = re.search(r"steamapps/common/([^'/]*Proton[^'/]*)'?/proton|compatibilitytools\.d/([^'/]+)'?/proton", cmd)
    return (m.group(1) or m.group(2)) if m else "native (no Proton)"

def window_lines(path, start, end):
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    out, keep = [], False
    for line in lines:
        if m := LINE_TS.match(line):
            ts = datetime.strptime(m.group(1), TS)
            keep = start <= ts <= end
        if keep:
            out.append(line)
    return out

def journal(start, end, *extra):
    r = run(["journalctl", "--no-pager", "-o", "short-iso", "--since", start.strftime(TS),
             "--until", end.strftime(TS), *extra])
    return r.stdout

def copy_small(src, dst):
    try:
        if src.stat().st_size <= MAX_COPY:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
    except OSError:
        pass
    return False

def game_files(game, start, end):
    lo, hi = start.timestamp() - 300, end.timestamp() + 600
    roots = [APPS / "common" / game["installdir"]]
    users = APPS / "compatdata" / game["appid"] / "pfx/drive_c/users/steamuser"
    roots += [users / "AppData", users / "Documents", users / "Saved Games"]
    for root in roots:
        if not root.exists():
            continue
        for f in root.rglob("*"):
            try:
                if f.is_file() and f.suffix.lower() in GAME_FILE_EXT and f.name != "steam_appid.txt" \
                        and lo <= f.stat().st_mtime <= hi:
                    yield root, f
            except OSError:
                continue

def fmt_dur(td):
    m = int(td.total_seconds() // 60)
    return f"{m // 60}h {m % 60}m" if m >= 60 else f"{m}m"

def cmd_logs(args):
    game = find_game(args.game)
    appid = game["appid"]
    ss = sessions(appid)
    if args.list:
        if not ss:
            print(f"steam has no sessions of {game['name']} yet")
        for i, s in enumerate(reversed(ss), 1):
            end = s["end"] or datetime.now()
            print(f"  {i:>2}. {s['start']:%Y-%m-%d %H:%M}  {fmt_dur(end - s['start']):>7}  {proton_from_cmd(s['cmd'])}")
        return
    if not ss:
        raise SystemExit(f"steam has no sessions of {game['name']} (it only keeps the last few days)")
    if not 1 <= args.session <= len(ss):
        raise SystemExit(f"there's only {len(ss)} sessions, see: bench logs {args.game} --list")
    s = ss[-args.session]
    running = run(["pgrep", "-f", f"SteamLaunch AppId={appid}"]).returncode == 0 and args.session == 1
    end = datetime.now() if running or not s["end"] else s["end"]
    start = s["start"]
    slug = norm(game["name"]) or appid
    out = LOGS / "games" / slug / start.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    # proton log
    plog = Path.home() / f"steam-{appid}.log"
    lo = launch_options(appid)
    proton_log = None
    if plog.exists() and plog.stat().st_mtime >= start.timestamp():
        proton_log = out / "proton.log"
        if not copy_small(plog, proton_log):
            with plog.open("rb") as f:  # huge log, keep the tail
                f.seek(-MAX_COPY, 2)
                proton_log.write_bytes(f.read())

    kernel = journal(start, end, "_TRANSPORT=kernel")  # -k would mean current boot only
    errors = journal(start, end, "-p", "err")
    (out / "kernel.log").write_text(kernel)
    (out / "journal-errors.log").write_text(errors)

    sdir = out / "steam"
    sdir.mkdir(exist_ok=True)
    for name in ("console_log.txt", "gameprocess_log.txt", "compat_log.txt", "shader_log.txt", "content_log.txt"):
        lines = window_lines(STEAM / "logs" / name, start - timedelta(minutes=2), end)
        if lines:
            (sdir / name).write_text("\n".join(lines) + "\n")

    copied = []
    for root, f in game_files(game, start, end):
        rel = f.relative_to(root)
        if copy_small(f, out / "game-files" / root.name / rel):
            copied.append(f"{root.name}/{rel}")

    # findings
    found = []
    for label, pat, why in KNOWN:
        hits = [l for l in kernel.splitlines() + errors.splitlines() if re.search(pat, l)]
        if hits:
            found.append((label, len(hits), why, hits[0][-160:]))
    perr = Counter()
    if proton_log:
        for l in proton_log.read_text(errors="replace").splitlines():
            if ":err:" in l:
                perr[re.sub(r"^\S+:\S+:err:", "err:", l)[:120]] += 1
    dumps = [c for c in copied if c.lower().endswith((".dmp", ".mdmp"))]
    bad_exit = [e for e in s["exits"] if e not in (0, -1)]  # steam logs -1 for normal helper exits
    oldest = oldest_system_log()
    logs_gone = oldest and oldest > start

    lines = [
        f"{game['name']} (AppID {appid})",
        f"session   {start:%Y-%m-%d %H:%M:%S} -> {'still running' if running else f'{end:%H:%M:%S}'}  ({fmt_dur(end - start)})",
        f"proton    {proton_from_cmd(s['cmd'])}",
        f"launch    {lo or '(none)'}",
        f"now       kernel {run(['uname', '-r']).stdout.strip()}, nvidia {driver_version()} (might not match the session)",
        "",
        "what i found:",
    ]
    if found:
        for label, n, why, sample in found:
            lines += [f"  ! {label} x{n}: {why}", f"      e.g. {sample}"]
    if bad_exit:
        lines.append(f"  ! exit code {', '.join(map(str, sorted(set(bad_exit))))}: it crashed or got force closed")
    if dumps:
        lines.append(f"  ! crash dumps: {', '.join(dumps)}")
    if perr:
        lines.append(f"  - proton logged {sum(perr.values())} errors, these the most:")
        lines += [f"      {n:>5}x {msg}" for msg, n in perr.most_common(5)]
    if logs_gone:
        lines += [f"  ? system logs from before {oldest:%Y-%m-%d %H:%M} are gone, so i can't check this session",
                  "    for driver errors. play again & run this right after"]
    if not (found or bad_exit or dumps or perr or logs_gone):
        lines.append("  nothing weird in the system logs for this session")
    uses_proton = proton_from_cmd(s["cmd"]) != "native (no Proton)"
    if uses_proton and not proton_log:
        want = ("PROTON_LOG=1 " + lo) if lo and "PROTON_LOG" not in lo else "PROTON_LOG=1 %command%"
        if "PROTON_LOG" in lo:
            nag = ["! launch options have PROTON_LOG but no log showed up for this session.",
                   f"  it should be at ~/steam-{appid}.log, play again & check"]
        else:
            nag = ["! no proton log, you forgot PROTON_LOG=1 :(",
                   "  steam > right click the game > properties > launch options, set it to:",
                   f"    {want}",
                   f"  then play again & run: bench logs {args.game}",
                   "  take it back out after, the log gets big"]
        lines = lines[:6] + nag + [""] + lines[6:]
    elif uses_proton and "PROTON_LOG" in lo:
        lines.append(f"  - got the proton log. you can take PROTON_LOG=1 back out of launch options now")
    lines += ["", "saved to:", f"  {out}/"]
    lines += [f"    {p.relative_to(out)}" for p in sorted(out.rglob("*")) if p.is_file() and p.name != "summary.txt"][:40]
    (out / "launch-command.txt").write_text(s["cmd"] + "\n")
    text = "\n".join(lines) + "\n"
    (out / "summary.txt").write_text(text)
    print(text, end="")

def oldest_system_log():
    r = run(["sh", "-c", "journalctl --system --no-pager -o short-unix -q | head -1"])
    try:
        return datetime.fromtimestamp(float(r.stdout.split()[0]))
    except (IndexError, ValueError):
        return None

def driver_version():
    try:
        return Path("/sys/module/nvidia/version").read_text().strip()
    except OSError:
        return "n/a"

def add_parser(sub):
    p = sub.add_parser("logs", help="grab a game's logs from its last session")
    p.add_argument("game", help="name (fuzzy) or AppID")
    p.add_argument("--session", type=int, default=1, help="1 = latest, 2 = one before, ...")
    p.add_argument("--list", action="store_true", help="list recent sessions")
    p.set_defaults(func=cmd_logs)
