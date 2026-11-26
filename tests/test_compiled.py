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

    def interpreted(self, file: Path):
        said = []
        execute = Execute(output=said.append)
        execute.program_dir = file.parent
        for line in file.read_text().splitlines():
            result = execute.run(line)
            if result is not None:
                said.append(str(result))
        return said

    def compiled(self, artifact: Path):
        said = []
        execute = Execute(output=said.append)
        lines = build.load(artifact, execute)
        build.run_lines(execute, lines, output=lambda value: said.append(str(value)))
        return said

    def test_a_build_runs_the_recorded_lines(self):
        folder, file = self.program("use core\ndef double A0\n    A0 * 2\n\nsay double 21\n")
        artifact = build.compile_program(str(file))
        self.assertTrue(build.fresh(artifact))
        data = pickle.loads(artifact.read_bytes())
        self.assertEqual([kind for kind, _, file, _ in data["lines"] if file is None],
                         ["define", "define", "run"])

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

    def test_compile_does_not_run_runtime_statements(self):
        folder, file = self.program("use core\n\nerror stop now\n")
        artifact = build.compile_program(str(file))  # must not stop the build
        data = pickle.loads(artifact.read_bytes())
        self.assertEqual(data["lines"][-1][:2], ("run", "error stop now"))

    def test_reading_statements_change_how_the_build_is_read(self):
        text = ("use core\n"
                "comment is #\n"
                "argument is X\n"
                "indent 2\n"
                "# a comment the build must skip\n"
                "def twice X0\n"
                "  X0 + X0\n"
                "say twice 21\n")
        folder, file = self.program(text)
        expected = self.interpreted(file)
        self.assertEqual(expected, ["42"])
        self.assertEqual(self.compiled(build.compile_program(str(file))), expected)

    def test_runtime_statements_run_when_the_build_runs(self):
        folder, file = self.program("use core\n\n`2 * 3`\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            artifact = build.compile_program(str(file))
        self.assertEqual(out.getvalue(), "")  # no echo at build time
        self.assertEqual(self.compiled(artifact), ["2 * 3", "6"])

    def test_runtime_lines_in_used_files_are_replayed_in_their_file(self):
        folder, file = self.program('use helpers\n\nsay "main"\n')
        (folder / "helpers.def").write_text('use core\n\nsay "from helper"\n')
        expected = self.interpreted(file)
        self.assertEqual(expected, ["from helper", "main"])

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            artifact = build.compile_program(str(file))
        self.assertEqual(out.getvalue(), "")  # nothing prints at build time
        self.assertEqual(self.compiled(artifact), expected)

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
