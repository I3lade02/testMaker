import argparse
import csv
import difflib
import io
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


APP_VERSION = "0.6.0"

Translator = Optional[Callable[..., str]]

QUESTION_TYPES = ("multiple", "truefalse", "shortanswer", "numerical", "matching")

CORE_MESSAGES: Dict[str, str] = {
    "issue_no_blocks": "No question blocks found.",
    "issue_block_too_short": "Block is too short (needs question + at least 1 answer).",
    "issue_bad_answer_format": "Answer line doesn't match 'a) ...' or '1) ...' format: {line}",
    "issue_duplicate_answer_key": "Answer key '{answer_key}' is duplicated within the block.",
    "issue_empty_answer_text": "Answer '{answer_key}' has no text.",
    "issue_no_correct_and_default_disabled": "No correct answer marked with ')*' and default not allowed.",
    "issue_correct_keys_missing": "Correct key(s) {keys} not found in answers; used first answer '{fallback}' instead.",
    "issue_invalid_question_type": "Unsupported question type '{question_type}'.",
    "issue_truefalse_requires_two_answers": "True/False blocks need exactly two answers.",
    "issue_shortanswer_wrong_ignored": "Short-answer blocks ignore incorrect answer lines; only marked answers are exported.",
    "issue_numerical_wrong_ignored": "Numerical blocks ignore incorrect answer lines; only the first correct answer is exported.",
    "issue_invalid_numerical_answer": "Numerical answer '{answer}' is not valid. Use e.g. '42' or '42 +/- 0.5'.",
    "issue_matching_answer_format": "Matching answers must use 'left -> right' format: {line}",
    "issue_duplicate_question": "Looks like a duplicate of block {other_block}.",
    "issue_similar_question": "Looks very similar to block {other_block}.",
    "issue_gift_unparsed_tail": "Some trailing text could not be parsed as GIFT.",
    "issue_gift_bad_question": "Could not parse one GIFT question near '{snippet}'.",
    "issue_csv_no_question_column": "CSV import requires a 'question' column.",
}


def _message(translate: Translator, message_key: str, **kwargs: Any) -> str:
    if translate is not None:
        try:
            translated = translate(message_key, **kwargs)
        except Exception:
            translated = message_key
        if translated != message_key:
            return translated

    template = CORE_MESSAGES.get(message_key, message_key)
    return template.format(**kwargs) if kwargs else template


BLOCK_SPLIT_RE = re.compile(r"\n\s*\n+", re.MULTILINE)
ANSWER_RE = re.compile(r"^\s*([a-zA-Z]|\d+)\)\s*(.*)\s*$")
MARKED_CORRECT_RE = re.compile(r"^\s*([a-zA-Z]|\d+)\)\*\s*(.*)\s*$")
TOLERANT_PREFIX_RE = re.compile(r"^\s*([a-zA-Z]|\d+)\s*[\)\.]\s*(\*)?\s*(.*)\s*$")
DIRECTIVE_RE = re.compile(r"^\s*@([a-zA-Z_]+)\s*:\s*(.*)\s*$")
NUMERICAL_RE = re.compile(
    r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*(?:(?:\+/-|±|:)\s*([-+]?\d+(?:[.,]\d+)?))?\s*$"
)


@dataclass
class BlockSpan:
    start: int
    end: int
    text: str


@dataclass
class ConvertIssue:
    block_index: int
    message: str
    start: int
    end: int
    severity: str
    code: str = ""


@dataclass
class Stats:
    blocks_total: int = 0
    blocks_ok: int = 0
    blocks_error: int = 0
    warnings: int = 0
    answers_min: int = 0
    answers_max: int = 0
    answers_avg: float = 0.0
    unmarked_correct: int = 0


@dataclass
class QuestionItem:
    question: str
    answers: List[str] = field(default_factory=list)
    correct_indices: List[int] = field(default_factory=list)
    title: str = ""
    question_type: str = "multiple"
    category: str = ""
    correct_feedback: str = ""
    incorrect_feedback: str = ""
    general_feedback: str = ""
    accepted_answers: List[str] = field(default_factory=list)
    matching_pairs: List[Tuple[str, str]] = field(default_factory=list)
    numerical_value: Optional[float] = None
    numerical_tolerance: float = 0.0
    block_index: int = 0
    start: int = 0
    end: int = 0
    answer_feedback: Dict[int, str] = field(default_factory=dict)
    source_text: str = ""


@dataclass
class EvaluationResult:
    is_correct: bool
    score: float
    feedback: str = ""
    correct_answer: str = ""


def iter_blocks_with_spans(text: str) -> List[BlockSpan]:
    if not text.strip():
        return []

    text_stripped = text.strip("\n")
    if not text_stripped.strip():
        return []

    blocks: List[BlockSpan] = []
    last = 0

    for match in BLOCK_SPLIT_RE.finditer(text_stripped):
        start = last
        end = match.start()
        block = text_stripped[start:end].strip()
        if block:
            blocks.append(BlockSpan(start=start, end=end, text=block))
        last = match.end()

    if last < len(text_stripped):
        block = text_stripped[last:].strip()
        if block:
            blocks.append(BlockSpan(start=last, end=len(text_stripped), text=block))

    offset = text.find(text_stripped)
    if offset == -1:
        offset = 0
    for block in blocks:
        block.start += offset
        block.end += offset

    return blocks


def normalize_question_line(question: str) -> str:
    question = question.strip()
    if question.endswith("?") or question.endswith(":"):
        question = question[:-1].rstrip()
    return question


def text_without_last_incomplete_block(full_text: str) -> str:
    blocks = iter_blocks_with_spans(full_text)
    if not blocks:
        return full_text

    last = blocks[-1]
    lines = [line.strip() for line in last.text.splitlines() if line.strip()]
    if len(lines) < 2:
        return full_text[: last.start].rstrip()

    answer_lines = lines[1:]
    has_any_answer_prefix = any(
        ANSWER_RE.match(line) or MARKED_CORRECT_RE.match(line) for line in answer_lines
    )
    if not has_any_answer_prefix and not any("->" in line for line in answer_lines):
        return full_text[: last.start].rstrip()

    return full_text


def distribute_weights(count: int, total: float, decimals: int = 3) -> List[float]:
    if count <= 0:
        return []
    if count == 1:
        return [round(total, decimals)]
    raw = total / count
    weights = [round(raw, decimals) for _ in range(count)]
    partial_sum = sum(weights[:-1])
    weights[-1] = round(total - partial_sum, decimals)
    return weights


def fmt_pct(value: float, decimals: int = 3) -> str:
    pct = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    if pct == "-0":
        pct = "0"
    return pct


def format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def escape_gift_text(text: str) -> str:
    escaped = text.replace("\\", "\\\\")
    for char in ("~", "=", "#", "{", "}"):
        escaped = escaped.replace(char, "\\" + char)
    return escaped


def unescape_gift_text(text: str) -> str:
    output: List[str] = []
    escape_next = False
    for char in text:
        if escape_next:
            output.append(char)
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        output.append(char)
    if escape_next:
        output.append("\\")
    return "".join(output)


