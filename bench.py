#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import cpu
import hw
import logs
import state
import watch

def main():
    prog = Path(sys.argv[0]).name
    ap = argparse.ArgumentParser(prog=prog, description="benchmarks + troubleshooting")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for mod in (cpu, hw, logs, state, watch):
        mod.add_parser(sub)
    args = ap.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
