#!/usr/bin/env python3
"""Generate booklet HTML for all 20 years."""

import subprocess, sys

YEARS = list(range(2007, 2027))

for year in YEARS:
    print(f"--- {year} ---", flush=True)
    result = subprocess.run(
        [sys.executable, "prototype_gen.py"],
        env={**__import__("os").environ, "SAMSTONES_YEAR": str(year)},
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"  ERROR on {year}")
