import json
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QGroupBox,
    QRadioButton,
    QButtonGroup,
    QPushButton,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QAbstractButton,
    QTextEdit,
    QSpinBox,
)

from gift_formatter_core import (
    APP_VERSION,
    ANSWER_RE,
    MARKED_CORRECT_RE,
    ConvertIssue,
    EvaluationResult,
    QuestionItem,
    Stats,
    apply_quick_fix,
    available_quick_fixes,
    convert_blocks_with_positions,
    csv_text_to_blocks,
    evaluate_question,
    export_questions_by_category,
    import_gift_to_blocks,
    iter_blocks_with_spans,
    question_summary,
    sanitize_single_line,
    text_without_last_incomplete_block,
)

THEME_PALETTES = {
    "light": {
        "window_bg": "#f7f8fa",
        "surface_bg": "#ffffff",
        "editor_bg": "#ffffff",
        "border": "#d0d7de",
        "border_focus": "#4f8cff",
        "text": "#1f2937",
        "muted_text": "#667085",
        "group_title": "#475467",
        "hover_bg": "#eef2ff",
        "pressed_bg": "#e0e7ff",
        "checked_bg": "#dbeafe",
        "selection_bg": "#dbeafe",
        "splitter": "#d0d7de",
        "list_selected_text": "#111827",
        "active_block_bg": "#dbeafe",
        "issue_warning_bg": "#fef3c7",
        "issue_warning_border": "#f59e0b",
        "issue_error_bg": "#fee2e2",
        "issue_error_border": "#ef4444",
    },
    "dark": {
        "window_bg": "#0f1115",
        "surface_bg": "#151924",
        "editor_bg": "#0f141f",
        "border": "#2b3444",
        "border_focus": "#60a5fa",
        "text": "#e7eaf0",
        "muted_text": "#a7b1c2",
        "group_title": "#cfd6e6",
        "hover_bg": "#222a3a",
        "pressed_bg": "#2a3550",
        "checked_bg": "#25314a",
        "selection_bg": "#2a3d66",
        "splitter": "#252b3a",
        "list_selected_text": "#f8fafc",
        "active_block_bg": "#1b2335",
        "issue_warning_bg": "#3b2f1d",
        "issue_warning_border": "#f59e0b",
        "issue_error_bg": "#3a1f24",
        "issue_error_border": "#ef4444",
    },
}


THEME_QSS = """
* {
    font-family: "Segoe UI", "Inter", "Roboto", sans-serif;
    font-size: 13px;
}

QWidget, QDialog {
    background: %(window_bg)s;
    color: %(text)s;
}

QMainWindow {
    background: %(window_bg)s;
}

QToolBar {
    background: %(surface_bg)s;
    border-bottom: 1px solid %(border)s;
    padding: 6px;
    spacing: 6px;
}

QToolButton {
    background: transparent;
    border: none;
    padding: 8px;
    border-radius: 10px;
    color: %(text)s;
}

QToolButton:hover {
    background: %(hover_bg)s;
}

QToolButton:pressed {
    background: %(pressed_bg)s;
}

QToolButton:checked {
    background: %(checked_bg)s;
}

QLabel {
    color: %(text)s;
    background: transparent;
}

QLabel#AuthorLabel {
    color: %(muted_text)s;
}

QLabel#IssueBanner {
    border-radius: 8px;
    padding: 8px 10px;
}

QLabel#IssueBanner[severity="warning"] {
    background: %(issue_warning_bg)s;
    border: 1px solid %(issue_warning_border)s;
    color: %(text)s;
}

QLabel#IssueBanner[severity="error"] {
    background: %(issue_error_bg)s;
    border: 1px solid %(issue_error_border)s;
    color: %(text)s;
}

QCheckBox, QRadioButton {
    color: %(text)s;
    background: transparent;
    spacing: 6px;
}

QPushButton {
    background: %(surface_bg)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
    padding: 6px 12px;
    color: %(text)s;
}

QPushButton:hover {
    background: %(hover_bg)s;
}

QPushButton:pressed {
    background: %(pressed_bg)s;
}

QPushButton:disabled {
    color: %(muted_text)s;
}

QPlainTextEdit, QListWidget, QComboBox, QLineEdit {
    background: %(editor_bg)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
    color: %(text)s;
}

QPlainTextEdit {
    padding: 10px;
    selection-background-color: %(selection_bg)s;
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: 13px;
}

QComboBox {
    padding: 6px 10px;
    font-size: 14px;
    selection-background-color: %(selection_bg)s;
}

QLineEdit {
    padding: 6px 10px;
}

QComboBox QAbstractItemView {
    background: %(surface_bg)s;
    border: 1px solid %(border)s;
    color: %(text)s;
    selection-background-color: %(selection_bg)s;
    selection-color: %(list_selected_text)s;
    padding: 6px;
}

QPlainTextEdit:focus, QListWidget:focus, QComboBox:focus, QLineEdit:focus {
    border: 1px solid %(border_focus)s;
}

QListWidget::item:selected {
    background: %(selection_bg)s;
    color: %(list_selected_text)s;
}

QSplitter::handle {
    background: %(splitter)s;
    height: 6px;
}

QStatusBar {
    background: %(surface_bg)s;
    border-top: 1px solid %(border)s;
    color: %(muted_text)s;
}

QGroupBox {
    border: 1px solid %(border)s;
    border-radius: 8px;
    margin-top: 8px;
    color: %(text)s;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: %(group_title)s;
    font-weight: bold;
}
"""


def build_theme_stylesheet(theme: str) -> str:
    palette = THEME_PALETTES["dark" if str(theme).lower() == "dark" else "light"]
    return THEME_QSS % palette
# ---------- Input Highlighter ----------

