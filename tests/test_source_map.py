"""Bound def-lang arguments must not change the words shown in errors."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import interpreter  # noqa: E402
from deflang.exception import DefException  # noqa: E402
from deflang.execute import Execute  # noqa: E402


class TestSourceMap(unittest.TestCase):
    def setUp(self):
        self.execute = Execute()
        self.execute.program_dir = interpreter.LIBRARY_PROGRAM
        self.execute.run("use core")

    def test_an_argument_shows_the_value_written_at_the_call(self):
        self.run_lines("python[written] fail A0", "    return 1 / 0", "")
        self.run_lines("def wrap A0", "    fail A0", "")
        with self.assertRaises(DefException) as raised:
            self.execute.run("wrap 5")
        self.assertIn("in 'fail 5': ZeroDivisionError", str(raised.exception))

    def test_custom_argument_names_are_bound_too(self):
        self.execute.run("argument is X")
        self.run_lines("def twice X0", "    X0 * 2", "")
        self.assertEqual(self.execute.run("twice 4"), 8)

    def test_a_literal_that_looks_like_an_argument_is_kept(self):
        self.run_lines("python[written] fail A0", "    return 1 / 0", "")
        self.run_lines("def wrap A0", '    fail "A0"', "")
        with self.assertRaises(DefException) as raised:
            self.execute.run("wrap 5")
        self.assertIn('in \'fail "A0"\': ZeroDivisionError', str(raised.exception))

    def run_lines(self, *lines):
        for line in lines:
            self.execute.run(line)


if __name__ == "__main__":
    unittest.main()
