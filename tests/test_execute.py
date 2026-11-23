"""Run with:  python3 -m unittest discover tests"""
import os
import shutil
import socket
import subprocess
import time
import sys
import json
import tempfile
import threading
import tomllib
import urllib.error
import urllib.request
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import interpreter  # noqa: E402  finds ../deflang and ../deflang-lib
from interpreter import LIBRARY_PROGRAM, SAMPLES, library, link_libraries  # noqa: E402

from deflang.exception import DefException  # noqa: E402
from deflang.execute import Execute  # noqa: E402


class DefTest(unittest.TestCase):
    def setUp(self):
        self.e = Execute()
        self.e.program_dir = LIBRARY_PROGRAM
        self.e.run("use core")

    def run_lines(self, *lines):
        result = None
        for line in lines:
            result = self.e.run(line)
        return result


class TestMath(DefTest):
    def test_basic_operators(self):
        self.assertEqual(self.run_lines("2 + 3"), 5)
        self.assertEqual(self.run_lines("2 * 3"), 6)
        self.assertEqual(self.run_lines("7 / 2"), 3.5)
        self.assertEqual(self.run_lines("6 / 3"), 2)
        self.assertEqual(self.run_lines("2 plus 3"), 5)

    def test_subtraction_is_left_to_right(self):
        self.assertEqual(self.run_lines("10 - 2 - 3"), 5)

    def test_numbers_are_literals(self):
        self.assertEqual(self.run_lines("-3"), -3)
        self.assertEqual(self.run_lines("1e-3"), 0.001)

    def test_word_numbers(self):
        self.assertEqual(self.run_lines("one + two"), 3)

    def test_sum_of_list(self):
        self.assertEqual(self.run_lines("sum of [1, 2, 3]"), 6)


class TestValues(DefTest):
    def test_assignment_takes_the_whole_right_side(self):
        self.assertEqual(self.run_lines("a is 2 + 3", "a"), 5)

    def test_text_concat(self):
        self.assertEqual(self.run_lines("a is 2", '"value: " a'), "value: 2")

    def test_patterns_do_not_match_inside_strings(self):
        self.assertEqual(self.run_lines('"Is it?" = "Is it?"'), True)

    def test_indexing(self):
        self.run_lines("x is [10, 20]")
        self.assertEqual(self.run_lines("x #2"), 20)
        self.assertEqual(self.run_lines("x No. 1"), 10)

    def test_the_and_that(self):
        self.assertEqual(self.run_lines("the 4 + 4"), 8)
        self.assertEqual(self.run_lines("2 that > 1"), True)

    def test_means(self):
        self.assertEqual(self.run_lines("less than means <", "2 less than 3"), True)

    def test_clean_forgets_values(self):
        self.run_lines("a is 1")
        self.e.clean()
        with self.assertRaises(DefException):
            self.run_lines("a")


class TestComparison(DefTest):
    def test_comparison_binds_looser_than_math(self):
        self.assertEqual(self.run_lines("2 + 3 > 4"), True)

    def test_longer_phrase_wins(self):
        self.run_lines("x is 3")
        self.assertEqual(self.run_lines("x greater than or equal to 3"), True)
        self.assertEqual(self.run_lines("x greater than 3"), False)

    def test_text_equality(self):
        self.assertEqual(self.run_lines('"a" = "a"'), True)

    def test_conditions(self):
        self.assertEqual(self.run_lines("is 5 > 3 ?", '\t"yes"'), "yes")
        self.assertIsNone(self.run_lines("is 2 > 3 ?", '    "yes"'))
        self.assertEqual(self.run_lines("is not ?", '\t"no"'), "no")

    def test_every_indented_line_checks_the_last_question(self):
        self.run_lines("a is 7", "is a > 5 ?", "    b is a * 2", "    c is b + 1")
        self.assertEqual(self.run_lines("c"), 15)

    def test_def_body_is_not_a_condition(self):
        self.run_lines("is 2 > 3 ?", "def nine", "    9")
        self.assertEqual(self.run_lines("nine"), 9)

    def test_hello_world(self):
        self.run_lines("a is 2", "b is a greater than 3 ?")
        self.assertEqual(
            self.run_lines('"Is " a " greater than 3? " b'), "Is 2 greater than 3? False"
        )


class TestArray(DefTest):
    def test_each_of_them_passes(self):
        self.assertIsNone(self.run_lines("[1, 2, 3] each of them is > 0"))

    def test_each_of_them_fails(self):
        with self.assertRaisesRegex(DefException, "1 is not > 1"):
            self.run_lines("[1, 2, 3] each of them is > 1")


class TestErrors(DefTest):
    def test_unknown_name(self):
        with self.assertRaisesRegex(DefException, "unknown name 'nope'"):
            self.run_lines("nope")

    def test_not_a_number(self):
        with self.assertRaisesRegex(DefException, "expected a number"):
            self.run_lines('2 + "a"')

    def test_error_statement(self):
        with self.assertRaisesRegex(DefException, "boom"):
            self.run_lines("error boom")

    def test_python_error_in_body_names_the_line(self):
        self.run_lines("python explode", "    return 1 / 0")
        with self.assertRaisesRegex(DefException, "in 'explode': ZeroDivisionError"):
            self.run_lines("explode")

    def test_indented_line_without_question(self):
        with self.assertRaisesRegex(DefException, "no line above it to belong to"):
            self.run_lines("    oops")

    def test_missing_quote(self):
        with self.assertRaisesRegex(DefException, "missing closing quote"):
            self.run_lines('"abc')


class TestDefinitions(DefTest):
    def test_user_def(self):
        self.run_lines("def double A0", "    A0 * 2")
        # defined after math, so it binds tighter: (double 2) + 3
        self.assertEqual(self.run_lines("double 2 + 3"), 7)

    def test_as_written_gets_source_text(self):
        self.run_lines("python[written] source of A0", "    return A0")
        self.assertEqual(self.run_lines("source of 1 + 1"), "1 + 1")


    def test_argument_name(self):
        self.run_lines("argument is X", "def twice X0", "    X0 * 2")
        self.assertEqual(self.run_lines("twice 4"), 8)

    def test_comment(self):
        # // is the default
        self.assertIsNone(self.run_lines("// anything, even nope"))

    def test_comment_marker_replaces_the_old_one(self):
        self.run_lines("comment is #")
        self.assertIsNone(self.run_lines("# anything"))
        with self.assertRaises(DefException):
            self.run_lines("// no longer a comment")
        self.run_lines("comment is //")
        self.assertIsNone(self.run_lines("// a comment again"))

    def test_each_file_starts_with_argument_A(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "inner.def").write_text("python half A0\n    return A0 / 2\n")
            Path(folder, "main.def").write_text("argument is X\nuse inner\npython twice X0\n    return X0 * 2\n")
            e = Execute()
            e.run(f"use {Path(folder, 'main')}")
            self.assertEqual(e.run("half 4"), 2)   # inner.def wrote A0, not X0
            self.assertEqual(e.run("twice 4"), 8)  # main.def kept X after the import

    def test_comment_marker_stays_in_its_file(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "other.def").write_text("comment is #\n# a comment here\n")
            Path(folder, "main.def").write_text("use other\n// still a comment\n")
            e = Execute()
            e.run(f"use {Path(folder, 'main')}")
            with self.assertRaises(DefException):
                e.run("# not a comment out here")


class TestImport(unittest.TestCase):
    def test_imports_once_and_relative_to_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "lib").mkdir()
            Path(folder, "lib", "inner.def").write_text("def seven\n    7\n")
            Path(folder, "lib", "outer.def").write_text("use inner\n")
            e = Execute()
            old = os.getcwd()
            os.chdir(folder)
            try:
                e.run("use lib/outer")
                e.run("use lib/outer")
                e.run("use lib/inner")
            finally:
                os.chdir(old)
            self.assertEqual(e.run("seven"), 7)
            self.assertEqual(len(e.definitions), 1)

    def test_missing_file(self):
        with self.assertRaisesRegex(DefException, "cannot use 'nothing'"):
            Execute().run("use nothing")

    def test_error_shows_file_and_line(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "bad.def")
            path.write_text("\n    stray\n")
            with self.assertRaisesRegex(DefException, r"bad\.def:2: indented line with no line above it"):
                Execute().run(f"use {folder}/bad")