def sanitize_single_line(text: str) -> str:
    return " ".join(part.strip() for part in text.splitlines() if part.strip()).strip()


def build_question_title(prefix: str, number: int) -> str:
    prefix = sanitize_single_line(prefix)
    if not prefix:
        return ""
    return f"{prefix}{number}"


def format_question_header(question: str, title: str) -> str:
    escaped_question = escape_gift_text(question)
    if not title:
        return escaped_question

    safe_title = sanitize_single_line(title).replace("::", " - ")
    return f"::{safe_title}::{escaped_question}"


def format_answer_feedback(answer_text: str, feedback_text: str) -> str:
    rendered = escape_gift_text(answer_text)
    feedback_text = sanitize_single_line(feedback_text)
    if feedback_text:
        rendered += "#" + escape_gift_text(feedback_text)
    return rendered


def normalize_question_type(question_type: str) -> str:
    value = sanitize_single_line(question_type).lower().replace("-", "").replace("_", "")
    aliases = {
        "": "multiple",
        "multiple": "multiple",
        "multichoice": "multiple",
        "choice": "multiple",
        "mcq": "multiple",
        "truefalse": "truefalse",
        "tf": "truefalse",
        "shortanswer": "shortanswer",
        "short": "shortanswer",
        "sa": "shortanswer",
        "numerical": "numerical",
        "number": "numerical",
        "numeric": "numerical",
        "matching": "matching",
        "match": "matching",
    }
    return aliases.get(value, "")


def generate_answer_key(index: int) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    if index < len(alphabet):
        return alphabet[index]
    return str(index + 1)


def split_feedback_text(text: str) -> Tuple[str, str]:
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "#":
            return text[:index].strip(), unescape_gift_text(text[index + 1 :].strip())
    return text.strip(), ""


def similarity_signature(question: QuestionItem) -> str:
    pieces = [normalize_question_line(question.question).lower(), question.question_type]
    if question.question_type == "matching":
        for left, right in question.matching_pairs:
            pieces.append(left.lower())
            pieces.append(right.lower())
    elif question.question_type == "shortanswer":
        pieces.extend(answer.lower() for answer in question.accepted_answers)
    elif question.question_type == "numerical":
        if question.numerical_value is not None:
            pieces.append(format_number(question.numerical_value))
            pieces.append(format_number(question.numerical_tolerance))
    else:
        pieces.extend(answer.lower() for answer in question.answers)
        pieces.extend(str(index) for index in question.correct_indices)
    combined = " ".join(pieces)
    return re.sub(r"\W+", " ", combined).strip()


def question_summary(question: QuestionItem) -> str:
    if question.question_type == "matching":
        return "; ".join(f"{left} -> {right}" for left, right in question.matching_pairs)
    if question.question_type == "shortanswer":
        return ", ".join(question.accepted_answers)
    if question.question_type == "numerical" and question.numerical_value is not None:
        if question.numerical_tolerance > 0:
            return f"{format_number(question.numerical_value)} +/- {format_number(question.numerical_tolerance)}"
        return format_number(question.numerical_value)
    return ", ".join(question.answers)


def parse_numeric_answer(answer_text: str) -> Optional[Tuple[float, float]]:
    match = NUMERICAL_RE.match(answer_text.replace(",", "."))
    if not match:
        return None
    value = float(match.group(1))
    tolerance = float(match.group(2)) if match.group(2) is not None else 0.0
    return value, abs(tolerance)


def split_block_directives(block_text: str) -> Tuple[Dict[str, str], List[str]]:
    directives: Dict[str, str] = {}
    content_lines: List[str] = []
    question_seen = False

    for raw_line in block_text.splitlines():
        stripped = raw_line.strip()
        if not question_seen:
            match = DIRECTIVE_RE.match(raw_line)
            if match:
                directives[match.group(1).strip().lower()] = match.group(2).strip()
                continue
            if not stripped:
                continue
            question_seen = True
        content_lines.append(raw_line)

    return directives, content_lines


def autocorrect_answer_line(line: str) -> Tuple[str, int]:
    original = line
    stripped = line.strip()
    stripped = re.sub(r"\t+", " ", stripped)
    stripped = re.sub(r" {2,}", " ", stripped)

    match = TOLERANT_PREFIX_RE.match(stripped)
    if not match:
        marked = re.match(r"^\s*([a-zA-Z]|\d+)\)\*\s*(.*)\s*$", stripped)
        if marked:
            key = marked.group(1)
            rest = marked.group(2).strip()
            key_norm = key.lower() if key.isalpha() else key
            fixed = f"{key_norm})* {rest}".rstrip()
            return fixed, 0 if fixed == original.strip() else 1
        return original.rstrip(), 0

    key = match.group(1)
    star = match.group(2)
    rest = (match.group(3) or "").strip()
    key_norm = key.lower() if key.isalpha() else key
    fixed = f"{key_norm})* {rest}".rstrip() if star else f"{key_norm}) {rest}".rstrip()
    return fixed, 0 if fixed == original.strip() else 1


def autocorrect_block_text(block_text: str) -> Tuple[str, int]:
    directives, content_lines = split_block_directives(block_text)
    fixes = 0
    output_lines: List[str] = []

    for key, value in directives.items():
        output_lines.append(f"@{key}: {value}")

    seen_question = False
    for line in content_lines:
        raw = line.rstrip("\n")
        if not seen_question:
            if raw.strip():
                seen_question = True
            output_lines.append(raw.rstrip())
            continue
        if raw.strip() == "":
            output_lines.append(raw)
            continue
        fixed, line_fixes = autocorrect_answer_line(raw)
        output_lines.append(fixed)
        fixes += line_fixes

    return "\n".join(output_lines).strip(), fixes


def parse_standard_answers(
    raw_answers: List[str],
    tolerant: bool,
    translate: Translator,
) -> Tuple[Optional[List[Tuple[str, str, bool]]], Optional[Tuple[str, str]], int]:
    answers: List[Tuple[str, str, bool]] = []
    seen_keys = set()
    fixes = 0

    for raw_line in raw_answers:
        working_line = raw_line
        if tolerant:
            working_line, line_fixes = autocorrect_answer_line(raw_line)
            fixes += line_fixes

        marked = MARKED_CORRECT_RE.match(working_line)
        if marked:
            key = marked.group(1).strip()
            key_norm = key.lower() if key.isalpha() else key
            text = marked.group(2).strip()
            if key_norm in seen_keys:
                return None, ("issue_duplicate_answer_key", key_norm), fixes
            if not text:
                return None, ("issue_empty_answer_text", key_norm), fixes
            seen_keys.add(key_norm)
            answers.append((key_norm, text, True))
            continue

        match = ANSWER_RE.match(working_line)
        if not match:
            return None, ("issue_bad_answer_format", raw_line.strip()), fixes

        key = match.group(1).strip()
        key_norm = key.lower() if key.isalpha() else key
        text = match.group(2).strip()
        if key_norm in seen_keys:
            return None, ("issue_duplicate_answer_key", key_norm), fixes
        if not text:
            return None, ("issue_empty_answer_text", key_norm), fixes
        seen_keys.add(key_norm)
        answers.append((key_norm, text, False))

    return answers, None, fixes


