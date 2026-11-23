"""Runs the `Example:` of every def and checks its `→` result, so the examples in the
comments (shown in the editor's hover) stay true.

    // Example: 22.857 rounded to 1 place
    //          → 22.9

What a result can say:
    VALUE                      the value the example gives, like 22.9, "HI", [1, 2], True
    EXPR is VALUE              afterwards, EXPR (a variable or a phrase) is VALUE
    prints A, B, C             what `say` printed; "…" skips the middle
    yes / no                   the answer of a question
    error: MESSAGE             the def-lang error it raises
    GET /path answers BODY     what the web server answers; BODY is JSON, text, "the file PATH",
                               or "a page containing TEXT"
    asks ...; typing A and B makes NAME VALUE      `give`, with A and B typed in
    a whole number from A to B / one of them       random results
After the result:
    , when NAME was VALUE      NAME is VALUE before the example ("it" is the result's name)
    , when FILE holds TEXT     the program folder has FILE with TEXT in it
    , after LINE               LINE runs before the example
    , and EXPR is VALUE        one more check
    , so ... / , like ...      notes, not checked
    (not checked)              the example isn't run (time, dates, waiting, server setup)
And at the end of the example: `, for GET /path?a=1` runs it during that request.

Run with:  python3 -m unittest discover tests
"""
import ast
import json
import re
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import interpreter  # noqa: E402  finds ../deflang and ../deflang-lib
from interpreter import LIB, LIBRARY_PROGRAM, SAMPLES  # noqa: E402

from deflang.exception import DefException  # noqa: E402
from deflang.execute import Execute  # noqa: E402
from deflang.tree import Call  # noqa: E402

def where(path):
    return path.relative_to(LIB) if path.is_relative_to(LIB) else path.relative_to(SAMPLES)


CLAUSE = re.compile(r", (?=(?:when|after|and|so|like) )")


def examples():
    """(file, line number, example, result) for every Example: in the library and the packages."""
    files = sorted(LIB.rglob("*.def")) + sorted(SAMPLES.glob("*/def/*.def"))
    for path in files:
        lines = path.read_text().split("\n")
        for number, line in enumerate(lines):
            m = re.match(r"\s*//\s*Example:\s*(.+)$", line)
            if not m:
                continue
            result = re.match(r"\s*//\s*→\s*(.+)$", lines[number + 1] if number + 1 < len(lines) else "")
            if not result:
                raise AssertionError(f"{path.name}:{number + 1}: an Example: needs a → line below it")
            yield path, number + 1, m.group(1).strip(), result.group(1).strip()


def def_below(path, number):
    """The pattern of the definition line right below the example on line `number`, or
    None: `python[written] A0 is A1` gives `A0 is A1`."""
    for line in path.read_text().split("\n")[number:]:
        m = re.match(r"(?:internal\s+)*(def|python|html|css|javascript)(\[[^\]]*\])?\s+(\S.*)$", line)
        if m:
            return m.group(3).strip()
        if line.strip() and not line.lstrip().startswith("//"):
            return None
    return None


def value(text):
    """A def-lang value written in a result: 22.9, "HI", [1, 2], True."""
    return ast.literal_eval(text.strip())


def engine_for(path, said):
    """An interpreter with the defs the example's file sees: for a library's file, the
    core library and the file itself; for a package, its own imports."""
    e = Execute(output=lambda v: said.append(str(v)))
    package = path.parent.parent if (path.parent.parent / "main.def").is_file() else None
    if package:
        e.program_dir = package
        for line in (package / "main.def").read_text().splitlines():
            if line.startswith("use "):
                e.run(line)
    else:
        # a library's file: the core library, and the file itself (`use web/server`, `use language/html`)
        e.program_dir = LIBRARY_PROGRAM
        e.run("use core")
        library = path.parent.name
        e.run(f"use {library}" if path.stem == "main" else f"use {library}/{path.stem}")
    return e


def request(e, url):
    query = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&")) if "?" in url else {}
    e["store"]["web"]["request"] = {"path": url.split("?")[0], "query": query, "page": False}


def get(e, url):
    """Start the example's web server on a free port, GET url, stop it."""
    e.run("server on port 0")
    e["store"]["web"]["settings_file"] = None  # not the package's settings.toml: its port may be in use
    thread = threading.Thread(target=e.run, args=("start the server",), daemon=True)
    thread.start()
    for _ in range(200):
        if "server" in e["store"]["web"]:
            break
        threading.Event().wait(0.01)
    try:
        port = e["store"]["web"]["server"].server_address[1]
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{url}") as response:
                return response.read()
        except urllib.error.HTTPError as error:
            return error.read()
    finally:
        e["store"]["web"]["server"].shutdown()
        thread.join(5)
        del e["store"]["web"]["server"]


