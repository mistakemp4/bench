# bench

my pc testing & troubleshooting tool. `oracle` is the same thing with a cooler name.

## Table of Contents

- [Installing](#installing)
- [Checking Everything](#checking-everything)
- [Game Logs](#game-logs)
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

part of the name works (`va11`, `finals`, `p5r`). for a proton log, set the game's launch options to `PROTON_LOG=1 %command%` first & take it out after.

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
- state reports: `~/logs/state/`

## Rebuilding the Page

```bash
$ python3 page/build.py page page/out
```