def resolve_correct_keys(
    answers: List[Tuple[str, str, bool]],
    default_correct_key: str,
    assume_default_if_unmarked: bool,
) -> Tuple[Optional[List[str]], List[Tuple[str, Dict[str, str]]], bool]:
    default_key_norm = default_correct_key.lower() if default_correct_key.isalpha() else default_correct_key
    marked = [key for key, _text, is_marked in answers if is_marked]
    local_issues: List[Tuple[str, Dict[str, str]]] = []
    used_default = False

    if not marked:
        if not assume_default_if_unmarked:
            return None, [("issue_no_correct_and_default_disabled", {})], False
        marked = [default_key_norm]
        used_default = True

    keys_in_block = [key for key, _text, _is_marked in answers]
    missing = [key for key in marked if key not in keys_in_block]
    if missing:
        fallback = keys_in_block[0]
        local_issues.append(
            (
                "issue_correct_keys_missing",
                {"keys": ", ".join(missing), "fallback": fallback},
            )
        )
        marked = [fallback]

    deduped: List[str] = []
    seen = set()
    for key in marked:
        if key not in seen:
            deduped.append(key)
            seen.add(key)

    return deduped, local_issues, used_default


def build_multiple_question(
    question_text: str,
    answers: List[Tuple[str, str, bool]],
    correct_keys: List[str],
    metadata: Dict[str, str],
) -> QuestionItem:
    answer_texts = [text for _key, text, _marked in answers]
    correct_indices = [index for index, (key, _text, _marked) in enumerate(answers) if key in correct_keys]
    return QuestionItem(
        question=normalize_question_line(question_text),
        answers=answer_texts,
        correct_indices=correct_indices,
        question_type="multiple",
        category=sanitize_single_line(metadata.get("category", "")),
        title=sanitize_single_line(metadata.get("name", "")),
        correct_feedback=sanitize_single_line(metadata.get("feedback_correct", "")),
        incorrect_feedback=sanitize_single_line(metadata.get("feedback_incorrect", "")),
        general_feedback=sanitize_single_line(metadata.get("feedback_general", "")),
    )


def build_truefalse_question(
    question_text: str,
    answers: List[Tuple[str, str, bool]],
    correct_keys: List[str],
    metadata: Dict[str, str],
) -> QuestionItem:
    correct_key = correct_keys[0]
    correct_index = next((index for index, (key, _text, _marked) in enumerate(answers) if key == correct_key), 0)
    correct_bool = 0 if correct_index == 0 else 1
    return QuestionItem(
        question=normalize_question_line(question_text),
        answers=["True", "False"],
        correct_indices=[correct_bool],
        question_type="truefalse",
        category=sanitize_single_line(metadata.get("category", "")),
        title=sanitize_single_line(metadata.get("name", "")),
        correct_feedback=sanitize_single_line(metadata.get("feedback_correct", "")),
        incorrect_feedback=sanitize_single_line(metadata.get("feedback_incorrect", "")),
        general_feedback=sanitize_single_line(metadata.get("feedback_general", "")),
    )


def build_shortanswer_question(
    question_text: str,
    answers: List[Tuple[str, str, bool]],
    correct_keys: List[str],
    metadata: Dict[str, str],
) -> QuestionItem:
    accepted_answers = [text for key, text, _marked in answers if key in correct_keys]
    return QuestionItem(
        question=normalize_question_line(question_text),
        answers=list(accepted_answers),
        correct_indices=list(range(len(accepted_answers))),
        accepted_answers=list(accepted_answers),
        question_type="shortanswer",
        category=sanitize_single_line(metadata.get("category", "")),
        title=sanitize_single_line(metadata.get("name", "")),
        correct_feedback=sanitize_single_line(metadata.get("feedback_correct", "")),
        incorrect_feedback=sanitize_single_line(metadata.get("feedback_incorrect", "")),
        general_feedback=sanitize_single_line(metadata.get("feedback_general", "")),
    )


def build_numerical_question(
    question_text: str,
    answers: List[Tuple[str, str, bool]],
    correct_keys: List[str],
    metadata: Dict[str, str],
) -> Tuple[Optional[QuestionItem], Optional[Tuple[str, Dict[str, str]]]]:
    answer_text = next((text for key, text, _marked in answers if key in correct_keys), answers[0][1])
    parsed = parse_numeric_answer(answer_text)
    if parsed is None:
        return None, ("issue_invalid_numerical_answer", {"answer": answer_text})
    value, tolerance = parsed
    return (
        QuestionItem(
            question=normalize_question_line(question_text),
            answers=[answer_text],
            correct_indices=[0],
            accepted_answers=[answer_text],
            numerical_value=value,
            numerical_tolerance=tolerance,
            question_type="numerical",
            category=sanitize_single_line(metadata.get("category", "")),
            title=sanitize_single_line(metadata.get("name", "")),
            correct_feedback=sanitize_single_line(metadata.get("feedback_correct", "")),
            incorrect_feedback=sanitize_single_line(metadata.get("feedback_incorrect", "")),
            general_feedback=sanitize_single_line(metadata.get("feedback_general", "")),
        ),
        None,
    )


def build_matching_question(
    question_text: str,
    raw_answers: List[str],
    tolerant: bool,
    metadata: Dict[str, str],
) -> Tuple[Optional[QuestionItem], Optional[Tuple[str, Dict[str, str]]], int]:
    matching_pairs: List[Tuple[str, str]] = []
    fixes = 0

    for raw_line in raw_answers:
        line = raw_line
        if tolerant:
            line, line_fixes = autocorrect_answer_line(raw_line)
            fixes += line_fixes

        match = MARKED_CORRECT_RE.match(line) or ANSWER_RE.match(line)
        if match:
            pair_text = match.group(2).strip()
        else:
            pair_text = raw_line.strip()

        if "->" not in pair_text:
            return None, ("issue_matching_answer_format", {"line": raw_line.strip()}), fixes
        left, right = [part.strip() for part in pair_text.split("->", 1)]
        if not left or not right:
            return None, ("issue_matching_answer_format", {"line": raw_line.strip()}), fixes
        matching_pairs.append((left, right))

    return (
        QuestionItem(
            question=normalize_question_line(question_text),
            answers=[left for left, _right in matching_pairs],
            matching_pairs=matching_pairs,
            question_type="matching",
            category=sanitize_single_line(metadata.get("category", "")),
            title=sanitize_single_line(metadata.get("name", "")),
            correct_feedback=sanitize_single_line(metadata.get("feedback_correct", "")),
            incorrect_feedback=sanitize_single_line(metadata.get("feedback_incorrect", "")),
            general_feedback=sanitize_single_line(metadata.get("feedback_general", "")),
        ),
        None,
        fixes,
    )


