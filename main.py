import re
import sys
from dataclasses import dataclass
from docx import Document
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from PySide6 import QtCore

from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtGui import (
    QAction,
    QIcon,
    QTextCursor,
    QTextCharFormat,
    QFont,
    QSyntaxHighlighter,
    QColor,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QComboBox,
    QCheckBox,
    QMessageBox,
    QFileDialog,
    QSplitter,
    QStatusBar,
    QMainWindow,
    QToolBar,
    QSizePolicy,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QGroupBox,
    QRadioButton,
    QButtonGroup,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QStyle,
)

# Split blocks by one or more blank lines
BLOCK_SPLIT_RE = re.compile(r"\n\s*\n+", re.MULTILINE)

# Canonical answer formats supported by the parser:
# a) text
# a)* text
# 1) text
# 1)* text
ANSWER_RE = re.compile(r"^\s*([a-zA-Z]|\d+)\)\s*(.*)\s*$")
MARKED_CORRECT_RE = re.compile(r"^\s*([a-zA-Z]|\d+)\)\*\s*(.*)\s*$")  # a)* / 1)*


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
    severity: str  # "error" or "warning"


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

LIGHT_QSS = """
QMainWindow { background: #f7f8fa; }
QToolBar { background: #ffffff; border-bottom: 1px solid #e6e6e6; padding: 6px; spacing: 6px; }
QToolButton { background: transparent; border: none; padding: 8px; border-radius: 10px; }
QToolButton:hover { background: #eef2ff; }
QToolButton:pressed { background: #e0e7ff; }
QToolButton:checked { background: #dbeafe; }

QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 8px;
    padding: 10px;
    font-family: "JetBrains Mono","Consolas",monospace;
    font-size: 13px;
}
QPlainTextEdit:focus { border: 1px solid #4f8cff; }

QComboBox {
    background: #ffffff;
    border: 1px solid #cfd6dd;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 14px;
}
QStatusBar { background: #ffffff; border-top: 1px solid #e6e6e6; }
"""

DARK_QSS = """
QMainWindow { background: #0f1115; color: #e7eaf0; }
QToolBar { background: #151924; border-bottom: 1px solid #252b3a; padding: 6px; spacing: 6px; }
QToolButton { background: transparent; border: none; padding: 8px; border-radius: 10px; color: #e7eaf0; }
QToolButton:hover { background: #222a3a; }
QToolButton:pressed { background: #2a3550; }
QToolButton:checked { background: #25314a; }

QLabel { color: #e7eaf0; }
QGroupBox { border: 1px solid #252b3a; border-radius: 8px; margin-top: 8px; color: #e7eaf0; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #cfd6e6; font-weight: bold; }

QPlainTextEdit {
    background: #0f141f;
    border: 1px solid #252b3a;
    border-radius: 8px;
    padding: 10px;
    color: #e7eaf0;
    selection-background-color: #2a3d66;
    font-family: "JetBrains Mono","Consolas",monospace;
    font-size: 13px;
}
QPlainTextEdit:focus { border: 1px solid #4f8cff; }

QComboBox {
    background: #0f141f;
    border: 1px solid #252b3a;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 14px;
    color: #e7eaf0;
}

QStatusBar { background: #151924; border-top: 1px solid #252b3a; color: #cfd6e6; }
"""


@dataclass
class QuestionItem:
    question: str
    answers: List[str]
    correct_indices: List[int]  # multiple correct supported


def iter_blocks_with_spans(text: str) -> List[BlockSpan]:
    if not text.strip():
        return []

    text_stripped = text.strip("\n")
    if not text_stripped.strip():
        return []

    blocks: List[BlockSpan] = []
    last = 0

    for m in BLOCK_SPLIT_RE.finditer(text_stripped):
        start = last
        end = m.start()
        block = text_stripped[start:end].strip()
        if block:
            blocks.append(BlockSpan(start=start, end=end, text=block))
        last = m.end()

    if last < len(text_stripped):
        block = text_stripped[last:].strip()
        if block:
            blocks.append(BlockSpan(start=last, end=len(text_stripped), text=block))

    offset = text.find(text_stripped)
    if offset == -1:
        offset = 0
    for b in blocks:
        b.start += offset
        b.end += offset

    return blocks


def normalize_question_line(q: str) -> str:
    q = q.strip()
    if q.endswith("?") or q.endswith(":"):
        q = q[:-1].rstrip()
    return q


def text_without_last_incomplete_block(full_text: str) -> str:
    """
    For auto-convert: ignore the last block if it's incomplete (draft).
    This prevents errors while the user is still typing.
    """
    blocks = iter_blocks_with_spans(full_text)
    if not blocks:
        return full_text

    last = blocks[-1]
    lines = [ln.strip() for ln in last.text.splitlines() if ln.strip()]

    # Incomplete if only question line or nothing
    if len(lines) < 2:
        return full_text[: last.start].rstrip()

    # If there are lines, but no answer-like prefixes yet, treat as draft
    answer_lines = lines[1:]
    has_any_answer_prefix = any(
        ANSWER_RE.match(ln) or MARKED_CORRECT_RE.match(ln) for ln in answer_lines
    )
    if not has_any_answer_prefix:
        return full_text[: last.start].rstrip()

    return full_text


# ---------- Multiple-correct export helpers ----------

def distribute_weights(count: int, total: float, decimals: int = 3) -> List[float]:
    """
    Returns `count` weights that sum to `total`, with rounding.
    The last value is adjusted to preserve exact sum (within float precision).
    """
    if count <= 0:
        return []
    if count == 1:
        return [round(total, decimals)]
    raw = total / count
    w = [round(raw, decimals) for _ in range(count)]
    s = sum(w[:-1])
    w[-1] = round(total - s, decimals)
    return w


def fmt_pct(x: float, decimals: int = 3) -> str:
    s = f"{x:.{decimals}f}".rstrip("0").rstrip(".")
    if s == "-0":
        s = "0"
    return s


# ---------- Tolerant auto-fix helpers ----------

TOLERANT_PREFIX_RE = re.compile(
    r"^\s*([a-zA-Z]|\d+)\s*[\)\.]\s*(\*)?\s*(.*)\s*$"
)


def autocorrect_answer_line(line: str) -> Tuple[str, int]:
    original = line
    s = line.strip()

    s = re.sub(r"\t+", " ", s)
    s = re.sub(r" {2,}", " ", s)

    m = TOLERANT_PREFIX_RE.match(s)
    if not m:
        m2 = re.match(r"^\s*([a-zA-Z]|\d+)\)\*\s*(.*)\s*$", s)
        if m2:
            key = m2.group(1)
            rest = m2.group(2).strip()
            key_norm = key.lower() if key.isalpha() else key
            fixed = f"{key_norm})* {rest}".rstrip()
            return fixed, (0 if fixed == original.strip() else 1)
        return original.rstrip(), 0

    key = m.group(1)
    star = m.group(2)
    rest = (m.group(3) or "").strip()

    key_norm = key.lower() if key.isalpha() else key
    if star:
        fixed = f"{key_norm})* {rest}".rstrip()
    else:
        fixed = f"{key_norm}) {rest}".rstrip()

    fixes = 0
    if fixed != original.strip():
        fixes = 1
    return fixed, fixes


