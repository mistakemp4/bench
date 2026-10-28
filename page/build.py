import html, re, sys
from pathlib import Path
D = Path(sys.argv[1]); O = Path(sys.argv[2])
def out(name):
    t = (O / f"{name}.txt").read_text()
    t = re.sub(r"\n{3,}", "\n\n", t).strip("\n")
    e = html.escape(t)
    e = re.sub(r"(?m)^(\s*! .*)$", r'<span class="bad">\1</span>', e)
    e = re.sub(r"(?m)^(\s*\? .*)$", r'<span class="q">\1</span>', e)
    e = re.sub(r"(?m)^(\s*ok .*)$", r'<span class="ok">\1</span>', e)
    e = re.sub(r"(?m)^(saved .*)$", r'<span class="dim">\1</span>', e)
    e = e.replace("same (noise)", '<span class="dim">same (noise)</span>')
    return e
def sec(id_, tag, title, what, cmds, figs, note=""):
    f = "\n".join(f'<figure><figcaption><b>$</b> {html.escape(c)}</figcaption><pre>{out(n)}</pre></figure>' for c, n in figs)
    c = "".join(f"<code>{html.escape(x)}</code>" for x in cmds)
    n = f'<p class="note">{note}</p>' if note else ""
    return f'''<section id="{id_}">
<div class="head"><h2><span>bench</span> {title}</h2><span class="tag">{tag}</span></div>
<p class="what">{what}</p>
<div class="cmds">{c}</div>
{f}
{n}
</section>'''
S = [
 sec("state", "troubleshooting", "state", "checks everything in 2 seconds: drivers, gpu & VRAM, temps, RAM, drives, displays, audio, failed services, kernel errors & updates. run it before & after a change, then compare.",
     ["bench state --note \"before driver update\"", "bench state list", "bench state compare"],
     [("bench state --note \"for the page\"", "state"), ("bench state compare", "state-compare")],
     "compare only shows things that really changed, like a new driver, VRAM going way up or a service failing. small temp & load wiggles get ignored."),
 sec("logs", "troubleshooting", "logs", "grabs a game's logs from its last session into one folder: proton log, steam logs, the game's own log files & system errors from while i was playing. works for any steam game.",
     ["bench logs deadlock", "bench logs deadlock --list", "bench logs deadlock --session 2"],
     [("bench logs deadlock --list", "logs-list"), ("bench logs deadlock", "logs")],
     "it tells me when i forgot PROTON_LOG=1. the gone-logs warning shows up because cachyos only keeps about a day of system logs. raising the limit to 1 GB fixes that."),
 sec("cpu", "benchmark", "cpu", "30s idle, 5 min at full load on every core, then 1 min cooling down. records temps, clock speed, throttling & a score. made for before & after repasting.",
     ["bench cpu --note \"before repaste\" --room 22", "bench cpu list", "bench cpu compare"],
     [("bench cpu --duration 20 --note \"page demo\"", "cpu"), ("bench cpu compare", "cpu-compare")],
     "these are short 20s demo runs. differences smaller than ~1.5°C or 2% count as noise."),
 sec("gpu", "benchmark", "gpu", "runs glmark2 off-screen at 1920x1080 & records gpu temp, clock, power, fan, VRAM & whether it hit a thermal limit.",
     ["bench gpu --note \"baseline\"", "bench gpu list", "bench gpu compare"],
     [("bench gpu list", "gpu")]),
 sec("disk", "benchmark", "disk", "4 quick speed tests on a drive (big reads & writes, small random reads & writes) plus drive temp & SMART health.",
     ["bench disk", "bench disk --path /mnt/games", "bench disk compare"],
     [("bench disk list", "disk")], "SMART health needs sudo to read, so it says that for now."),
 sec("mem", "benchmark", "mem", "fills most of my free RAM, writes patterns & checks them back. catches unstable RAM fast. a real full test is memtest86+ at boot.",
     ["bench mem", "bench mem --seconds 600", "bench mem compare"],
     [("bench mem --seconds 15", "mem")]),
]
(D / "index.html").write_text((D / "tmpl.html").read_text().replace("__SECTIONS__", "\n".join(S)))
print("ok", len((D / "index.html").read_text()))