def parse_block(
    block_text: str,
    default_correct_key: str = "a",
    assume_default_if_unmarked: bool = True,
    tolerant: bool = False,
    translate: Translator = None,
) -> Tuple[Optional[QuestionItem], Optional[ConvertIssue], List[Tuple[str, Dict[str, str]]], int, bool]:
    directives, content_lines = split_block_directives(block_text)
    lines = [line.strip() for line in content_lines if line.strip()]
    if len(lines) < 2:
        return (
            None,
            ConvertIssue(0, _message(translate, "issue_block_too_short"), 0, 0, "error", "issue_block_too_short"),
            [],
            0,
            False,
        )

    question_text = lines[0]
    raw_answers = lines[1:]
    question_type = normalize_question_type(directives.get("type", "multiple"))
    if not question_type:
        raw_type = directives.get("type", "")
        return (
            None,
            ConvertIssue(
                0,
                _message(translate, "issue_invalid_question_type", question_type=raw_type),
                0,
                0,
                "error",
                "issue_invalid_question_type",
            ),
            [],
            0,
            False,
        )

    local_warnings: List[Tuple[str, Dict[str, str]]] = []

    if question_type == "matching":
        question, error, fixes = build_matching_question(question_text, raw_answers, tolerant, directives)
        if error is not None:
            return (
                None,
                ConvertIssue(
                    0,
                    _message(translate, error[0], **error[1]),
                    0,
                    0,
                    "error",
                    error[0],
                ),
                [],
                fixes,
                False,
            )
        return question, None, local_warnings, fixes, False

    parsed_answers, error_info, fixes = parse_standard_answers(raw_answers, tolerant=tolerant, translate=translate)
    if error_info is not None:
        key, value = error_info
        kwargs = {"answer_key": value} if "answer_key" in key or "empty_answer" in key else {"line": value}
        return (
            None,
            ConvertIssue(0, _message(translate, key, **kwargs), 0, 0, "error", key),
            [],
            fixes,
            False,
        )

    answers = parsed_answers or []
    correct_keys, correct_issues, used_default = resolve_correct_keys(
        answers,
        default_correct_key=default_correct_key,
        assume_default_if_unmarked=assume_default_if_unmarked,
    )
    if correct_keys is None:
        issue_key, issue_kwargs = correct_issues[0]
        return (
            None,
            ConvertIssue(0, _message(translate, issue_key, **issue_kwargs), 0, 0, "error", issue_key),
            [],
            fixes,
            False,
        )
    local_warnings.extend(correct_issues)

    if question_type == "multiple":
        return build_multiple_question(question_text, answers, correct_keys, directives), None, local_warnings, fixes, used_default

    if question_type == "truefalse":
        if len(answers) != 2:
            return (
                None,
                ConvertIssue(
                    0,
                    _message(translate, "issue_truefalse_requires_two_answers"),
                    0,
                    0,
                    "error",
                    "issue_truefalse_requires_two_answers",
                ),
                [],
                fixes,
                used_default,
            )
        return build_truefalse_question(question_text, answers, correct_keys, directives), None, local_warnings, fixes, used_default

    if question_type == "shortanswer":
        if any(key not in correct_keys for key, _text, _marked in answers):
            local_warnings.append(("issue_shortanswer_wrong_ignored", {}))
        return build_shortanswer_question(question_text, answers, correct_keys, directives), None, local_warnings, fixes, used_default

    if question_type == "numerical":
        if any(key not in correct_keys for key, _text, _marked in answers):
            local_warnings.append(("issue_numerical_wrong_ignored", {}))
        question, error = build_numerical_question(question_text, answers, correct_keys, directives)
        if error is not None:
            return (
                None,
                ConvertIssue(0, _message(translate, error[0], **error[1]), 0, 0, "error", error[0]),
                [],
                fixes,
                used_default,
            )
        return question, None, local_warnings, fixes, used_default

    return (
        None,
        ConvertIssue(
            0,
            _message(translate, "issue_invalid_question_type", question_type=question_type),
            0,
            0,
            "error",
            "issue_invalid_question_type",
        ),
        [],
        fixes,
        False,
    )


def render_multiple_question(question: QuestionItem, multi_mode: str, pct_decimals: int) -> List[str]:
    output_lines = [f"{format_question_header(question.question, question.title)} {{"]
    correct_indices = list(question.correct_indices)

    if len(correct_indices) <= 1:
        correct_index = correct_indices[0] if correct_indices else 0
        for answer_index, text in enumerate(question.answers):
            prefix = "=" if answer_index == correct_index else "~"
            feedback_text = question.correct_feedback if answer_index == correct_index else question.incorrect_feedback
            output_lines.append(prefix + format_answer_feedback(text, feedback_text))
        output_lines.append("}")
        return output_lines

    correct_weights = distribute_weights(len(correct_indices), 100.0, decimals=pct_decimals)
    correct_weight_map = {index: weight for index, weight in zip(correct_indices, correct_weights)}

    wrong_indices = [index for index in range(len(question.answers)) if index not in correct_weight_map]
    wrong_weight_map: Dict[int, float] = {}
    if str(multi_mode) == "wipe":
        wrong_weight_map = {index: -100.0 for index in wrong_indices}
    elif str(multi_mode) == "penalize" and wrong_indices:
        wrong_weights = distribute_weights(len(wrong_indices), -100.0, decimals=pct_decimals)
        wrong_weight_map = {index: weight for index, weight in zip(wrong_indices, wrong_weights)}

    for index, text in enumerate(question.answers):
        feedback_text = question.correct_feedback if index in correct_weight_map else question.incorrect_feedback
        rendered_text = format_answer_feedback(text, feedback_text)
        if index in correct_weight_map:
            output_lines.append(f"~%{fmt_pct(correct_weight_map[index], pct_decimals)}%{rendered_text}")
        elif index in wrong_weight_map:
            output_lines.append(f"~%{fmt_pct(wrong_weight_map[index], pct_decimals)}%{rendered_text}")
        else:
            output_lines.append("~" + rendered_text)

    output_lines.append("}")
    return output_lines


def render_question_to_gift(question: QuestionItem, multi_mode: str = "wipe", pct_decimals: int = 3) -> str:
    qtype = normalize_question_type(question.question_type)
    header = format_question_header(normalize_question_line(question.question), question.title)

    if qtype == "multiple":
        return "\n".join(render_multiple_question(question, multi_mode=multi_mode, pct_decimals=pct_decimals))

    if qtype == "truefalse":
        correct_bool = bool(question.correct_indices and question.correct_indices[0] == 0)
        token = "TRUE" if correct_bool else "FALSE"
        if question.correct_feedback or question.incorrect_feedback:
            token += f"#{escape_gift_text(question.correct_feedback)}#{escape_gift_text(question.incorrect_feedback)}"
        return f"{header} {{{token}}}"

    if qtype == "shortanswer":
        lines = [f"{header} {{"]
        accepted_answers = question.accepted_answers or question.answers
        for answer in accepted_answers:
            lines.append("=" + format_answer_feedback(answer, question.correct_feedback))
        lines.append("}")
        return "\n".join(lines)

    if qtype == "numerical":
        value = question.numerical_value if question.numerical_value is not None else 0.0
        spec = format_number(value)
        if question.numerical_tolerance > 0:
            spec += ":" + format_number(question.numerical_tolerance)
        return f"{header} {{#{spec}}}"

    if qtype == "matching":
        lines = [f"{header} {{"]
        for left, right in question.matching_pairs:
            lines.append("=" + escape_gift_text(left) + " -> " + escape_gift_text(right))
        lines.append("}")
        return "\n".join(lines)

    return f"{header} {{}}"


