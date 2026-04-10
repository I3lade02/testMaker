import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from gift_formatter_core import (
    apply_quick_fix,
    convert_blocks_with_positions,
    csv_text_to_blocks,
    evaluate_question,
    export_questions_by_category,
    import_gift_to_blocks,
    run_cli,
)


class GiftFormatterCoreTests(unittest.TestCase):
    def test_duplicate_answer_key_is_error(self):
        text = "Question:\na) First\na) Second\n"

        output, issues, stats, fixes, questions = convert_blocks_with_positions(text)

        self.assertEqual(output, "")
        self.assertEqual(fixes, 0)
        self.assertEqual(questions, [])
        self.assertEqual(stats.blocks_error, 1)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, "error")
        self.assertIn("duplicated", issues[0].message)

    def test_empty_answer_text_is_error(self):
        text = "Question:\na)\n"

        output, issues, stats, fixes, questions = convert_blocks_with_positions(text)

        self.assertEqual(output, "")
        self.assertEqual(fixes, 0)
        self.assertEqual(questions, [])
        self.assertEqual(stats.blocks_error, 1)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, "error")
        self.assertIn("has no text", issues[0].message)

    def test_missing_correct_without_default_errors(self):
        text = "Question:\na) First\nb) Second\n"

        output, issues, stats, fixes, questions = convert_blocks_with_positions(
            text,
            assume_default_if_unmarked=False,
        )

        self.assertEqual(output, "")
        self.assertEqual(fixes, 0)
        self.assertEqual(questions, [])
        self.assertEqual(stats.blocks_error, 1)
        self.assertEqual(len(issues), 1)
        self.assertIn("default not allowed", issues[0].message)

    def test_tolerant_mode_autocorrects_answer_prefixes(self):
        text = "Question:\nA. * Correct\nb ) Wrong\n"

        output, issues, stats, fixes, questions = convert_blocks_with_positions(
            text,
            tolerant=True,
        )

        self.assertEqual(issues, [])
        self.assertGreaterEqual(fixes, 2)
        self.assertEqual(stats.blocks_ok, 1)
        self.assertEqual(
            output,
            "Question {\n=Correct\n~Wrong\n}",
        )
        self.assertEqual(questions[0].correct_indices, [0])

    def test_multiple_correct_penalize_weights(self):
        text = "Question:\na)* Correct 1\nb) Wrong 1\nc)* Correct 2\nd) Wrong 2\n"

        output, issues, stats, fixes, questions = convert_blocks_with_positions(
            text,
            multi_mode="penalize",
        )

        self.assertEqual(issues, [])
        self.assertEqual(fixes, 0)
        self.assertEqual(stats.blocks_ok, 1)
        self.assertEqual(
            output,
            "Question {\n"
            "~%50%Correct 1\n"
            "~%-50%Wrong 1\n"
            "~%50%Correct 2\n"
            "~%-50%Wrong 2\n"
            "}",
        )
        self.assertEqual(questions[0].correct_indices, [0, 2])

    def test_special_characters_are_escaped(self):
        text = r"Question {1}:" + "\n" + r"a) A ~ B = C # D { E } \\ F" + "\n"

        output, issues, stats, fixes, questions = convert_blocks_with_positions(text)

        self.assertEqual(issues, [])
        self.assertEqual(fixes, 0)
        self.assertEqual(stats.blocks_ok, 1)
        self.assertEqual(
            output,
            "Question \\{1\\} {\n=A \\~ B \\= C \\# D \\{ E \\} \\\\\\\\ F\n}",
        )
        self.assertEqual(questions[0].question, "Question {1}")
        self.assertEqual(questions[0].answers, [r"A ~ B = C # D { E } \\ F"])

    def test_translate_callback_is_used_for_issue_messages(self):
        text = "Question:\na)\n"

        def translate(key, **kwargs):
            if key == "issue_empty_answer_text":
                return f"PRELOZENO {kwargs['answer_key']}"
            return key

        output, issues, stats, fixes, questions = convert_blocks_with_positions(
            text,
            translate=translate,
        )

        self.assertEqual(output, "")
        self.assertEqual(fixes, 0)
        self.assertEqual(questions, [])
        self.assertEqual(stats.blocks_error, 1)
        self.assertEqual(issues[0].message, "PRELOZENO a")

    def test_category_and_generated_titles_are_exported(self):
        text = "First question:\na) One\n\nSecond question:\na) Two\n"

        output, issues, stats, fixes, questions = convert_blocks_with_positions(
            text,
            category="Grammar",
            question_name_prefix="Q",
            question_name_start=3,
        )

        self.assertEqual(issues, [])
        self.assertEqual(fixes, 0)
        self.assertEqual(stats.blocks_ok, 2)
        self.assertEqual(
            output,
            "$CATEGORY: Grammar\n\n"
            "::Q3::First question {\n=One\n}\n\n"
            "::Q4::Second question {\n=Two\n}",
        )
        self.assertEqual([question.title for question in questions], ["Q3", "Q4"])

    def test_optional_feedback_is_appended_to_answers(self):
        text = "Question:\na)* Correct\nb) Wrong\n"

        output, issues, stats, fixes, questions = convert_blocks_with_positions(
            text,
            correct_feedback="Nice job",
            incorrect_feedback="Try again",
        )

        self.assertEqual(issues, [])
        self.assertEqual(fixes, 0)
        self.assertEqual(stats.blocks_ok, 1)
        self.assertEqual(
            output,
            "Question {\n=Correct#Nice job\n~Wrong#Try again\n}",
        )
        self.assertEqual(questions[0].correct_indices, [0])

    def test_cli_writes_output_with_metadata_options(self):
        input_text = "Question:\na)* First\nb) Second\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "quiz.txt"
            output_path = Path(tmpdir) / "quiz.gift"
            input_path.write_text(input_text, encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = run_cli(
                    [
                        str(input_path),
                        "-o",
                        str(output_path),
                        "--category",
                        "Science",
                        "--name-prefix",
                        "Quiz",
                        "--correct-feedback",
                        "Correct",
                        "--incorrect-feedback",
                        "Incorrect",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "$CATEGORY: Science\n\n"
                "::Quiz1::Question {\n"
                "=First#Correct\n"
                "~Second#Incorrect\n"
                "}\n",
            )

    def test_cli_returns_error_when_explicit_correct_answer_is_required(self):
        input_text = "Question:\na) First\nb) Second\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "quiz.txt"
            input_path.write_text(input_text, encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = run_cli([str(input_path), "--no-default"])

            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("ERROR block 1", stderr.getvalue())
            self.assertIn("default not allowed", stderr.getvalue())

    def test_shortanswer_type_exports_and_scores(self):
        text = "@type: shortanswer\nCapital of France:\na)* Paris\nb)* PARIS\nc) London\n"

        output, issues, stats, fixes, questions = convert_blocks_with_positions(text)

        self.assertEqual(stats.blocks_ok, 1)
        self.assertEqual(len(issues), 1)
        self.assertIn("ignore incorrect answer lines", issues[0].message)
        self.assertEqual(
            output,
            "Capital of France {\n=Paris\n=PARIS\n}",
        )
        result = evaluate_question(questions[0], "paris")
        self.assertTrue(result.is_correct)
        self.assertEqual(result.score, 1.0)

    def test_numerical_type_exports_and_scores(self):
        text = "@type: numerical\nPi rounded:\na)* 3.14 +/- 0.01\nb) 3.0\n"

        output, issues, stats, fixes, questions = convert_blocks_with_positions(text)

        self.assertEqual(stats.blocks_ok, 1)
        self.assertEqual(len(issues), 1)
        self.assertIn("ignore incorrect answer lines", issues[0].message)
        self.assertEqual(output, "Pi rounded {#3.14:0.01}")
        self.assertTrue(evaluate_question(questions[0], "3.145").is_correct)
        self.assertFalse(evaluate_question(questions[0], "3.5").is_correct)

    def test_matching_type_exports_and_scores(self):
        text = "@type: matching\nMatch capitals:\na) Prague -> Czechia\nb) Vienna -> Austria\n"

        output, issues, stats, fixes, questions = convert_blocks_with_positions(text)

        self.assertEqual(issues, [])
        self.assertEqual(stats.blocks_ok, 1)
        self.assertEqual(
            output,
            "Match capitals {\n=Prague -> Czechia\n=Vienna -> Austria\n}",
        )
        result = evaluate_question(
            questions[0],
            {"Prague": "Czechia", "Vienna": "Austria"},
        )
        self.assertTrue(result.is_correct)
        self.assertEqual(result.score, 1.0)

    def test_gift_roundtrip_imports_back_to_editable_blocks(self):
        gift_text = (
            "$CATEGORY: Grammar\n\n"
            "::Q1::Sky color {\n"
            "=Blue#Good\n"
            "~Green#Nope\n"
            "}\n\n"
            "::Q2::Earth is flat {FALSE#Correct#Wrong}\n"
        )

        blocks, issues, questions = import_gift_to_blocks(gift_text)

        self.assertEqual(issues, [])
        self.assertIn("@category: Grammar", blocks)
        self.assertIn("@name: Q1", blocks)
        self.assertIn("@feedback_correct: Good", blocks)
        self.assertIn("@type: truefalse", blocks)
        self.assertEqual(len(questions), 2)

    def test_duplicate_similarity_detection_adds_warning(self):
        text = (
            "Capital of France:\na)* Paris\nb) London\n\n"
            "Capital of France:\na)* Paris\nb) London\n"
        )

        output, issues, stats, fixes, questions = convert_blocks_with_positions(text)

        self.assertEqual(stats.blocks_ok, 2)
        self.assertEqual(len(questions), 2)
        self.assertTrue(any(issue.code == "issue_duplicate_question" for issue in issues))
        self.assertIn("Capital of France", output)

    def test_quick_fix_can_renumber_answers(self):
        block = "Question:\na) One\na) Two\n"

        fixed = apply_quick_fix(block, "renumber_answers")

        self.assertEqual(
            fixed,
            "Question:\na) One\nb) Two",
        )

    def test_export_questions_by_category_splits_outputs(self):
        text = (
            "@category: Math\nWhat is one plus zero?\na)* One\n\n"
            "@category: Science\nChemical symbol for oxygen?\na)* O\n"
        )

        output, issues, stats, fixes, questions = convert_blocks_with_positions(text)
        split = export_questions_by_category(questions)

        self.assertEqual(issues, [])
        self.assertEqual(stats.blocks_ok, 2)
        self.assertIn("math", split)
        self.assertIn("science", split)
        self.assertIn("$CATEGORY: Math", split["math"])
        self.assertIn("$CATEGORY: Science", split["science"])
        self.assertIn("What is one plus zero", output)

    def test_csv_import_builds_blocks(self):
        csv_text = "question,a,b,correct\nCapital?,Prague,Brno,a\n"

        blocks, issues = csv_text_to_blocks(csv_text)

        self.assertEqual(issues, [])
        self.assertEqual(
            blocks,
            "Capital?\na)* Prague\nb) Brno",
        )


if __name__ == "__main__":
    unittest.main()