class TestGroups(DefTest):
    def give(self, line, *answers):
        with mock.patch("builtins.input", side_effect=list(answers)):
            return self.run_lines(line)

    def test_give_reads_numbers(self):
        self.give("give 2 numbers", "3", "4")
        self.assertEqual(self.run_lines("numbers"), [3, 4])
        self.assertEqual(self.run_lines("their sum"), 7)

    def test_give_checks_the_condition(self):
        with self.assertRaisesRegex(DefException, "15 is not <= 14"):
            self.give("give 2 numbers less than or equal to 14", "15", "2")

    def test_one_of_and_it(self):
        self.run_lines("cards is [11, 5, 11]")
        self.assertTrue(self.run_lines("one of the cards is 11"))
        self.run_lines("it should be converted to 1")
        self.assertEqual(self.run_lines("cards"), [1, 5, 11])
        self.assertFalse(self.run_lines("one of the cards is 7"))

    def test_is_greater_than_is_a_comparison_not_an_assignment(self):
        self.run_lines("x is 30")
        self.assertTrue(self.run_lines("x is greater than 21"))
        self.assertEqual(self.run_lines("x"), 30)

    def test_black_jack(self):
        program = (SAMPLES / "black-jack" / "main.def").read_text()
        for answers, expected in [(("10", "9"), "You win"), (("11", "11"), "You win"), (("13", "10"), "You lost")]:
            e = Execute()
            e.program_dir = SAMPLES / "black-jack"  # its libraries.toml: core, global
            printed = []
            with mock.patch("builtins.input", side_effect=list(answers)):
                for line in program.splitlines():
                    result = e.run(line)
                    if result is not None:
                        printed.append(result)
            self.assertEqual(printed, [expected], answers)


class TestEcho(unittest.TestCase):
    def setUp(self):
        self.printed = []
        self.e = Execute(output=self.printed.append)
        self.e.program_dir = LIBRARY_PROGRAM
        self.e.run("use core")

    def test_backtick_line_prints_then_runs(self):
        self.assertEqual(self.e.run("`a is 2 + 3`"), None)
        self.assertEqual(self.printed, ["a is 2 + 3"])
        self.assertEqual(self.e.run("a"), 5)

    def test_backtick_line_returns_its_value(self):
        self.assertEqual(self.e.run("`2 * 3`"), 6)

    def test_indented_backtick_line_only_prints_when_the_answer_is_yes(self):
        self.e.run("is 2 > 3 ?")
        self.e.run("    `\"big\"`")
        self.assertEqual(self.printed, [])
        self.e.run("is not ?")
        self.assertEqual(self.e.run("    `\"small\"`"), "small")
        self.assertEqual(self.printed, ['"small"'])


class TestNumberWords(DefTest):
    def test_number_words(self):
        for text, value in [
            ("zero", 0), ("seven", 7), ("fourteen", 14), ("twenty one", 21),
            ("twenty-one", 21), ("one hundred and five", 105),
            ("two thousand twenty six", 2026), ("three million", 3000000),
        ]:
            self.assertEqual(self.run_lines(text), value, text)

    def test_number_words_in_math(self):
        self.assertEqual(self.run_lines("twenty one + two"), 23)
        self.assertEqual(self.run_lines("ten - three"), 7)
        self.assertEqual(self.run_lines("five plus five"), 10)
        self.assertEqual(self.run_lines("twelve > eleven"), True)

    def test_number_words_do_not_take_over_other_phrases(self):
        self.run_lines("cards is [11, 5]")
        self.assertTrue(self.run_lines("one of the cards is eleven"))

    def test_restricted_argument(self):
        self.run_lines("python[written] (A0: [a-z]+) shouted", "    return A0.upper()")
        self.assertEqual(self.run_lines("hello shouted"), "HELLO")
        with self.assertRaisesRegex(DefException, "unknown name"):
            self.run_lines("hello world shouted")

class TestReadableDefs(DefTest):
    def test_symbols_need_no_spaces(self):
        self.assertEqual(self.run_lines("2+3*4"), 14)

    def test_words_need_spaces(self):
        self.run_lines("def A0 doubled", "    A0 * 2")
        self.assertEqual(self.run_lines("4 doubled"), 8)
        with self.assertRaises(DefException):
            self.run_lines("4doubled")

    def test_stacked_def_lines_share_a_body(self):
        self.run_lines("def A0 twice", "def twice A0", "    A0 * 2")
        self.assertEqual(self.run_lines("3 twice"), 6)
        self.assertEqual(self.run_lines("twice 3"), 6)

    def test_flags_go_on_the_first_line_of_a_group(self):
        with self.assertRaisesRegex(DefException, "flags of its first line"):
            self.run_lines("def A0 twice", "python twice A0")
        self.run_lines("python A0 thrice", "python thrice A0", "    return number(a[0]) * 3")
        self.assertEqual(self.run_lines("thrice 2"), 6)

    def test_def_lang_body_returns_its_last_value(self):
        self.run_lines(
            "def A0 sign",
            "    is A0 > 0 ?",
            '        "positive"',
            "    is not ?",
            '        "not positive"',
        )
        self.assertEqual(self.run_lines("5 sign"), "positive")
        self.assertEqual(self.run_lines("-5 sign"), "not positive")

    def test_def_lang_body_gets_values(self):
        self.run_lines("def greet A0", '    "hello " A0')
        self.assertEqual(self.run_lines('greet "Sam"'), "hello Sam")
        self.assertEqual(self.run_lines("n is 2 + 2", "greet n"), "hello 4")

    def test_library_defs(self):
        self.assertEqual(self.run_lines("3 squared + 1"), 10)
        self.assertEqual(self.run_lines("half of 9"), 4.5)
        self.assertEqual(self.run_lines("50 percent of 30"), 15)
        self.assertEqual(self.run_lines("10 minus 4 divided by 2"), 8)
        self.assertTrue(self.run_lines("5 is between 1 and 10"))
        self.assertFalse(self.run_lines("15 is between 1 and 10"))
        self.assertTrue(self.run_lines("both 1 < 2 and 3 > 2"))
        self.assertTrue(self.run_lines("either 1 > 2 or 3 > 2"))
        self.assertTrue(self.run_lines("not 1 > 2"))
        self.assertIsNone(self.run_lines("all of [1, 2] are > 0"))

    def test_number_words_with_and_still_work_in_math(self):
        self.assertEqual(self.run_lines("one hundred and two plus 100"), 202)

    def test_regex_flag_keeps_raw_patterns(self):
        self.run_lines("def[regex] (shout)\\s+A0 or (yell)\\s+A0", "    A0")
        self.assertEqual(self.run_lines("yell 3"), 3)


class TestLoopsAndTools(DefTest):
    def setUp(self):
        self.said = []
        self.e = Execute(output=self.said.append)
        self.e.program_dir = LIBRARY_PROGRAM
        self.e.run("use core")

    def test_repeat(self):
        self.run_lines("repeat 3 times: say \"hi\"")
        self.assertEqual(self.said, ["hi", "hi", "hi"])

    def test_for_each_with_text_and_math(self):
        self.run_lines('for each n in numbers from 1 to 3: say n " x 7 = " n * 7')
        self.assertEqual(self.said, ["1 x 7 = 7", "2 x 7 = 14", "3 x 7 = 21"])

    def test_repeat_while(self):
        self.run_lines("n is 0", "repeat while n < 5: n is n + 2")
        self.assertEqual(self.run_lines("n"), 6)

    def test_repeat_while_stops_runaway_loops(self):
        with self.assertRaisesRegex(DefException, "ever false"):
            self.run_lines("repeat while 1 < 2: 1")

    def test_numbers_from_count_down(self):
        self.assertEqual(self.run_lines("numbers from 3 to 1"), [3, 2, 1])

    def test_lists(self):
        self.run_lines("list is []", 'add "milk" to list', 'add "eggs" to list', 'remove "milk" from list')
        self.assertEqual(self.run_lines("list"), ["eggs"])
        with self.assertRaisesRegex(DefException, "milk is not in list"):
            self.run_lines('remove "milk" from list')
        self.assertEqual(self.run_lines('say "You need " count of list " things: " list joined with ", "'), None)
        self.assertEqual(self.said[-1], "You need 1 things: eggs")

    def test_text_and_list_tools(self):
        self.assertEqual(self.run_lines('length of "hello"'), 5)
        self.assertEqual(self.run_lines('words of "a b c"'), ["a", "b", "c"])
        self.assertEqual(self.run_lines('"hi" in upper case'), "HI")
        self.assertTrue(self.run_lines('"hello" contains "ell"'))
        self.assertEqual(self.run_lines("largest of [3, 9, 2]"), 9)
        self.assertEqual(self.run_lines("first of [3, 9, 2]"), 3)
        self.assertEqual(self.run_lines("average of [2, 4]"), 3)
        self.assertTrue(self.run_lines("[] is empty"))

    def test_rounding_is_looser_than_math(self):
        self.assertEqual(self.run_lines("70 / 1.75 squared rounded to 1 place"), 22.9)
        self.assertEqual(self.run_lines("70 / 1.75 squared rounded to 2 places"), 22.86)
        self.assertEqual(self.run_lines("2.6 rounded"), 3)
        self.assertEqual(self.run_lines('"BMI " 70 / 1.75 squared rounded to 1 place'), "BMI 22.9")

    def test_random(self):
        for _ in range(20):
            self.assertIn(self.run_lines("random number between 1 and 3"), [1, 2, 3])
        self.assertIn(self.run_lines("random item of [5, 6]"), [5, 6])

    def test_if_otherwise(self):
        self.assertEqual(self.run_lines("x is 175", "x / 100 if x > 3 otherwise x"), 1.75)
        self.assertEqual(self.run_lines("y is 1.8", "y / 100 if y > 3 otherwise y"), 1.8)
        # only the chosen part runs
        self.assertEqual(self.run_lines('"yes" if 1 < 2 otherwise nope'), "yes")

    def test_print_is_say(self):
        self.run_lines('print "a"')
        self.assertEqual(self.said, ["a"])
        # "show" is not an alias: the web server has `page ... shows`
        self.assertEqual(self.e.apply_aliases("show views"), "show views")

    def test_the_time(self):
        self.assertRegex(self.run_lines("the time"), r"^\d\d:\d\d$")


