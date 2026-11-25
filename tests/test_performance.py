"""Guardrails for interpreter runtime work: parser behaviour and speed budgets."""
import json
import unittest

from bench_runtime import engine, measure_lines, measure_loops, prime
from parse_corpus import BASELINE, parse_corpus


class TestParseCorpus(unittest.TestCase):
    def test_every_def_line_parses_as_it_did(self):
        expected = json.loads(BASELINE.read_text())
        actual = parse_corpus()
        self.assertEqual(len(actual), len(expected), "the corpus of .def files changed")
        for want, got in zip(expected, actual):
            self.assertEqual(got, want, f"{want['file']}:{want['line']} parses differently")


class TestRuntimeBudget(unittest.TestCase):
    def test_simple_program_stays_fast(self):
        execute = engine()
        lines = prime(execute)
        per_line = measure_lines(execute, rounds=100, lines=lines)
        self.assertLess(per_line, 1500, f"parse/evaluate is {per_line:.0f} us/line")

        loops = measure_loops(execute, iterations=500)
        self.assertLess(loops["constant"], 1.0, f"constant loop: {loops['constant']:.2f}s")
        self.assertLess(loops["text_join"], 2.0, f"text-join loop: {loops['text_join']:.2f}s")


if __name__ == "__main__":
    unittest.main()
