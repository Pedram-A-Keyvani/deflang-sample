"""A modifier can add a real capability: hooks around a definition call."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import interpreter  # noqa: E402
from deflang import build  # noqa: E402
from deflang.exception import DefException  # noqa: E402
from deflang.execute import Execute  # noqa: E402


TRACE = """\
modifier traced
    hook call start in python
        traced = self["cycle"]["owner"]
        self["cycle"]["state"][traced]["n"] = 1
        self.say("start " + self["cycle"]["text"] + " by " + traced)
    hook call end in python
        traced = self["cycle"]["owner"]
        self.say("end " + as_text(self["cycle"]["state"][traced]["n"]))

traced def double A0
    A0 * 2
"""


class TestHooks(unittest.TestCase):
    def program(self, text: str):
        folder = Path(tempfile.mkdtemp())
        interpreter.link_libraries(folder, "core")
        file = folder / "main.def"
        file.write_text("use core\n" + text)
        return folder, file

    def engine(self, file: Path, output=None):
        execute = Execute(output=output if output is not None else lambda value: None)
        execute.program_dir = file.parent
        for line in file.read_text().splitlines():
            result = execute.run(line)
            if result is not None and output is not None:
                output(str(result))
        return execute

    def test_a_modifier_adds_start_and_end_hooks(self):
        _, file = self.program(TRACE + "\nsay double 21\n")
        said = []
        self.engine(file, said.append)
        self.assertEqual(said, ["start double 21 by traced", "end 1", "42"])

    def test_two_modifiers_keep_their_state_apart(self):
        _, file = self.program("""\
modifier timed
    hook call start in python
        timed = self["cycle"]["owner"]
        self["cycle"]["state"][timed]["started"] = "now"
    hook call end in python
        timed = self["cycle"]["owner"]
        self.say("timed saw " + self["cycle"]["state"][timed]["started"])

modifier counted
    hook call start in python
        counted = self["cycle"]["owner"]
        self["cycle"]["state"][counted]["started"] = "now"
    hook call end in python
        counted = self["cycle"]["owner"]
        self.say("counted saw " + self["cycle"]["state"][counted]["started"])

timed counted def work A0
    A0 * 2

say work 21
""")
        said = []
        self.engine(file, said.append)
        self.assertEqual(said, ["counted saw now", "timed saw now", "42"])

    def test_an_error_hook_sees_the_error(self):
        _, file = self.program("""\
modifier guarded
    hook call error in python
        guarded = self["cycle"]["owner"]
        E = self["cycle"]["error"]
        self.say(guarded + ": " + as_text(E))

guarded python fails
    raise DefException("boom")

fails
""")
        said = []
        with self.assertRaises(DefException):
            self.engine(file, said.append)
        self.assertEqual(said, ["guarded: boom"])

    def test_nested_calls_have_separate_state(self):
        _, file = self.program("""\
modifier nested
    hook call start in python
        nested = self["cycle"]["owner"]
        D = self["cycle"]["depth"]
        self["cycle"]["state"][nested]["depth"] = D
        self.say("enter " + self["cycle"]["text"] + " " + as_text(D))
    hook call end in python
        nested = self["cycle"]["owner"]
        self.say("leave " + as_text(self["cycle"]["state"][nested]["depth"]))

nested def twice A0
    A0 * 2

nested def four_times A0
    twice twice A0

say four_times 1
""")
        said = []
        self.engine(file, said.append)
        self.assertEqual(said, [
            "enter four_times 1 0", "enter twice A0 1", "leave 1",
            "enter twice twice A0 1", "leave 1", "leave 0", "4",
        ])

    def test_hooks_survive_a_compiled_build(self):
        _, file = self.program(TRACE + "\nsay double 21\n")
        artifact = build.compile_program(str(file))

        interpreted = []
        self.engine(file, interpreted.append)
        compiled = []
        execute = Execute(output=lambda value: compiled.append(str(value)))
        lines = build.load(artifact, execute)
        build.run_lines(execute, lines, output=lambda value: compiled.append(str(value)))
        self.assertEqual(compiled, interpreted)

    def test_a_flag_hook_acts_on_the_definition_using_it(self):
        _, file = self.program("""\
flag marked
    hook call start in python
        self.say("marked " + self["cycle"]["text"])

python[marked] answer
    return 42

say answer
""")
        said = []
        self.engine(file, said.append)
        self.assertEqual(said, ["marked answer", "42"])

    def test_a_statement_hook_acts_around_its_does(self):
        _, file = self.program("""\
statement shout
    words shout A0
    does in python
        self.say(as_text(A0).upper())
    hook call start in python
        self.say("shouting")

shout hello
""")
        said = []
        self.engine(file, said.append)
        self.assertEqual(said, ["shouting", "HELLO"])

    def test_a_duplicate_modifier_needs_replaces(self):
        folder, file = self.program(TRACE)
        other = folder / "other.def"
        other.write_text("modifier traced\n    does in def\n        set name to traced\n")
        execute = Execute()
        execute.program_dir = folder
        execute.run(f"use {file.stem}")
        with self.assertRaises(DefException) as raised:
            execute.run(f"use {other.stem}")
        self.assertIn("to replace it, write `replaces", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