class InputHighlighter(QSyntaxHighlighter):
    STATE_EXPECT_QUESTION = 0
    STATE_EXPECT_ANSWERS = 1

    def __init__(self, document):
        super().__init__(document)

        self.fmt_question = QTextCharFormat()
        self.fmt_question.setFontWeight(QFont.Bold)

        self.fmt_correct = QTextCharFormat()
        self.fmt_correct.setFontWeight(QFont.DemiBold)

        self.fmt_error = QTextCharFormat()
        self.fmt_error.setUnderlineStyle(QTextCharFormat.SingleUnderline)

        self.set_theme("light")

    def set_theme(self, theme: str):
        self.theme = "dark" if str(theme).lower() == "dark" else "light"
        if self.theme == "dark":
            question_color = "#93c5fd"
            correct_color = "#86efac"
            error_color = "#fca5a5"
        else:
            question_color = "#1f4e79"
            correct_color = "#1b5e20"
            error_color = "#b71c1c"

        self.fmt_question.setForeground(QColor(question_color))
        self.fmt_correct.setForeground(QColor(correct_color))
        self.fmt_error.setForeground(QColor(error_color))
        self.rehighlight()

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
            severity = self.tr_("issues_error_prefix") if it.severity == "error" else self.tr_("issues_warning_prefix")
            text = self.tr_(
                "issues_item",
                severity=severity,
                block_index=it.block_index,
                message=it.message,
            )
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
        self.user_responses: Dict[int, Any] = {}
        self.evaluations: Dict[int, EvaluationResult] = {}
        self.answer_buttons: List[QAbstractButton] = []
        self.match_boxes: Dict[str, QComboBox] = {}
        self.text_answer_edit: Optional[QLineEdit] = None
        self.current_answer_order: List[int] = []
        self.remaining_seconds = 0

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.lbl_counter = QLabel("")
        top_row.addWidget(self.lbl_counter)
        self.lbl_score = QLabel("")
        top_row.addWidget(self.lbl_score)
        self.lbl_timer = QLabel("")
        top_row.addWidget(self.lbl_timer)
        top_row.addStretch(1)

        self.cb_shuffle = QCheckBox(self.tr_("preview_shuffle"))
        self.cb_shuffle.stateChanged.connect(self._render)
        top_row.addWidget(self.cb_shuffle)

        self.lbl_time_limit = QLabel(self.tr_("preview_time_limit"))
        top_row.addWidget(self.lbl_time_limit)
        self.spin_time_limit = QSpinBox()
        self.spin_time_limit.setRange(0, 600)
        self.spin_time_limit.setValue(0)
        self.spin_time_limit.valueChanged.connect(self._render)
        top_row.addWidget(self.spin_time_limit)

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
        self._answers_layout = gb_layout

        self.lbl_feedback = QLabel("")
        self.lbl_feedback.setWordWrap(True)
        self.lbl_feedback.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.lbl_feedback)

        nav = QHBoxLayout()
        self.btn_prev = QPushButton("◀ " + self.tr_("preview_prev"))
        self.btn_submit = QPushButton(self.tr_("preview_submit"))
        self.btn_next = QPushButton(self.tr_("preview_next") + " ▶")
        self.btn_prev.clicked.connect(self.prev_q)
        self.btn_submit.clicked.connect(self.submit_current)
        self.btn_next.clicked.connect(self.next_q)
        nav.addWidget(self.btn_prev)
        nav.addStretch(1)
        nav.addWidget(self.btn_submit)
        nav.addWidget(self.btn_next)
        layout.addLayout(nav)

        close_btns = QDialogButtonBox(QDialogButtonBox.Close)
        close_btns.rejected.connect(self.close)
        close_btns.accepted.connect(self.close)
        layout.addWidget(close_btns)

        self.resize(650, 520)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick_timer)

    def set_questions(self, questions: List[QuestionItem], start_index: int = 0):
        self.questions = questions or []
        self.index = max(0, min(start_index, len(self.questions) - 1)) if self.questions else 0
        self.user_responses = {}
        self.evaluations = {}
        self._render()

    def _clear_answers(self):
        for btn in self.answer_buttons:
            self.btn_group.removeButton(btn)
            btn.deleteLater()
        self.answer_buttons = []
        self.match_boxes = {}
        self.text_answer_edit = None
        self.current_answer_order = []
        while self._answers_layout.count():
            item = self._answers_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _update_score_label(self):
        if not self.questions:
            self.lbl_score.setText("")
            return
        total_score = sum(result.score for result in self.evaluations.values())
        self.lbl_score.setText(self.tr_("preview_score", score=f"{total_score:.2f}", total=len(self.questions)))

    def _start_timer_for_question(self):
        self.timer.stop()
        self.remaining_seconds = self.spin_time_limit.value()
        if self.remaining_seconds <= 0:
            self.lbl_timer.setText("")
            return
        self.lbl_timer.setText(self.tr_("preview_time_left", seconds=self.remaining_seconds))
        self.timer.start(1000)

    def _tick_timer(self):
        self.remaining_seconds -= 1
        if self.remaining_seconds <= 0:
            self.timer.stop()
            self.lbl_timer.setText(self.tr_("preview_time_left", seconds=0))
            self.submit_current()
            return
        self.lbl_timer.setText(self.tr_("preview_time_left", seconds=self.remaining_seconds))

    def _collect_response(self) -> Any:
        if not self.questions:
            return None
        question = self.questions[self.index]
        qtype = question.question_type

        if qtype in ("multiple", "truefalse"):
            selected: set[int] = set()
            for display_index, button in enumerate(self.answer_buttons):
                if button.isChecked() and display_index < len(self.current_answer_order):
                    selected.add(self.current_answer_order[display_index])
            return selected

        if qtype in ("shortanswer", "numerical"):
            return self.text_answer_edit.text() if self.text_answer_edit is not None else ""

        if qtype == "matching":
            return {left: combo.currentData() for left, combo in self.match_boxes.items()}

        return None

    def _render_multiple(self, question: QuestionItem, show_correct: bool):
        correct_set = set(question.correct_indices or [])
        is_multi = len(correct_set) > 1
        self.group_box.setTitle(self.tr_("preview_answers_multi" if is_multi else "preview_answers"))

        order = list(range(len(question.answers)))
        if self.cb_shuffle.isChecked():
            random.Random(question.block_index or self.index + 1).shuffle(order)
        self.current_answer_order = order

        stored_response = self.user_responses.get(self.index, set())
        if not isinstance(stored_response, set):
            stored_response = set()

        for answer_index in order:
            text = question.answers[answer_index]
            button: QAbstractButton
            if is_multi:
                button = QCheckBox(text)
            else:
                button = QRadioButton(text)
                self.btn_group.addButton(button)
            self._answers_layout.addWidget(button)
            self.answer_buttons.append(button)
            button.setChecked(answer_index in stored_response)
            if show_correct and answer_index in correct_set:
                button.setStyleSheet("font-weight: 900; font-size: 14px;")
            else:
                button.setStyleSheet("")

    def _render_text_answer(self, question: QuestionItem):
        self.group_box.setTitle(self.tr_("preview_answer_field"))
        edit = QLineEdit()
        edit.setPlaceholderText(
            self.tr_("preview_enter_number") if question.question_type == "numerical" else self.tr_("preview_enter_text")
        )
        previous_value = self.user_responses.get(self.index, "")
        edit.setText(str(previous_value))
        self.text_answer_edit = edit
        self._answers_layout.addWidget(edit)

    def _render_matching(self, question: QuestionItem):
        self.group_box.setTitle(self.tr_("preview_matching"))
        stored_response = self.user_responses.get(self.index, {})
        if not isinstance(stored_response, dict):
            stored_response = {}
        choices = [right for _left, right in question.matching_pairs]
        if self.cb_shuffle.isChecked():
            choices = list(choices)
            random.Random(question.block_index or self.index + 1).shuffle(choices)

        for left, right in question.matching_pairs:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            prompt = QLabel(left)
            prompt.setMinimumWidth(180)
            combo = QComboBox()
            combo.addItem("", "")
            for choice in choices:
                combo.addItem(choice, choice)
            current_value = stored_response.get(left, "")
            combo.setCurrentIndex(max(0, combo.findData(current_value)))
            row_layout.addWidget(prompt)
            row_layout.addWidget(combo, 1)
            self._answers_layout.addWidget(row)
            self.match_boxes[left] = combo

    def _render_feedback(self, question: QuestionItem, show_correct: bool):
        result = self.evaluations.get(self.index)
        if result is None:
            if show_correct:
                self.lbl_feedback.setText(
                    self.tr_("preview_correct_answer", answer=question_summary(question) or self.tr_("preview_no_feedback"))
                )
            else:
                self.lbl_feedback.setText("")
            return

        verdict_key = "preview_result_correct" if result.is_correct else "preview_result_wrong"
        lines = [self.tr_(verdict_key, score=f"{result.score:.2f}")]
        if result.feedback:
            lines.append(result.feedback)
        if result.correct_answer:
            lines.append(self.tr_("preview_correct_answer", answer=result.correct_answer))
        self.lbl_feedback.setText("\n".join(lines))

    def _render(self):
        if not self.questions:
            self.timer.stop()
            self.lbl_counter.setText(self.tr_("preview_empty"))
            self.lbl_question.setText("")
            self._clear_answers()
            self.group_box.setTitle(self.tr_("preview_answers"))
            self.lbl_feedback.setText("")
            self.lbl_timer.setText("")
            self._update_score_label()
            self.btn_prev.setEnabled(False)
            self.btn_submit.setEnabled(False)
            self.btn_next.setEnabled(False)
            return

        q = self.questions[self.index]
        self.lbl_counter.setText(self.tr_("preview_counter", i=self.index + 1, n=len(self.questions)))
        self.lbl_question.setText(q.question)

        self._clear_answers()

        show_correct = self.cb_show_correct.isChecked()
        if q.question_type in ("multiple", "truefalse"):
            self._render_multiple(q, show_correct)
        elif q.question_type in ("shortanswer", "numerical"):
            self._render_text_answer(q)
        elif q.question_type == "matching":
            self._render_matching(q)
        else:
            self.group_box.setTitle(self.tr_("preview_answers"))

        self._render_feedback(q, show_correct)
        self._update_score_label()
        self._start_timer_for_question()
        self.btn_prev.setEnabled(self.index > 0)
        self.btn_submit.setEnabled(True)
        self.btn_next.setEnabled(self.index < len(self.questions) - 1)

    def submit_current(self):
        if not self.questions:
            return
        self.timer.stop()
        response = self._collect_response()
        self.user_responses[self.index] = response
        self.evaluations[self.index] = evaluate_question(self.questions[self.index], response)
        self._render_feedback(self.questions[self.index], self.cb_show_correct.isChecked())
        self._update_score_label()

    def prev_q(self):
        if self.index > 0:
            self.user_responses[self.index] = self._collect_response()
            self.index -= 1
            self._render()

    def next_q(self):
        if self.index < len(self.questions) - 1:
            self.user_responses[self.index] = self._collect_response()
            self.index += 1
            self._render()