class TestWeb(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        Path(self.folder.name, "page.html").write_text("<p>{{ visits }} visits, {{ query \"name\" }}</p>")
        Path(self.folder.name, "style.css").write_text("p {}")
        self.e = Execute(output=lambda value: None)
        self.e.program_dir = LIBRARY_PROGRAM
        for line in [
            "use core",
            "use web/server",
            "shared visits is 0",
            "def home page",
            "    visits is visits + 1",
            f'    template "{self.folder.name}/page.html"',
            "server on port 0",
            'page "/" shows home page',
            'page "/hello" shows "<h1>Hello, " query "name" "</h1>"',
            f'the assets are in "{self.folder.name}"',
            'api "/api/double" runs doubled is query "n" * 2 and sends doubled',
            'api "/api/echo" sends visits',
            'api "/api/broken" runs error no such thing and sends visits',
            'serve "<p>the app</p>" at "/"',
            'serve "<p>admin</p>" at "/admin/"',
        ]:
            self.e.run(line)
        self.thread = threading.Thread(target=self.e.run, args=("start the server",), daemon=True)
        self.thread.start()
        for _ in range(100):
            if "server" in self.e["store"]["web"]:
                break
            threading.Event().wait(0.02)
        self.base = f"http://127.0.0.1:{self.e["store"]["web"]['server'].server_address[1]}"

    def tearDown(self):
        self.e["store"]["web"]["server"].shutdown()
        self.thread.join(5)
        self.folder.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode()

    def test_pages_run_on_every_visit(self):
        self.assertEqual(self.get("/?name=Sam"), (200, "<p>1 visits, Sam</p>"))
        self.assertEqual(self.get("/"), (200, "<p>2 visits, </p>"))

    def test_query_is_escaped(self):
        self.assertEqual(self.get("/hello?name=%3Cb%3E"), (200, "<h1>Hello, &lt;b&gt;</h1>"))

    def test_static_files_and_404(self):
        self.assertEqual(self.get("/style.css"), (200, "p {}"))
        self.assertEqual(self.get("/missing.png")[0], 404)
        # never a file outside the folder: an address without an extension gets the app page
        self.assertNotIn("root:", self.get("/../etc/passwd")[1])
        self.assertEqual(self.get("/../etc/hosts.txt")[0], 404)

    def test_api_sends_json(self):
        self.assertEqual(json.loads(self.get("/api/double?n=21")[1]), {"doubled": 42})
        self.assertEqual(json.loads(self.get("/api/echo")[1]), {"visits": 0})

    def test_api_query_is_data_not_html(self):
        self.e.run('api "/api/name" runs name is query "n" and sends name')
        self.assertEqual(json.loads(self.get("/api/name?n=%3Cb%3E")[1]), {"name": "<b>"})

    def test_each_request_has_its_own_variables(self):
        self.assertEqual(json.loads(self.get("/api/double?n=21")[1]), {"doubled": 42})
        # doubled was that request's own
        self.assertNotIn("doubled", self.e["variables"])
        self.e.run('api "/api/left" sends doubled')
        self.assertEqual(self.get("/api/left")[0], 400)

    def test_shared_variables_outlive_a_request(self):
        self.get("/")
        self.get("/")
        self.assertEqual(json.loads(self.get("/api/echo")[1]), {"visits": 2})

    def test_api_errors_are_json(self):
        status, body = self.get("/api/broken")
        self.assertEqual((status, json.loads(body)), (400, {"error": "no such thing"}))

    def test_an_app_is_served_under_its_address(self):
        self.assertEqual(self.get("/some/view"), (200, "<p>the app</p>"))
        # the longest address wins
        self.assertEqual(self.get("/admin"), (200, "<p>admin</p>"))
        self.assertEqual(self.get("/admin/users"), (200, "<p>admin</p>"))
        self.assertEqual(self.get("/administrator"), (200, "<p>the app</p>"))
        # an api, a page and an asset come first
        self.assertEqual(self.get("/style.css"), (200, "p {}"))
        self.assertEqual(json.loads(self.get("/api/echo")[1]), {"visits": 0})


class TestVariables(DefTest):
    def test_a_defs_variables_are_its_own(self):
        self.run_lines("def greet", '    name is "Sam"', '    "hi " name')
        self.assertEqual(self.run_lines("greet"), "hi Sam")
        self.assertNotIn("name", self.e["variables"])

    def test_a_def_reads_the_programs_variables(self):
        self.run_lines("rate is 2", "def doubled A0", "    A0 * rate")
        self.assertEqual(self.run_lines("doubled 4"), 8)

    def test_setting_one_inside_a_def_does_not_change_the_programs(self):
        self.run_lines("x is 5", "def change", "    x is 9", "    x")
        self.assertEqual(self.run_lines("change"), 9)
        self.assertEqual(self.run_lines("x"), 5)

    def test_shared_variables_are_changed_in_place(self):
        self.run_lines("shared visits is 0", "def count", "    visits is visits + 1")
        self.run_lines("count", "count")
        self.assertEqual(self.run_lines("visits"), 2)

    def test_questions_and_lists_inside_a_def(self):
        self.run_lines("def name or stranger A0", "    name is A0", "    is name empty?", '        name is "stranger"', "    name")
        self.assertEqual(self.run_lines('name or stranger ""'), "stranger")
        self.assertEqual(self.run_lines('name or stranger "Sam"'), "Sam")
        self.run_lines("def shopping", '    add "milk" to list', '    add "tea" to list', "    count of list")
        self.assertEqual(self.run_lines("shopping"), 2)
        self.assertNotIn("list", self.e["variables"])

    def test_a_as_written_def_runs_where_its_code_was_written(self):
        # `the A0` gets the words, so it sees the caller's own variables
        self.run_lines("def total", "    numbers is [1, 2]", "    sum of the numbers")
        self.assertEqual(self.run_lines("total"), 3)


class TestFileVariables(unittest.TestCase):
    """A variable set outside a def is its file's; every file that means a shared one says `shared NAME`."""

    def program(self, **files):
        folder = tempfile.mkdtemp()
        link_libraries(folder, "core")
        for name, text in files.items():
            Path(folder, f"{name}.def").write_text(text)
        e = Execute()
        e.program_dir = Path(folder)
        e.run("use core")
        return e

    def test_a_files_variables_are_its_own(self):
        e = self.program(other="use core\nsecret is 7\n")
        e.run("use other")
        with self.assertRaisesRegex(DefException, "unknown name 'secret'"):
            e.run("secret")

    def test_a_def_sees_the_file_it_was_made_in(self):
        e = self.program(rates="use core\nrate is 2\ndef double A0\n    A0 * rate\n")
        e.run("use rates")
        self.assertEqual(e.run("double 4"), 8)  # rate is rates.def's, not this file's

    def test_use_names_from_a_file(self):
        e = self.program(
            counter="use core\nshared visits is 0\n",
            visit="use core\nuse visits from counter\ndef count the visit\n    visits is visits + 1\n")
        e.run("use visit")
        e.run("count the visit")
        e.run("count the visit")
        e.run("use visits from counter")
        self.assertEqual(e.run("visits"), 2)  # the same variable in all three files

    def test_use_as_gives_it_another_name(self):
        e = self.program(counter="use core\nshared visits is 0\n")
        e.run("use visits as count from counter")
        e.run("count is count + 5")
        e.run("use visits from counter")
        self.assertEqual(e.run("visits"), 5)

    def test_without_use_a_name_is_the_files_own(self):
        e = self.program(counter="use core\nshared visits is 0\n")
        e.run("use counter")
        e.run("visits is 99")  # this file's own visits: counter's stays
        e.run("use visits from counter")
        self.assertEqual(e.run("visits"), 0)

    def test_only_shared_names_can_be_used(self):
        e = self.program(counter="use core\nsecret is 1\n")
        with self.assertRaisesRegex(DefException, "counter has no shared variable 'secret'"):
            e.run("use secret from counter")

    def test_as_is_only_for_names(self):
        with self.assertRaisesRegex(DefException, "`as` is only for names"):
            self.program().run("use core as c")

    def test_shared_alone_and_with_the_rest_of_a_line(self):
        e = self.program()
        e.run("shared total")              # only makes total shared
        e.run("total is 3")
        e.run("shared visits is total + 1")  # shared visits, then visits is total + 1
        self.assertEqual([e.run("total"), e.run("visits")], [3, 4])

    def test_two_files_may_share_the_same_name(self):
        # each shared variable belongs to the file that made it
        e = self.program(a="use core\nshared n is 1\n", b="use core\nshared n is 2\n")
        e.run("use n as first from a")
        e.run("use n as second from b")
        self.assertEqual([e.run("first"), e.run("second")], [1, 2])


class TestReload(DefTest):
    def test_a_changed_file_gets_its_new_defs(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder, "greet.def")
            file.write_text('shared count is 0\ndef hi\n    "one"\n')
            self.run_lines(f"use {folder}/greet", "count is 5")
            self.assertEqual(self.run_lines("hi"), "one")
            self.assertEqual(self.e.changed_files(), [])
            file.write_text('shared count is 0\ndef hi\n    "two"\ndef bye\n    "bye"\n')
            os.utime(file, ns=(time.time_ns(), time.time_ns() + 10**9))
            self.assertEqual(self.e.changed_files(), [file.resolve()])
            self.e.reload(file.resolve())
            self.assertEqual(self.run_lines("hi"), "two")
            self.assertEqual(self.run_lines("bye"), "bye")
            # only the defs: `shared count is 0` didn't run again
            self.assertEqual(self.run_lines("count"), 5)
            self.assertEqual(len([d for d in self.e.definitions if d.source == "hi"]), 1)

    def test_a_new_import_is_loaded(self):
        # the page didn't use CSS when it was read; now it imports the CSS language and has a def css
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder, "page.def")
            file.write_text('use language/html\nhtml page\n    <p>hi</p>\n')
            self.run_lines(f"use {folder}/page")
            file.write_text('use language/html\nuse language/css\n'
                            'html page\n    <style def="look"></style>\ncss look\n    p { color: red; }\n')
            self.e.reload(file.resolve())
            self.assertEqual(self.run_lines("page"), '<style def="look">p { color: red; }</style>')

    def test_an_error_keeps_the_old_defs(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder, "greet.def")
            file.write_text('def hi\n    "one"\n')
            self.run_lines(f"use {folder}/greet")
            file.write_text('def[regex] hi (\n    "two"\n')
            with self.assertRaises(DefException):
                self.e.reload(file.resolve())
            self.assertEqual(self.run_lines("hi"), "one")