class TestExamples(unittest.TestCase):
    def test_every_example(self):
        found = list(examples())
        self.assertGreater(len(found), 70)
        for path, number, given, result in found:
            with self.subTest(f"{where(path)}:{number}: {given}"):
                self.check(path, given, result)

    def test_each_example_is_read_with_its_own_def(self):
        """A def that matches its whole example line should be the one that wraps it
        (see `wraps` in core/tree.py: brackets, sentences, word lists, then def order)."""
        for path, number, given, result in examples():
            if result.endswith("(not checked)"):
                continue
            definition = def_below(path, number)
            if definition is None:
                continue
            given = re.sub(r", for GET \S+$", "", given)
            with self.subTest(f"{where(path)}:{number}: {given}"):
                e = engine_for(path, [])
                mine = [d for d in e.definitions if d.file == path.resolve() and d.source == definition]
                if not mine or not mine[0].matches(given):
                    continue  # the example uses the def inside a longer line, or another way
                tree = e._parser.parse(given)
                wrapper = tree.definition if isinstance(tree, Call) else None
                self.assertTrue(wrapper is mine[0], f"`{given}` is read as `{wrapper.source if wrapper else given}`, "
                              f"not `{definition}`: write the example (or the def) so its fixed words surround the rest, "
                              f"or make it an `as written` sentence that starts the line")

    def check(self, path, given, result):
        if result.endswith("(not checked)"):
            return
        said = []
        e = engine_for(path, said)
        # the example's lines are like a file of their own: they mean the shared variables
        for file, place in list(e["files"].items()):
            for name, key in list(place["names"].items()):
                if key == (file, name):
                    e["files"][None]["names"][name] = key
        outcome, *clauses = CLAUSE.split(result)

        checks = []
        name_in_result = outcome.split(" is ")[0] if " is " in outcome else None
        for clause in clauses:
            word, rest = clause.split(" ", 1)
            if word == "when" and " holds " in rest:
                file, text = rest.split(" holds ", 1)
                folder = Path(tempfile.mkdtemp())
                (folder / file).parent.mkdir(parents=True, exist_ok=True)
                (folder / file).write_text(text)
                e.program_dir = folder
            elif word == "when":
                name, text = rest.split(" was ", 1)
                e.run(f"{name_in_result if name == 'it' else name} is {text}")
            elif word == "after":
                e.run(rest)
            elif word == "and":
                checks.append(rest)

        m = re.match(r"(.+), for GET (\S+)$", given)
        if m:
            given = m.group(1)
            request(e, m.group(2))

        typed = re.match(r"asks .*; typing (.+) makes (\S+) (.+)$", outcome)
        inputs = typed.group(1).split(" and ") if typed else []
        said.clear()
        error = None
        try:
            with mock.patch("builtins.input", side_effect=inputs):
                answer = e.run(given)
        except DefException as problem:
            error = " ".join(map(str, problem.args))

        if outcome.startswith("error: "):
            self.assertEqual(error, outcome[len("error: "):])
            return
        self.assertIsNone(error, f"the example raised: {error}")

        if outcome.startswith("prints "):
            printed = ", ".join(said)
            expected = outcome[len("prints "):]
            if "…" in expected:
                start, end = (part.strip(" ,") for part in expected.split("…"))
                self.assertTrue(printed.startswith(start) and printed.endswith(end), printed)
            else:
                self.assertEqual(printed, expected)
        elif outcome in ("yes", "no"):
            self.assertEqual(e["answer"], outcome == "yes")
        elif outcome.startswith("GET "):
            url, body = outcome[4:].split(" answers ", 1)
            data = get(e, url)
            if body.startswith("{"):
                self.assertEqual(json.loads(data), json.loads(body))
            elif body.startswith("a page containing "):
                self.assertIn(body[len("a page containing "):], data.decode())
            elif body.startswith("the file "):
                self.assertEqual(data, (e.program_dir / body[len("the file "):]).read_bytes())
            else:
                self.assertEqual(data.decode(), body)
        elif typed:
            self.assertEqual(e.run(typed.group(2)), value(typed.group(3)))
        elif outcome.startswith("a whole number from "):
            low, high = map(int, re.findall(r"-?\d+", outcome)[:2])
            self.assertIn(answer, range(low, high + 1))
        elif outcome.startswith("one of them"):
            self.assertIn(answer, value(re.search(r"\[.*\]", given).group(0)))
        elif " is " in outcome:
            checks.insert(0, outcome)
        else:
            self.assertEqual(answer, value(outcome))

        for check in checks:
            expression, expected = check.split(" is ", 1)
            self.assertEqual(e.run(expression), value(expected), check)


if __name__ == "__main__":
    unittest.main()
