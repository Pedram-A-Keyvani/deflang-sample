"""Entries can add real capabilities: hooks around the kernel's cycles."""
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

    def test_a_declared_modifier_does_nothing_until_it_is_used(self):
        _, file = self.program("""\
modifier watched
    hook line start in python
        self.say("a line ran")
    hook file start in python
        self.say("a file was read")

def double A0
    A0 * 2

say double 21
""")
        said = []
        self.engine(file, said.append)
        self.assertEqual(said, ["42"])

    def test_a_file_hook_wraps_reading_a_used_file(self):
        _, file = self.program("""\
modifier watched
    hook file start in python
        watched = self["cycle"]["owner"]
        self["cycle"]["state"][watched]["name"] = as_text(self["cycle"]["text"])
        self.say("open " + self["cycle"]["state"][watched]["name"])
    hook file end in python
        watched = self["cycle"]["owner"]
        self.say("closed " + as_text(self["cycle"]["file"]))

watched use part
say part_answer
""")
        file.parent.joinpath("part.def").write_text("python part_answer\n    return 42\n")
        said = []
        self.engine(file, said.append)
        self.assertEqual(said[0], "open part")
        self.assertTrue(said[1].startswith("closed "))
        self.assertIn("part.def", said[1])
        self.assertEqual(said[2], "42")

    def test_a_define_hook_sees_the_definition_it_makes(self):
        _, file = self.program("""\
modifier watched
    hook define start in python
        self.say("define " + self["cycle"]["pattern"])
    hook define end in python
        D = self["cycle"]["definition"]
        self.say("made " + D.source)

watched def double A0
    A0 * 2

say double 21
""")
        said = []
        self.engine(file, said.append)
        self.assertEqual(said, ["define double A0", "made double A0", "42"])

    def test_a_line_hook_wraps_a_running_line(self):
        _, file = self.program("""\
modifier watched
    hook line start in python
        watched = self["cycle"]["owner"]
        self["cycle"]["state"][watched]["text"] = self["cycle"]["text"]
        self.say("line " + self["cycle"]["kind"] + " " + self["cycle"]["text"])
    hook line end in python
        watched = self["cycle"]["owner"]
        self.say("read " + self["cycle"]["state"][watched]["text"])

watched def double A0
    A0 * 2

watched say double 21
""")
        said = []
        self.engine(file, said.append)
        self.assertEqual(said, ["line expression say double 21", "line expression A0 * 2",
                                "read A0 * 2", "42", "read say double 21"])

    def test_a_body_hook_wraps_the_body_of_a_def(self):
        _, file = self.program("""\
modifier watched
    hook body start in python
        self.say("body " + self["cycle"]["text"])
    hook body end in python
        self.say("done " + self["cycle"]["definition"].source)

watched def double A0
    A0 * 2

say double 21
""")
        said = []
        self.engine(file, said.append)
        self.assertEqual(said, ["body double 21", "done double A0", "42"])

    def test_a_scope_hook_wraps_own_variables(self):
        _, file = self.program("""\
modifier watched
    hook scope start in python
        watched = self["cycle"]["owner"]
        self["cycle"]["state"][watched]["n"] = 1
        self.say("scope start")
    hook scope end in python
        watched = self["cycle"]["owner"]
        self.say("scope end " + as_text(self["cycle"]["state"][watched]["n"]))

watched def double A0
    A0 * 2

say double 21
""")
        said = []
        self.engine(file, said.append)
        self.assertEqual(said, ["scope start", "scope end 1", "42"])

    def test_body_and_scope_hooks_survive_a_compiled_build(self):
        _, file = self.program("""\
modifier watched
    hook body start in python
        self.say("body " + self["cycle"]["text"])
    hook scope start in python
        self.say("scope")

watched def double A0
    A0 * 2

say double 21
""")
        artifact = build.compile_program(str(file))
        interpreted = []
        self.engine(file, interpreted.append)
        compiled = []
        execute = Execute(output=lambda value: compiled.append(str(value)))
        lines = build.load(artifact, execute)
        build.run_lines(execute, lines, output=lambda value: compiled.append(str(value)))
        self.assertEqual(compiled, interpreted)

    def test_line_hooks_survive_a_compiled_build(self):
        _, file = self.program("""\
modifier watched
    hook line start in python
        self.say("line " + self["cycle"]["text"])

watched def double A0
    A0 * 2

watched say double 21
""")
        artifact = build.compile_program(str(file))
        interpreted = []
        self.engine(file, interpreted.append)
        compiled = []
        execute = Execute(output=lambda value: compiled.append(str(value)))
        lines = build.load(artifact, execute)
        build.run_lines(execute, lines, output=lambda value: compiled.append(str(value)))
        self.assertEqual(compiled, interpreted)

    def test_shared_uses_a_define_hook_instead_of_a_reserved_set_word(self):
        _, file = self.program("shared visits is 0\nsay visits\n")
        said = []
        execute = self.engine(file, said.append)
        self.assertEqual(said, ["0"])
        self.assertEqual(execute["files"][None]["names"], {"visits": (None, "visits")})
        _, wrong = self.program("shared def x\n    1\n")
        with self.assertRaisesRegex(DefException, "shared names a variable, not a definition"):
            self.engine(wrong)

    def test_internal_uses_a_define_hook_instead_of_a_reserved_set_word(self):
        folder, file = self.program("use part\n")
        part = folder / "part.def"
        part.write_text("internal def A0 halved\n    A0 / 2\n")
        execute = self.engine(file)
        found = [d for d in execute.definitions if d.source == "A0 halved" and d.file == part]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].visibility, "file")
        self.assertFalse(found[0].seen_by(None))
        with self.assertRaisesRegex(DefException, "unknown name '8 halved'"):
            execute.run("8 halved")
        _, wrong = self.program("internal visits is 4\n")
        with self.assertRaisesRegex(DefException, "internal marks a definition, not a name"):
            self.engine(wrong)

    def test_shared_and_internal_hooks_survive_a_compiled_build(self):
        _, file = self.program("""\
shared visits is 0
internal def A0 halved
    A0 / 2

say 8 halved
say visits
""")
        artifact = build.compile_program(str(file))
        interpreted = []
        self.engine(file, interpreted.append)
        compiled = []
        execute = Execute(output=lambda value: compiled.append(str(value)))
        lines = build.load(artifact, execute)
        build.run_lines(execute, lines, output=lambda value: compiled.append(str(value)))
        self.assertEqual(compiled, interpreted)

    def test_replacing_an_entry_replaces_its_hooks(self):
        _, file = self.program("""\
use first
use second

timed say 1
""")
        file.parent.joinpath("first.def").write_text("""\
modifier timed
    hook line start in python
        self.say("old")
""")
        file.parent.joinpath("second.def").write_text("""\
modifier timed
    replaces first
    hook line start in python
        self.say("new")
""")
        said = []
        self.engine(file, said.append)
        self.assertEqual(said, ["new", "1"])

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
