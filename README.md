# deflang-sample

Sample programs in [def-lang](https://github.com/Pedram-A-Keyvani/deflang), using the
libraries of [deflang-lib](https://github.com/Pedram-A-Keyvani/deflang-lib), and the
tests of both.

| Sample | Shows |
|---|---|
| `hello-world/` | the smallest program: `say "Hello world!"` |
| `black-jack/` | asking for numbers, questions, `one of … is`, `their sum` |
| `bmi/` | asking for values, a program in two files (`use def/bmi`), questions inside a def |
| `times-table/` | a loop (`for each … in …`), and joined text with math inside |
| `website/` | a single page application of components: each one file with its view (HTML), style (CSS), script (JavaScript) and data; every address in `def/routes.def`; shared variables; `settings.toml` |

## Running a sample

Each sample is a program: a folder with a `main.def` and a `libraries.toml`. Its
libraries are installed globally, from GitHub, once:

```console
$ cd website
$ def-lang install
$ def-lang run .
```

`def-lang install` reads `libraries.toml`:

```toml
core = { from = "https://github.com/Pedram-A-Keyvani/deflang-lib.git#core", global = "0.1.0" }
```

The website runs until Ctrl+C, at http://localhost:8000; `website/settings.toml`
changes how it runs, even while it runs.

## The tests

They test the interpreter and the libraries, with the repositories next to this one:

```
deflang/          the interpreter (or $DEFLANG)
deflang-lib/      the libraries (or $DEFLANG_LIB)
deflang-sample/   this one
```

```console
$ python3 -m unittest discover -s tests
```

They need no network: a global folder of their own points to `../deflang-lib`.

- `tests/test_execute.py`: the language, the libraries and the samples.
- `tests/test_examples.py`: every `// Example:` in the libraries and samples is run,
  and checked against its result.
