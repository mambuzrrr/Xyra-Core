# editor.py
import sys
import os
import tempfile
from typing import Callable, Tuple

from PyQt6.QtWidgets import (
    QMainWindow,
    QTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QApplication,
    QMessageBox,
    QHBoxLayout,
    QLabel,
    QFileDialog,
)
from PyQt6.QtGui import QFont, QKeySequence, QShortcut, QTextCursor
from PyQt6.QtCore import Qt

SaveCallback = Callable[[str, str], Tuple[bool, str]]


class TextEditorWindow(QMainWindow):
    """
    Einfache eigenständige Editor-Klasse.
    Usage: editor = TextEditorWindow(remote_path, initial_text, save_callback)
    save_callback(remote_path, content) -> (success:bool, message:str)
    """
    def __init__(self, remote_path: str, initial_text: str, save_callback: SaveCallback):
        super().__init__()
        self.remote_path = remote_path
        self.save_callback = save_callback

        self.setWindowTitle(f"Edit - {self.remote_path}")
        self.resize(1000, 700)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Editor
        self.editor = QTextEdit()
        self.editor.setPlainText(initial_text)
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        # Monospace font for code
        mono = QFont("Courier New")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(11)
        self.editor.setFont(mono)
        layout.addWidget(self.editor)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_save = QPushButton("Save to server")
        btn_save.clicked.connect(self.on_save)
        btn_row.addWidget(btn_save)

        btn_save_local = QPushButton("Save to disk...")
        btn_save_local.clicked.connect(self.on_save_local)
        btn_row.addWidget(btn_save_local)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Status area with cursor position
        self.status_label = QLabel("")
        self.statusBar().addPermanentWidget(self.status_label)
        self.update_cursor_position()

        # Shortcuts (QShortcut is imported from QtGui)
        # Ctrl+S -> on_save
        self.shortcut_save = QShortcut(QKeySequence("Ctrl+S"), self)
        self.shortcut_save.activated.connect(self.on_save)

        # Ctrl+Q -> close
        self.shortcut_quit = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.shortcut_quit.activated.connect(self.close)

        # Signals
        self.editor.textChanged.connect(self.on_text_changed)
        self.editor.cursorPositionChanged.connect(self.update_cursor_position)

        # Make sure document modification state is tracked
        self.editor.document().setModified(False)

    def on_text_changed(self):
        modified = self.editor.document().isModified()
        title = f"Edit - {self.remote_path}"
        if modified:
            title = "*" + title
        self.setWindowTitle(title)

    def update_cursor_position(self):
        cursor: QTextCursor = self.editor.textCursor()
        # QTextCursor returns 0-based positions; convert to 1-based human-friendly
        line = cursor.blockNumber() + 1
        col = cursor.positionInBlock() + 1
        self.status_label.setText(f"Line: {line}  Col: {col}")

    def on_save(self):
        content = self.editor.toPlainText()
        try:
            success, msg = self.save_callback(self.remote_path, content)
        except Exception as e:
            success = False
            msg = f"Exception: {e}"
        if success:
            # mark as saved
            self.editor.document().setModified(False)
            self.statusBar().showMessage("Saved to server", 3000)
            self.on_text_changed()
        else:
            # keep modified state
            self.statusBar().showMessage(f"Save failed: {msg}", 7000)
            QMessageBox.warning(self, "Save fehlgeschlagen", f"Speichern auf Server fehlgeschlagen:\n{msg}")

    def on_save_local(self):
        # Save a local backup; does not call remote save callback
        filename, _ = QFileDialog.getSaveFileName(self, "Save to disk", self.remote_path)
        if not filename:
            return
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())
            self.statusBar().showMessage(f"Saved to {filename}", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Save fehlgeschlagen", f"Lokales Speichern fehlgeschlagen:\n{e}")

    def closeEvent(self, event):
        """
        Wenn das Dokument geändert wurde, nachfragen (Speichern / Verwerfen / Abbrechen).
        """
        if self.editor.document().isModified():
            res = QMessageBox.question(
                self,
                "Ungespeicherte Änderungen",
                "Das Dokument wurde verändert. Möchten Sie die Änderungen speichern?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if res == QMessageBox.StandardButton.Save:
                # Versuchen zu speichern; falls Save fehlschlägt, abbrechen
                self.on_save()
                if self.editor.document().isModified():
                    # Save failed or still modified -> cancel close
                    event.ignore()
                    return
            elif res == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            # if Discard, allow close
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    def dummy_save(remote_path: str, content: str):
        # Plattformunabhängige Dummy-Save in das temporäre Verzeichnis
        try:
            tmpdir = tempfile.gettempdir()
            fname = os.path.join(tmpdir, "editor_dummy_save.txt")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(content)
            return True, ""
        except Exception as e:
            return False, str(e)

    w = TextEditorWindow("/tmp/test.txt", "Hello world\n", dummy_save)
    w.show()
    sys.exit(app.exec())
