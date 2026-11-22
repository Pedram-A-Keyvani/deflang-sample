"""What the tests run on, all from the repositories next to this one:

- the interpreter: ../deflang, or the folder in $DEFLANG;
- the libraries: ../deflang-lib, or the folder in $DEFLANG_LIB.

The samples install their libraries globally from GitHub. So the tests needn't, a
global folder of their own points to ../deflang-lib: the tests always run on the
libraries next to them, without the network."""
import atexit
import os
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTERPRETER = Path(os.environ.get("DEFLANG", HERE.parent.parent / "deflang")).resolve()
if not (INTERPRETER / "execute.py").is_file():
    raise SystemExit(f"the def-lang interpreter isn't at {INTERPRETER}: put the deflang project next to this one, or set DEFLANG")
sys.path.insert(0, str(INTERPRETER.parent))

LIB = Path(os.environ.get("DEFLANG_LIB", HERE.parent.parent / "deflang-lib")).resolve()
if not (LIB / "core" / "library.toml").is_file():
    raise SystemExit(f"the def-lang libraries aren't at {LIB}: put deflang-lib next to this one, or set DEFLANG_LIB")

# every library of deflang-lib: name -> (folder, version)
LIBRARIES = {}
for toml in sorted(LIB.rglob("library.toml")):
    info = tomllib.loads(toml.read_text())
    LIBRARIES[info["name"]] = (toml.parent, str(info.get("version", "0")))

GLOBAL = Path(tempfile.mkdtemp(prefix="deflang-global-"))
for name, (folder, version) in LIBRARIES.items():
    (GLOBAL / name).mkdir()
    (GLOBAL / name / version).symlink_to(folder, target_is_directory=True)
os.environ["DEFLANG_GLOBAL"] = str(GLOBAL)
atexit.register(shutil.rmtree, GLOBAL, ignore_errors=True)

SAMPLES = HERE.parent


def library(name: str) -> Path:
    """The folder of a library of deflang-lib: core, html (language/html), web, ..."""
    return LIBRARIES[name][0]


def link_libraries(program, *names):
    """Give a test program deflang-lib's libraries, used where they are."""
    names = names or ("core", "web", "html", "javascript", "css")
    Path(program, "libraries.toml").write_text("".join(f'{n} = {{ from = "{library(n)}", link = true }}\n' for n in names))


# a program that has every library of deflang-lib: for tests that just need the words
LIBRARY_PROGRAM = Path(tempfile.mkdtemp(prefix="deflang-library-program-"))
link_libraries(LIBRARY_PROGRAM)
atexit.register(shutil.rmtree, LIBRARY_PROGRAM, ignore_errors=True)


# a sample's libraries from git that live in the project (not global) are copies in its
# libraries/, made by `def-lang install`: the tests make them from ../deflang-lib, each run
for toml in sorted(SAMPLES.glob("*/libraries.toml")):
    for name, entry in tomllib.loads(toml.read_text()).items():
        if "://" in entry.get("from", "") and not entry.get("global") and name in LIBRARIES:
            copies = toml.parent / "libraries"
            copies.mkdir(exist_ok=True)
            if not (copies / ".gitignore").exists():
                (copies / ".gitignore").write_text("# copies made by `def-lang install`: run it to make them again\n*\n")
            shutil.rmtree(copies / name, ignore_errors=True)
            shutil.copytree(library(name), copies / name, ignore=shutil.ignore_patterns(".git", "__pycache__"))