def autocorrect_block_text(block_text: str) -> Tuple[str, int]:
    lines = block_text.splitlines()
    out_lines: List[str] = []
    fixes = 0

    seen_question = False
    for ln in lines:
        raw = ln.rstrip("\n")
        if not seen_question:
            if raw.strip() == "":
                out_lines.append(raw)
                continue
            out_lines.append(raw.rstrip())
            seen_question = True
            continue

        if raw.strip() == "":
            out_lines.append(raw)
            continue

        fixed, f = autocorrect_answer_line(raw)
        out_lines.append(fixed)
        fixes += f

    return "\n".join(out_lines), fixes


# ---------- Parsing / conversion ----------

def parse_block(
    block_text: str,
    tolerant: bool = False,
) -> Tuple[
    Optional[Tuple[str, List[Tuple[str, str, bool]], List[str]]],
    Optional[str],
    int
]:
    """
    Returns (question, answers, marked_correct_keys), error, fixes_count
    answers: list of (key, text, is_marked_correct)
    marked_correct_keys: list of keys (can be empty)
    """
    fixes = 0
    text_to_parse = block_text

    if tolerant:
        text_to_parse, fixes = autocorrect_block_text(block_text)

    lines = [ln.strip() for ln in text_to_parse.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None, "Block is too short (needs question + at least 1 answer).", fixes

    question = lines[0]
    raw_answers = lines[1:]

    answers: List[Tuple[str, str, bool]] = []
    marked_correct_keys: List[str] = []

    for ln in raw_answers:
        m_marked = MARKED_CORRECT_RE.match(ln)
        if m_marked:
            key = m_marked.group(1).strip()
            key_norm = key.lower() if key.isalpha() else key
            text = m_marked.group(2).strip()
            answers.append((key_norm, text, True))
            marked_correct_keys.append(key_norm)
            continue

        m = ANSWER_RE.match(ln)
        if not m:
            return None, f"Answer line doesn't match 'a) ...' or '1) ...' format: {ln}", fixes
        key = m.group(1).strip()
        key_norm = key.lower() if key.isalpha() else key
        text = m.group(2).strip()
        answers.append((key_norm, text, False))

    # Remove duplicates in marked_correct_keys while keeping order
    seen = set()
    dedup = []
    for k in marked_correct_keys:
        if k not in seen:
            dedup.append(k)
            seen.add(k)
    marked_correct_keys = dedup

    return (question, answers, marked_correct_keys), None, fixes


def convert_blocks_with_positions(
    all_text: str,
    default_correct_key: str = "a",
    assume_default_if_unmarked: bool = True,
    tolerant: bool = False,
    multi_mode: str = "wipe",  # "wipe" or "penalize"
    pct_decimals: int = 3,
) -> Tuple[str, List[ConvertIssue], Stats, int, List[QuestionItem]]:
    blocks = iter_blocks_with_spans(all_text)
    stats = Stats(blocks_total=len(blocks))
    if not blocks:
        return "", [ConvertIssue(0, "No question blocks found.", 0, 0, "error")], stats, 0, []

    outputs: List[str] = []
    issues: List[ConvertIssue] = []
    questions: List[QuestionItem] = []

    default_key_norm = default_correct_key.lower() if default_correct_key.isalpha() else default_correct_key
    answer_counts: List[int] = []
    fixes_total = 0

    for idx, block in enumerate(blocks, start=1):
        parsed, err, fixes = parse_block(block.text, tolerant=tolerant)
        fixes_total += fixes

        if err:
            issues.append(ConvertIssue(idx, err, block.start, block.end, "error"))
            stats.blocks_error += 1
            continue

        question, answers, marked_correct_keys = parsed
        answer_counts.append(len(answers))
        stats.blocks_ok += 1

        if not marked_correct_keys:
            stats.unmarked_correct += 1

        keys_in_block = [k for (k, _t, _m) in answers]

        correct_keys: List[str] = list(marked_correct_keys)

        if not correct_keys:
            if assume_default_if_unmarked:
                correct_keys = [default_key_norm]
            else:
                issues.append(
                    ConvertIssue(
                        idx,
                        "No correct answer marked with ')*' and default not allowed.",
                        block.start,
                        block.end,
                        "error",
                    )
                )
                stats.blocks_ok -= 1
                stats.blocks_error += 1
                continue

        missing = [k for k in correct_keys if k not in keys_in_block]
        if missing:
            fallback = keys_in_block[0]
            issues.append(
                ConvertIssue(
                    idx,
                    f"Correct key(s) {missing} not found in answers; used first answer '{fallback}' instead.",
                    block.start,
                    block.end,
                    "warning",
                )
            )
            stats.warnings += 1
            correct_keys = [fallback]

        is_multi = len(correct_keys) >= 2

        q_line = normalize_question_line(question)
        out_lines = [f"{q_line} {{"]

        ans_texts: List[str] = [t for (_k, t, _m) in answers]
        correct_indices: List[int] = []

        if not is_multi:
            correct_key = correct_keys[0]
            for i, (key, text, _is_marked) in enumerate(answers):
                prefix = "=" if key == correct_key else "~"
                out_lines.append(prefix + text)
                if key == correct_key:
                    correct_indices = [i]
            out_lines.append("}")
            outputs.append("\n".join(out_lines))
        else:
            # Multiple-correct: use ~%weights% style (matching your examples)
            c_weights = distribute_weights(len(correct_keys), 100.0, decimals=pct_decimals)
            correct_weight_map: Dict[str, float] = {k: w for k, w in zip(correct_keys, c_weights)}

            wrong_keys = [k for k in keys_in_block if k not in correct_keys]
            wrong_weight_map: Dict[str, float] = {}

            if str(multi_mode) == "wipe":
                # A) wipe: any wrong selection removes all points
                wrong_weight_map = {k: -100.0 for k in wrong_keys}
            elif str(multi_mode) == "penalize":
                # B) partial: split -100 across wrong answers
                if len(wrong_keys) > 0:
                    w_weights = distribute_weights(len(wrong_keys), -100.0, decimals=pct_decimals)
                    wrong_weight_map = {k: w for k, w in zip(wrong_keys, w_weights)}

            for i, (key, text, _is_marked) in enumerate(answers):
                if key in correct_weight_map:
                    w = correct_weight_map[key]
                    out_lines.append(f"~%{fmt_pct(w, pct_decimals)}%{text}")
                    correct_indices.append(i)
                else:
                    if key in wrong_weight_map:
                        w = wrong_weight_map[key]
                        out_lines.append(f"~%{fmt_pct(w, pct_decimals)}%{text}")
                    else:
                        out_lines.append("~" + text)

            out_lines.append("}")
            outputs.append("\n".join(out_lines))

        display_q = q_line
        if display_q.endswith(" ?"):
            display_q = display_q[:-2].rstrip()

        questions.append(
            QuestionItem(
                question=display_q,
                answers=ans_texts,
                correct_indices=correct_indices,
            )
        )

    stats.warnings = max(stats.warnings, len([i for i in issues if i.severity == "warning"]))

    if answer_counts:
        stats.answers_min = min(answer_counts)
        stats.answers_max = max(answer_counts)
        stats.answers_avg = sum(answer_counts) / len(answer_counts)

    return "\n\n".join(outputs), issues, stats, fixes_total, questions


# ---------- Input Highlighter ----------

class InputHighlighter(QSyntaxHighlighter):
    STATE_EXPECT_QUESTION = 0
    STATE_EXPECT_ANSWERS = 1

    def __init__(self, document):
        super().__init__(document)

        self.fmt_question = QTextCharFormat()
        self.fmt_question.setFontWeight(QFont.Bold)
        self.fmt_question.setForeground(QColor("#1f4e79"))

        self.fmt_correct = QTextCharFormat()
        self.fmt_correct.setForeground(QColor("#1b5e20"))
        self.fmt_correct.setFontWeight(QFont.DemiBold)

        self.fmt_error = QTextCharFormat()
        self.fmt_error.setForeground(QColor("#b71c1c"))
        self.fmt_error.setUnderlineStyle(QTextCharFormat.SingleUnderline)

        self.theme = "light"

    def highlightBlock(self, text: str):
        s = text.rstrip("\n")
        stripped = s.strip()

        if stripped == "":
            self.setCurrentBlockState(self.STATE_EXPECT_QUESTION)
            return

        prev_state = self.previousBlockState()
        if prev_state == -1:
            prev_state = self.STATE_EXPECT_QUESTION

        if prev_state == self.STATE_EXPECT_QUESTION:
            self.setFormat(0, len(s), self.fmt_question)
            self.setCurrentBlockState(self.STATE_EXPECT_ANSWERS)
            return

        if MARKED_CORRECT_RE.match(s):
            self.setFormat(0, len(s), self.fmt_correct)
        elif ANSWER_RE.match(s):
            pass
        else:
            self.setFormat(0, len(s), self.fmt_error)

        self.setCurrentBlockState(self.STATE_EXPECT_ANSWERS)


# ---------- Stats dialog ----------

class StatsDialog(QDialog):
    def __init__(self, parent: QWidget, tr_func, stats: Optional[Stats], fixes_count: int):
        super().__init__(parent)
        self.tr_ = tr_func
        self.setWindowTitle(self.tr_("stats_title"))
        self.setModal(False)

        layout = QVBoxLayout(self)
        self.form = QFormLayout()
        layout.addLayout(self.form)

        self.lbl_q = QLabel("-")
        self.lbl_ok = QLabel("-")
        self.lbl_err = QLabel("-")
        self.lbl_warn = QLabel("-")
        self.lbl_ans_min = QLabel("-")
        self.lbl_ans_max = QLabel("-")
        self.lbl_ans_avg = QLabel("-")
        self.lbl_unmarked = QLabel("-")
        self.lbl_fixes = QLabel("-")

        self.form.addRow(self.tr_("stats_questions"), self.lbl_q)
        self.form.addRow(self.tr_("stats_ok"), self.lbl_ok)
        self.form.addRow(self.tr_("stats_errors"), self.lbl_err)
        self.form.addRow(self.tr_("stats_warnings"), self.lbl_warn)
        self.form.addRow(self.tr_("stats_ans_min"), self.lbl_ans_min)
        self.form.addRow(self.tr_("stats_ans_max"), self.lbl_ans_max)
        self.form.addRow(self.tr_("stats_ans_avg"), self.lbl_ans_avg)
        self.form.addRow(self.tr_("stats_unmarked"), self.lbl_unmarked)
        self.form.addRow(self.tr_("stats_fixes"), self.lbl_fixes)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        buttons.accepted.connect(self.close)
        layout.addWidget(buttons)

        self.set_stats(stats, fixes_count)

    def set_stats(self, stats: Optional[Stats], fixes_count: int):
        if not stats or stats.blocks_total == 0:
            self.lbl_q.setText("0")
            self.lbl_ok.setText("0")
            self.lbl_err.setText("0")
            self.lbl_warn.setText("0")
            self.lbl_ans_min.setText("-")
            self.lbl_ans_max.setText("-")
            self.lbl_ans_avg.setText("-")
            self.lbl_unmarked.setText("0")
            self.lbl_fixes.setText(str(fixes_count))
            return

        self.lbl_q.setText(str(stats.blocks_total))
        self.lbl_ok.setText(str(stats.blocks_ok))
        self.lbl_err.setText(str(stats.blocks_error))
        self.lbl_warn.setText(str(stats.warnings))
        self.lbl_ans_min.setText(str(stats.answers_min))
        self.lbl_ans_max.setText(str(stats.answers_max))
        self.lbl_ans_avg.setText(f"{stats.answers_avg:.2f}")
        self.lbl_unmarked.setText(str(stats.unmarked_correct))
        self.lbl_fixes.setText(str(fixes_count))


# ---------- Issues dialog ----------

class IssuesDialog(QDialog):
    def __init__(self, parent: QWidget, tr_func, jump_callback):
        super().__init__(parent)
        self.tr_ = tr_func
        self.jump_callback = jump_callback
        self.setModal(False)
        self.setWindowTitle(self.tr_("issues_title"))

        layout = QVBoxLayout(self)

        self.listw = QListWidget()
        self.listw.itemDoubleClicked.connect(self._on_open)
        layout.addWidget(self.listw)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.close)
        btns.accepted.connect(self.close)
        layout.addWidget(btns)

        self.resize(760, 420)

    def set_issues(self, issues: List[ConvertIssue]):
        self.listw.clear()

        if not issues:
            item = QListWidgetItem(self.tr_("issues_empty"))
            item.setFlags(Qt.NoItemFlags)
            self.listw.addItem(item)
            return

        ordered = sorted(issues, key=lambda x: (0 if x.severity == "error" else 1, x.block_index))

        for it in ordered:
            prefix = "ERROR" if it.severity == "error" else "WARNING"
            text = f"[{prefix}] Block {it.block_index}: {it.message}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, (it.start, it.end))
            self.listw.addItem(item)

    def _on_open(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if not data:
            return
        start, end = data
        self.jump_callback(start, end)


# ---------- Preview (Student view) ----------

class PreviewDialog(QDialog):
    def __init__(self, parent: QWidget, tr_func):
        super().__init__(parent)
        self.tr_ = tr_func
        self.setWindowTitle(self.tr_("preview_title"))
        self.setModal(False)

        self.questions: List[QuestionItem] = []
        self.index = 0

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.lbl_counter = QLabel("")
        top_row.addWidget(self.lbl_counter)
        top_row.addStretch(1)

        self.cb_show_correct = QCheckBox(self.tr_("preview_show_correct"))
        self.cb_show_correct.setChecked(False)
        self.cb_show_correct.stateChanged.connect(self._render)
        top_row.addWidget(self.cb_show_correct)

        layout.addLayout(top_row)

        self.lbl_question = QLabel("")
        self.lbl_question.setWordWrap(True)
        self.lbl_question.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.lbl_question)

        self.group_box = QGroupBox(self.tr_("preview_answers"))
        gb_layout = QVBoxLayout(self.group_box)
        layout.addWidget(self.group_box)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)
        self.answer_buttons: List[QRadioButton] = []
        self._answers_layout = gb_layout

        nav = QHBoxLayout()
        self.btn_prev = QPushButton("◀ " + self.tr_("preview_prev"))
        self.btn_next = QPushButton(self.tr_("preview_next") + " ▶")
        self.btn_prev.clicked.connect(self.prev_q)
        self.btn_next.clicked.connect(self.next_q)
        nav.addWidget(self.btn_prev)
        nav.addStretch(1)
        nav.addWidget(self.btn_next)
        layout.addLayout(nav)

        close_btns = QDialogButtonBox(QDialogButtonBox.Close)
        close_btns.rejected.connect(self.close)
        close_btns.accepted.connect(self.close)
        layout.addWidget(close_btns)

        self.resize(650, 520)

    def set_questions(self, questions: List[QuestionItem], start_index: int = 0):
        self.questions = questions or []
        self.index = max(0, min(start_index, len(self.questions) - 1)) if self.questions else 0
        self._render()

    def _clear_answers(self):
        for btn in self.answer_buttons:
            self.btn_group.removeButton(btn)
            btn.deleteLater()
        self.answer_buttons = []

    def _render(self):
        if not self.questions:
            self.lbl_counter.setText(self.tr_("preview_empty"))
            self.lbl_question.setText("")
            self._clear_answers()
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            return

        q = self.questions[self.index]
        self.lbl_counter.setText(self.tr_("preview_counter", i=self.index + 1, n=len(self.questions)))
        self.lbl_question.setText(q.question)

        self._clear_answers()

        show_correct = self.cb_show_correct.isChecked()
        correct_set = set(q.correct_indices or [])

        for i, ans in enumerate(q.answers):
            rb = QRadioButton(ans)
            self.btn_group.addButton(rb, i)
            self._answers_layout.addWidget(rb)
            self.answer_buttons.append(rb)

            if show_correct and i in correct_set:
                rb.setStyleSheet("font-weight: 900; font-size: 14px;")
            else:
                rb.setStyleSheet("")

        self.btn_prev.setEnabled(self.index > 0)
        self.btn_next.setEnabled(self.index < len(self.questions) - 1)

    def prev_q(self):
        if self.index > 0:
            self.index -= 1
            self._render()

    def next_q(self):
        if self.index < len(self.questions) - 1:
            self.index += 1
            self._render()