def render_questions_to_gift(
    questions: Sequence[QuestionItem],
    global_category: str = "",
    question_name_prefix: str = "",
    question_name_start: int = 1,
    multi_mode: str = "wipe",
    pct_decimals: int = 3,
) -> str:
    outputs: List[str] = []
    current_category = ""
    start_number = max(1, question_name_start)

    for offset, original_question in enumerate(questions):
        question = QuestionItem(**original_question.__dict__)
        if not question.title and question_name_prefix:
            question.title = build_question_title(question_name_prefix, start_number + offset)

        category = sanitize_single_line(question.category or global_category)
        question.category = category
        if category and category != current_category:
            outputs.append(f"$CATEGORY: {category}")
            current_category = category

        outputs.append(render_question_to_gift(question, multi_mode=multi_mode, pct_decimals=pct_decimals))

    return "\n\n".join(outputs).strip()


def analyze_similarity(
    questions: Sequence[QuestionItem],
    blocks: Sequence[BlockSpan],
    translate: Translator = None,
    threshold: float = 0.88,
) -> List[ConvertIssue]:
    issues: List[ConvertIssue] = []
    signatures: List[str] = []
    prompts: List[str] = []

    for index, question in enumerate(questions):
        signature = similarity_signature(question)
        prompt = re.sub(r"\W+", " ", question.question.lower()).strip()
        signatures.append(signature)
        prompts.append(prompt)

        for other_index in range(index):
            if signature and signature == signatures[other_index]:
                issues.append(
                    ConvertIssue(
                        question.block_index,
                        _message(translate, "issue_duplicate_question", other_block=questions[other_index].block_index),
                        question.start,
                        question.end,
                        "warning",
                        "issue_duplicate_question",
                    )
                )
                break

            if not prompt or not prompts[other_index]:
                continue
            ratio = difflib.SequenceMatcher(None, prompt, prompts[other_index]).ratio()
            if ratio >= threshold:
                issues.append(
                    ConvertIssue(
                        question.block_index,
                        _message(translate, "issue_similar_question", other_block=questions[other_index].block_index),
                        question.start,
                        question.end,
                        "warning",
                        "issue_similar_question",
                    )
                )
                break

    return issues


def convert_blocks_with_positions(
    all_text: str,
    default_correct_key: str = "a",
    assume_default_if_unmarked: bool = True,
    tolerant: bool = False,
    multi_mode: str = "wipe",
    pct_decimals: int = 3,
    category: str = "",
    question_name_prefix: str = "",
    question_name_start: int = 1,
    correct_feedback: str = "",
    incorrect_feedback: str = "",
    translate: Translator = None,
) -> Tuple[str, List[ConvertIssue], Stats, int, List[QuestionItem]]:
    blocks = iter_blocks_with_spans(all_text)
    stats = Stats(blocks_total=len(blocks))
    if not blocks:
        return (
            "",
            [ConvertIssue(0, _message(translate, "issue_no_blocks"), 0, 0, "error", "issue_no_blocks")],
            stats,
            0,
            [],
        )

    issues: List[ConvertIssue] = []
    questions: List[QuestionItem] = []
    fixes_total = 0
    answer_counts: List[int] = []

    for index, block in enumerate(blocks, start=1):
        question, error, local_warnings, fixes, used_default = parse_block(
            block.text,
            default_correct_key=default_correct_key,
            assume_default_if_unmarked=assume_default_if_unmarked,
            tolerant=tolerant,
            translate=translate,
        )
        fixes_total += fixes

        if error is not None:
            error.block_index = index
            error.start = block.start
            error.end = block.end
            issues.append(error)
            stats.blocks_error += 1
            continue

        assert question is not None
        question.block_index = index
        question.start = block.start
        question.end = block.end
        question.source_text = block.text

        if not question.category:
            question.category = sanitize_single_line(category)
        if not question.correct_feedback:
            question.correct_feedback = sanitize_single_line(correct_feedback)
        if not question.incorrect_feedback:
            question.incorrect_feedback = sanitize_single_line(incorrect_feedback)

        if used_default:
            stats.unmarked_correct += 1

        if not question.title and question_name_prefix:
            question.title = build_question_title(question_name_prefix, max(1, question_name_start) + len(questions))

        answer_count = len(question.answers) or len(question.accepted_answers) or len(question.matching_pairs)
        answer_counts.append(answer_count)
        stats.blocks_ok += 1
        questions.append(question)

        for issue_key, kwargs in local_warnings:
            issues.append(
                ConvertIssue(
                    index,
                    _message(translate, issue_key, **kwargs),
                    block.start,
                    block.end,
                    "warning",
                    issue_key,
                )
            )

    similarity_issues = analyze_similarity(questions, blocks, translate=translate)
    issues.extend(similarity_issues)

    stats.warnings = len([issue for issue in issues if issue.severity == "warning"])

    if answer_counts:
        stats.answers_min = min(answer_counts)
        stats.answers_max = max(answer_counts)
        stats.answers_avg = sum(answer_counts) / len(answer_counts)

    result = render_questions_to_gift(
        questions,
        global_category=category,
        question_name_prefix=question_name_prefix,
        question_name_start=question_name_start,
        multi_mode=multi_mode,
        pct_decimals=pct_decimals,
    )

    return result, issues, stats, fixes_total, questions


def _format_issue_lines(issues: Sequence[ConvertIssue]) -> List[str]:
    lines: List[str] = []
    for issue in issues:
        severity = issue.severity.upper()
        lines.append(f"{severity} block {issue.block_index}: {issue.message}")
    return lines


def split_gift_questions(gift_text: str) -> Tuple[List[Tuple[str, str, str, int, int]], List[ConvertIssue]]:
    items: List[Tuple[str, str, str, int, int]] = []
    issues: List[ConvertIssue] = []
    current_category = ""
    text = gift_text
    index = 0

    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break

        if text.startswith("$CATEGORY:", index):
            line_end = text.find("\n", index)
            if line_end == -1:
                line_end = len(text)
            current_category = text[index + 10 : line_end].strip()
            index = line_end + 1
            continue

        brace_start = text.find("{", index)
        if brace_start == -1:
            tail = text[index:].strip()
            if tail:
                issues.append(
                    ConvertIssue(
                        0,
                        _message(None, "issue_gift_unparsed_tail"),
                        index,
                        len(text),
                        "warning",
                        "issue_gift_unparsed_tail",
                    )
                )
            break

        header = text[index:brace_start].strip()
        body_start = brace_start + 1
        body_end = body_start
        escaped = False
        while body_end < len(text):
            char = text[body_end]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "}":
                break
            body_end += 1

        if body_end >= len(text):
            snippet = sanitize_single_line(text[index : min(len(text), index + 80)])
            issues.append(
                ConvertIssue(
                    0,
                    _message(None, "issue_gift_bad_question", snippet=snippet),
                    index,
                    len(text),
                    "error",
                    "issue_gift_bad_question",
                )
            )
            break

        body = text[body_start:body_end].strip()
        items.append((current_category, header, body, index, body_end + 1))
        index = body_end + 1

    return items, issues


