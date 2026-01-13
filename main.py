import re
import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPlainTextEdit, QPushButton, QComboBox,
    QCheckBox, QMessageBox, QFileDialog
)

BLOCK_SPLIT_RE = re.compile(r"\n\s*\n+", re.MULTILINE)
ANSWER_RE = re.compile(r"^\s*([a-zA-Z])\)\s*(.*)\s*$")
MARKED_CORRECT_RE = re.compile(r"^\s*([a-zA-Z])\)\*\s*(.*)\s*$")  # a)* correct


def normalize_question_line(q: str) -> str:
    q = q.strip()
    if q.endswith("?"):
        q = q[:-1].rstrip()
    return q + " ?"


def parse_block(block_text: str):
    lines = [ln.strip() for ln in block_text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None, "Block is too short (needs question + at least 1 answer)."

    question = lines[0]
    raw_answers = lines[1:]

    answers = []
    marked_correct_letter = None

    for ln in raw_answers:
        m_marked = MARKED_CORRECT_RE.match(ln)
        if m_marked:
            letter = m_marked.group(1).lower()
            text = m_marked.group(2).strip()
            answers.append((letter, text, True))
            if marked_correct_letter is not None and marked_correct_letter != letter:
                return None, "Multiple answers are marked correct using ')*'."
            marked_correct_letter = letter
            continue

        m = ANSWER_RE.match(ln)
        if not m:
            return None, f"Answer line doesn't match 'a) ...' format: {ln}"
        letter = m.group(1).lower()
        text = m.group(2).strip()
        answers.append((letter, text, False))

    return (question, answers, marked_correct_letter), None


def convert_blocks(all_text: str, default_correct_letter: str = "a", assume_default_if_unmarked: bool = True):
    blocks = [b.strip() for b in BLOCK_SPLIT_RE.split(all_text.strip()) if b.strip()]
    if not blocks:
        return "", ["No question blocks found."]

    outputs = []
    errors = []

    for idx, block in enumerate(blocks, start=1):
        parsed, err = parse_block(block)
        if err:
            errors.append(f"Block {idx}: {err}")
            continue

        question, answers, marked_correct_letter = parsed

        correct_letter = marked_correct_letter
        if correct_letter is None:
            if assume_default_if_unmarked:
                correct_letter = default_correct_letter.lower()
            else:
                errors.append(f"Block {idx}: No correct answer marked with ')*' and default not allowed.")
                continue

        q_line = question
        out_lines = [f"{q_line} {{"]

        for letter, text, _is_marked in answers:
            prefix = "=" if letter == correct_letter else "~"
            out_lines.append(prefix + text)

        out_lines.append("}")
        outputs.append("\n".join(out_lines))

    return "\n\n".join(outputs), errors


class GiftFormatter(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Test Formatter → Moodle .GIFT")

        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Default correct:"))
        self.correct_combo = QComboBox()
        self.correct_combo.addItems(list("abcd"))
        self.correct_combo.setCurrentText("a")
        controls.addWidget(self.correct_combo)

        self.assume_default_cb = QCheckBox("Use default if none marked with ')*'")
        self.assume_default_cb.setChecked(True)
        controls.addWidget(self.assume_default_cb)

        controls.addStretch(1)
        layout.addLayout(controls)

        layout.addWidget(QLabel("Input (separate questions by blank lines; mark correct with a)* if you want):"))
        self.input_edit = QPlainTextEdit()
        layout.addWidget(self.input_edit, 2)

        btn_row = QHBoxLayout()
        self.convert_btn = QPushButton("Convert →")
        self.convert_btn.clicked.connect(self.on_convert)
        btn_row.addWidget(self.convert_btn)

        self.copy_btn = QPushButton("Copy output")
        self.copy_btn.clicked.connect(self.on_copy)
        btn_row.addWidget(self.copy_btn)

        self.save_btn = QPushButton("Save as .gift")
        self.save_btn.clicked.connect(self.on_save_gift)
        btn_row.addWidget(self.save_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.on_clear)
        btn_row.addWidget(self.clear_btn)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("Output:"))
        self.output_edit = QPlainTextEdit()
        self.output_edit.setReadOnly(True)
        layout.addWidget(self.output_edit, 2)

    def on_clear(self):
        self.input_edit.clear()
        self.output_edit.clear()

    def on_convert(self):
        text = self.input_edit.toPlainText()
        default_letter = self.correct_combo.currentText()
        assume_default = self.assume_default_cb.isChecked()

        out, errors = convert_blocks(
            text,
            default_correct_letter=default_letter,
            assume_default_if_unmarked=assume_default
        )
        self.output_edit.setPlainText(out)

        if errors:
            QMessageBox.warning(self, "Some blocks had issues", "\n".join(errors))

    def on_copy(self):
        QApplication.clipboard().setText(self.output_edit.toPlainText())
        QMessageBox.information(self, "Copied", "Output copied to clipboard.")

    def on_save_gift(self):
        content = self.output_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "Nothing to save", "Convert something first so the output is not empty.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Moodle GIFT file",
            "quiz.gift",
            "Moodle GIFT (*.gift)"
        )
        if not path:
            return

        if not path.lower().endswith(".gift"):
            path += ".gift"

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content + "\n")
            QMessageBox.information(self, "Saved", f"Saved successfully:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = GiftFormatter()
    w.resize(900, 700)
    w.show()
    sys.exit(app.exec())