class FileDropPlainTextEdit(QPlainTextEdit):
    """
    QPlainTextEdit that accepts file drag&drop and emits local file paths
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self.on_file_dropped = None #callback(path: str) -> None
        
    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md and md.hasUrls():
            urls = md.urls()
            if urls and urls[0].isLocalFile():
                event.acceptProposedAction()
                return
        event.ignore()
        
    def dropEvent(self, event):
        md = event.mimeData()
        if md and md.hasUrls():
            for url in md.urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    if callable(self.on_file_dropped):
                        self.on_file_dropped(path)
                    break
                event.acceptProposedAction()
                return
            event.ignore()
# ---------- Main window ----------

class GiftFormatterMainWindow(QMainWindow):
    ORG_NAME = "Testovac"
    APP_NAME = "GiftFormatter"

    def __init__(self, icon_path: Optional[Path] = None):
        super().__init__()
        self.icon_path = icon_path
        if icon_path and icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.settings = QSettings(self.ORG_NAME, self.APP_NAME)

        self.lang = "cs"
        self.T: Dict[str, Dict[str, str]] = {
            "cs": {
                "app_title": "GIFT formatter",
                "controls_default_correct": "Výchozí správná:",
                "controls_use_default": "Použít výchozí, pokud není označeno ')*'",
                "controls_auto": "Auto převod",
                "controls_tolerant": "Tolerantní režim (auto-opravy)",
                "controls_language": "Jazyk:",
                "controls_multi_mode": "Více správných (export):",
                "multi_wipe": "A) Smazat body při chybě (−100% za špatnou)",
                "multi_penalize": "B) Částečně penalizovat (−100% rozdělit mezi špatné)",
                "label_input": "Vstup:",
                "label_output": "Výstup:",
                "toolbar_convert": "🔄 Převést",
                "toolbar_copy": "📋 Kopírovat",
                "toolbar_save": "💾 Uložit .gift",
                "toolbar_clear": "🧹 Vymazat",
                "toolbar_stats": "📊 Statistiky",
                "toolbar_preview": "👩‍🎓 Náhled",
                "toolbar_auto": "⚡ Auto",
                "toolbar_issues": "⚠️ Problémy",
                "tooltip_default_correct": "Použije se, pokud žádná odpověď není označená pomocí ')*'.",
                "tooltip_auto": "Automaticky převádí chvíli po dopsání.",
                "tooltip_tolerant": "Zkusí automaticky opravit běžné chyby formátu (A., 1., mezery...).",
                "tooltip_multi_mode": "Použije se jen pro bloky s 2+ správnými odpověďmi (více ')*').",
                "tooltip_stats": "Otevřít okno se statistikou posledního převodu.",
                "tooltip_preview": "Zobrazí otázky jako student (náhled).",
                "tooltip_auto_action": "Přepnout automatický převod při psaní.",
                "tooltip_issues": "Zobrazit seznam varování/chyb a skočit na blok.",
                "issues_title": "Problémy (varování a chyby)",
                "issues_empty": "Žádná varování ani chyby.",
                "status_ready": "Připraveno. Vlož otázky do vstupu.",
                "status_cleared": "Vymazáno.",
                "status_empty": "Vstup je prázdný.",
                "status_copied": "Výstup zkopírován do schránky.",
                "status_saved": "Uloženo: {path}",
                "status_ok": "Převedeno bez chyb ({count} otázek).",
                "status_warn": "Převedeno s upozorněními: {w}.",
                "status_err": "Převedeno s chybami: {e} chyba(y), {w} upozornění.",
                "status_fixes": "Auto-opravy: {n}",
                "msg_nothing_to_save_title": "Není co ukládat",
                "msg_nothing_to_save": "Nejprve něco převeď, ať není výstup prázdný.",
                "msg_save_title": "Uložit Moodle GIFT soubor",
                "msg_convert_failed_title": "Převod selhal",
                "msg_preview_no_questions": "Nebyly nalezeny žádné validní otázky pro náhled.",
                "stats_title": "Statistika testu",
                "stats_questions": "Počet otázek:",
                "stats_ok": "OK bloky:",
                "stats_errors": "Chyby:",
                "stats_warnings": "Varování:",
                "stats_ans_min": "Min odpovědí:",
                "stats_ans_max": "Max odpovědí:",
                "stats_ans_avg": "Průměr odpovědí:",
                "stats_unmarked": "Bez ')*':",
                "stats_fixes": "Auto-opravy (počet zásahů):",
                "preview_title": "Náhled testu (Student view)",
                "preview_answers": "Odpovědi",
                "preview_prev": "Předchozí",
                "preview_next": "Další",
                "preview_show_correct": "Ukázat správné",
                "preview_counter": "Otázka {i} / {n}",
                "preview_empty": "Žádné otázky",
                "author_label": "Autor: Ondřej Beránek",
                "placeholder": (
                    "Odděluj otázky prázdným řádkem.\n"
                    "Odpovědi mohou být 'a) ...' nebo '1) ...'.\n"
                    "Správnou označ pomocí 'a)*' nebo '1)*'.\n"
                    "Pro více správných odpovědí označ více řádků ')*'.\n"
                    "Konec otázky ':' se při převodu odstraní.\n\n"
                    "Příklad (multiple):\n"
                    "Text otázky:\n"
                    "a)* Správně\n"
                    "b) Špatně\n"
                    "c)* Správně\n"
                ),
                "toolbar_open": "📂 Otevřít",
                "tooltip_open": "Načíst text ze souboru do vstupu (Ctrl+O).",
                "msg_open_title": "Otevřít soubor",
                "msg_open_failed_title": "Načtení selhalo",
                "status_loaded": "Načteno: {path}",

            },
            "en": {
                "app_title": "GIFT formatter",
                "controls_default_correct": "Default correct:",
                "controls_use_default": "Use default if none marked with ')*'",
                "controls_auto": "Auto convert",
                "controls_tolerant": "Tolerant mode (auto-fixes)",
                "controls_language": "Language:",
                "controls_multi_mode": "Multiple correct (export):",
                "multi_wipe": "A) Wipe on mistake (−100% per wrong)",
                "multi_penalize": "B) Partial penalty (split −100% among wrong)",
                "label_input": "Input:",
                "label_output": "Output:",
                "toolbar_convert": "🔄 Convert",
                "toolbar_copy": "📋 Copy",
                "toolbar_save": "💾 Save .gift",
                "toolbar_clear": "🧹 Clear",
                "toolbar_stats": "📊 Stats",
                "toolbar_preview": "👩‍🎓 Preview",
                "toolbar_auto": "⚡ Auto",
                "toolbar_issues": "⚠️ Issues",
                "tooltip_default_correct": "Used if no answer is marked with ')*'.",
                "tooltip_auto": "Automatically converts a moment after you stop typing.",
                "tooltip_tolerant": "Tries to automatically fix common formatting issues (A., 1., spacing...).",
                "tooltip_multi_mode": "Applied only to blocks with 2+ correct answers (multiple ')*').",
                "tooltip_stats": "Open stats window for the last conversion.",
                "tooltip_preview": "Show questions like a student (preview).",
                "tooltip_auto_action": "Toggle automatic conversion while typing.",
                "tooltip_issues": "Show warnings/errors list and jump to a block.",
                "issues_title": "Issues (warnings and errors)",
                "issues_empty": "No warnings or errors.",
                "status_ready": "Ready. Paste your questions into Input.",
                "status_cleared": "Cleared.",
                "status_empty": "Input is empty.",
                "status_copied": "Output copied to clipboard.",
                "status_saved": "Saved: {path}",
                "status_ok": "Converted OK ({count} question(s)).",
                "status_warn": "Converted with warnings: {w}.",
                "status_err": "Converted with errors: {e} error(s), {w} warning(s).",
                "status_fixes": "Auto-fixes: {n}",
                "msg_nothing_to_save_title": "Nothing to save",
                "msg_nothing_to_save": "Convert something first so the output is not empty.",
                "msg_save_title": "Save Moodle GIFT file",
                "msg_convert_failed_title": "Conversion failed",
                "msg_preview_no_questions": "No valid questions found for preview.",
                "stats_title": "Test statistics",
                "stats_questions": "Questions:",
                "stats_ok": "OK blocks:",
                "stats_errors": "Errors:",
                "stats_warnings": "Warnings:",
                "stats_ans_min": "Min answers:",
                "stats_ans_max": "Max answers:",
                "stats_ans_avg": "Avg answers:",
                "stats_unmarked": "No ')*':",
                "stats_fixes": "Auto-fixes (count):",
                "preview_title": "Test preview (Student view)",
                "preview_answers": "Answers",
                "preview_prev": "Previous",
                "preview_next": "Next",
                "preview_show_correct": "Show correct",
                "preview_counter": "Question {i} / {n}",
                "preview_empty": "No questions",
                "author_label": "Author: Ondřej Beránek",
                "placeholder": (
                    "Separate questions by blank lines.\n"
                    "Answers can be 'a) ...' or '1) ...'.\n"
                    "Mark correct answers with 'a)*' or '1)*'.\n"
                    "For multiple correct, mark multiple lines with ')*'.\n"
                    "Question ending ':' will be removed.\n\n"
                    "Example (multiple):\n"
                    "Question text:\n"
                    "a)* Correct\n"
                    "b) Wrong\n"
                    "c)* Correct\n"
                ),
                "toolbar_open": "📂 Open",
                "tooltip_open": "Load text from a file into Input (Ctrl+O).",
                "msg_open_title": "Open file",
                "msg_open_failed_title": "Load failed",
                "status_loaded": "Loaded: {path}",
            },
        }

        # --- Central UI ---
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        controls = QHBoxLayout()

        self.lbl_default_correct = QLabel()
        controls.addWidget(self.lbl_default_correct)

        self.correct_combo = QComboBox()
        self.correct_combo.setEditable(True)
        self.correct_combo.addItems(["a", "b", "c", "d", "1", "2", "3", "4"])
        self.correct_combo.setCurrentIndex(0)

        self.correct_combo.setMinimumWidth(80)
        self.correct_combo.setMinimumHeight(32)
        controls.addWidget(self.correct_combo)

        self.assume_default_cb = QCheckBox()
        self.assume_default_cb.setChecked(True)
        controls.addWidget(self.assume_default_cb)

        self.tolerant_cb = QCheckBox()
        self.tolerant_cb.setChecked(True)
        controls.addWidget(self.tolerant_cb)

        controls.addSpacing(16)

        self.lbl_multi_mode = QLabel()
        controls.addWidget(self.lbl_multi_mode)

        self.multi_mode_combo = QComboBox()
        self.multi_mode_combo.addItem("A) Wipe on mistake", "wipe")
        self.multi_mode_combo.addItem("B) Partial penalty", "penalize")
        controls.addWidget(self.multi_mode_combo)

        controls.addSpacing(16)

        self.lbl_language = QLabel()
        controls.addWidget(self.lbl_language)

        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Čeština", "cs")
        self.lang_combo.addItem("English", "en")
        controls.addWidget(self.lang_combo)

        controls.addStretch(1)
        layout.addLayout(controls)

        # Editors
        self.input_edit = FileDropPlainTextEdit()
        self.input_edit.on_file_dropped = self.load_text_file
        self.output_edit = QPlainTextEdit()
        self.output_edit.setReadOnly(True)

        self.highlighter = InputHighlighter(self.input_edit.document())
        self.input_edit.cursorPositionChanged.connect(self._refresh_block_highlight)

        self.splitter = QSplitter(Qt.Vertical)
        input_wrap = QWidget()
        input_layout = QVBoxLayout(input_wrap)
        input_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_input = QLabel()
        input_layout.addWidget(self.lbl_input)
        input_layout.addWidget(self.input_edit)

        output_wrap = QWidget()
        output_layout = QVBoxLayout(output_wrap)
        output_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_output = QLabel()
        output_layout.addWidget(self.lbl_output)
        output_layout.addWidget(self.output_edit)

        self.splitter.addWidget(input_wrap)
        self.splitter.addWidget(output_wrap)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        layout.addWidget(self.splitter, 1)

        # Status + author label
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self.lbl_author = QLabel("")
        self.lbl_author.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_author.setStyleSheet("color: #666;")
        self.status.addPermanentWidget(self.lbl_author)

        # Toolbar
        self._build_toolbar()

        # Auto convert timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.convert_auto)

        self.input_edit.textChanged.connect(self._on_text_changed)
        self.correct_combo.currentTextChanged.connect(self._on_text_changed)
        self.assume_default_cb.stateChanged.connect(self._on_text_changed)
        self.tolerant_cb.stateChanged.connect(self._on_text_changed)
        self.multi_mode_combo.currentIndexChanged.connect(self._on_text_changed)

        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)

        # Data for dialogs
        self.last_stats: Optional[Stats] = None
        self.last_fixes: int = 0
        self.last_questions: List[QuestionItem] = []
        self.last_issues: List[ConvertIssue] = []
        self.stats_dialog: Optional[StatsDialog] = None
        self.preview_dialog: Optional[PreviewDialog] = None
        self.issues_dialog: Optional[IssuesDialog] = None

        # Load settings & apply language
        self.load_settings()
        self.apply_language(self.lang)

        self.status.showMessage(self.tr_("status_ready"), 4000)

    def _icon(self, theme_name: str, fallback: QStyle.StandardPixmap) -> QIcon:
        ico = QIcon.fromTheme(theme_name)
        if not ico.isNull():
            return ico
        return self.style().standardIcon(fallback)
    
    def apply_theme(self, theme: str):
        theme = "dark" if str(theme).lower() == "dark" else "light"
        self.theme = theme
        qss = DARK_QSS if theme == "dark" else LIGHT_QSS
        QApplication.instance().setStyleSheet(qss)

        #IDE highlight se mění podle theme
        self._refresh_block_highlight()

        if hasattr(self, "act_theme"):
            self.act_theme.blockSignals(True)
            self.act_theme.setChecked(self.theme == "dark")
            self.act_theme.blockSignals(False)

    def toggle_theme(self, checked: bool):
        new_theme = "dark" if checked else "light"
        self.apply_theme(new_theme)
        self.settings.setValue("ui/theme", new_theme)

    def _refresh_block_highlight(self):
        try:
            text = self.input_edit_toPlainText()
            if not text.strip():
                self.input_edit.setExtraSelections([])
                return
            
            cursor = self.input_edit.textCursor()
            pos = cursor.position()

            blocks = iter_blocks_with_spans(text)
            if not blocks:
                self.input_edit.setExtraSelections([])
                return
            
            active = None
            for b in blocks:
                if b.start <= pos <= b.end:
                    active = b
                    break

            if active is None:
                self.input_edit.setExtraSelections([])
                return
            
            #set color based on theme
            bg = QColor("#eef2ff") if self.theme != "dark" else QColor("#1b2335")
            bg.setAlpha(120)

            sel = QPlainTextEdit.ExtraSelection()
            fmt = sel.format
            fmt.setBackground(bg)

            c = self.input_edit.textCursor()
            c.setPosition(active.start)
            c.setPosition(active.end, QTextCursor.KeepAnchor)
            sel.cursor = c

            self.input_edit.setExtraSelections([sel])
        except Exception:
            pass


    # -------- i18n --------

    def tr_(self, key: str, **kwargs: Any) -> str:
        s = self.T.get(self.lang, self.T["en"]).get(key, key)
        if kwargs:
            try:
                return s.format(**kwargs)
            except Exception:
                return s
        return s

    def apply_language(self, lang_code: str):
        self.lang = lang_code
        self.setWindowTitle(self.tr_("app_title"))

        self.lbl_default_correct.setText(self.tr_("controls_default_correct"))
        self.assume_default_cb.setText(self.tr_("controls_use_default"))
        self.act_auto.setText(self.tr_("controls_auto"))
        self.tolerant_cb.setText(self.tr_("controls_tolerant"))
        self.lbl_language.setText(self.tr_("controls_language"))
        self.lbl_multi_mode.setText(self.tr_("controls_multi_mode"))

        cur = self.multi_mode_combo.currentData()
        self.multi_mode_combo.blockSignals(True)
        self.multi_mode_combo.clear()
        self.multi_mode_combo.addItem(self.tr_("multi_wipe"), "wipe")
        self.multi_mode_combo.addItem(self.tr_("multi_penalize"), "penalize")
        idx = 0 if cur != "penalize" else 1
        self.multi_mode_combo.setCurrentIndex(idx)
        self.multi_mode_combo.blockSignals(False)

        self.lbl_input.setText(self.tr_("label_input"))
        self.lbl_output.setText(self.tr_("label_output"))

        self.correct_combo.setToolTip(self.tr_("tooltip_default_correct"))
        self.act_auto.setToolTip(self.tr_("tooltip_auto"))
        self.tolerant_cb.setToolTip(self.tr_("tooltip_tolerant"))
        self.multi_mode_combo.setToolTip(self.tr_("tooltip_multi_mode"))

        self.input_edit.setPlaceholderText(self.tr_("placeholder"))

        self.act_convert.setToolTip(self.tr_("toolbar_convert"))
        self.act_copy.setToolTip(self.tr_("toolbar_copy"))
        self.act_save.setToolTip(self.tr_("toolbar_save"))
        self.act_clear.setToolTip(self.tr_("toolbar_clear"))
        self.act_stats.setToolTip(self.tr_("toolbar_stats"))
        self.act_stats.setToolTip(self.tr_("tooltip_stats"))
        self.act_preview.setToolTip(self.tr_("toolbar_preview"))
        self.act_preview.setToolTip(self.tr_("tooltip_preview"))
        self.act_open.setText(self.tr_("toolbar_open"))
        self.act_open.setToolTip(self.tr_("tooltip_open"))

        self.act_auto.setText(self.tr_("toolbar_auto"))
        self.act_auto.setToolTip(self.tr_("tooltip_auto_action"))

        self.act_issues.setText(self.tr_("toolbar_issues"))
        self.act_issues.setToolTip(self.tr_("tooltip_issues"))

        self.lbl_author.setText(self.tr_("author_label"))

        self.act_theme.setToolTip("Dark Mode" if self.lang == "en" else "Tmavý režim")

        if self.stats_dialog is not None:
            was_visible = self.stats_dialog.isVisible()
            self.stats_dialog.close()
            self.stats_dialog = StatsDialog(self, self.tr_, self.last_stats, self.last_fixes)
            if was_visible:
                self.stats_dialog.show()

        if self.preview_dialog is not None:
            was_visible = self.preview_dialog.isVisible()
            self.preview_dialog.close()
            self.preview_dialog = PreviewDialog(self, self.tr_)
            self.preview_dialog.set_questions(self.last_questions, 0)
            if was_visible:
                self.preview_dialog.show()

        if self.issues_dialog is not None:
            self.issues_dialog.setWindowTitle(self.tr_("issues_title"))
            self.issues_dialog.set_issues(self.last_issues)

    def _on_language_changed(self):
        lang_code = self.lang_combo.currentData()
        if lang_code in ("cs", "en"):
            self.apply_language(lang_code)
            self.status.showMessage(self.tr_("status_ready"), 2000)

    # -------- Toolbar --------

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)

        # icon-only modern look
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        tb.setIconSize(QtCore.QSize(20, 20))  
        tb.setContentsMargins(8, 6, 8, 6)

        self.addToolBar(tb)

        # --- Actions ---
        self.act_open = QAction("", self)
        self.act_open.setShortcut("Ctrl+O")
        self.act_open.triggered.connect(self.open_file)
        tb.addAction(self.act_open)
        
        self.act_convert = QAction(self._icon("view-refresh", QStyle.SP_BrowserReload), "", self)
        self.act_convert.setShortcut("Ctrl+Enter")
        self.act_convert.triggered.connect(self.convert_now)
        tb.addAction(self.act_convert)

        self.act_copy = QAction(self._icon("edit-copy", QStyle.SP_DialogOpenButton), "", self)
        self.act_copy.setShortcut("Ctrl+Shift+C")
        self.act_copy.triggered.connect(self.copy_output)
        tb.addAction(self.act_copy)

        self.act_save = QAction(self._icon("document-save", QStyle.SP_DialogSaveButton), "", self)
        self.act_save.setShortcut("Ctrl+S")
        self.act_save.triggered.connect(self.save_gift)
        tb.addAction(self.act_save)

        self.act_clear = QAction(self._icon("edit-clear", QStyle.SP_DialogResetButton), "", self)
        self.act_clear.setShortcut("Ctrl+L")
        self.act_clear.triggered.connect(self.clear_all)
        tb.addAction(self.act_clear)

        tb.addSeparator()

        self.act_stats = QAction(self._icon("view-statistics", QStyle.SP_FileDialogInfoView), "", self)
        self.act_stats.setShortcut("Ctrl+I")
        self.act_stats.triggered.connect(self.show_stats)
        tb.addAction(self.act_stats)

        self.act_preview = QAction(self._icon("view-preview", QStyle.SP_FileDialogContentsView), "", self)
        self.act_preview.setShortcut("Ctrl+P")
        self.act_preview.triggered.connect(self.show_preview)
        tb.addAction(self.act_preview)

        self.act_issues = QAction(self._icon("dialog-warning", QStyle.SP_MessageBoxWarning), "", self)
        self.act_issues.setShortcut("Ctrl+W")
        self.act_issues.triggered.connect(self.show_issues)
        tb.addAction(self.act_issues)

        tb.addSeparator()

        self.act_auto = QAction(self._icon("media-playback-start", QStyle.SP_MediaPlay), "", self)
        self.act_auto.setCheckable(True)
        self.act_auto.setChecked(True)
        self.act_auto.triggered.connect(self._toggle_auto_from_action)
        tb.addAction(self.act_auto)

        tb.addSeparator()

        self.act_theme = QAction(self._icon("weather-clear-night", QStyle.SP_TitleBarShadeButton), "", self)
        self.act_theme.setCheckable(True)
        self.act_theme.setChecked(False) #default light
        self.act_theme.triggered.connect(self.toggle_theme)
        tb.addAction(self.act_theme)


    def _toggle_auto_from_action(self, checked: bool):
        self.status.showMessage(
            ("Auto: ON" if self.lang == "en" else "Auto: ZAP") if checked
            else ("Auto: OFF" if self.lang == "en" else "Auto: VYP"),
            2000,
        )
        self.settings.setValue("ui/auto_convert", checked)
        
    def open_file(self):
        start_dir = self.settings.value("ui/last_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr_("msg_open_title"),
            start_dir,
            "Text/Word (*.txt, *.gift, *.md, *.docx);;All files (*.*)",
        )
        if not path:
            return
        self.load_text_file(path)
    
    def load_text_file(self, path: str):
        # 1) vždy hned normalizuj path a vytvoř Path objekt
        try:
            p = Path(str(path)).expanduser()
        except Exception as e:
            QMessageBox.critical(self, "Load failed", f"Invalid path:\n{path}\n\n{e}")
            return

        # 2) základní validace
        if not p.exists() or not p.is_file():
            QMessageBox.warning(self, "Load failed", f"File not found:\n{p}")
            return

        suffix = p.suffix.lower()

        # 3) docx větev (pokud ji chceš)
        if suffix == ".docx":
            try:
                from docx import Document
                doc = Document(str(p))
                text = "\n".join(par.text for par in doc.paragraphs)
                self.input_edit.setPlainText(text)
                self.convert_now()
                return
            except Exception as e:
                QMessageBox.critical(self, "Load failed", f"Cannot read .docx:\n{e}")
                return

        # 4) zbytek – textové soubory
        try:
            data = p.read_bytes()
        except Exception as e:
            QMessageBox.critical(self, "Load failed", f"Cannot read file:\n{p}\n\n{e}")
            return

        # jednoduchá detekce binárního souboru
        if b"\x00" in data[:4096]:
            QMessageBox.warning(
                self,
                "Load failed",
                "This file looks like a binary file (e.g., .pdf/image).\n"
                "Please use a plain text file (.txt/.gift/.md) or .docx."
            )
            return

        text = None
        for enc in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except Exception:
                continue

        if text is None:
            QMessageBox.critical(self, "Load failed", f"Cannot decode file:\n{p}")
            return

        self.input_edit.setPlainText(text)
        self.convert_now()


    # -------- QSettings --------

    def load_settings(self):
        lang = self.settings.value("ui/lang", "cs")
        if lang not in ("cs", "en"):
            lang = "cs"
        self.lang = lang
        self.lang_combo.setCurrentIndex(0 if lang == "cs" else 1)

        auto = self.settings.value("ui/auto_convert", True, type=bool)
        assume_default = self.settings.value("ui/assume_default", True, type=bool)
        tolerant = self.settings.value("ui/tolerant", True, type=bool)
        default_key = self.settings.value("ui/default_correct", "a")
        multi_mode = self.settings.value("ui/multi_mode", "wipe")
        theme = self.settings.value("ui/theme", "light")

        self.act_auto.setChecked(bool(auto))
        self.assume_default_cb.setChecked(bool(assume_default))
        self.tolerant_cb.setChecked(bool(tolerant))
        self.correct_combo.setCurrentText(str(default_key))
        self.apply_theme(str(theme))

        self.multi_mode_combo.setCurrentIndex(1 if str(multi_mode) == "penalize" else 0)

        geom = self.settings.value("ui/geometry")
        if geom is not None:
            try:
                self.restoreGeometry(geom)
            except Exception:
                pass

        sizes = self.settings.value("ui/splitter_sizes")
        if isinstance(sizes, list) and len(sizes) == 2:
            try:
                self.splitter.setSizes([int(sizes[0]), int(sizes[1])])
            except Exception:
                pass

    def save_settings(self):
        self.settings.setValue("ui/lang", self.lang_combo.currentData() or self.lang)
        self.settings.setValue("ui/auto_convert", self.act_auto.isChecked())
        self.settings.setValue("ui/assume_default", self.assume_default_cb.isChecked())
        self.settings.setValue("ui/tolerant", self.tolerant_cb.isChecked())
        self.settings.setValue("ui/default_correct", self.correct_combo.currentText().strip() or "a")
        self.settings.setValue("ui/multi_mode", self.multi_mode_combo.currentData() or "wipe")
        self.settings.setValue("ui/geometry", self.saveGeometry())
        self.settings.setValue("ui/splitter_sizes", self.splitter.sizes())

    def closeEvent(self, event):
        self.save_settings()
        super().closeEvent(event)

    # -------- UI helpers --------

    def _on_text_changed(self, *_args):
        if not self.act_auto.isChecked():
            return
        self._timer.start(3000)


    def highlight_span(self, start: int, end: int):
        cursor = self.input_edit.textCursor()
        cursor.setPosition(max(0, start))
        cursor.setPosition(max(0, end), QTextCursor.KeepAnchor)
        self.input_edit.setTextCursor(cursor)
        self.input_edit.ensureCursorVisible()
        self.input_edit.setFocus()

    def convert_auto(self):
        self.convert_now(silent=True, from_auto=True)

    # -------- Actions --------

    def clear_all(self):
        self.input_edit.clear()
        self.output_edit.clear()
        self.last_stats = None
        self.last_fixes = 0
        self.last_questions = []
        self.last_issues = []

        if self.stats_dialog is not None:
            self.stats_dialog.set_stats(self.last_stats, self.last_fixes)
        if self.preview_dialog is not None:
            self.preview_dialog.set_questions([], 0)
        if self.issues_dialog is not None:
            self.issues_dialog.set_issues([])

        self.status.showMessage(self.tr_("status_cleared"), 2000)

    def convert_now(self, silent: bool = False, from_auto: bool = False):
        text = self.input_edit.toPlainText()
        default_key = (self.correct_combo.currentText() or "a").strip()
        assume_default = self.assume_default_cb.isChecked()
        tolerant = self.tolerant_cb.isChecked()
        multi_mode = self.multi_mode_combo.currentData() or "wipe"

        if default_key.endswith(")"):
            default_key = default_key[:-1]

        text_for_convert = text_without_last_incomplete_block(text) if from_auto else text

        out, issues, stats, fixes, questions = convert_blocks_with_positions(
            text_for_convert,
            default_correct_key=default_key,
            assume_default_if_unmarked=assume_default,
            tolerant=tolerant,
            multi_mode=str(multi_mode),
            pct_decimals=3,
        )

        self.output_edit.setPlainText(out)

        self.last_stats = stats
        self.last_fixes = fixes
        self.last_questions = questions
        self.last_issues = issues

        if self.stats_dialog is not None:
            self.stats_dialog.set_stats(self.last_stats, self.last_fixes)

        if self.preview_dialog is not None:
            current_idx = self.preview_dialog.index if self.preview_dialog.questions else 0
            self.preview_dialog.set_questions(self.last_questions, current_idx)

        if self.issues_dialog is not None:
            self.issues_dialog.set_issues(self.last_issues)

        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]

        if not text.strip():
            if not silent:
                self.status.showMessage(self.tr_("status_empty"), 3000)
            return

        if tolerant and fixes > 0 and not silent:
            self.status.showMessage(self.tr_("status_fixes", n=fixes), 2500)

        if errors:
            if not silent:
                first = errors[0]
                if first.start != first.end:
                    self.highlight_span(first.start, first.end)
                self.status.showMessage(self.tr_("status_err", e=len(errors), w=len(warnings)), 6000)

                if not out.strip():
                    msg = "\n".join([f"Block {i.block_index}: {i.message}" for i in errors[:20]])
                    if len(errors) > 20:
                        msg += f"\n... and {len(errors) - 20} more."
                    QMessageBox.warning(self, self.tr_("msg_convert_failed_title"), msg)
        elif warnings:
            if not silent:
                first = warnings[0]
                if first.start != first.end:
                    self.highlight_span(first.start, first.end)
            hint = " (Ctrl+W)"
            self.status.showMessage(self.tr_("status_warn", w=len(warnings)) + hint, 3000 if silent else 5000)
        else:
            count = len(questions)
            self.status.showMessage(self.tr_("status_ok", count=count), 2500 if silent else 4000)

    def copy_output(self):
        QApplication.clipboard().setText(self.output_edit.toPlainText())
        self.status.showMessage(self.tr_("status_copied"), 2500)

    def save_gift(self):
        content = self.output_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, self.tr_("msg_nothing_to_save_title"), self.tr_("msg_nothing_to_save"))
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr_("msg_save_title"),
            "quiz.gift",
            "Moodle GIFT (*.gift)",
        )
        if not path:
            return
        if not path.lower().endswith(".gift"):
            path += ".gift"

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content + "\n")
            self.status.showMessage(self.tr_("status_saved", path=path), 6000)
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def show_stats(self):
        if self.stats_dialog is None:
            self.stats_dialog = StatsDialog(self, self.tr_, self.last_stats, self.last_fixes)
        else:
            self.stats_dialog.set_stats(self.last_stats, self.last_fixes)

        self.stats_dialog.show()
        self.stats_dialog.raise_()
        self.stats_dialog.activateWindow()

    def show_preview(self):
        if not self.last_questions:
            self.convert_now()

        if not self.last_questions:
            QMessageBox.information(self, self.tr_("preview_title"), self.tr_("msg_preview_no_questions"))
            return

        if self.preview_dialog is None:
            self.preview_dialog = PreviewDialog(self, self.tr_)
        self.preview_dialog.set_questions(self.last_questions, 0)
        self.preview_dialog.show()
        self.preview_dialog.raise_()
        self.preview_dialog.activateWindow()

    def show_issues(self):
        if self.issues_dialog is None:
            self.issues_dialog = IssuesDialog(self, self.tr_, self.highlight_span)

        self.issues_dialog.setWindowTitle(self.tr_("issues_title"))
        self.issues_dialog.set_issues(self.last_issues)

        self.issues_dialog.show()
        self.issues_dialog.raise_()
        self.issues_dialog.activateWindow()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    style_path = Path(__file__).parent / "style.qss"
    if style_path.exists():
        app.setStyleSheet(style_path.read_text(encoding="utf-8"))
    else:
        app.setStyleSheet(LIGHT_QSS)

    icon_path = Path(__file__).parent / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    w = GiftFormatterMainWindow(icon_path=icon_path)
    w.resize(1020, 880)
    w.show()
    sys.exit(app.exec())