def parse_gift_header(header: str) -> Tuple[str, str]:
    header = header.strip()
    if header.startswith("::"):
        next_sep = header.find("::", 2)
        if next_sep != -1:
            title = unescape_gift_text(header[2:next_sep].strip())
            question = unescape_gift_text(header[next_sep + 2 :].strip())
            return title, question
    return "", unescape_gift_text(header.strip())


def parse_choice_line(line: str) -> Tuple[bool, str, str]:
    prefix = line[:1]
    remainder = line[1:].strip()
    correct = prefix == "="
    if prefix == "~" and remainder.startswith("%"):
        weight_end = remainder.find("%", 1)
        if weight_end != -1:
            try:
                weight = float(remainder[1:weight_end])
                correct = weight > 0
                remainder = remainder[weight_end + 1 :].strip()
            except Exception:
                pass
    answer_text, feedback = split_feedback_text(remainder)
    return correct, unescape_gift_text(answer_text), feedback


def parse_gift_to_questions(gift_text: str, translate: Translator = None) -> Tuple[List[QuestionItem], List[ConvertIssue]]:
    raw_items, issues = split_gift_questions(gift_text)
    questions: List[QuestionItem] = []

    for block_index, (category, header, body, start, end) in enumerate(raw_items, start=1):
        title, question_text = parse_gift_header(header)
        stripped_body = body.strip()
        question: Optional[QuestionItem] = None

        if stripped_body.upper().startswith("TRUE") or stripped_body.upper().startswith("FALSE"):
            correct_bool = stripped_body.upper().startswith("TRUE")
            parts = stripped_body.split("#")
            correct_feedback = unescape_gift_text(parts[1].strip()) if len(parts) > 1 else ""
            incorrect_feedback = unescape_gift_text(parts[2].strip()) if len(parts) > 2 else ""
            question = QuestionItem(
                question=question_text,
                title=title,
                category=category,
                question_type="truefalse",
                answers=["True", "False"],
                correct_indices=[0 if correct_bool else 1],
                correct_feedback=correct_feedback,
                incorrect_feedback=incorrect_feedback,
            )
        elif stripped_body.startswith("#"):
            spec = stripped_body[1:].strip()
            value_text = spec
            if "#" in spec:
                value_text = spec.split("#", 1)[0].strip()
            if ":" in value_text:
                number_text, tolerance_text = [part.strip() for part in value_text.split(":", 1)]
                value = float(number_text)
                tolerance = abs(float(tolerance_text))
            else:
                value = float(value_text)
                tolerance = 0.0
            question = QuestionItem(
                question=question_text,
                title=title,
                category=category,
                question_type="numerical",
                answers=[value_text],
                correct_indices=[0],
                accepted_answers=[value_text],
                numerical_value=value,
                numerical_tolerance=tolerance,
            )
        else:
            lines = [line.strip() for line in stripped_body.splitlines() if line.strip()]
            if lines and all(line.startswith("=") and "->" in line for line in lines):
                pairs: List[Tuple[str, str]] = []
                for line in lines:
                    pair_text = line[1:].strip()
                    left, right = [unescape_gift_text(part.strip()) for part in pair_text.split("->", 1)]
                    pairs.append((left, right))
                question = QuestionItem(
                    question=question_text,
                    title=title,
                    category=category,
                    question_type="matching",
                    answers=[left for left, _right in pairs],
                    matching_pairs=pairs,
                )
            elif lines and all(line.startswith("=") for line in lines):
                accepted_answers: List[str] = []
                correct_feedback = ""
                for line in lines:
                    _correct, answer_text, feedback = parse_choice_line(line)
                    accepted_answers.append(answer_text)
                    if feedback and not correct_feedback:
                        correct_feedback = feedback
                question = QuestionItem(
                    question=question_text,
                    title=title,
                    category=category,
                    question_type="shortanswer",
                    answers=list(accepted_answers),
                    correct_indices=list(range(len(accepted_answers))),
                    accepted_answers=accepted_answers,
                    correct_feedback=correct_feedback,
                )
            elif lines:
                answers: List[str] = []
                correct_indices: List[int] = []
                correct_feedback = ""
                incorrect_feedback = ""
                for line_index, line in enumerate(lines):
                    is_correct, answer_text, feedback = parse_choice_line(line)
                    answers.append(answer_text)
                    if is_correct:
                        correct_indices.append(line_index)
                        if feedback and not correct_feedback:
                            correct_feedback = feedback
                    elif feedback and not incorrect_feedback:
                        incorrect_feedback = feedback
                question = QuestionItem(
                    question=question_text,
                    title=title,
                    category=category,
                    question_type="multiple",
                    answers=answers,
                    correct_indices=correct_indices,
                    correct_feedback=correct_feedback,
                    incorrect_feedback=incorrect_feedback,
                )

        if question is None:
            snippet = sanitize_single_line(header)[:60] or "question"
            issues.append(
                ConvertIssue(
                    block_index,
                    _message(translate, "issue_gift_bad_question", snippet=snippet),
                    start,
                    end,
                    "error",
                    "issue_gift_bad_question",
                )
            )
            continue

        question.block_index = block_index
        question.start = start
        question.end = end
        questions.append(question)

    return questions, issues


def question_to_editable_block(question: QuestionItem) -> str:
    lines: List[str] = []
    qtype = normalize_question_type(question.question_type)
    if qtype and qtype != "multiple":
        lines.append(f"@type: {qtype}")
    if question.category:
        lines.append(f"@category: {question.category}")
    if question.title:
        lines.append(f"@name: {question.title}")
    if question.correct_feedback:
        lines.append(f"@feedback_correct: {question.correct_feedback}")
    if question.incorrect_feedback:
        lines.append(f"@feedback_incorrect: {question.incorrect_feedback}")
    if question.general_feedback:
        lines.append(f"@feedback_general: {question.general_feedback}")

    lines.append(question.question)

    if qtype == "truefalse":
        correct_index = question.correct_indices[0] if question.correct_indices else 0
        lines.append("a)* True" if correct_index == 0 else "a) True")
        lines.append("b)* False" if correct_index == 1 else "b) False")
        return "\n".join(lines)

    if qtype == "shortanswer":
        accepted_answers = question.accepted_answers or question.answers
        for index, answer in enumerate(accepted_answers):
            lines.append(f"{generate_answer_key(index)})* {answer}")
        return "\n".join(lines)

    if qtype == "numerical":
        value = question.numerical_value if question.numerical_value is not None else 0.0
        answer_text = format_number(value)
        if question.numerical_tolerance > 0:
            answer_text += f" +/- {format_number(question.numerical_tolerance)}"
        lines.append(f"a)* {answer_text}")
        return "\n".join(lines)

    if qtype == "matching":
        for index, (left, right) in enumerate(question.matching_pairs):
            lines.append(f"{generate_answer_key(index)}) {left} -> {right}")
        return "\n".join(lines)

    correct_set = set(question.correct_indices)
    for index, answer in enumerate(question.answers):
        suffix = ")*" if index in correct_set else ")"
        lines.append(f"{generate_answer_key(index)}{suffix} {answer}")
    return "\n".join(lines)


