"""Golden parse corpus for the interpreter.

Every `.def` line of deflang-lib and deflang-sample is parsed with `use core`
loaded, and its tree (or error) is recorded. This is the reference for changes
to the parser: they must either produce exactly the same corpus or update the
baseline deliberately with `python3 tests/parse_corpus.py --write`.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import interpreter  # noqa: E402  sets up the interpreter and the offline libraries
from deflang.execute import Execute  # noqa: E402
from deflang.tree import Call, Literal, Name  # noqa: E402

SAMPLES = HERE.parent
LIB = interpreter.LIB
BASELINE = HERE / "perf" / "parse_baseline.json"


def file_label(path):
    """A stable, machine-independent name for a definition's file."""
    if path is None:
        return None
    path = Path(path)
    for root, label in ((LIB, "<lib>"), (SAMPLES, "<sample>")):
        try:
            return label + "/" + path.relative_to(root).as_posix()
        except ValueError:
            pass
    return path.name


def normalise(text):
    """Keep messages from embedding this machine's folders in the baseline."""
    text = str(text)
    for root, label in ((LIB, "<lib>"), (SAMPLES, "<sample>")):
        text = text.replace(str(root), label)
    return text


def serialise(node):
    """A compact tree: no regex objects, no compiled functions, no addresses."""
    if isinstance(node, Literal):
        return ["literal", repr(node.value)]
    if isinstance(node, Name):
        return ["name", node.name]
    if isinstance(node, Call):
        return ["call", normalise(node.definition.source), file_label(node.definition.file),
                node.text, node.lost, [serialise(a) if not isinstance(a, str) else ["words", a]
                                       for a in node.arguments]]
    raise TypeError(f"unknown parse node: {node!r}")


def source_files():
    files = []
    for root in (LIB, SAMPLES):
        for path in sorted(root.rglob("*.def")):
            parts = set(path.parts)
            if {"libraries", "__pycache__", ".git"} & parts or path.name.startswith("."):
                continue  # installed copies and generated folders, not source
            files.append(path)
    return files


def parse_corpus():
    engine = Execute()
    engine.program_dir = interpreter.LIBRARY_PROGRAM
    engine.run("use core")
    corpus = []
    for path in source_files():
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            entry = {"file": file_label(path), "line": number, "text": line}
            try:
                entry["tree"] = serialise(engine._parser.parse(line))
            except Exception as error:  # a bad line is part of the language's behaviour too
                entry["error"] = [type(error).__name__, normalise(error)]
            corpus.append(entry)
    return corpus


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="replace the baseline with today's parse results")
    arguments = parser.parse_args()
    corpus = parse_corpus()
    if arguments.write:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(corpus, separators=(",", ":"), ensure_ascii=False) + "\n")
        print(f"wrote {len(corpus)} lines to {BASELINE}")
        return 0
    expected = json.loads(BASELINE.read_text())
    if corpus == expected:
        print(f"{len(corpus)} lines match the baseline")
        return 0
    differences = [f"{a['file']}:{a['line']}" for a, b in zip(corpus, expected) if a != b]
    print(f"{len(differences)} of {len(corpus)} lines differ: {', '.join(differences[:10])}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
