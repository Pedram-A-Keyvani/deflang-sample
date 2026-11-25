"""deflang-lib's ENTRIES.md: each example gives the output the page shows.

In each section, the code blocks before a ```console block are one program: a block is
the file named right above it (`helpers.def`), or else main.def. The program runs with
deflang-lib's libraries, as `def-lang run` runs it.

Run with:  python3 -m unittest discover tests
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from interpreter import INTERPRETER, LIB, link_libraries  # noqa: E402

PAGE = LIB / "ENTRIES.md"
BLOCK = re.compile(r"```(console)?\n(.*?)```", re.S)


def examples():
    """(section, {file: text}, output) for each example of the page."""
    for section in re.split(r"^## ", PAGE.read_text(), flags=re.M)[1:]:
        title = section.splitlines()[0]
        files, at = {}, 0
        for m in BLOCK.finditer(section):
            if m.group(1):  # the output of the files before it
                if files:
                    yield title, files, m.group(2).strip()
                files = {}
            else:
                above = section[at:m.start()].strip().splitlines()
                name = re.search(r"`(\w[\w/.-]*\.def)`", above[-1]) if above else None
                files[name.group(1) if name else "main.def"] = m.group(2)
            at = m.end()


class TestEntriesPage(unittest.TestCase):
    def test_the_page_has_examples(self):
        self.assertGreaterEqual(len(list(examples())), 5)

    def test_each_example_gives_its_output(self):
        for title, files, output in examples():
            with self.subTest(title), tempfile.TemporaryDirectory() as folder:
                for name, text in files.items():
                    Path(folder, name).write_text(text)
                link_libraries(folder)
                run = subprocess.run([sys.executable, "-m", "deflang", "run", folder], capture_output=True, text=True,
                                     env={**os.environ, "PYTHONPATH": str(INTERPRETER.parent)}, timeout=60)
                said = re.sub(r"\x1b\[[0-9;]*m", "", run.stdout + run.stderr).strip()
                self.assertEqual(said, output, f"{title}: {sorted(files)}")


if __name__ == "__main__":
    unittest.main()
