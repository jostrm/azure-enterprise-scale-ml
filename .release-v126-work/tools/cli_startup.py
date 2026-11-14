#!/usr/bin/env python3
"""Measure CLI start-up: wall-clock median of N runs and the -X importtime total. Usage: cli_startup.py <venv python> [runs]"""
import os, statistics, subprocess, sys, time
python = sys.argv[1]; runs = int(sys.argv[2]) if len(sys.argv) > 2 else 30
env = {"PATH": os.path.dirname(python) + ":/usr/bin:/bin", "HOME": "/root", "LANG": "C.UTF-8"}
def wall(args):
    samples = []
    for _ in range(runs):
        start = time.perf_counter(); subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env); samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples), min(samples)
def importtime(args):
    out = subprocess.run([python, "-X", "importtime", *args], capture_output=True, text=True, env=env).stderr
    rows = [line for line in out.splitlines() if line.startswith("import time:") and "|" in line and "cumulative" not in line]
    total = sum(int(line.split("|")[0].split(":")[1]) for line in rows)
    return total / 1000, len(rows)
print("interpreter only        median/min ms: %.1f / %.1f" % wall([python, "-c", "pass"]))
for label, args in (("azurefactory --help", ["-m", "azurefactory", "--help"]), ("azurefactory esaf --help", ["-m", "azurefactory", "esaf", "--help"]), ("from azurefactory import esaf", ["-c", "from azurefactory import esaf"])):
    median, low = wall([python, *args]); total, modules = importtime(args)
    print(f"{label:30s} median/min ms: {median:.1f} / {low:.1f}   importtime total ms: {total:.1f}   modules imported: {modules}")