class HistoryDialog(QDialog):
    def __init__(self, parent: QWidget, tr_func, restore_callback):
        super().__init__(parent)
        self.tr_ = tr_func
        self.restore_callback = restore_callback
        self.setModal(False)
        self.setWindowTitle(self.tr_("history_title"))

        layout = QVBoxLayout(self)
        self.listw = QListWidget()
        self.listw.itemDoubleClicked.connect(self._restore_selected)
        layout.addWidget(self.listw)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.btn_restore = QPushButton(self.tr_("history_restore"))
        self.btn_restore.clicked.connect(self._restore_current_item)
        buttons.addButton(self.btn_restore, QDialogButtonBox.ActionRole)
        buttons.rejected.connect(self.close)
        buttons.accepted.connect(self.close)
        layout.addWidget(buttons)
        self.resize(760, 420)

    def set_snapshots(self, snapshots: List[Dict[str, Any]]):
        self.listw.clear()
        if not snapshots:
            item = QListWidgetItem(self.tr_("history_empty"))
            item.setFlags(Qt.NoItemFlags)
            self.listw.addItem(item)
            self.btn_restore.setEnabled(False)
            return

        for snapshot in reversed(snapshots):
            text = snapshot.get("text", "")
            excerpt = sanitize_single_line(text)[:70] or self.tr_("history_snapshot")
            timestamp = snapshot.get("timestamp", "")
            item = QListWidgetItem(f"{timestamp}  {excerpt}")
            item.setData(Qt.UserRole, snapshot)
            self.listw.addItem(item)

        self.btn_restore.setEnabled(True)
        self.listw.setCurrentRow(0)

    def _restore_current_item(self):
        item = self.listw.currentItem()
        if item is None:
            return
        self._restore_selected(item)

    def _restore_selected(self, item: QListWidgetItem):
        snapshot = item.data(Qt.UserRole)
        if not snapshot:
            return
        self.restore_callback(snapshot)

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
                "controls_expert_settings": "Expert settings",
                "controls_export_group": "Metadata exportu",
                "controls_question_bank": "Banka otázek",
                "controls_category": "Kategorie:",
                "controls_name_prefix": "Prefix názvů otázek:",
                "controls_correct_feedback": "Feedback pro správné:",
                "controls_incorrect_feedback": "Feedback pro špatné:",
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
                "toolbar_history": "🕘 Historie",
                "toolbar_batch_export": "🗂️ Export kategorií",
                "tooltip_default_correct": "Použije se, pokud žádná odpověď není označená pomocí ')*'.",
                "tooltip_auto": "Automaticky převádí chvíli po dopsání.",
                "tooltip_tolerant": "Zkusí automaticky opravit běžné chyby formátu (A., 1., mezery...).",
                "tooltip_multi_mode": "Použije se jen pro bloky s 2+ správnými odpověďmi (více ')*').",
                "tooltip_category": "Volitelně přidá řádek $CATEGORY na začátek exportu.",
                "tooltip_name_prefix": "Vygeneruje názvy otázek jako např. Otazka1, Otazka2, ...",
                "tooltip_correct_feedback": "Volitelný feedback přidaný ke všem správným odpovědím.",
                "tooltip_incorrect_feedback": "Volitelný feedback přidaný ke všem špatným odpovědím.",
                "tooltip_stats": "Otevřít okno se statistikou posledního převodu.",
                "tooltip_preview": "Zobrazí otázky jako student (náhled).",
                "tooltip_auto_action": "Přepnout automatický převod při psaní.",
                "tooltip_issues": "Zobrazit seznam varování/chyb a skočit na blok.",
                "tooltip_history": "Obnovit dříve auto-uložený snapshot.",
                "tooltip_batch_export": "Uložit otázky po kategoriích do vybrané složky.",
                "tooltip_theme": "Tmavý režim",
                "issues_title": "Problémy (varování a chyby)",
                "issues_empty": "Žádná varování ani chyby.",
                "issues_error_prefix": "CHYBA",
                "issues_warning_prefix": "VAROVÁNÍ",
                "issues_item": "[{severity}] Blok {block_index}: {message}",
                "status_ready": "Připraveno. Vlož otázky do vstupu.",
                "status_cleared": "Vymazáno.",
                "status_empty": "Vstup je prázdný.",
                "status_copied": "Výstup zkopírován do schránky.",
                "status_saved": "Uloženo: {path}",
                "status_ok": "Převedeno bez chyb ({count} otázek).",
                "status_warn": "Převedeno s upozorněními: {w}.",
                "status_err": "Převedeno s chybami: {e} chyba(y), {w} upozornění.",
                "status_fixes": "Auto-opravy: {n}",
                "status_history_restored": "Obnoven snapshot z historie.",
                "status_batch_saved": "Kategorie exportovány do: {path}",
                "msg_nothing_to_save_title": "Není co ukládat",
                "msg_nothing_to_save": "Nejprve něco převeď, ať není výstup prázdný.",
                "msg_save_title": "Uložit Moodle GIFT soubor",
                "msg_save_failed_title": "Uložení selhalo",
                "msg_convert_failed_title": "Převod selhal",
                "msg_batch_export_title": "Vyber složku pro export kategorií",
                "msg_batch_export_empty": "Nejsou k dispozici žádné otázky pro export po kategoriích.",
                "msg_preview_no_questions": "Nebyly nalezeny žádné validní otázky pro náhled.",
                "msg_invalid_path": "Neplatná cesta:\n{path}\n\n{error}",
                "msg_file_not_found": "Soubor nebyl nalezen:\n{path}",
                "msg_docx_module_missing": "Podpora .docx není dostupná, protože není nainstalován balíček python-docx.",
                "msg_cannot_read_docx": "Soubor .docx se nepodařilo načíst:\n{error}",
                "msg_cannot_read_file": "Soubor se nepodařilo přečíst:\n{path}\n\n{error}",
                "msg_binary_file": (
                    "Tento soubor vypadá jako binární soubor (např. .pdf nebo obrázek).\n"
                    "Použij prostý text (.txt/.gift/.md) nebo .docx."
                ),
                "msg_cannot_decode_file": "Soubor se nepodařilo dekódovat:\n{path}",
                "convert_failed_line": "Blok {block_index}: {message}",
                "convert_failed_more": "... a dalších {count}.",
                "issue_no_blocks": "Nebyly nalezeny žádné bloky otázek.",
                "issue_block_too_short": "Blok je příliš krátký (potřebuje otázku a alespoň 1 odpověď).",
                "issue_bad_answer_format": "Řádek odpovědi neodpovídá formátu 'a) ...' nebo '1) ...': {line}",
                "issue_duplicate_answer_key": "Klíč odpovědi '{answer_key}' se v bloku opakuje.",
                "issue_empty_answer_text": "Odpověď '{answer_key}' nemá žádný text.",
                "issue_no_correct_and_default_disabled": "Žádná správná odpověď není označená pomocí ')*' a výchozí odpověď není povolená.",
                "issue_correct_keys_missing": "Správné klíče {keys} nebyly mezi odpověďmi nalezeny; místo nich byla použita první odpověď '{fallback}'.",
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
                "preview_answers_multi": "Odpovědi (vyber všechny správné)",
                "preview_prev": "Předchozí",
                "preview_next": "Další",
                "preview_show_correct": "Ukázat správné",
                "preview_counter": "Otázka {i} / {n}",
                "preview_empty": "Žádné otázky",
                "preview_shuffle": "Míchat",
                "preview_time_limit": "Čas:",
                "preview_time_left": "Zbývá: {seconds}s",
                "preview_score": "Skóre {score}/{total}",
                "preview_submit": "Vyhodnotit",
                "preview_answer_field": "Odpověď",
                "preview_enter_text": "Napiš odpověď",
                "preview_enter_number": "Zadej číslo",
                "preview_matching": "Přiřazování",
                "preview_result_correct": "Správně ({score})",
                "preview_result_wrong": "Špatně ({score})",
                "preview_correct_answer": "Správná odpověď: {answer}",
                "preview_no_feedback": "Bez dalšího feedbacku.",
                "history_title": "Historie snapshotů",
                "history_restore": "Obnovit",
                "history_empty": "Historie je zatím prázdná.",
                "history_snapshot": "Snapshot",
                "bank_search_placeholder": "Hledat otázky...",
                "bank_filter_all": "Vše",
                "bank_filter_errors": "Jen chyby",
                "bank_filter_warnings": "Varování + chyby",
                "bank_filter_duplicates": "Duplikáty",
                "bank_filter_similar": "Podobné",
                "quick_fix_autocorrect_block": "Auto-opravit blok",
                "quick_fix_renumber_answers": "Přečíslovat odpovědi",
                "quick_fix_mark_first_answer_correct": "Označit první jako správnou",
                "quick_fix_remove_empty_answers": "Odebrat prázdné odpovědi",
                "quick_fix_canonicalize_truefalse": "Normalizovat True/False",
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
                "controls_expert_settings": "Expert settings",
                "controls_export_group": "Export metadata",
                "controls_question_bank": "Question bank",
                "controls_category": "Category:",
                "controls_name_prefix": "Question name prefix:",
                "controls_correct_feedback": "Correct feedback:",
                "controls_incorrect_feedback": "Incorrect feedback:",
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
                "toolbar_history": "🕘 History",
                "toolbar_batch_export": "🗂️ Export categories",
                "tooltip_default_correct": "Used if no answer is marked with ')*'.",
                "tooltip_auto": "Automatically converts a moment after you stop typing.",
                "tooltip_tolerant": "Tries to automatically fix common formatting issues (A., 1., spacing...).",
                "tooltip_multi_mode": "Applied only to blocks with 2+ correct answers (multiple ')*').",
                "tooltip_category": "Optionally prepend a $CATEGORY line to the export.",
                "tooltip_name_prefix": "Generate question titles such as Question1, Question2, ...",
                "tooltip_correct_feedback": "Optional feedback appended to every correct answer.",
                "tooltip_incorrect_feedback": "Optional feedback appended to every incorrect answer.",
                "tooltip_stats": "Open stats window for the last conversion.",
                "tooltip_preview": "Show questions like a student (preview).",
                "tooltip_auto_action": "Toggle automatic conversion while typing.",
                "tooltip_issues": "Show warnings/errors list and jump to a block.",
                "tooltip_history": "Restore a previously auto-saved snapshot.",
                "tooltip_batch_export": "Save questions grouped by category into a directory.",
                "tooltip_theme": "Dark Mode",
                "issues_title": "Issues (warnings and errors)",
                "issues_empty": "No warnings or errors.",
                "issues_error_prefix": "ERROR",
                "issues_warning_prefix": "WARNING",
                "issues_item": "[{severity}] Block {block_index}: {message}",
                "status_ready": "Ready. Paste your questions into Input.",
                "status_cleared": "Cleared.",
                "status_empty": "Input is empty.",
                "status_copied": "Output copied to clipboard.",
                "status_saved": "Saved: {path}",
                "status_ok": "Converted OK ({count} question(s)).",
                "status_warn": "Converted with warnings: {w}.",
                "status_err": "Converted with errors: {e} error(s), {w} warning(s).",
                "status_fixes": "Auto-fixes: {n}",
                "status_history_restored": "Restored snapshot from history.",
                "status_batch_saved": "Exported categories to: {path}",
                "msg_nothing_to_save_title": "Nothing to save",
                "msg_nothing_to_save": "Convert something first so the output is not empty.",
                "msg_save_title": "Save Moodle GIFT file",
                "msg_save_failed_title": "Save failed",
                "msg_convert_failed_title": "Conversion failed",
                "msg_batch_export_title": "Choose a folder for category export",
                "msg_batch_export_empty": "There are no questions available for category export.",
                "msg_preview_no_questions": "No valid questions found for preview.",
                "msg_invalid_path": "Invalid path:\n{path}\n\n{error}",
                "msg_file_not_found": "File not found:\n{path}",
                "msg_docx_module_missing": "DOCX support is unavailable because python-docx is not installed.",
                "msg_cannot_read_docx": "Cannot read .docx:\n{error}",
                "msg_cannot_read_file": "Cannot read file:\n{path}\n\n{error}",
                "msg_binary_file": (
                    "This file looks like a binary file (e.g., .pdf/image).\n"
                    "Please use a plain text file (.txt/.gift/.md) or .docx."
                ),
                "msg_cannot_decode_file": "Cannot decode file:\n{path}",
                "convert_failed_line": "Block {block_index}: {message}",
                "convert_failed_more": "... and {count} more.",
                "issue_no_blocks": "No question blocks found.",
                "issue_block_too_short": "Block is too short (needs question + at least 1 answer).",
                "issue_bad_answer_format": "Answer line doesn't match 'a) ...' or '1) ...' format: {line}",
                "issue_duplicate_answer_key": "Answer key '{answer_key}' is duplicated within the block.",
                "issue_empty_answer_text": "Answer '{answer_key}' has no text.",
                "issue_no_correct_and_default_disabled": "No correct answer marked with ')*' and default not allowed.",
                "issue_correct_keys_missing": "Correct key(s) {keys} not found in answers; used first answer '{fallback}' instead.",
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
                "preview_answers_multi": "Answers (select all that apply)",
                "preview_prev": "Previous",
                "preview_next": "Next",
                "preview_show_correct": "Show correct",
                "preview_counter": "Question {i} / {n}",
                "preview_empty": "No questions",
                "preview_shuffle": "Shuffle",
                "preview_time_limit": "Time:",
                "preview_time_left": "Left: {seconds}s",
                "preview_score": "Score {score}/{total}",
                "preview_submit": "Submit",
                "preview_answer_field": "Answer",
                "preview_enter_text": "Type your answer",
                "preview_enter_number": "Enter a number",
                "preview_matching": "Matching",
                "preview_result_correct": "Correct ({score})",
                "preview_result_wrong": "Wrong ({score})",
                "preview_correct_answer": "Correct answer: {answer}",
                "preview_no_feedback": "No extra feedback.",
                "history_title": "Snapshot history",
                "history_restore": "Restore",
                "history_empty": "History is empty.",
                "history_snapshot": "Snapshot",
                "bank_search_placeholder": "Search questions...",
                "bank_filter_all": "All",
                "bank_filter_errors": "Errors only",
                "bank_filter_warnings": "Warnings + errors",
                "bank_filter_duplicates": "Duplicates",
                "bank_filter_similar": "Similar",
                "quick_fix_autocorrect_block": "Auto-fix block",
                "quick_fix_renumber_answers": "Renumber answers",
                "quick_fix_mark_first_answer_correct": "Mark first answer correct",
                "quick_fix_remove_empty_answers": "Remove empty answers",
                "quick_fix_canonicalize_truefalse": "Normalize True/False",
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

        self.expert_toggle_btn = QPushButton()
        self.expert_toggle_btn.setCheckable(True)
        self.expert_toggle_btn.toggled.connect(self._toggle_expert_settings)
        layout.addWidget(self.expert_toggle_btn)

        self.export_group = QGroupBox()
        export_form = QFormLayout(self.export_group)
        export_form.setContentsMargins(12, 12, 12, 12)

        self.lbl_category = QLabel()
        self.category_edit = QLineEdit()
        export_form.addRow(self.lbl_category, self.category_edit)

        self.lbl_name_prefix = QLabel()
        self.name_prefix_edit = QLineEdit()
        export_form.addRow(self.lbl_name_prefix, self.name_prefix_edit)

        self.lbl_correct_feedback = QLabel()
        self.correct_feedback_edit = QLineEdit()
        export_form.addRow(self.lbl_correct_feedback, self.correct_feedback_edit)

        self.lbl_incorrect_feedback = QLabel()
        self.incorrect_feedback_edit = QLineEdit()
        export_form.addRow(self.lbl_incorrect_feedback, self.incorrect_feedback_edit)

        layout.addWidget(self.export_group)

        self.main_splitter = QSplitter(Qt.Horizontal)

        sidebar_wrap = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_wrap)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_bank = QLabel()
        sidebar_layout.addWidget(self.lbl_bank)
        self.bank_search = QLineEdit()
        sidebar_layout.addWidget(self.bank_search)
        self.bank_filter = QComboBox()
        sidebar_layout.addWidget(self.bank_filter)
        self.bank_list = QListWidget()
        self.bank_list.itemClicked.connect(self._jump_from_bank_item)
        sidebar_layout.addWidget(self.bank_list, 1)
        self.main_splitter.addWidget(sidebar_wrap)

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
        self.inline_issue_label = QLabel("")
        self.inline_issue_label.setObjectName("IssueBanner")
        self.inline_issue_label.setWordWrap(True)
        self.inline_issue_label.hide()
        input_layout.addWidget(self.inline_issue_label)
        self.quick_fix_wrap = QWidget()
        self.quick_fix_layout = QHBoxLayout(self.quick_fix_wrap)
        self.quick_fix_layout.setContentsMargins(0, 0, 0, 0)
        self.quick_fix_wrap.hide()
        input_layout.addWidget(self.quick_fix_wrap)
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
        self.main_splitter.addWidget(self.splitter)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 4)
        layout.addWidget(self.main_splitter, 1)

        # Status + author label
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self.lbl_author = QLabel("")
        self.lbl_author.setObjectName("AuthorLabel")
        self.lbl_author.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status.addPermanentWidget(self.lbl_author)

        # Toolbar
        self._build_toolbar()

        # Auto convert timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.convert_auto)
        self._session_timer = QTimer(self)
        self._session_timer.setSingleShot(True)
        self._session_timer.timeout.connect(self.save_session_state)
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.timeout.connect(self.save_history_snapshot)
        self._restoring_session = False
        self._restored_session = False

        self.input_edit.textChanged.connect(self._on_text_changed)
        self.correct_combo.currentTextChanged.connect(self._on_text_changed)
        self.assume_default_cb.stateChanged.connect(self._on_text_changed)
        self.tolerant_cb.stateChanged.connect(self._on_text_changed)
        self.multi_mode_combo.currentIndexChanged.connect(self._on_text_changed)
        self.category_edit.textChanged.connect(self._on_text_changed)
        self.name_prefix_edit.textChanged.connect(self._on_text_changed)
        self.correct_feedback_edit.textChanged.connect(self._on_text_changed)
        self.incorrect_feedback_edit.textChanged.connect(self._on_text_changed)
        self.bank_search.textChanged.connect(self._refresh_question_bank)
        self.bank_filter.currentIndexChanged.connect(self._refresh_question_bank)

        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)

        # Data for dialogs
        self.last_stats: Optional[Stats] = None
        self.last_fixes: int = 0
        self.last_questions: List[QuestionItem] = []
        self.last_issues: List[ConvertIssue] = []
        self.stats_dialog: Optional[StatsDialog] = None
        self.preview_dialog: Optional[PreviewDialog] = None
        self.issues_dialog: Optional[IssuesDialog] = None
        self.history_dialog: Optional[HistoryDialog] = None
        self.session_history: List[Dict[str, Any]] = []
        self.current_block_span = None

        # Load settings & apply language
        self.load_settings()
        self.apply_language(self.lang)
        if self._restored_session and self.input_edit.toPlainText().strip():
            self.convert_now(silent=True)

        self.status.showMessage(self.tr_("status_ready"), 4000)

    def _icon(self, theme_name: str, fallback: QStyle.StandardPixmap) -> QIcon:
        ico = QIcon.fromTheme(theme_name)
        if not ico.isNull():
            return ico
        return self.style().standardIcon(fallback)
    
    def apply_theme(self, theme: str):
        theme = "dark" if str(theme).lower() == "dark" else "light"
        self.theme = theme
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_theme_stylesheet(theme))

        self.highlighter.set_theme(theme)

        self._refresh_block_highlight()

        if hasattr(self, "act_theme"):
            self.act_theme.blockSignals(True)
            self.act_theme.setChecked(self.theme == "dark")
            self.act_theme.blockSignals(False)

    def _theme_palette(self) -> Dict[str, str]:
        return THEME_PALETTES["dark" if getattr(self, "theme", "light") == "dark" else "light"]

    def _update_expert_toggle_text(self):
        label = self.tr_("controls_expert_settings")
        prefix = "▼" if self.expert_toggle_btn.isChecked() else "▶"
        self.expert_toggle_btn.setText(f"{prefix} {label}")

    def _toggle_expert_settings(self, checked: bool):
        self.export_group.setVisible(checked)
        self._update_expert_toggle_text()
        if hasattr(self, "settings"):
            self.settings.setValue("ui/expert_settings_expanded", checked)

    def toggle_theme(self, checked: bool):
        new_theme = "dark" if checked else "light"
        self.apply_theme(new_theme)
        self.settings.setValue("ui/theme", new_theme)

    def _clear_quick_fix_buttons(self):
        while self.quick_fix_layout.count():
            item = self.quick_fix_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.quick_fix_wrap.hide()

    def _set_quick_fix_actions(self, issue: Optional[ConvertIssue]):
        self._clear_quick_fix_buttons()
        if issue is None:
            return
        for fix_id in available_quick_fixes(issue):
            button = QPushButton(self.tr_(f"quick_fix_{fix_id}"))
            button.clicked.connect(lambda _checked=False, current_fix=fix_id: self._apply_quick_fix(current_fix))
            self.quick_fix_layout.addWidget(button)
        if self.quick_fix_layout.count():
            self.quick_fix_layout.addStretch(1)
            self.quick_fix_wrap.show()

    def _replace_block_text(self, start: int, end: int, new_block_text: str):
        cursor = self.input_edit.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        cursor.insertText(new_block_text)
        self.input_edit.setTextCursor(cursor)
        self.convert_now(silent=True)

    def _apply_quick_fix(self, fix_id: str):
        block = self.current_block_span
        if block is None:
            return
        new_block_text = apply_quick_fix(block.text, fix_id)
        if new_block_text.strip() == block.text.strip():
            return
        self._replace_block_text(block.start, block.end, new_block_text)

    def _refresh_question_bank(self):
        if not hasattr(self, "bank_list"):
            return
        self.bank_list.clear()

        query = sanitize_single_line(self.bank_search.text()).lower()
        filter_value = self.bank_filter.currentData() if self.bank_filter.count() else "all"
        issues_by_block: Dict[int, List[ConvertIssue]] = {}
        for issue in self.last_issues:
            issues_by_block.setdefault(issue.block_index, []).append(issue)

        for question in self.last_questions:
            issues = issues_by_block.get(question.block_index, [])
            severity = "ok"
            if any(issue.severity == "error" for issue in issues):
                severity = "error"
            elif any(issue.severity == "warning" for issue in issues):
                severity = "warning"

            if filter_value == "errors" and severity != "error":
                continue
            if filter_value == "warnings" and severity == "ok":
                continue
            if filter_value == "duplicates" and not any(issue.code == "issue_duplicate_question" for issue in issues):
                continue
            if filter_value == "similar" and not any(issue.code == "issue_similar_question" for issue in issues):
                continue

            label_type = question.question_type.upper()
            title = question.title or question.question
            summary = f"[{label_type}] {question.block_index}. {title}"
            if severity == "error":
                summary = "[ERROR] " + summary
            elif severity == "warning":
                summary = "[WARN] " + summary

            searchable = f"{summary} {question.question} {question_summary(question)}".lower()
            if query and query not in searchable:
                continue

            item = QListWidgetItem(summary)
            item.setData(Qt.UserRole, (question.start, question.end))
            self.bank_list.addItem(item)

    def _jump_from_bank_item(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if not data:
            return
        start, end = data
        self.highlight_span(start, end)

    def _set_inline_issue_banner(self, issue: Optional[ConvertIssue]):
        if issue is None:
            self.inline_issue_label.clear()
            self.inline_issue_label.hide()
            self._set_quick_fix_actions(None)
            return

        severity = (
            self.tr_("issues_error_prefix")
            if issue.severity == "error"
            else self.tr_("issues_warning_prefix")
        )
        self.inline_issue_label.setText(
            self.tr_(
                "issues_item",
                severity=severity,
                block_index=issue.block_index,
                message=issue.message,
            )
        )
        self.inline_issue_label.setProperty("severity", issue.severity)
        self.inline_issue_label.style().unpolish(self.inline_issue_label)
        self.inline_issue_label.style().polish(self.inline_issue_label)
        self.inline_issue_label.show()
        self._set_quick_fix_actions(issue)

    def _make_selection(self, start: int, end: int, color_hex: str, alpha: int) -> QTextEdit.ExtraSelection:
        selection = QTextEdit.ExtraSelection()
        color = QColor(color_hex)
        color.setAlpha(alpha)
        selection.format.setBackground(color)

        cursor = self.input_edit.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        selection.cursor = cursor
        return selection

    def _refresh_block_highlight(self):
        text = self.input_edit.toPlainText()
        if not text.strip():
            self.input_edit.setExtraSelections([])
            self._set_inline_issue_banner(None)
            return

        cursor = self.input_edit.textCursor()
        pos = cursor.position()

        blocks = iter_blocks_with_spans(text)
        if not blocks:
            self.input_edit.setExtraSelections([])
            self._set_inline_issue_banner(None)
            return

        active = None
        for block in blocks:
            if block.start <= pos <= block.end:
                active = block
                break
        self.current_block_span = active

        palette = self._theme_palette()
        selections: List[QTextEdit.ExtraSelection] = []
        current_issue: Optional[ConvertIssue] = None

        for issue in self.last_issues:
            if issue.start == issue.end:
                continue
            color_key = "issue_error_bg" if issue.severity == "error" else "issue_warning_bg"
            selections.append(self._make_selection(issue.start, issue.end, palette[color_key], 105))
            if active is not None and issue.start == active.start and issue.end == active.end:
                current_issue = issue
            elif current_issue is None and issue.start <= pos <= issue.end:
                current_issue = issue

        if active is not None:
            selections.append(self._make_selection(active.start, active.end, palette["active_block_bg"], 120))

        self.input_edit.setExtraSelections(selections)
        self._set_inline_issue_banner(current_issue)


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
        self.setWindowTitle(f"{self.tr_('app_title')} {APP_VERSION}")

        self.lbl_default_correct.setText(self.tr_("controls_default_correct"))
        self.assume_default_cb.setText(self.tr_("controls_use_default"))
        self.act_auto.setText(self.tr_("controls_auto"))
        self.tolerant_cb.setText(self.tr_("controls_tolerant"))
        self.lbl_language.setText(self.tr_("controls_language"))
        self.lbl_multi_mode.setText(self.tr_("controls_multi_mode"))
        self._update_expert_toggle_text()
        self.export_group.setTitle(self.tr_("controls_export_group"))
        self.lbl_bank.setText(self.tr_("controls_question_bank"))
        self.lbl_category.setText(self.tr_("controls_category"))
        self.lbl_name_prefix.setText(self.tr_("controls_name_prefix"))
        self.lbl_correct_feedback.setText(self.tr_("controls_correct_feedback"))
        self.lbl_incorrect_feedback.setText(self.tr_("controls_incorrect_feedback"))

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
        self.category_edit.setToolTip(self.tr_("tooltip_category"))
        self.name_prefix_edit.setToolTip(self.tr_("tooltip_name_prefix"))
        self.correct_feedback_edit.setToolTip(self.tr_("tooltip_correct_feedback"))
        self.incorrect_feedback_edit.setToolTip(self.tr_("tooltip_incorrect_feedback"))
        self.bank_search.setPlaceholderText(self.tr_("bank_search_placeholder"))

        self.input_edit.setPlaceholderText(self.tr_("placeholder"))

        current_bank_filter = self.bank_filter.currentData()
        self.bank_filter.blockSignals(True)
        self.bank_filter.clear()
        self.bank_filter.addItem(self.tr_("bank_filter_all"), "all")
        self.bank_filter.addItem(self.tr_("bank_filter_errors"), "errors")
        self.bank_filter.addItem(self.tr_("bank_filter_warnings"), "warnings")
        self.bank_filter.addItem(self.tr_("bank_filter_duplicates"), "duplicates")
        self.bank_filter.addItem(self.tr_("bank_filter_similar"), "similar")
        bank_index = max(0, self.bank_filter.findData(current_bank_filter))
        self.bank_filter.setCurrentIndex(bank_index)
        self.bank_filter.blockSignals(False)

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
        if hasattr(self, "act_history"):
            self.act_history.setText(self.tr_("toolbar_history"))
            self.act_history.setToolTip(self.tr_("tooltip_history"))
        if hasattr(self, "act_batch_export"):
            self.act_batch_export.setText(self.tr_("toolbar_batch_export"))
            self.act_batch_export.setToolTip(self.tr_("tooltip_batch_export"))

        self.lbl_author.setText(self.tr_("author_label"))

        self.act_theme.setToolTip(self.tr_("tooltip_theme"))

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

        if self.history_dialog is not None:
            self.history_dialog.setWindowTitle(self.tr_("history_title"))
            self.history_dialog.btn_restore.setText(self.tr_("history_restore"))
            self.history_dialog.set_snapshots(self.session_history)

        self._refresh_block_highlight()
        self._refresh_question_bank()

    def _on_language_changed(self):
        lang_code = self.lang_combo.currentData()
        if lang_code in ("cs", "en"):
            self.apply_language(lang_code)
            if self.input_edit.toPlainText().strip():
                self.convert_now(silent=True)
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

        self.act_batch_export = QAction(self._icon("folder-download", QStyle.SP_DialogSaveButton), "", self)
        self.act_batch_export.triggered.connect(self.export_categories)
        tb.addAction(self.act_batch_export)

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

        self.act_history = QAction(self._icon("document-open-recent", QStyle.SP_FileDialogDetailedView), "", self)
        self.act_history.triggered.connect(self.show_history)
        tb.addAction(self.act_history)

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
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.tr_("msg_open_title"),
            start_dir,
            "Supported (*.txt *.gift *.md *.docx *.csv);;All files (*.*)",
        )
        if not paths:
            return
        self.load_text_files(paths)

    def _decode_text_file(self, file_path: Path) -> str:
        data = file_path.read_bytes()
        if b"\x00" in data[:4096]:
            raise ValueError(self.tr_("msg_binary_file"))
        for enc in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
            try:
                return data.decode(enc)
            except Exception:
                continue
        raise ValueError(self.tr_("msg_cannot_decode_file", path=file_path))

    def _load_single_path(self, path: str) -> str:
        try:
            file_path = Path(str(path)).expanduser()
        except Exception as e:
            raise ValueError(self.tr_("msg_invalid_path", path=path, error=e)) from e

        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(self.tr_("msg_file_not_found", path=file_path))

        suffix = file_path.suffix.lower()

        if suffix == ".docx":
            try:
                from docx import Document
            except ImportError:
                raise ValueError(self.tr_("msg_docx_module_missing"))
            try:
                doc = Document(str(file_path))
                return "\n".join(par.text for par in doc.paragraphs)
            except Exception as e:
                raise ValueError(self.tr_("msg_cannot_read_docx", error=e)) from e

        try:
            if suffix == ".gift":
                imported, issues, _questions = import_gift_to_blocks(self._decode_text_file(file_path), translate=self.tr_)
                if issues:
                    self.last_issues = issues
                return imported
            if suffix == ".csv":
                blocks, issues = csv_text_to_blocks(self._decode_text_file(file_path), translate=self.tr_)
                if issues:
                    raise ValueError(issues[0].message)
                return blocks
            return self._decode_text_file(file_path)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(self.tr_("msg_cannot_read_file", path=file_path, error=e)) from e

    def load_text_files(self, paths: List[str]):
        texts: List[str] = []
        last_parent = None
        for raw_path in paths:
            try:
                text = self._load_single_path(raw_path)
            except FileNotFoundError as e:
                QMessageBox.warning(self, self.tr_("msg_open_failed_title"), str(e))
                return
            except Exception as e:
                QMessageBox.critical(self, self.tr_("msg_open_failed_title"), str(e))
                return
            texts.append(text.strip())
            last_parent = str(Path(raw_path).expanduser().parent)

        self.input_edit.setPlainText("\n\n".join(part for part in texts if part))
        if last_parent:
            self.settings.setValue("ui/last_dir", last_parent)
        self.convert_now()
        if len(paths) == 1:
            self.status.showMessage(self.tr_("status_loaded", path=paths[0]), 3000)
        else:
            self.status.showMessage(self.tr_("status_loaded", path=f"{len(paths)} files"), 3000)

    def load_text_file(self, path: str):
        self.load_text_files([path])


    # -------- QSettings --------

    def load_settings(self):
        self._restoring_session = True
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
        expert_settings_expanded = self.settings.value("ui/expert_settings_expanded", False, type=bool)

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

        main_sizes = self.settings.value("ui/main_splitter_sizes")
        if isinstance(main_sizes, list) and len(main_sizes) == 2:
            try:
                self.main_splitter.setSizes([int(main_sizes[0]), int(main_sizes[1])])
            except Exception:
                pass

        if self.settings.contains("session/lang"):
            session_lang = self.settings.value("session/lang", lang)
            if session_lang in ("cs", "en"):
                self.lang = session_lang
                self.lang_combo.setCurrentIndex(0 if session_lang == "cs" else 1)

        if self.settings.contains("session/default_correct"):
            self.correct_combo.setCurrentText(str(self.settings.value("session/default_correct", default_key)))
        if self.settings.contains("session/assume_default"):
            self.assume_default_cb.setChecked(self.settings.value("session/assume_default", assume_default, type=bool))
        if self.settings.contains("session/tolerant"):
            self.tolerant_cb.setChecked(self.settings.value("session/tolerant", tolerant, type=bool))
        if self.settings.contains("session/multi_mode"):
            session_multi_mode = self.settings.value("session/multi_mode", multi_mode)
            self.multi_mode_combo.setCurrentIndex(1 if str(session_multi_mode) == "penalize" else 0)

        self.category_edit.setText(self.settings.value("session/category", "", type=str))
        self.name_prefix_edit.setText(self.settings.value("session/name_prefix", "", type=str))
        self.correct_feedback_edit.setText(self.settings.value("session/correct_feedback", "", type=str))
        self.incorrect_feedback_edit.setText(self.settings.value("session/incorrect_feedback", "", type=str))

        has_expert_values = any(
            (
                self.category_edit.text().strip(),
                self.name_prefix_edit.text().strip(),
                self.correct_feedback_edit.text().strip(),
                self.incorrect_feedback_edit.text().strip(),
            )
        )
        self.expert_toggle_btn.setChecked(bool(expert_settings_expanded or has_expert_values))

        session_text = self.settings.value("session/input_text", "", type=str)
        session_cursor = self.settings.value("session/cursor_position", 0, type=int)
        if session_text:
            self.input_edit.setPlainText(session_text)
            cursor = self.input_edit.textCursor()
            cursor.setPosition(max(0, min(int(session_cursor), len(session_text))))
            self.input_edit.setTextCursor(cursor)
            self._restored_session = True

        history_raw = self.settings.value("session/history", "[]", type=str)
        try:
            parsed_history = json.loads(history_raw)
            if isinstance(parsed_history, list):
                self.session_history = parsed_history[-25:]
        except Exception:
            self.session_history = []

        self._restoring_session = False

    def save_settings(self):
        self.settings.setValue("ui/lang", self.lang_combo.currentData() or self.lang)
        self.settings.setValue("ui/auto_convert", self.act_auto.isChecked())
        self.settings.setValue("ui/assume_default", self.assume_default_cb.isChecked())
        self.settings.setValue("ui/tolerant", self.tolerant_cb.isChecked())
        self.settings.setValue("ui/default_correct", self.correct_combo.currentText().strip() or "a")
        self.settings.setValue("ui/multi_mode", self.multi_mode_combo.currentData() or "wipe")
        self.settings.setValue("ui/expert_settings_expanded", self.expert_toggle_btn.isChecked())
        self.settings.setValue("ui/theme", getattr(self, "theme", "light"))
        self.settings.setValue("ui/geometry", self.saveGeometry())
        self.settings.setValue("ui/splitter_sizes", self.splitter.sizes())
        self.settings.setValue("ui/main_splitter_sizes", self.main_splitter.sizes())

    def save_session_state(self):
        if getattr(self, "_restoring_session", False):
            return

        text = self.input_edit.toPlainText()
        cursor = self.input_edit.textCursor()

        self.settings.setValue("session/input_text", text)
        self.settings.setValue("session/cursor_position", cursor.position())
        self.settings.setValue("session/category", self.category_edit.text())
        self.settings.setValue("session/name_prefix", self.name_prefix_edit.text())
        self.settings.setValue("session/correct_feedback", self.correct_feedback_edit.text())
        self.settings.setValue("session/incorrect_feedback", self.incorrect_feedback_edit.text())
        self.settings.setValue("session/default_correct", self.correct_combo.currentText().strip() or "a")
        self.settings.setValue("session/assume_default", self.assume_default_cb.isChecked())
        self.settings.setValue("session/tolerant", self.tolerant_cb.isChecked())
        self.settings.setValue("session/multi_mode", self.multi_mode_combo.currentData() or "wipe")
        self.settings.setValue("session/lang", self.lang_combo.currentData() or self.lang)
        self.settings.setValue("session/history", json.dumps(self.session_history[-25:]))

    def save_history_snapshot(self):
        if getattr(self, "_restoring_session", False):
            return
        text = self.input_edit.toPlainText().strip()
        if not text:
            return

        snapshot = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "text": self.input_edit.toPlainText(),
            "cursor_position": self.input_edit.textCursor().position(),
            "category": self.category_edit.text(),
            "name_prefix": self.name_prefix_edit.text(),
            "correct_feedback": self.correct_feedback_edit.text(),
            "incorrect_feedback": self.incorrect_feedback_edit.text(),
        }
        if self.session_history and self.session_history[-1].get("text") == snapshot["text"]:
            return

        self.session_history.append(snapshot)
        self.session_history = self.session_history[-25:]
        self.settings.setValue("session/history", json.dumps(self.session_history))
        if self.history_dialog is not None:
            self.history_dialog.set_snapshots(self.session_history)

    def clear_session_state(self):
        self._session_timer.stop()
        for key in (
            "session/input_text",
            "session/cursor_position",
            "session/category",
            "session/name_prefix",
            "session/correct_feedback",
            "session/incorrect_feedback",
            "session/default_correct",
            "session/assume_default",
            "session/tolerant",
            "session/multi_mode",
            "session/lang",
        ):
            self.settings.remove(key)

    def closeEvent(self, event):
        self.save_history_snapshot()
        self.save_session_state()
        self.save_settings()
        super().closeEvent(event)

    # -------- UI helpers --------

    def _on_text_changed(self, *_args):
        if not getattr(self, "_restoring_session", False):
            self._session_timer.start(800)
            self._history_timer.start(15000)
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
        self._timer.stop()
        self._history_timer.stop()
        self.input_edit.clear()
        self.output_edit.clear()
        self.category_edit.clear()
        self.name_prefix_edit.clear()
        self.correct_feedback_edit.clear()
        self.incorrect_feedback_edit.clear()
        self.last_stats = None
        self.last_fixes = 0
        self.last_questions = []
        self.last_issues = []
        self._set_inline_issue_banner(None)
        self.clear_session_state()

        if self.stats_dialog is not None:
            self.stats_dialog.set_stats(self.last_stats, self.last_fixes)
        if self.preview_dialog is not None:
            self.preview_dialog.set_questions([], 0)
        if self.issues_dialog is not None:
            self.issues_dialog.set_issues([])
        if self.history_dialog is not None:
            self.history_dialog.set_snapshots(self.session_history)

        self._refresh_block_highlight()
        self._refresh_question_bank()

        self.status.showMessage(self.tr_("status_cleared"), 2000)

    def convert_now(self, silent: bool = False, from_auto: bool = False):
        self._timer.stop()
        text = self.input_edit.toPlainText()
        default_key = (self.correct_combo.currentText() or "a").strip()
        assume_default = self.assume_default_cb.isChecked()
        tolerant = self.tolerant_cb.isChecked()
        multi_mode = self.multi_mode_combo.currentData() or "wipe"
        category = self.category_edit.text()
        question_name_prefix = self.name_prefix_edit.text()
        correct_feedback = self.correct_feedback_edit.text()
        incorrect_feedback = self.incorrect_feedback_edit.text()

        if not text.strip():
            self.output_edit.clear()
            self.last_stats = None
            self.last_fixes = 0
            self.last_questions = []
            self.last_issues = []
            self._refresh_block_highlight()
            self._refresh_question_bank()
            if not silent:
                self.status.showMessage(self.tr_("status_empty"), 3000)
            return

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
            category=category,
            question_name_prefix=question_name_prefix,
            correct_feedback=correct_feedback,
            incorrect_feedback=incorrect_feedback,
            translate=self.tr_,
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

        self._refresh_block_highlight()
        self._refresh_question_bank()

        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]

        if tolerant and fixes > 0 and not silent:
            self.status.showMessage(self.tr_("status_fixes", n=fixes), 2500)

        if errors:
            if not silent:
                first = errors[0]
                if first.start != first.end:
                    self.highlight_span(first.start, first.end)
                self.status.showMessage(self.tr_("status_err", e=len(errors), w=len(warnings)), 6000)

                if not out.strip():
                    msg = "\n".join(
                        [
                            self.tr_("convert_failed_line", block_index=issue.block_index, message=issue.message)
                            for issue in errors[:20]
                        ]
                    )
                    if len(errors) > 20:
                        msg += "\n" + self.tr_("convert_failed_more", count=len(errors) - 20)
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
            QMessageBox.critical(self, self.tr_("msg_save_failed_title"), str(e))

    def export_categories(self):
        if not self.last_questions:
            self.convert_now(silent=True)
        if not self.last_questions:
            QMessageBox.information(self, self.tr_("msg_save_failed_title"), self.tr_("msg_batch_export_empty"))
            return

        target_dir = QFileDialog.getExistingDirectory(
            self,
            self.tr_("msg_batch_export_title"),
            self.settings.value("ui/last_dir", str(Path.home())),
        )
        if not target_dir:
            return

        outputs = export_questions_by_category(
            self.last_questions,
            multi_mode=str(self.multi_mode_combo.currentData() or "wipe"),
        )
        try:
            for filename, content in outputs.items():
                output_path = Path(target_dir) / f"{filename}.gift"
                output_path.write_text(content + ("\n" if content and not content.endswith("\n") else ""), encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, self.tr_("msg_save_failed_title"), str(e))
            return

        self.status.showMessage(self.tr_("status_batch_saved", path=target_dir), 5000)

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

    def restore_history_snapshot(self, snapshot: Dict[str, Any]):
        self._restoring_session = True
        self.input_edit.setPlainText(snapshot.get("text", ""))
        self.category_edit.setText(snapshot.get("category", ""))
        self.name_prefix_edit.setText(snapshot.get("name_prefix", ""))
        self.correct_feedback_edit.setText(snapshot.get("correct_feedback", ""))
        self.incorrect_feedback_edit.setText(snapshot.get("incorrect_feedback", ""))
        cursor = self.input_edit.textCursor()
        cursor.setPosition(max(0, min(int(snapshot.get("cursor_position", 0)), len(self.input_edit.toPlainText()))))
        self.input_edit.setTextCursor(cursor)
        self._restoring_session = False
        self.convert_now(silent=True)
        self.save_session_state()
        self.status.showMessage(self.tr_("status_history_restored"), 3000)

    def show_history(self):
        if self.history_dialog is None:
            self.history_dialog = HistoryDialog(self, self.tr_, self.restore_history_snapshot)
        self.history_dialog.setWindowTitle(self.tr_("history_title"))
        self.history_dialog.set_snapshots(self.session_history)
        self.history_dialog.show()
        self.history_dialog.raise_()
        self.history_dialog.activateWindow()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(build_theme_stylesheet("light"))

    icon_path = Path(__file__).parent / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    w = GiftFormatterMainWindow(icon_path=icon_path)
    w.resize(1020, 880)
    w.show()
    sys.exit(app.exec())
