"""Compiled builds use the same language and evaluator as the interpreter."""
import contextlib
import io
import pickle
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import interpreter  # noqa: E402
from deflang import build, __main__ as command  # noqa: E402
from deflang.execute import Execute  # noqa: E402


class TestCompiled(unittest.TestCase):
    def program(self, text: str):
        folder = Path(tempfile.mkdtemp())
        interpreter.link_libraries(folder, "core")
        file = folder / "main.def"
        file.write_text(text)
        return folder, file

    def test_a_build_runs_the_recorded_lines(self):
        folder, file = self.program("use core\ndef double A0\n    A0 * 2\n\nsay double 21\n")
        artifact = build.compile_program(str(file))
        self.assertTrue(build.fresh(artifact))
        data = pickle.loads(artifact.read_bytes())
        self.assertEqual([kind for kind, _ in data["lines"]], ["define", "define", "run"])

        said = []
        execute = Execute(output=said.append)
        lines = build.load(artifact, execute)
        build.run_lines(execute, lines, output=said.append)
        self.assertEqual(said, ["42"])
        self.assertEqual(execute.run("double 4"), 8)

    def test_a_changed_source_makes_the_build_stale(self):
        folder, file = self.program("use core\n\nsay 1\n")
        artifact = build.compile_program(str(file))
        self.assertTrue(build.fresh(artifact))
        file.write_text("use core\n\nsay 2\n")
        self.assertFalse(build.fresh(artifact))

    def test_library_hooks_survive_the_artifact(self):
        folder, file = self.program(
            "use core\n"
            "python[written] source of A0\n"
            "    return A0\n"
            "python[regex] (A0: \\d+) percent\n"
            "    return number(A0) / 100\n"
        )
        artifact = build.compile_program(str(file))
        execute = Execute()
        build.run_lines(execute, build.load(artifact, execute))
        self.assertEqual(execute.run("source of hello"), "hello")
        self.assertEqual(execute.run("50 percent"), 0.5)

    def test_compile_does_not_evaluate_the_program(self):
        folder, file = self.program('use core\n\nsay "should not print at build"\n')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            build.compile_program(str(file))
        self.assertEqual(out.getvalue(), "")

    def test_auto_mode_falls_back_to_the_sources_when_a_build_is_stale(self):
        folder, file = self.program("use core\n\nsay 1\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            command.main(["compile", str(file)])
            command.main(["run", str(file)])
            file.write_text("use core\n\nsay 2\n")
            out.seek(0)
            out.truncate(0)
            command.main(["run", str(file)])
        self.assertIn("2", out.getvalue())
        self.assertNotIn("1", out.getvalue())

    def test_the_cli_runs_a_fresh_build(self):
        folder, file = self.program("use core\ndef double A0\n    A0 * 2\n\nsay double 21\n")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(command.main(["compile", str(file)]), 0)
            self.assertIsNone(command.main(["run", "--compiled", str(file)]))
        self.assertIn("42", out.getvalue())


if __name__ == "__main__":
    unittest.main()
