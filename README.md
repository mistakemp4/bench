# bench

my pc testing & troubleshooting tool. `oracle` is the same thing with a cooler name.

## Table of Contents

- [Installing](#installing)
- [Checking Everything](#checking-everything)
- [Game Logs](#game-logs)
- [Recording While I Play](#recording-while-i-play)
- [Benchmarks](#benchmarks)
- [Comparing Runs](#comparing-runs)
- [Where Stuff Saves](#where-stuff-saves)
- [Rebuilding the Page](#rebuilding-the-page)

## Installing

```bash
$ ln -s ~/src/bench/bench.py ~/.local/bin/bench
$ ln -s ~/src/bench/bench.py ~/.local/bin/oracle
$ sudo pacman -S stress-ng glmark2 fio
```

## Checking Everything

```bash
$ bench state --note "before driver update"
$ bench state compare
```

## Game Logs

```bash
$ bench logs deadlock
$ bench logs deadlock --list
$ bench logs deadlock --session 2
```

part of the name works (`va11`, `finals`, `p5r`).

for a proton log next time:

```bash
$ bench proton-log deadlock
$ bench proton-log
$ bench proton-log deadlock --off
```

it turns on for the next launch only & turns off when i close the game. needs bench-watch running.

## Recording While I Play

```bash
$ systemctl --user enable --now ~/src/bench/systemd/bench-watch.service
```

it saves vram, temps & ram every 2 seconds while a steam game is open. `bench logs` shows them for that session. recordings & saved proton logs get deleted after 30 days.

## Benchmarks

```bash
$ bench cpu --note "before repaste" --room 22
$ bench gpu
$ bench disk
$ bench mem
```

close heavy stuff first. cpu won't start if something is already using it.

## Comparing Runs

every test has `list` & `compare`. compare uses the last two runs unless i give it two ids.

```bash
$ bench cpu list
$ bench cpu compare
```

## Where Stuff Saves

- tests: `~/logs/bench/<test>/`
- game logs: `~/logs/games/<game>/`
- recordings: `~/logs/sensors/`
- proton logs: `~/logs/proton/`
- state reports: `~/logs/state/`

## Rebuilding the Page

```bash
$ python3 page/build.py page page/out
```