class TestSettings(unittest.TestCase):
    """settings.toml in the program's folder, read again while the website runs."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.view = self.folder / "view.def"
        self.view.write_text('shared hits is 0\ndef the page\n    hits is hits + 1\n    "<p>one " hits "</p>"\n')
        self.said = []
        self.e = Execute(output=lambda value: self.said.append(str(value)))
        self.e.program_dir = self.folder
        link_libraries(self.folder)
        for line in ["use core", "use web/server", "use view", 'serve the page at "/"']:
            self.e.run(line)
        self.thread = None

    def tearDown(self):
        if self.thread:
            self.e["store"]["web"]["server"].shutdown()
            self.thread.join(5)
        shutil.rmtree(self.folder)

    def settings(self, text):
        file = self.folder / "settings.toml"
        file.write_text(text)
        # a new time, even within the same clock tick
        later = time.time_ns() + 10**9 * (2 + len(self.said))
        os.utime(file, ns=(later, later))

    def start(self):
        self.thread = threading.Thread(target=self.e.run, args=("start the server",), daemon=True)
        self.thread.start()
        self.wait(lambda: "server" in self.e["store"]["web"])

    def wait(self, condition):
        for _ in range(200):
            if condition():
                return True
            time.sleep(0.02)
        self.fail("it didn't happen: " + "; ".join(self.said))

    def port(self):
        return self.e["store"]["web"]["server"].server_address[1]

    def get(self, path="/", port=None):
        with urllib.request.urlopen(f"http://127.0.0.1:{port or self.port()}{path}", timeout=5) as response:
            return response.read().decode()

    def test_the_file_wins_over_server_on_port(self):
        self.e.run("server on port 1")  # not allowed for a program: only the file's port works
        self.settings("port = 0\n")
        self.start()
        self.assertEqual(self.get(), "<p>one 1</p>")

    def test_an_unknown_setting_stops_the_start(self):
        self.settings("port = 0\nrelaod = true\n")
        with self.assertRaisesRegex(DefException, "unknown setting 'relaod'"):
            self.e.run("start the server")
        self.settings('port = "8000"\n')
        with self.assertRaisesRegex(DefException, "port must be a whole number"):
            self.e.run("start the server")
        self.settings("port = 0\nwatch = 0.01\n")
        with self.assertRaisesRegex(DefException, "watch is 0 \\(off\\), or at least 0.1 seconds"):
            self.e.run("start the server")
        # the old names are gone: the message lists the settings there are
        self.settings("port = 0\nreload = true\n")
        with self.assertRaisesRegex(DefException, "unknown setting 'reload' \\(the settings are port, everyone, watch\\)"):
            self.e.run("start the server")

    def test_a_new_port_while_it_runs(self):
        self.settings("port = 0\n")
        self.start()
        old = self.port()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            new = probe.getsockname()[1]
        self.settings(f"port = {new}\n")
        self.wait(lambda: self.port() == new)
        self.assertEqual(self.get(port=new), "<p>one 1</p>")
        with self.assertRaises(OSError):
            self.get(port=old)
        # the shared value stayed
        self.assertEqual(self.get(port=new), "<p>one 2</p>")
        self.assertIn(f"settings changed: now on http://localhost:{new}", self.said)

    def test_watch_shows_a_changed_view(self):
        self.settings("port = 0\nwatch = 0.1\n")
        self.start()
        self.assertEqual(self.get(), "<p>one 1</p>")
        self.view.write_text('shared hits is 0\ndef the page\n    hits is hits + 1\n    "<p>two " hits "</p>"\n')
        later = time.time_ns() + 10**9
        os.utime(self.view, ns=(later, later))
        time.sleep(0.15)
        # the new def, and hits wasn't set back to 0
        self.assertEqual(self.get(), "<p>two 2</p>")
        self.assertIn("read again: view.def", self.said)

    def test_without_watch_nothing_is_read_again(self):
        self.settings("port = 0\n")
        self.start()
        self.view.write_text('def the page\n    "<p>two</p>"\n')
        later = time.time_ns() + 10**9
        os.utime(self.view, ns=(later, later))
        time.sleep(0.15)
        self.assertEqual(self.get(), "<p>one 1</p>")

    def test_turning_watch_on_while_it_runs(self):
        self.settings("port = 0\n")
        self.start()
        port = self.port()
        self.settings(f"port = {port}\nwatch = 0.1\n")
        self.wait(lambda: "settings changed: watch is 0.1" in self.said)

    def test_a_bad_setting_keeps_the_last_ones(self):
        self.settings("port = 0\n")
        self.start()
        port = self.port()
        self.settings("port = 0\nwatch = yes\n")
        self.wait(lambda: any(line.startswith("settings not changed") for line in self.said))
        self.assertEqual(self.port(), port)
        self.assertEqual(self.get(), "<p>one 1</p>")


class TestLibraries(unittest.TestCase):
    """A program's libraries: copies in libraries/ (from git), global copies, and local
    folders of the project (linked). From a git repo laid out like deflang-lib."""

    def setUp(self):
        self.program = Path(tempfile.mkdtemp())
        self.repo = Path(tempfile.mkdtemp())
        self.global_folder = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"DEFLANG_GLOBAL": str(self.global_folder)})
        self.env.start()
        for name, inside in [("core", "core"), ("modifier", "modifier"), ("web", "web"), ("language", "language")]:
            shutil.copytree(library(name), self.repo / inside)
        git = lambda *args: subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)
        git("init", "--quiet")
        git("add", ".")
        git("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "--quiet", "-m", "libraries")
        self.url = f"file://{self.repo}"
        self.said = []

    def tearDown(self):
        self.env.stop()
        for folder in (self.program, self.repo, self.global_folder):
            shutil.rmtree(folder)

    def install(self, source, **options):
        from deflang import libraries
        return libraries.install(self.program, str(source), say=self.said.append, **options)

    def run_program(self, *lines):
        e = Execute(output=lambda value: self.said.append(str(value)))
        e.program_dir = self.program
        result = None
        for line in lines:
            result = e.run(line)
        return result

    def listed(self):
        return (self.program / "libraries.toml").read_text()

    @staticmethod
    def version(name):
        """The version deflang-lib's library.toml gives the library `name`."""
        return tomllib.loads((library(name) / "library.toml").read_text())["version"]

    def test_from_git_into_the_project(self):
        # web's own libraries.toml lists ../language: it comes from the same repo
        self.assertEqual(self.install(f"{self.url}#web"), ["web", "language"])
        self.assertTrue((self.program / "libraries" / "web" / "server.def").is_file())
        self.assertTrue((self.program / "libraries" / "language" / "javascript.def").is_file())
        self.assertIn(f'web = {{ from = "{self.url}#web", version = "{self.version("web")}" }}', self.listed())
        self.assertIn(f'language = {{ from = "{self.url}#language", version = "{self.version("language")}" }}', self.listed())
        self.assertEqual((self.program / "libraries" / ".gitignore").read_text().splitlines()[-1], "*")

    def test_a_new_version_is_shown_and_written(self):
        self.install(f"{self.url}#core")
        toml = self.repo / "core" / "library.toml"
        before = tomllib.loads(toml.read_text())["version"]
        toml.write_text(toml.read_text().replace(f'version = "{before}"', 'version = "9.9.9"'))
        git = lambda *args: subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)
        git("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "--quiet", "-am", "core 9.9.9")
        from deflang import libraries
        libraries.install_all(self.program, say=self.said.append)
        self.assertIn(f"core: {before} → 9.9.9", self.said)
        self.assertIn('version = "9.9.9"', self.listed())

    def test_a_program_runs_with_only_its_libraries(self):
        self.install(f"{self.url}#core")
        self.assertEqual(self.run_program("use core", "x is 2 + 3", "x squared"), 25)

    def test_global(self):
        self.assertEqual(self.install(f"{self.url}#web", globally=True), ["web", "language"])
        self.assertTrue((self.global_folder / "web" / self.version("web") / "server.def").is_file())
        self.assertFalse((self.program / "libraries").exists())
        self.assertIn(f'web = {{ from = "{self.url}#web", version = "{self.version("web")}", global = true }}', self.listed())
        self.install(f"{self.url}#core", globally=True)
        self.assertEqual(self.run_program("use core", "3 squared"), 9)

    def test_a_local_library_is_linked(self):
        # core's own libraries.toml lists ../modifier: linked the same way
        shutil.copytree(library("core"), self.program / "my-libraries" / "core")
        shutil.copytree(library("modifier"), self.program / "my-libraries" / "modifier")
        self.install(self.program / "my-libraries" / "core", link=True)
        self.assertFalse((self.program / "libraries" / "core").exists())
        self.assertIn('core = { from = "my-libraries/core", link = true }', self.listed())
        self.assertIn('modifier = { from = "my-libraries/modifier", link = true }', self.listed())
        self.assertEqual(self.run_program("use core", "3 squared"), 9)

    def test_install_again_from_the_list(self):
        from deflang import libraries
        self.install(f"{self.url}#core")
        self.install(f"{self.url}#web", globally=True)
        shutil.rmtree(self.program / "libraries")
        shutil.rmtree(self.global_folder / "web")
        self.assertEqual(sorted(libraries.install_all(self.program, say=self.said.append)), ["core", "language", "modifier", "web"])
        self.assertTrue((self.global_folder / "web" / self.version("web")).is_dir())
        self.assertEqual(self.run_program("use core", "3 squared"), 9)

    def test_the_rules(self):
        from deflang import libraries
        outside = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(library("core"), outside / "core")
            shutil.copytree(library("core"), self.program / "mine")
            cases = [
                ((f"{self.url}#core",), {"link": True}, "a library from git can't be linked"),
                ((self.program / "mine",), {}, "a folder is used where it is: write link = true"),
                ((self.program / "mine",), {"globally": True}, "only a library from git can be global"),
                ((outside / "core",), {"link": True}, "is outside the project"),
            ]
            for args, options, message in cases:
                with self.subTest(message), self.assertRaisesRegex(DefException, message):
                    self.install(*args, **options)
            (self.program / "libraries.toml").write_text('core = "somewhere"\n')
            with self.assertRaisesRegex(DefException, 'write core as core = { from = "..." }'):
                libraries.listed(self.program)
            # the old form of a global library says how it is written now
            (self.program / "libraries.toml").write_text('core = { from = "x.git#core", global = "0.1.0" }\n')
            with self.assertRaisesRegex(DefException, 'as version = "0.1.0", global = true'):
                libraries.listed(self.program)
        finally:
            shutil.rmtree(outside)

    def test_a_missing_library_says_how_to_install_it(self):
        with self.assertRaisesRegex(DefException, "no library 'core' \\(install it with: python -m deflang install"):
            self.run_program("use core")

    def test_the_command(self):
        from deflang import libraries
        from deflang.__main__ import main
        with mock.patch("sys.stdout"), mock.patch("os.getcwd", return_value=str(self.program)), \
                mock.patch("pathlib.Path.cwd", return_value=self.program):
            self.assertIsNone(main(["install", f"{self.url}#core", "--global"]))
        version = tomllib.loads((library("core") / "library.toml").read_text())["version"]
        self.assertTrue((self.global_folder / "core" / version / "main.def").is_file())
        settings = self.program / "settings.toml"
        with mock.patch.object(libraries, "SETTINGS", settings), mock.patch.dict(os.environ, {"DEFLANG_GLOBAL": ""}), \
                mock.patch("sys.stdout"):
            self.assertIsNone(main(["setup", "--global-folder", str(self.program / "chosen")]))
            self.assertEqual(libraries.global_folder(), self.program / "chosen")


class TestHowALineIsRead(DefTest):
    """Which def wraps a line, from its shape: no flag needed."""

    def outer(self, line):
        tree = self.e._parser.parse(line)
        return tree.definition.source

    def test_brackets_wrap_what_they_surround(self):
        self.run_lines("python[written] api2 A0 runs A1 and sends A2", "    return A1")
        self.assertEqual(self.outer('api2 "/a" runs x is 1 and sends x'), "api2 A0 runs A1 and sends A2")
        self.assertEqual(self.outer("is 5 > 3 ?"), "is A0 ?")
        self.assertEqual(self.outer('"yes" if 1 < 2 otherwise "no"'), "A0 if A1 otherwise A2")

    def test_a_sentence_wraps_what_follows_it(self):
        # it takes its arguments as written and starts the line with two or more fixed words
        self.assertEqual(self.outer("all of [1, 2] are > 1"), "all of A0 are A1")
        self.assertEqual(self.outer("repeat 3 times: x is x + 1"), "repeat A0 times : A1")
        # but not the closing `?` of a question
        self.assertEqual(self.outer("one of [1, 11] is 11?"), "A0 ?")

    def test_a_phrase_is_not_a_sentence(self):
        # the same shape, but count of takes a value: (count of x) = 0
        self.assertEqual(self.outer("count of [] = 0"), "A0 = A1")
        self.assertTrue(self.run_lines("count of [] = 0"))

    def test_joined_text_is_a_def(self):
        # core makes it after `say` and `is`, and before math: math runs inside it
        self.assertEqual(self.outer('say "x = " 2 + 3'), "say A0")
        self.assertEqual(self.run_lines('"x = " 2 + 3'), "x = 5")
        self.assertEqual(self.run_lines('"<" 1 ">" 2 * 3 "!"'), "<1>6!")
        self.assertEqual(self.run_lines('"a" "b"'), "ab")

    def test_a_text_at_the_end_is_not_a_closing_word(self):
        # a sentence wraps joined text that ends the line (unlike the `?` of a question)
        self.run_lines("python[written] show A0 as A1", "    return A1")
        self.assertEqual(self.outer('show "/x" as "<p>" 1 "</p>"'), "show A0 as A1")

    def test_a_reading_with_no_value_loses(self):
        # joining is made first, but `size of` alone is no value: so it is `size of A0`
        self.run_lines("python size of A0", "    return len(A0)")
        self.assertEqual(self.outer('size of "abc"'), "size of A0")
        self.assertEqual(self.run_lines('size of "abc"'), 3)
        self.assertEqual(self.run_lines('"n: " size of "abc"'), "n: 3")

    def test_number_words_are_one_value(self):
        self.assertEqual(self.run_lines("one hundred and two plus 100"), 202)

    def test_otherwise_the_first_def_wraps(self):
        self.assertEqual(self.outer("x is 3 squared"), "A0 is A1")
        self.assertEqual(self.outer("x is 2 + 3"), "A0 is A1")


class TestQuestions(DefTest):
    def test_questions_read_like_english(self):
        self.run_lines('name is ""')
        self.assertEqual(self.run_lines("is name empty?", '    "no name"'), "no name")
        self.assertEqual(self.run_lines("x is 5", "is x between 1 and 10?", '    "inside"'), "inside")
        self.assertIsNone(self.run_lines("is x between 6 and 10?", '    "inside"'))

    def test_statement_forms_still_work(self):
        self.assertTrue(self.run_lines("[] is empty"))
        self.assertTrue(self.run_lines("5 is between 1 and 10"))
        self.run_lines("y is 3")
        self.assertEqual(self.run_lines("y"), 3)


class TestPackages(unittest.TestCase):
    def test_files_are_relative_to_the_program(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "pages").mkdir()
            Path(folder, "def").mkdir()
            Path(folder, "def", "web.server.def").write_text((library("web") / "server.def").read_text())
            link_libraries(folder, "core")
            Path(folder, "pages", "hi.html").write_text("<p>{{ 1 + 1 }}</p>")
            e = Execute()
            e.program_dir = Path(folder)
            e.run("use core")
            e.run("use def/web.server")  # found in the package's own def/ folder
            self.assertEqual(e.run('template "pages/hi.html"'), "<p>2</p>")

    def run_package(self, name, *answers):
        package = SAMPLES / name
        said = []
        e = Execute(output=said.append)
        e.program_dir = package
        with mock.patch("builtins.input", side_effect=list(answers)):
            for line in (package / "main.def").read_text().splitlines():
                e.run(line)
        return said

    def test_bmi_package(self):
        self.assertEqual(self.run_package("bmi", "70", "1.75")[1:], ["Your BMI is 22.9", "That is healthy"])
        self.assertEqual(self.run_package("bmi", "70", "175")[1], "Your BMI is 22.9")
        self.assertEqual(self.run_package("bmi", "50", "1.80")[2], "That is underweight")

    def test_times_table_package(self):
        said = self.run_package("times-table", "7")
        self.assertEqual(len(said), 10)
        self.assertEqual(said[2], "3 x 7 = 21")

    def test_website_bmi_accepts_meters_and_centimeters(self):
        e = Execute(output=lambda value: None)
        e.program_dir = SAMPLES / "website"
        for line in ["use core", "use web/server", "use language/html", "use language/css", "use def/components/bmi"]:
            e.run(line)
        for height in ["1.75", "175"]:
            e["store"]["web"]["request"] = {"path": "/api/bmi", "query": {"weight": "70", "height": height}, "page": False}
            self.assertEqual((e.run("bmi"), e.run("verdict")), (22.9, "healthy"), height)
        # its weight and height were the def's own
        self.assertNotIn("weight", e["variables"])
        self.assertNotIn("height", e["variables"])

    def test_website_package_exists(self):
        package = SAMPLES / "website"
        components = ["nav", "home", "hello", "bmi", "missing"]
        for name in ["main.def", "def/site.page.def", "def/routes.def", *[f"def/components/{c}.def" for c in components]]:
            self.assertTrue((package / name).is_file(), name)


class TestLanguages(DefTest):
    def test_a_language_of_your_own(self):
        self.run_lines(
            "language upper",
            "    does",
            "        return fill(BODY, [as_text(value) for value in VAR]).upper()",
            "upper shout A0",
            "    hello A0, how are you?",
        )
        self.assertEqual(self.run_lines('shout "sam"'), "HELLO SAM, HOW ARE YOU?")

    def test_html_is_imported(self):
        self.assertNotIn("html", self.e["language"])  # not part of the core
        self.run_lines("use language/html", "html greeting A0", "    <p>Hello A0</p>")
        self.assertEqual(self.run_lines('greeting "<b>Sam</b>"'), "<p>Hello &lt;b&gt;Sam&lt;/b&gt;</p>")
        self.assertIn("html", self.e["language"])

    def test_an_element_gets_a_defs_html(self):
        self.run_lines("use language/html", "html links", "    <a href=\"/\">Home</a>",
                       "html page", "    <nav def=\"links\"></nav><main def=\"words\"></main>",
                       "def words", '    "<b>bold</b>"')
        # a def html result goes in as it is; any other value is escaped
        self.assertEqual(self.run_lines("page"), '<nav def="links"><a href="/">Home</a></nav><main def="words">&lt;b&gt;bold&lt;/b&gt;</main>')

    def test_a_script_gets_a_defs_javascript(self):
        self.run_lines("use language/html", "use language/javascript",
                       "javascript hello", "    say('</p>')",
                       "html page", "    <script def=\"hello\"></script>")
        # its code cannot end the <script> early, and data-def is not def
        self.assertEqual(self.run_lines("page"), "<script def=\"hello\">say('<\\/p>')</script>")
        self.run_lines("html other", '    <p data-def="hello"></p>')
        self.assertEqual(self.run_lines("other"), '<p data-def="hello"></p>')

    def test_a_style_gets_a_defs_css(self):
        self.run_lines("use language/html", "use language/css",
                       "css accent A0", "    h1 { color: A0; }",
                       "html page", "    <style def=\"teal accent\"></style>",
                       "def teal accent", '    accent "teal"')
        self.assertEqual(self.run_lines("page"), '<style def="teal accent">h1 { color: teal; }</style>')
        with self.assertRaisesRegex(DefException, "can't have"):
            self.run_lines('accent "red; } body { display: none"')

    def test_python_is_built_in(self):
        e = Execute()
        e.run("python seven")
        e.run("    return 7")
        self.assertEqual(e.run("seven"), 7)

    def test_without_a_declaration_it_is_a_pattern_word(self):
        # `def html thing`: a def-lang def whose pattern is `html thing`
        e = Execute()
        e.run("def html thing")
        e.run("    3")
        self.assertEqual(e.run("html thing"), 3)

    def test_a_language_needs_does(self):
        self.run_lines("language empty", "empty nothing", "    text")
        with self.assertRaisesRegex(DefException, "language empty has no `does`"):
            self.run_lines("nothing")

    def test_a_built_in_entry_is_not_declared_again(self):
        with self.assertRaisesRegex(DefException, "language python is built in: it can't be replaced"):
            self.run_lines("language python")


class TestKernel(unittest.TestCase):
    """The kernel's shapes (KERNEL.md): language[flags] pattern, entries, modifiers."""

    def setUp(self):
        self.said = []
        self.e = Execute(output=lambda value: self.said.append(str(value)))
        self.run_lines("python say A0", "    self.say(A0)")

    def run_lines(self, *lines):
        result = None
        for line in lines:
            result = self.e.run(line)
        return result

    def test_flags_in_brackets(self):
        self.run_lines("python[written] source of A0", "    return A0")
        self.assertEqual(self.run_lines("source of 1 + 1"), "1 + 1")
        self.run_lines("def[regex] (A0: \\d+)% or (A0: \\d+) percent", "    A0")
        self.assertEqual(self.run_lines("50 percent"), 50)

    def test_the_flag_errors(self):
        for line, message in [
            ("def[] x", "no flags in def\\[\\]"),
            ("def[as written] x", "unknown flag 'as' \\(the flags are: regex, written\\)"),
            ("def[regex 3] x", "flag regex takes no value"),
        ]:
            with self.subTest(line), self.assertRaisesRegex(DefException, message):
                self.run_lines(line)

    def test_a_pattern_may_start_with_a_bracket(self):
        # after a space, `[` is the pattern's
        self.run_lines("def [ A0 ] first", "    A0")
        self.assertEqual(self.run_lines("[ 7 ] first"), 7)

    def test_a_group_has_one_language_and_flags(self):
        self.run_lines("def A0 plus A1", "def the sum of A0 and A1", "    A0")
        self.assertEqual(self.run_lines("the sum of 4 and 5"), 4)
        self.run_lines("python[written] one A0")
        with self.assertRaisesRegex(DefException, "the language and flags of its first line"):
            self.run_lines("python two A0")

    def test_an_entry_and_its_fields(self):
        self.run_lines("language upper", "    does", "        return fill(BODY, [as_text(v) for v in VAR]).upper()",
                       "upper shout A0", "    hi A0")
        self.assertEqual(self.run_lines('shout "sam"'), "HI SAM")
        self.assertIn("upper", self.e["language"])
        for lines, message in [
            (["language two words"], "an entry is its kind and a one-word name"),
            (["language odd", "    color red"], "language odd has no field 'color' \\(its fields are: does, editor, flags, replaces\\)"),
            (["modifier odd", "    applies to everything"], "applies to definition or name, not everything"),
            (["statement odd", "        words odd"], "the fields of statement odd are one level in"),
        ]:
            with self.subTest(lines[-1]), self.assertRaisesRegex(DefException, message):
                self.run_lines(*lines)

    def test_a_language_takes_only_its_flags(self):
        self.run_lines("language shout", "    does", "        return BODY.upper()")
        with self.assertRaisesRegex(DefException, "shout takes no flag 'written'"):
            self.run_lines("shout[written] hi")
        self.run_lines("language loud", "    flags written", "    does", "        return BODY.upper()")
        self.run_lines("loud[written] hey", "    hey")
        self.assertEqual(self.run_lines("hey"), "HEY")

    def test_a_statement_of_a_library(self):
        self.run_lines("statement greet", "    words greet A0", "    does", "        self.say('hi ' + a[0].strip())")
        self.run_lines("greet Pedram")
        self.assertEqual(self.said, ["hi Pedram"])

    def test_a_flag_of_a_library(self):
        self.run_lines("flag cache", "    takes number", "    does", "        TARGET.cache = int(VALUE)",
                       "def[cache 60] slow", "    1")
        self.assertEqual([d.cache for d in self.e.definitions if d.source == "slow"], [60])
        with self.assertRaisesRegex(DefException, "flag cache takes a number"):
            self.run_lines("def[cache] fast")

    def test_modifiers(self):
        self.run_lines("modifier shared", "    applies to name", "    does", "        self['files'][self['file']]['names'][TARGET] = (self['file'], TARGET)",
                       "python[written] A0 is A1", "    self['variables'][A0] = self.run(A1)",
                       "shared visits is 3")
        self.assertEqual(self.run_lines("visits"), 3)
        self.run_lines("modifier internal", "    applies to definition", "    does", "        TARGET.internal = True")
        with self.assertRaisesRegex(DefException, "internal applies to a definition"):
            self.run_lines("internal visits is 4")
        with self.assertRaisesRegex(DefException, "shared applies to a name"):
            self.run_lines("shared def x", "    1")

    def test_an_entry_is_replaced_only_with_replaces(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "loud.def").write_text("language loud\n    does\n        return BODY.upper()\n")
            entry = "// Louder.\nlanguage loud\n{}    does\n        return BODY.upper() + '!'\n"
            self.e.program_dir = Path(folder)
            self.run_lines("use loud")
            for replaces, message in [
                ("", "main.def:2: language loud is there already \\(declared in loud.def\\): to replace it, write `replaces loud` under `language loud`"),
                ("    replaces main\n", "main.def:3: language loud was declared in loud, not in main: replaces loud"),
            ]:
                Path(folder, "main.def").write_text(entry.format(replaces))
                with self.subTest(replaces), self.assertRaisesRegex(DefException, message):
                    self.run_lines(f"use {folder}/main")
                self.e._imported.discard(Path(folder, "main.def").resolve())
            self.assertEqual(self.run_lines("loud hi", "    hi", "hi"), "HI")  # still the first one
            Path(folder, "main.def").write_text(entry.format("    replaces loud\n"))
            self.run_lines(f"use {folder}/main")
            self.assertEqual(self.run_lines("loud hey", "    hey", "hey"), "HEY!")
            self.assertEqual(self.run_lines("hi"), "HI!")  # a def made before it runs with it too
        with self.assertRaisesRegex(DefException, "language odd replaces nothing"):
            self.run_lines("language odd", "    replaces core")

    def test_an_internal_def_is_seen_only_by_its_file(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "kernel.def").write_text(
                "modifier internal\n    applies to definition\n    does\n        TARGET.internal = True\n")
            Path(folder, "bmi.def").write_text(
                "use kernel\ninternal def A0 halved\n    A0 / 2\npython A0 / A1\n    return A0 / A1\n"
                "def bmi of A0\n    A0 halved\n")
            self.run_lines(f"use {folder}/bmi")
            self.assertEqual(self.run_lines("bmi of 10"), 5)  # its own def sees it, from here too
            with self.assertRaisesRegex(DefException, "unknown name '10 halved'"):
                self.run_lines("10 halved")


class TestTheTree(unittest.TestCase):
    """The Python API: what the interpreter has is the kernel's tree, self[...]."""

    def setUp(self):
        self.said = []
        self.e = Execute(output=lambda value: self.said.append(str(value)))

    def run_lines(self, *lines):
        result = None
        for line in lines:
            result = self.e.run(line)
        return result

    def test_its_keys(self):
        self.assertEqual(sorted(self.e.keys()), ["aliases", "answer", "definitions", "file", "files", "flag", "language",
                                                 "modifier", "program", "shared", "statement", "store", "variables"])
        with self.assertRaisesRegex(DefException, "the kernel has no 'color'"):
            self.e["color"]

    def test_a_body_reads_and_changes_it(self):
        self.run_lines("python[written] A0 is A1", "    self['variables'][A0] = self.run(A1)",
                       "python[written] A0 means A1", "    self['aliases'][A0] = A1",
                       "python count A0", "    self['store']['mine'].setdefault('n', 0)", "    self['store']['mine']['n'] += A0",
                       "python A0 ?", "    self['answer'] = bool(A0)",
                       "python A0 * A1", "    return A0 * A1")
        self.run_lines("x is 2 * 3")
        self.assertEqual(self.e["variables"]["x"], 6)
        self.run_lines("twice means 2 *")
        self.assertEqual(self.run_lines("twice 4"), 8)
        self.run_lines("count 2", "count 3")
        self.assertEqual(self.e["store"]["mine"], {"n": 5})
        self.run_lines("0 ?")
        self.assertIs(self.e["answer"], False)
        self.assertEqual([d.source for d in self.e["definitions"]][:2], ["A0 is A1", "A0 means A1"])

    def test_only_the_answer_is_set(self):
        self.run_lines("python break it", "    self['variables'] = {}")
        with self.assertRaisesRegex(DefException, "self\\['variables'\\] isn't replaced"):
            self.run_lines("break it")

    def test_a_files_place(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "counter.def").write_text(
                "comment is #\nindent 2\npython[written] A0 is A1\n  self['variables'][A0] = self.run(A1)\n"
                "modifier shared\n  applies to name\n  does\n    here = self['file']\n"
                "    self['files'][here]['names'][TARGET] = (here, TARGET)\nshared visits is 3\nlocal is 1\n")
            self.e.program_dir = Path(folder)
            self.run_lines("use visits from counter")
            counter = Path(folder, "counter.def").resolve()
            place = self.e["files"][counter]
            self.assertEqual((place["comment"], place["argument"], place["indent"]), ("#", "A", 2))
            self.assertEqual(place["variables"], {"local": 1})
            self.assertEqual(place["names"], {"visits": (counter, "visits")})
            self.assertEqual(self.e["shared"], {(counter, "visits"): 3})
            self.assertEqual(self.e["files"][None]["names"], {"visits": (counter, "visits")})
            self.assertEqual(self.run_lines("visits"), 3)
            self.assertEqual(self.e["program"], Path(folder))


class TestJavaScript(DefTest):
    def setUp(self):
        super().setUp()
        self.run_lines("use language/javascript")

    def test_arguments_are_javascript_values(self):
        self.run_lines("javascript greet A0", "    alert(A0)")
        self.assertEqual(self.run_lines('greet "Sam"'), 'alert("Sam")')
        self.assertEqual(self.run_lines("greet [1, 2]"), "alert([1, 2])")

    def test_a_value_cannot_end_the_script(self):
        self.run_lines("javascript greet A0", "    alert(A0)")
        self.assertEqual(self.run_lines('greet "</script>"'), 'alert("<\\/script>")')

    def test_javascript_comments_stay_in_the_body(self):
        self.run_lines("javascript note", "    // keep me", "    go()")
        self.assertEqual(self.run_lines("note"), "// keep me\ngo()")

    def test_a_view_runs_its_script(self):
        package = SAMPLES / "website"
        e = Execute(output=lambda value: None)
        e.program_dir = package
        for line in (package / "main.def").read_text().splitlines():
            if line.startswith("start the server"):
                break
            e.run(line)
        page = e.run("site page")
        self.assertIn('<template def="bmi view">', page)
        self.assertIn('<script def="count the characters left">', page)
        self.assertIn("input.maxLength - input.value.length", page)
        self.assertIn("new Function('view', script.textContent)(view)", page)
        # nothing was escaped: each part is a def's own code
        self.assertNotIn("&lt;", page)



class TestIndent(unittest.TestCase):
    """Levels: a line one level deeper belongs to the line above it."""

    def setUp(self):
        self.said = []
        self.e = Execute(output=lambda value: self.said.append(value))
        self.lines("python say A0", "    self.say(A0)",
                   "python A0 > A1 ?", "    self['answer'] = number(A0) > number(A1)",
                   "python otherwise ?", "    self['answer'] = not self['answer']")
        self.said.clear()

    def lines(self, *lines):
        for line in lines:
            self.e.run(line)

    def test_a_line_belongs_to_the_line_one_level_up(self):
        self.lines("5 > 3 ?", '    say "a"', "    5 > 10 ?", '        say "b"', '    say "c"')
        self.assertEqual(self.said, ["a", "c"])

    def test_a_skipped_line_skips_the_lines_below_it(self):
        self.lines("1 > 3 ?", "    5 > 3 ?", '        say "no"', '    say "no"', 'say "yes"')
        self.assertEqual(self.said, ["yes"])

    def test_the_answer_of_its_own_level(self):
        # `otherwise ?` turns around `x > 3 ?`, not the deeper `x > 10 ?`
        self.lines("5 > 3 ?", '    say "big"', "    5 > 10 ?", '        say "huge"', "otherwise ?", '    say "small"')
        self.assertEqual(self.said, ["big"])

    def test_indent_2_and_tabs(self):
        self.lines("indent 2", "5 > 3 ?", '  say "two"', "  5 > 4 ?", '    say "four"', "5 > 3 ?", '\tsay "tab"', '\t5 > 1 ?', '\t\tsay "tabs"')
        self.assertEqual(self.said, ["two", "four", "tab", "tabs"])

    def test_a_width_that_is_no_level(self):
        self.lines("5 > 3 ?")
        with self.assertRaisesRegex(DefException, "indented 2 spaces, but indent is 4: use a multiple of 4"):
            self.lines('  say "x"')

    def test_a_line_with_nothing_to_belong_to(self):
        self.lines("comment is //")  # ends the last def of setUp, like any unindented line
        with self.assertRaisesRegex(DefException, "no line above it to belong to"):
            self.lines('    say "x"')
        self.lines("5 > 3 ?")
        with self.assertRaisesRegex(DefException, "no line above it to belong to"):
            self.lines('        say "two levels down"')

    def test_levels_in_a_def_lang_body(self):
        self.lines("def tell A0", "    A0 > 3 ?", '        say "big"', "    otherwise ?", '        say "small"', "tell 5", "tell 1")
        self.assertEqual(self.said, ["big", "small"])

    def test_a_body_written_with_indent_2_runs_anywhere(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "two.def").write_text('indent 2\ndef tell A0\n  A0 > 3 ?\n    say "big"\n')
            self.lines(f"use {Path(folder, 'two')}")
            self.lines("tell 5")  # called from a file with indent 4
            self.assertEqual(self.said, ["big"])
            self.lines("5 > 3 ?", '    say "four"')  # and this file still has indent 4
            self.assertEqual(self.said, ["big", "four"])

    def test_a_def_call_has_its_own_levels(self):
        # the question inside `check` doesn't change which of the caller's lines run
        self.lines("def check A0", "    A0 > 100 ?", '        say "never"', "5 > 3 ?", "    check 1", '    say "still runs"')
        self.assertEqual(self.said, ["still runs"])

    def test_indent_is_per_file(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "inner.def").write_text("indent 2\n")
            self.lines(f"use {Path(folder, 'inner')}", "5 > 3 ?", '    say "four is the indent here"')
            self.assertEqual(self.said, ["four is the indent here"])


class TestTextPatterns(unittest.TestCase):
    """`"A0"` in a pattern: a text stands there."""

    def run_lines(self, e, *lines):
        result = None
        for line in lines:
            result = e.run(line)
        return result

    def test_a_text_argument_matches_only_text(self):
        e = Execute()
        self.run_lines(e, 'python shout "A0"', "    return A0.upper()")
        self.assertEqual(e.run('shout "hi"'), "HI")
        with self.assertRaises(DefException):
            e.run("shout 5")

    def test_joined_text_binds_by_order(self):
        join = ['python A0 "A1" A2', 'python "A0" A1', 'python A0 "A1"', '    return "".join(as_text(v) for v in a)']
        plus = ["python A0 + A1", "    return number(A0) + number(A1)"]
        made_after = Execute()
        self.run_lines(made_after, *join, *plus)
        self.assertEqual(made_after.run('"x = " 2 + 3'), "x = 5")
        made_before = Execute()
        self.run_lines(made_before, *plus, *join)
        with self.assertRaisesRegex(DefException, "expected a number"):
            made_before.run('"x = " 2 + 3')  # ("x = " 2) + 3

    def test_text_joins_here_is_gone(self):
        with self.assertRaisesRegex(DefException, "unknown name"):
            Execute().run("text joins here")


class TestCheck(unittest.TestCase):
    """`def-lang check`: errors without running anything."""

    def problems(self, text, texts=None):
        from deflang.check import check
        with tempfile.TemporaryDirectory() as folder:
            link_libraries(folder, "core")
            main = Path(folder, "main.def").resolve()
            main.write_text(text)
            found, _ = check(main, main.parent, {main: texts} if texts is not None else None)
            return [(line, message) for _, line, message in found]

    def test_a_good_program_has_none(self):
        self.assertEqual(self.problems("use core\nx is 5\nsay x + 1\nx > 3?\n    say x\n"), [])

    def test_the_errors_a_line_can_have(self):
        found = self.problems(
            "use core\nuse nothing\nsay y\nsay \"open\nrepeat 2 times: say z\n"
            "python broken A0\n    return (A0\n")
        lines = {line for line, _ in found}
        self.assertEqual(lines, {2, 3, 4, 5, 6})
        self.assertIn("unknown name 'z'", dict(found)[5])
        self.assertIn("syntax error", dict(found)[6])

    def test_nothing_runs(self):
        # no question asked, no output, and an error line doesn't stop it
        self.assertEqual(self.problems("use core\ngive weight\nsay weight\nerror stop\nsay weight\n"), [])

    def test_means_is_read(self):
        self.assertEqual(self.problems("use core\nadd means +\nsay 2 add 3\n"), [])

    def test_the_text_given_instead_of_the_file(self):
        self.assertEqual(self.problems("use core\n", texts="use core\nsay nope\n"), [(2, "unknown name 'nope'")])

    def test_the_examples_have_none(self):
        from deflang.check import check
        root = SAMPLES
        for name in ["website/main.def", "bmi/main.def", "times-table/main.def", "black-jack/main.def", "hello-world/main.def"]:
            with self.subTest(name):
                found, _ = check((root / name).resolve(), (root / name).resolve().parent)
                self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
