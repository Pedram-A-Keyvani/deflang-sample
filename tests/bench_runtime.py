"""Reproducible runtime benchmark for the interpreter.

Run from the sample folder:  python3 tests/bench_runtime.py
Optional: --rounds 300 --iterations 2000 --profile --json
"""
import argparse
import cProfile
import io
import json
import pstats
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import interpreter  # noqa: E402  sets up the interpreter and the offline libraries
from deflang.execute import Execute  # noqa: E402

LINES = [
    "2 + 3",
    "7 / 2",
    "one + two",
    'length of "hello"',
    "sum of [1, 2, 3]",
    "a is 2 + 3",
    '"a" joined with "b"',
]


def engine():
    """An interpreter with core loaded, as in DefTest.setUp()."""
    execute = Execute()
    execute.program_dir = interpreter.LIBRARY_PROGRAM
    execute.run("use core")
    return execute


def prime(execute, lines=LINES):
    """Keep only lines that run successfully, and warm the interpreter's caches."""
    usable = []
    for line in lines:
        try:
            execute.run(line)
            usable.append(line)
        except Exception:
            pass
    for line in usable:
        execute.run(line)
    return usable


def measure_lines(execute, rounds, lines=LINES):
    """Microseconds per line over `rounds` passes of the expression mix."""
    start = time.perf_counter()
    for _ in range(rounds):
        for line in lines:
            execute.run(line)
    return (time.perf_counter() - start) / (rounds * len(lines)) * 1e6


def measure_loops(execute, iterations):
    """Seconds for loops whose body is parsed on every iteration."""
    times = {}
    for name, line in (("constant", "2 + 3"), ("text_join", '"a" joined with "b"')):
        start = time.perf_counter()
        execute.run(f"repeat {iterations} times : {line}")
        times[name] = time.perf_counter() - start
    return times


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=300)
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--json", action="store_true", help="print results as JSON")
    arguments = parser.parse_args()

    execute = engine()
    lines = prime(execute)
    if arguments.profile:
        profiler = cProfile.Profile()
        profiler.enable()
        measure_lines(execute, 100, lines)
        profiler.disable()
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(20)
        print(stream.getvalue())

    results = {
        "definitions": len(execute.definitions),
        "lines": len(lines),
        "per_line_us": round(measure_lines(execute, arguments.rounds, lines), 1),
        "loop_seconds": {k: round(v, 3) for k, v in
                         measure_loops(execute, arguments.iterations).items()},
    }
    print(json.dumps(results, indent=2) if arguments.json else
          f"{results['definitions']} definitions, {results['lines']} lines: "
          f"{results['per_line_us']} us/line, loops {results['loop_seconds']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