def import_gift_to_blocks(gift_text: str, translate: Translator = None) -> Tuple[str, List[ConvertIssue], List[QuestionItem]]:
    questions, issues = parse_gift_to_questions(gift_text, translate=translate)
    blocks = [question_to_editable_block(question) for question in questions]
    return "\n\n".join(blocks), issues, questions


def slugify_filename(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.strip().lower()).strip("-")
    return slug or "uncategorized"


def export_questions_by_category(
    questions: Sequence[QuestionItem],
    multi_mode: str = "wipe",
    pct_decimals: int = 3,
) -> Dict[str, str]:
    grouped: Dict[str, List[QuestionItem]] = defaultdict(list)
    for question in questions:
        grouped[sanitize_single_line(question.category) or "Uncategorized"].append(question)

    outputs: Dict[str, str] = {}
    for category, grouped_questions in grouped.items():
        outputs[slugify_filename(category)] = render_questions_to_gift(
            grouped_questions,
            question_name_prefix="",
            question_name_start=1,
            multi_mode=multi_mode,
            pct_decimals=pct_decimals,
        )
    return outputs


def available_quick_fixes(issue: ConvertIssue) -> List[str]:
    mapping = {
        "issue_bad_answer_format": ["autocorrect_block", "renumber_answers"],
        "issue_duplicate_answer_key": ["renumber_answers"],
        "issue_empty_answer_text": ["remove_empty_answers"],
        "issue_no_correct_and_default_disabled": ["mark_first_answer_correct"],
        "issue_truefalse_requires_two_answers": ["canonicalize_truefalse"],
        "issue_matching_answer_format": ["autocorrect_block"],
        "issue_invalid_numerical_answer": ["autocorrect_block"],
    }
    return mapping.get(issue.code, [])


def renumber_answer_lines(block_text: str) -> str:
    directives, content_lines = split_block_directives(block_text)
    output_lines = [f"@{key}: {value}" for key, value in directives.items()]
    seen_question = False
    answer_index = 0

    for raw_line in content_lines:
        stripped = raw_line.strip()
        if not seen_question:
            if stripped:
                seen_question = True
            output_lines.append(raw_line.rstrip())
            continue
        if not stripped:
            output_lines.append(raw_line)
            continue

        fixed_line, _ = autocorrect_answer_line(raw_line)
        marked = MARKED_CORRECT_RE.match(fixed_line)
        normal = ANSWER_RE.match(fixed_line)
        if marked or normal:
            text = (marked or normal).group(2).strip()
            suffix = ")*" if marked else ")"
            output_lines.append(f"{generate_answer_key(answer_index)}{suffix} {text}")
            answer_index += 1
        else:
            output_lines.append(raw_line.rstrip())

    return "\n".join(output_lines).strip()


def mark_first_answer_correct(block_text: str) -> str:
    directives, content_lines = split_block_directives(block_text)
    output_lines = [f"@{key}: {value}" for key, value in directives.items()]
    seen_question = False
    corrected = False

    for raw_line in content_lines:
        stripped = raw_line.strip()
        if not seen_question:
            if stripped:
                seen_question = True
            output_lines.append(raw_line.rstrip())
            continue
        if not stripped:
            output_lines.append(raw_line)
            continue

        fixed_line, _ = autocorrect_answer_line(raw_line)
        marked = MARKED_CORRECT_RE.match(fixed_line)
        normal = ANSWER_RE.match(fixed_line)
        match = marked or normal
        if match:
            key = match.group(1).strip()
            text = match.group(2).strip()
            suffix = ")*" if not corrected else ")"
            output_lines.append(f"{key}{suffix} {text}")
            corrected = True
        else:
            output_lines.append(raw_line.rstrip())

    return "\n".join(output_lines).strip()


def remove_empty_answer_lines(block_text: str) -> str:
    directives, content_lines = split_block_directives(block_text)
    output_lines = [f"@{key}: {value}" for key, value in directives.items()]
    seen_question = False

    for raw_line in content_lines:
        stripped = raw_line.strip()
        if not seen_question:
            if stripped:
                seen_question = True
            output_lines.append(raw_line.rstrip())
            continue
        if not stripped:
            output_lines.append(raw_line)
            continue

        fixed_line, _ = autocorrect_answer_line(raw_line)
        marked = MARKED_CORRECT_RE.match(fixed_line)
        normal = ANSWER_RE.match(fixed_line)
        match = marked or normal
        if match and not match.group(2).strip():
            continue
        output_lines.append(raw_line.rstrip())

    return "\n".join(output_lines).strip()


def canonicalize_truefalse(block_text: str) -> str:
    directives, content_lines = split_block_directives(block_text)
    directives["type"] = "truefalse"
    question_line = next((line.strip() for line in content_lines if line.strip()), "")
    raw_answers = [line for line in content_lines[1:] if line.strip()]
    correct_index = 0
    for index, raw in enumerate(raw_answers):
        fixed_line, _ = autocorrect_answer_line(raw)
        if MARKED_CORRECT_RE.match(fixed_line):
            correct_index = 0 if index == 0 else 1
            break

    lines = [f"@{key}: {value}" for key, value in directives.items()]
    if question_line:
        lines.append(question_line)
    lines.append("a)* True" if correct_index == 0 else "a) True")
    lines.append("b)* False" if correct_index == 1 else "b) False")
    return "\n".join(lines).strip()


def apply_quick_fix(block_text: str, fix_id: str) -> str:
    fixes = {
        "autocorrect_block": lambda text: autocorrect_block_text(text)[0],
        "renumber_answers": renumber_answer_lines,
        "mark_first_answer_correct": mark_first_answer_correct,
        "remove_empty_answers": remove_empty_answer_lines,
        "canonicalize_truefalse": canonicalize_truefalse,
    }
    func = fixes.get(fix_id)
    if func is None:
        return block_text
    return func(block_text)


