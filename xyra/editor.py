import os
import sys
import tempfile
from typing import Callable, Tuple

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QKeySequence, QPainter, QTextCursor, QTextFormat, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

SaveCallback = Callable[[str, str], Tuple[bool, str]]


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.code_editor = editor

    def sizeHint(self):
        return QSize(self.code_editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.code_editor.line_number_area_paint_event(event)


class CodeTextEdit(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width(0)
        self.highlight_current_line()

    def line_number_area_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 22 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#101722"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        painter.setFont(self.font())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(QColor("#637083"))
                painter.drawText(0, top, self.line_number_area.width() - 8, self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, number)

            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self):
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#172235"))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])


class TextEditorWindow(QMainWindow):
    def __init__(self, remote_path: str, initial_text: str, save_callback: SaveCallback):
        super().__init__()
        self.remote_path = remote_path
        self.save_callback = save_callback

        self.setWindowTitle(f"Edit - {self.remote_path}")
        self.resize(1120, 760)
        self._saved_once = False

        central = QWidget()
        central.setObjectName("editorRoot")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 14, 14, 10)
        layout.setSpacing(10)

        self._apply_theme()
        layout.addWidget(self._build_header())

        self.editor = CodeTextEdit()
        self.editor.setPlainText(initial_text)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setTabStopDistance(4 * self.editor.fontMetrics().horizontalAdvance(" "))
        self.editor.setFont(self._code_font())
        layout.addWidget(self.editor, 1)

        self.status_label = QLabel("")
        self.statusBar().addPermanentWidget(self.status_label)
        self.statusBar().setSizeGripEnabled(False)
        self.update_cursor_position()

        self.shortcut_save = QShortcut(QKeySequence("Ctrl+S"), self)
        self.shortcut_save.activated.connect(self.on_save)
        self.shortcut_quit = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.shortcut_quit.activated.connect(self.close)

        self.editor.textChanged.connect(self.on_text_changed)
        self.editor.cursorPositionChanged.connect(self.update_cursor_position)
        self.editor.document().setModified(False)

    def _build_header(self):
        header = QFrame()
        header.setObjectName("editorHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(10)

        title_col = QVBoxLayout()
        self.title_label = QLabel(os.path.basename(self.remote_path) or self.remote_path)
        self.title_label.setObjectName("editorTitle")
        self.path_label = QLabel(self.remote_path)
        self.path_label.setObjectName("editorPath")
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.path_label)
        row.addLayout(title_col, 1)

        self.dirty_label = QLabel("Ready")
        self.dirty_label.setObjectName("dirtyBadge")
        row.addWidget(self.dirty_label)

        btn_save_local = QPushButton("Save local")
        btn_save_local.clicked.connect(self.on_save_local)
        row.addWidget(btn_save_local)

        btn_save = QPushButton("Save to server")
        btn_save.setObjectName("primaryButton")
        btn_save.clicked.connect(self.on_save)
        row.addWidget(btn_save)

        return header

    def _code_font(self):
        mono = QFont("Cascadia Code")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(11)
        return mono

    def _apply_theme(self):
        self.setStyleSheet("""
            QWidget#editorRoot {
                background: #0b1018;
                color: #e8eef7;
            }
            QFrame#editorHeader {
                background: #111a27;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
            }
            QLabel#editorTitle {
                color: #f5f8fc;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#editorPath {
                color: #8fa1b7;
                font-size: 11px;
            }
            QLabel#dirtyBadge {
                color: #a9f0c4;
                background: rgba(83,209,139,0.12);
                border: 1px solid rgba(83,209,139,0.22);
                border-radius: 11px;
                padding: 5px 10px;
            }
            QPushButton {
                color: #e8eef7;
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 12px;
                padding: 8px 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(110,168,255,0.15);
                border-color: rgba(110,168,255,0.35);
            }
            QPushButton#primaryButton {
                color: #071017;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #9ff8d4,
                    stop:1 #57dca8);
                border: 1px solid rgba(125,240,193,0.95);
                font-weight: 800;
            }
            QPushButton#primaryButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #b9ffe3,
                    stop:1 #6ff0bd);
                border-color: #d7ffef;
            }
            QPushButton#primaryButton:pressed {
                background: #4dc996;
                border-color: #4dc996;
            }
            QPlainTextEdit {
                color: #dce7f5;
                background: #0d131d;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
                padding: 12px;
                selection-background-color: rgba(110,168,255,0.35);
                selection-color: #ffffff;
            }
            QStatusBar {
                color: #93a5ba;
                background: transparent;
            }
            QStatusBar QLabel {
                color: #93a5ba;
            }
        """)
        self.setStatusBar(QStatusBar(self))

    def _language_label(self):
        ext = os.path.splitext(self.remote_path)[1].lower().lstrip(".")
        return ext.upper() if ext else "TEXT"

    def on_text_changed(self):
        modified = self.editor.document().isModified()
        title = f"Edit - {self.remote_path}"
        self.setWindowTitle(("*" if modified else "") + title)
        clean_text = "Saved" if self._saved_once else "Ready"
        self.dirty_label.setText("Unsaved" if modified else clean_text)
        self.dirty_label.setStyleSheet(
            "color:#ffe6a6; background:rgba(244,199,107,0.14); border:1px solid rgba(244,199,107,0.28); border-radius:11px; padding:5px 10px;"
            if modified else
            "color:#a9c8ef; background:rgba(110,168,255,0.12); border:1px solid rgba(110,168,255,0.24); border-radius:11px; padding:5px 10px;"
        )
        self.update_cursor_position()

    def update_cursor_position(self):
        cursor: QTextCursor = self.editor.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.positionInBlock() + 1
        chars = len(self.editor.toPlainText())
        self.status_label.setText(f"{self._language_label()}  |  Line {line}, Col {col}  |  {chars} chars  |  Ctrl+S save")

    def on_save(self):
        content = self.editor.toPlainText()
        try:
            success, msg = self.save_callback(self.remote_path, content)
        except Exception as e:
            success = False
            msg = f"Exception: {e}"
        if success:
            self.editor.document().setModified(False)
            self._saved_once = True
            self.statusBar().showMessage("Saved to server", 3000)
            self.on_text_changed()
        else:
            self.statusBar().showMessage(f"Save failed: {msg}", 7000)
            QMessageBox.warning(self, "Save failed", f"Saving to server failed:\n{msg}")

    def on_save_local(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Save local copy", self.remote_path)
        if not filename:
            return
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())
            self.statusBar().showMessage(f"Saved to {filename}", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"Local save failed:\n{e}")

    def closeEvent(self, event):
        if self.editor.document().isModified():
            res = QMessageBox.question(
                self,
                "Unsaved changes",
                "This document has unsaved changes. Save before closing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if res == QMessageBox.StandardButton.Save:
                self.on_save()
                if self.editor.document().isModified():
                    event.ignore()
                    return
            elif res == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    def dummy_save(remote_path: str, content: str):
        try:
            tmpdir = tempfile.gettempdir()
            fname = os.path.join(tmpdir, "editor_dummy_save.txt")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(content)
            return True, ""
        except Exception as e:
            return False, str(e)

    w = TextEditorWindow("/tmp/test.py", "def hello():\n    print('Hello from Xyra')\n", dummy_save)
    w.show()
    sys.exit(app.exec())