def evaluate_question(question: QuestionItem, response: Any) -> EvaluationResult:
    qtype = normalize_question_type(question.question_type)

    if qtype in ("multiple", "truefalse"):
        selected = set(response if isinstance(response, (list, set, tuple)) else ([response] if response is not None else []))
        correct = set(question.correct_indices)
        is_correct = selected == correct
        feedback = question.correct_feedback if is_correct else question.incorrect_feedback
        return EvaluationResult(
            is_correct=is_correct,
            score=1.0 if is_correct else 0.0,
            feedback=feedback,
            correct_answer=", ".join(question.answers[index] for index in question.correct_indices),
        )

    if qtype == "shortanswer":
        typed = sanitize_single_line(str(response or "")).lower()
        accepted = [sanitize_single_line(answer).lower() for answer in question.accepted_answers]
        is_correct = typed in accepted
        return EvaluationResult(
            is_correct=is_correct,
            score=1.0 if is_correct else 0.0,
            feedback=question.correct_feedback if is_correct else question.incorrect_feedback,
            correct_answer=", ".join(question.accepted_answers),
        )

    if qtype == "numerical":
        try:
            value = float(str(response).replace(",", "."))
        except Exception:
            return EvaluationResult(
                is_correct=False,
                score=0.0,
                feedback=question.incorrect_feedback,
                correct_answer=question_summary(question),
            )
        target = question.numerical_value if question.numerical_value is not None else 0.0
        tolerance = abs(question.numerical_tolerance)
        is_correct = abs(value - target) <= tolerance
        return EvaluationResult(
            is_correct=is_correct,
            score=1.0 if is_correct else 0.0,
            feedback=question.correct_feedback if is_correct else question.incorrect_feedback,
            correct_answer=question_summary(question),
        )

    if qtype == "matching":
        response_map = response if isinstance(response, dict) else {}
        total = len(question.matching_pairs)
        if total == 0:
            return EvaluationResult(is_correct=False, score=0.0, correct_answer="")
        matches = 0
        for left, right in question.matching_pairs:
            if response_map.get(left) == right:
                matches += 1
        score = matches / total
        return EvaluationResult(
            is_correct=matches == total,
            score=score,
            feedback=question.correct_feedback if matches == total else question.incorrect_feedback,
            correct_answer=question_summary(question),
        )

    return EvaluationResult(is_correct=False, score=0.0)


def csv_text_to_blocks(csv_text: str, translate: Translator = None) -> Tuple[str, List[ConvertIssue]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        return "", [ConvertIssue(0, _message(translate, "issue_csv_no_question_column"), 0, 0, "error", "issue_csv_no_question_column")]

    field_map = {field.lower().strip(): field for field in reader.fieldnames}
    question_field = field_map.get("question")
    if question_field is None:
        return "", [ConvertIssue(0, _message(translate, "issue_csv_no_question_column"), 0, 0, "error", "issue_csv_no_question_column")]

    blocks: List[str] = []
    answer_columns = [
        field_map[key]
        for key in sorted(field_map)
        if key in {"a", "b", "c", "d", "e", "f"} or key.startswith("answer")
    ]

    for row in reader:
        question = sanitize_single_line(row.get(question_field, ""))
        if not question:
            continue

        qtype = normalize_question_type(row.get(field_map.get("type", ""), "")) if field_map.get("type") else "multiple"
        category = sanitize_single_line(row.get(field_map.get("category", ""), "")) if field_map.get("category") else ""
        title = sanitize_single_line(row.get(field_map.get("name", ""), "")) if field_map.get("name") else ""
        correct = sanitize_single_line(row.get(field_map.get("correct", ""), "")) if field_map.get("correct") else ""

        lines: List[str] = []
        if qtype and qtype != "multiple":
            lines.append(f"@type: {qtype}")
        if category:
            lines.append(f"@category: {category}")
        if title:
            lines.append(f"@name: {title}")
        lines.append(question)

        correct_tokens = {token.strip().lower() for token in correct.split(",") if token.strip()}
        for answer_index, column in enumerate(answer_columns):
            value = sanitize_single_line(row.get(column, ""))
            if not value:
                continue
            key = generate_answer_key(answer_index)
            marker = ")*" if key.lower() in correct_tokens or value.lower() in correct_tokens else ")"
            lines.append(f"{key}{marker} {value}")

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks), []


def _read_input_text(input_path: str) -> str:
    if input_path == "-":
        return sys.stdin.read()
    return Path(input_path).read_text(encoding="utf-8")


def _read_supported_input(input_path: str) -> str:
    if input_path == "-":
        return sys.stdin.read()

    path = Path(input_path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        blocks, issues = csv_text_to_blocks(path.read_text(encoding="utf-8"))
        if issues:
            raise ValueError(issues[0].message)
        return blocks
    return path.read_text(encoding="utf-8")


def run_cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Convert question blocks into Moodle GIFT format.")
    parser.add_argument("inputs", nargs="*", default=["-"], help="Input file path(s) or '-' for stdin.")
    parser.add_argument("-o", "--output", help="Write output to this file instead of stdout.")
    parser.add_argument("--output-dir", help="Write one output file per category into this directory.")
    parser.add_argument("--default-correct", default="a", help="Default correct answer key if none is marked.")
    parser.add_argument("--no-default", action="store_true", help="Require explicit ')*' marking.")
    parser.add_argument("--tolerant", action="store_true", help="Enable tolerant auto-fixes.")
    parser.add_argument("--multi-mode", choices=("wipe", "penalize"), default="wipe")
    parser.add_argument("--category", default="", help="Fallback category for exported questions.")
    parser.add_argument("--name-prefix", default="", help="Generated question name prefix.")
    parser.add_argument("--name-start", type=int, default=1, help="Starting number for generated names.")
    parser.add_argument("--correct-feedback", default="", help="Feedback appended to correct answers.")
    parser.add_argument("--incorrect-feedback", default="", help="Feedback appended to incorrect answers.")
    parser.add_argument("--import-gift", action="store_true", help="Convert GIFT back into editable blocks.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")

    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.import_gift:
            imported_blocks: List[str] = []
            all_issues: List[ConvertIssue] = []
            for input_path in args.inputs:
                text = _read_input_text(input_path)
                blocks_text, issues, _questions = import_gift_to_blocks(text)
                imported_blocks.append(blocks_text)
                all_issues.extend(issues)
            output = "\n\n".join(part for part in imported_blocks if part.strip())
            issues = all_issues
            questions: List[QuestionItem] = []
        else:
            parts = [_read_supported_input(input_path) for input_path in args.inputs]
            input_text = "\n\n".join(part.strip() for part in parts if part.strip())
            output, issues, _stats, _fixes, questions = convert_blocks_with_positions(
                input_text,
                default_correct_key=args.default_correct,
                assume_default_if_unmarked=not args.no_default,
                tolerant=args.tolerant,
                multi_mode=args.multi_mode,
                category=args.category,
                question_name_prefix=args.name_prefix,
                question_name_start=args.name_start,
                correct_feedback=args.correct_feedback,
                incorrect_feedback=args.incorrect_feedback,
            )
    except Exception as exc:
        print(f"Failed to read input: {exc}", file=sys.stderr)
        return 2

    issue_lines = _format_issue_lines(issues)
    if issue_lines:
        print("\n".join(issue_lines), file=sys.stderr)

    try:
        if args.output_dir and not args.import_gift:
            output_dir = Path(args.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in export_questions_by_category(questions, multi_mode=args.multi_mode).items():
                output_path = output_dir / f"{filename}.gift"
                output_path.write_text(content + ("\n" if content and not content.endswith("\n") else ""), encoding="utf-8")
        elif args.output:
            Path(args.output).write_text(output + ("\n" if output and not output.endswith("\n") else ""), encoding="utf-8")
        else:
            if output:
                sys.stdout.write(output)
                if not output.endswith("\n"):
                    sys.stdout.write("\n")
    except Exception as exc:
        print(f"Failed to write output: {exc}", file=sys.stderr)
        return 2

    has_errors = any(issue.severity == "error" for issue in issues)
    return 1 if has_errors else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
