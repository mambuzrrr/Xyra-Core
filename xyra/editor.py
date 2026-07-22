"""Notepad-style remote text editor with Xyra's own visual language."""

import os
import posixpath
import re
import sys
import tempfile
from typing import Callable, Tuple

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import (
    QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QTextCursor,
    QTextDocument, QTextFormat, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QStatusBar, QStyle, QTabWidget, QTextEdit, QToolBar, QVBoxLayout, QWidget,
)

from xyra.application import apply_window_chrome
from xyra.editor_highlighting import XyraSyntaxHighlighter, detect_language

try:
    import qtawesome as qta
except Exception:
    qta = None


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
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width(0)
        self.highlight_current_line()

    def line_number_area_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(
                0, rect.y(), self.line_number_area.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        contents = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(
                contents.left(),
                contents.top(),
                self.line_number_area_width(),
                contents.height(),
            )
        )

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#111113"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        current_block = self.textCursor().blockNumber()

        painter.setFont(self.font())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(
                    QColor("#d8c39a")
                    if block_number == current_block
                    else QColor("#65625d")
                )
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 7,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self):
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#211f1b"))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])
        self.line_number_area.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            cursor = self.textCursor()
            before_cursor = cursor.block().text()[:cursor.positionInBlock()]
            indentation = re.match(r"^[\t ]*", before_cursor).group(0)
            if before_cursor.rstrip().endswith((":", "{", "[", "(")):
                indentation += "    "
            super().keyPressEvent(event)
            if indentation:
                self.insertPlainText(indentation)
            return
        super().keyPressEvent(event)


class TextEditorWindow(QMainWindow):
    def __init__(self, remote_path: str, initial_text: str, save_callback: SaveCallback):
        super().__init__()
        self.remote_path = remote_path
        self.save_callback = save_callback
        self.language = detect_language(remote_path)
        self.eol_mode = "CRLF" if "\r\n" in initial_text else "LF"
        self.encoding = "UTF-8"
        self.zoom_level = 100
        self._saved_once = False

        self.setWindowTitle(self._window_title(False))
        self.resize(1180, 800)
        apply_window_chrome(self)
        self._apply_theme()

        self.editor = self._new_editor(remote_path, initial_text, save_callback)
        self.highlighter = self.editor.highlighter

        self._create_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_workspace()
        self._build_status_bar()

        self.action_undo.setEnabled(False)
        self.action_redo.setEnabled(False)
        self.action_cut.setEnabled(False)
        self.action_copy.setEnabled(False)
        self.editor.document().setModified(False)

        close_find = QShortcut(QKeySequence("Escape"), self.find_bar)
        close_find.activated.connect(self._hide_find_bar)
        self._close_find_shortcut = close_find
        self.update_status()
        self._update_document_chrome(False)

    def _new_editor(self, remote_path: str, initial_text: str, save_callback: SaveCallback):
        editor = CodeTextEdit()
        editor.remote_path = remote_path
        editor.save_callback = save_callback
        editor.language = detect_language(remote_path)
        editor.eol_mode = "CRLF" if "\r\n" in initial_text else "LF"
        editor.encoding = "UTF-8"
        editor.zoom_level = 100
        editor.saved_once = False
        editor.setFont(self._code_font())
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        editor.setTabStopDistance(4 * editor.fontMetrics().horizontalAdvance(" "))
        editor.setPlainText(initial_text)
        editor.highlighter = XyraSyntaxHighlighter(editor.document(), editor.language)

        editor.textChanged.connect(lambda e=editor: self._editor_text_changed(e))
        editor.cursorPositionChanged.connect(lambda e=editor: self._editor_cursor_changed(e))
        editor.selectionChanged.connect(lambda e=editor: self._editor_cursor_changed(e))
        editor.document().modificationChanged.connect(
            lambda modified, e=editor: self._editor_modification_changed(e, modified)
        )
        editor.document().undoAvailable.connect(
            lambda available, e=editor: self._editor_history_changed(e, available, None)
        )
        editor.document().redoAvailable.connect(
            lambda available, e=editor: self._editor_history_changed(e, None, available)
        )
        editor.copyAvailable.connect(
            lambda available, e=editor: self._editor_copy_changed(e, available)
        )
        editor.document().setModified(False)
        return editor

    def _window_title(self, modified: bool):
        filename = os.path.basename(self.remote_path) or self.remote_path
        return f"{'*' if modified else ''}{filename} - Xyra Editor"

    def _code_font(self):
        font = QFont("Cascadia Code")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        return font

    def _icon(self, name: str, color: str = "#c9c5be", fallback=None):
        if qta is not None:
            try:
                return qta.icon(name, color=color)
            except Exception:
                pass
        if fallback is not None:
            return self.style().standardIcon(fallback)
        return QIcon()

    def _action(self, text, slot, *, shortcut=None, icon=None, checkable=False):
        action = QAction(icon or QIcon(), text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        return action

    def _create_actions(self):
        sp = QStyle.StandardPixmap
        self.action_save = self._action(
            "Save to server", self.on_save, shortcut="Ctrl+S",
            icon=self._icon("fa6s.floppy-disk", "#d8c39a", sp.SP_DialogSaveButton),
        )
        self.action_save_local = self._action(
            "Save local copy…", self.on_save_local, shortcut="Ctrl+Shift+S",
            icon=self._icon("fa6s.download", "#c7b7d8", sp.SP_ArrowDown),
        )
        self.action_close = self._action("Close", self.close, shortcut="Ctrl+W")
        self.action_undo = self._action(
            "Undo", lambda: self.editor.undo(), shortcut="Ctrl+Z",
            icon=self._icon("fa6s.rotate-left"),
        )
        self.action_redo = self._action(
            "Redo", lambda: self.editor.redo(), shortcut="Ctrl+Y",
            icon=self._icon("fa6s.rotate-right"),
        )
        self.action_cut = self._action(
            "Cut", lambda: self.editor.cut(), shortcut="Ctrl+X",
            icon=self._icon("fa6s.scissors"),
        )
        self.action_copy = self._action(
            "Copy", lambda: self.editor.copy(), shortcut="Ctrl+C",
            icon=self._icon("fa6s.copy"),
        )
        self.action_paste = self._action(
            "Paste", lambda: self.editor.paste(), shortcut="Ctrl+V",
            icon=self._icon("fa6s.paste"),
        )
        self.action_select_all = self._action(
            "Select all", lambda: self.editor.selectAll(), shortcut="Ctrl+A"
        )
        self.action_duplicate_line = self._action(
            "Duplicate current line", self.duplicate_current_line, shortcut="Ctrl+D"
        )
        self.action_delete_line = self._action(
            "Delete current line", self.delete_current_line, shortcut="Ctrl+L"
        )
        self.action_uppercase = self._action(
            "UPPERCASE", lambda: self.transform_selection(str.upper)
        )
        self.action_lowercase = self._action(
            "lowercase", lambda: self.transform_selection(str.lower)
        )
        self.action_find = self._action(
            "Find…", lambda: self._show_find_bar(False), shortcut="Ctrl+F",
            icon=self._icon("fa6s.magnifying-glass", "#d8c39a"),
        )
        self.action_replace = self._action(
            "Replace…", lambda: self._show_find_bar(True), shortcut="Ctrl+H",
            icon=self._icon("fa6s.right-left", "#c7b7d8"),
        )
        self.action_find_next = self._action(
            "Find next", self.find_next, shortcut="F3"
        )
        self.action_find_previous = self._action(
            "Find previous", lambda: self.find_next(backward=True), shortcut="Shift+F3"
        )
        self.action_goto = self._action(
            "Go to line…", self.go_to_line, shortcut="Ctrl+G"
        )
        self.action_wrap = self._action(
            "Word wrap", self.toggle_word_wrap, shortcut="Alt+Z", checkable=True,
            icon=self._icon("fa6s.align-left"),
        )
        self.action_zoom_in = self._action("Zoom in", self.zoom_in, shortcut="Ctrl++")
        self.action_zoom_out = self._action("Zoom out", self.zoom_out, shortcut="Ctrl+-")
        self.action_zoom_reset = self._action("Reset zoom", self.zoom_reset, shortcut="Ctrl+0")

    def _build_menus(self):
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.action_save)
        file_menu.addAction(self.action_save_local)
        file_menu.addSeparator()
        file_menu.addAction(self.action_close)

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self.action_undo)
        edit_menu.addAction(self.action_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_cut)
        edit_menu.addAction(self.action_copy)
        edit_menu.addAction(self.action_paste)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_duplicate_line)
        edit_menu.addAction(self.action_delete_line)
        case_menu = edit_menu.addMenu("Convert case")
        case_menu.addAction(self.action_uppercase)
        case_menu.addAction(self.action_lowercase)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_select_all)

        search_menu = self.menuBar().addMenu("&Search")
        search_menu.addAction(self.action_find)
        search_menu.addAction(self.action_find_next)
        search_menu.addAction(self.action_find_previous)
        search_menu.addAction(self.action_replace)
        search_menu.addSeparator()
        search_menu.addAction(self.action_goto)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.action_wrap)
        view_menu.addSeparator()
        view_menu.addAction(self.action_zoom_in)
        view_menu.addAction(self.action_zoom_out)
        view_menu.addAction(self.action_zoom_reset)

        language_menu = self.menuBar().addMenu("&Language")
        self.language_action = language_menu.addAction(self.language)
        self.language_action.setEnabled(False)

        encoding_menu = self.menuBar().addMenu("E&ncoding")
        encoding_action = encoding_menu.addAction("UTF-8")
        encoding_action.setCheckable(True)
        encoding_action.setChecked(True)
        encoding_action.setEnabled(False)

    def _build_toolbar(self):
        toolbar = QToolBar("Editor commands", self)
        toolbar.setObjectName("editorToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(17, 17))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        for action in (self.action_save, self.action_save_local):
            toolbar.addAction(action)
        toolbar.addSeparator()
        for action in (self.action_undo, self.action_redo):
            toolbar.addAction(action)
        toolbar.addSeparator()
        for action in (self.action_cut, self.action_copy, self.action_paste):
            toolbar.addAction(action)
        toolbar.addSeparator()
        for action in (self.action_find, self.action_replace, self.action_wrap):
            toolbar.addAction(action)

    def _build_workspace(self):
        root = QWidget()
        root.setObjectName("editorRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)

        path_strip = QFrame()
        path_strip.setObjectName("pathStrip")
        path_layout = QHBoxLayout(path_strip)
        path_layout.setContentsMargins(12, 5, 12, 5)
        path_layout.setSpacing(8)
        remote_label = QLabel("REMOTE")
        remote_label.setObjectName("remoteBadge")
        self.path_label = QLabel(self.remote_path)
        self.path_label.setObjectName("editorPath")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.dirty_label = QLabel("READY")
        self.dirty_label.setObjectName("dirtyBadge")
        path_layout.addWidget(remote_label)
        path_layout.addWidget(self.path_label, 1)
        path_layout.addWidget(self.dirty_label)
        layout.addWidget(path_strip)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("editorTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.addTab(self.editor, os.path.basename(self.remote_path) or self.remote_path)
        self.tabs.setTabToolTip(0, self.remote_path)
        self.tabs.currentChanged.connect(self._active_tab_changed)
        layout.addWidget(self.tabs, 1)

        self.find_bar = self._build_find_bar()
        layout.addWidget(self.find_bar)
        self.find_bar.hide()

    def _build_find_bar(self):
        frame = QFrame()
        frame.setObjectName("findBar")
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 7, 10, 7)
        row.setSpacing(7)

        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find")
        self.find_input.setClearButtonEnabled(True)
        self.find_input.returnPressed.connect(self.find_next)
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Replace with")
        self.replace_input.returnPressed.connect(self.replace_current)
        self.case_checkbox = QCheckBox("Match case")
        self.word_checkbox = QCheckBox("Whole word")

        previous_button = QPushButton("Previous")
        previous_button.clicked.connect(lambda: self.find_next(backward=True))
        next_button = QPushButton("Next")
        next_button.setObjectName("findPrimary")
        next_button.clicked.connect(self.find_next)
        self.replace_button = QPushButton("Replace")
        self.replace_button.clicked.connect(self.replace_current)
        self.replace_all_button = QPushButton("Replace all")
        self.replace_all_button.clicked.connect(self.replace_all)
        close_button = QPushButton("×")
        close_button.setObjectName("findClose")
        close_button.setFixedWidth(32)
        close_button.clicked.connect(self._hide_find_bar)

        row.addWidget(self.find_input, 2)
        row.addWidget(self.replace_input, 2)
        row.addWidget(self.case_checkbox)
        row.addWidget(self.word_checkbox)
        row.addWidget(previous_button)
        row.addWidget(next_button)
        row.addWidget(self.replace_button)
        row.addWidget(self.replace_all_button)
        row.addWidget(close_button)
        return frame

    def _build_status_bar(self):
        status = QStatusBar(self)
        status.setSizeGripEnabled(False)
        self.setStatusBar(status)
        self.status_cursor = QLabel()
        self.status_stats = QLabel()
        self.status_eol = QLabel(self.eol_mode)
        self.status_encoding = QLabel(self.encoding)
        self.status_language = QLabel(self.language)
        self.status_insert = QLabel("INS")
        self.status_zoom = QLabel("100%")
        for label in (
            self.status_cursor,
            self.status_stats,
            self.status_eol,
            self.status_encoding,
            self.status_language,
            self.status_insert,
            self.status_zoom,
        ):
            label.setObjectName("statusSegment")
            status.addPermanentWidget(label)

    def open_document(self, remote_path: str, initial_text: str, save_callback: SaveCallback):
        """Open a remote document in this window or focus its existing tab."""
        if self.focus_document(remote_path):
            return False

        editor = self._new_editor(remote_path, initial_text, save_callback)
        filename = os.path.basename(remote_path) or remote_path
        index = self.tabs.addTab(editor, filename)
        self.tabs.setTabToolTip(index, remote_path)
        self.tabs.setCurrentIndex(index)
        self.show()
        self.raise_()
        self.activateWindow()
        return True

    def _document_index(self, remote_path: str):
        normalized = posixpath.normpath((remote_path or "").replace("\\", "/"))
        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)
            existing = posixpath.normpath(editor.remote_path.replace("\\", "/"))
            if existing == normalized:
                return index
        return -1

    def focus_document(self, remote_path: str):
        index = self._document_index(remote_path)
        if index < 0:
            return False
        self.tabs.setCurrentIndex(index)
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        return True

    def _active_tab_changed(self, index: int):
        if index < 0:
            return
        editor = self.tabs.widget(index)
        if not isinstance(editor, CodeTextEdit):
            return
        self.editor = editor
        self.remote_path = editor.remote_path
        self.save_callback = editor.save_callback
        self.language = editor.language
        self.eol_mode = editor.eol_mode
        self.encoding = editor.encoding
        self.zoom_level = editor.zoom_level
        self._saved_once = editor.saved_once
        self.highlighter = editor.highlighter

        self.path_label.setText(editor.remote_path)
        self.status_eol.setText(editor.eol_mode)
        self.status_encoding.setText(editor.encoding)
        self.status_language.setText(editor.language)
        self.language_action.setText(editor.language)
        self.action_wrap.blockSignals(True)
        self.action_wrap.setChecked(
            editor.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        self.action_wrap.blockSignals(False)
        self.action_undo.setEnabled(editor.document().isUndoAvailable())
        self.action_redo.setEnabled(editor.document().isRedoAvailable())
        self.action_cut.setEnabled(editor.textCursor().hasSelection())
        self.action_copy.setEnabled(editor.textCursor().hasSelection())
        self._update_document_chrome(editor.document().isModified())
        self.update_status()
        editor.setFocus()

    def _editor_text_changed(self, editor: CodeTextEdit):
        if editor is self.editor:
            self.on_text_changed()

    def _editor_cursor_changed(self, editor: CodeTextEdit):
        if editor is self.editor:
            self.update_status()

    def _editor_modification_changed(self, editor: CodeTextEdit, modified: bool):
        index = self.tabs.indexOf(editor) if hasattr(self, "tabs") else -1
        if index >= 0:
            filename = os.path.basename(editor.remote_path) or editor.remote_path
            self.tabs.setTabText(index, f"{'*' if modified else ''}{filename}")
        if editor is self.editor and hasattr(self, "dirty_label"):
            self._update_document_chrome(modified)

    def _editor_history_changed(self, editor: CodeTextEdit, undo, redo):
        if editor is not self.editor or not hasattr(self, "action_undo"):
            return
        if undo is not None:
            self.action_undo.setEnabled(undo)
        if redo is not None:
            self.action_redo.setEnabled(redo)

    def _editor_copy_changed(self, editor: CodeTextEdit, available: bool):
        if editor is self.editor and hasattr(self, "action_copy"):
            self.action_cut.setEnabled(available)
            self.action_copy.setEnabled(available)

    def _close_tab(self, index: int):
        editor = self.tabs.widget(index)
        if not isinstance(editor, CodeTextEdit) or not self._confirm_close_editor(editor):
            return
        self.tabs.removeTab(index)
        editor.deleteLater()
        if self.tabs.count() == 0:
            self.close()

    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget#editorRoot { background: #0d0d0f; color: #e7e3dc; }
            QMenuBar {
                color: #d4d0c9; background: #141416;
                border-bottom: 1px solid #29292c; padding: 2px 5px;
            }
            QMenuBar::item { padding: 5px 9px; border-radius: 5px; }
            QMenuBar::item:selected { color: #ffffff; background: #292724; }
            QMenu {
                color: #e7e3dc; background: #18181a; border: 1px solid #343438;
                padding: 6px;
            }
            QMenu::item { padding: 7px 30px 7px 10px; border-radius: 5px; }
            QMenu::item:selected { background: #302c25; }
            QMenu::separator { height: 1px; margin: 5px 7px; background: #303034; }
            QToolBar#editorToolbar {
                spacing: 3px; padding: 5px 8px; background: #121214;
                border: none; border-bottom: 1px solid #29292c;
            }
            QToolBar#editorToolbar::separator {
                width: 1px; margin: 5px 6px; background: #303034;
            }
            QToolBar#editorToolbar QToolButton {
                background: transparent; border: 1px solid transparent;
                border-radius: 6px; padding: 5px;
            }
            QToolBar#editorToolbar QToolButton:hover {
                background: #292724; border-color: #4d473d;
            }
            QFrame#pathStrip {
                background: #161618; border-bottom: 1px solid #2c2c2f;
            }
            QLabel#remoteBadge {
                color: #8bc7a8; font-size: 8pt; font-weight: 700;
                background: #18241f; border: 1px solid #344f42;
                border-radius: 5px; padding: 3px 7px;
            }
            QLabel#editorPath { color: #8f8c86; font-size: 9pt; }
            QLabel#dirtyBadge {
                color: #aaa69f; font-size: 8pt; font-weight: 700;
                background: #1d1d1f; border: 1px solid #353538;
                border-radius: 5px; padding: 3px 7px;
            }
            QTabWidget#editorTabs::pane { border: none; background: #0f0f11; }
            QTabBar::tab {
                color: #aaa69f; background: #151517; border: none;
                border-right: 1px solid #2b2b2e; padding: 7px 28px 7px 13px;
                min-width: 130px;
            }
            QTabBar::tab:selected {
                color: #f3f1ed; background: #1c1c1f;
                border-top: 2px solid #d8c39a;
            }
            QTabBar::close-button { margin: 2px; }
            QPlainTextEdit {
                color: #dedbd5; background: #0f0f11; border: none;
                padding: 8px 10px; selection-background-color: #5d513d;
                selection-color: #ffffff;
            }
            QFrame#findBar {
                background: #18181a; border-top: 1px solid #343438;
            }
            QFrame#findBar QLineEdit {
                color: #f3f1ed; background: #111113; border: 1px solid #343438;
                border-radius: 6px; padding: 6px 9px;
            }
            QFrame#findBar QLineEdit:focus { border-color: #d8c39a; }
            QFrame#findBar QCheckBox { color: #aaa69f; spacing: 5px; }
            QFrame#findBar QPushButton {
                color: #d9d5ce; background: #222225; border: 1px solid #38383c;
                border-radius: 6px; padding: 6px 10px;
            }
            QFrame#findBar QPushButton:hover { background: #302c25; border-color: #5d513d; }
            QFrame#findBar QPushButton#findPrimary {
                color: #1b170f; background: #d8c39a; border-color: #d8c39a;
            }
            QFrame#findBar QPushButton#findClose {
                color: #aaa69f; background: transparent; border-color: transparent;
                font-size: 14pt;
            }
            QStatusBar {
                color: #8f8c86; background: #141416; border-top: 1px solid #29292c;
            }
            QLabel#statusSegment {
                color: #aaa69f; border-left: 1px solid #303034;
                padding: 3px 9px; font-size: 8.5pt;
            }
            QScrollBar:vertical { width: 15px; background: #0f0f11; }
            QScrollBar::handle:vertical {
                min-height: 38px; margin: 2px; border-radius: 5px; background: #3d3d41;
            }
            QScrollBar::handle:vertical:hover { background: #57534d; }
            QScrollBar:horizontal { height: 14px; background: #0f0f11; }
            QScrollBar::handle:horizontal {
                min-width: 38px; margin: 2px; border-radius: 5px; background: #3d3d41;
            }
            QScrollBar::handle:horizontal:hover { background: #57534d; }
            QScrollBar::add-line, QScrollBar::sub-line,
            QScrollBar::add-page, QScrollBar::sub-page {
                width: 0; height: 0; background: transparent;
            }
        """)

    def _show_find_bar(self, replace: bool):
        self.replace_input.setVisible(replace)
        self.replace_button.setVisible(replace)
        self.replace_all_button.setVisible(replace)
        selected = self.editor.textCursor().selectedText()
        if selected and "\u2029" not in selected and len(selected) <= 200:
            self.find_input.setText(selected)
        self.find_bar.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def _hide_find_bar(self):
        self.find_bar.hide()
        self.editor.setFocus()

    def _find_flags(self, *, backward=False):
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        if self.case_checkbox.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.word_checkbox.isChecked():
            flags |= QTextDocument.FindFlag.FindWholeWords
        return flags

    def find_next(self, _checked=False, *, backward=False):
        query = self.find_input.text()
        if not query:
            self._show_find_bar(False)
            return False

        found = self.editor.find(query, self._find_flags(backward=backward))
        if not found:
            cursor = self.editor.textCursor()
            cursor.movePosition(
                QTextCursor.MoveOperation.End
                if backward else QTextCursor.MoveOperation.Start
            )
            self.editor.setTextCursor(cursor)
            found = self.editor.find(query, self._find_flags(backward=backward))
        self.statusBar().showMessage(
            f"Found: {query}" if found else f"No matches: {query}",
            2200,
        )
        return found

    def _selection_matches_find(self):
        selected = self.editor.textCursor().selectedText()
        query = self.find_input.text()
        if self.case_checkbox.isChecked():
            return selected == query
        return selected.casefold() == query.casefold()

    def replace_current(self):
        if not self.find_input.text():
            return
        if not self._selection_matches_find() and not self.find_next():
            return
        cursor = self.editor.textCursor()
        cursor.insertText(self.replace_input.text())
        self.editor.setTextCursor(cursor)
        self.find_next()

    def replace_all(self):
        query = self.find_input.text()
        if not query:
            return
        document = self.editor.document()
        flags = self._find_flags()
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.beginEditBlock()
        count = 0
        while True:
            match = document.find(query, cursor, flags)
            if match.isNull():
                break
            match.insertText(self.replace_input.text())
            cursor = match
            count += 1
        cursor.endEditBlock()
        self.editor.setTextCursor(cursor)
        self.statusBar().showMessage(f"Replaced {count} occurrence{'s' if count != 1 else ''}", 3000)

    def go_to_line(self):
        maximum = max(1, self.editor.blockCount())
        current = self.editor.textCursor().blockNumber() + 1
        line, accepted = QInputDialog.getInt(
            self, "Go to line", "Line number", current, 1, maximum
        )
        if not accepted:
            return
        block = self.editor.document().findBlockByNumber(line - 1)
        cursor = QTextCursor(block)
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()
        self.editor.setFocus()

    def duplicate_current_line(self):
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        text = cursor.block().text()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.insertText("\n" + text)
        cursor.endEditBlock()

    def delete_current_line(self):
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.NextBlock,
            QTextCursor.MoveMode.KeepAnchor,
        )
        if not cursor.hasSelection():
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
        cursor.removeSelectedText()
        cursor.endEditBlock()

    def transform_selection(self, transform):
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            return
        selected = cursor.selectedText().replace("\u2029", "\n")
        cursor.insertText(transform(selected))

    def toggle_word_wrap(self, checked=False):
        self.editor.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if checked else QPlainTextEdit.LineWrapMode.NoWrap
        )
        self.statusBar().showMessage("Word wrap on" if checked else "Word wrap off", 1800)

    def zoom_in(self):
        if self.zoom_level >= 220:
            return
        self.editor.zoomIn(1)
        self.zoom_level += 10
        self.editor.zoom_level = self.zoom_level
        self.update_status()

    def zoom_out(self):
        if self.zoom_level <= 50:
            return
        self.editor.zoomOut(1)
        self.zoom_level -= 10
        self.editor.zoom_level = self.zoom_level
        self.update_status()

    def zoom_reset(self):
        while self.zoom_level > 100:
            self.editor.zoomOut(1)
            self.zoom_level -= 10
        while self.zoom_level < 100:
            self.editor.zoomIn(1)
            self.zoom_level += 10
        self.editor.zoom_level = self.zoom_level
        self.update_status()

    def on_text_changed(self):
        self.update_status()

    def _update_document_chrome(self, modified: bool):
        filename = os.path.basename(self.editor.remote_path) or self.editor.remote_path
        self._saved_once = self.editor.saved_once
        self.action_save.setEnabled(modified)
        self.setWindowTitle(self._window_title(modified))
        index = self.tabs.indexOf(self.editor)
        if index >= 0:
            self.tabs.setTabText(index, f"{'*' if modified else ''}{filename}")
        self.dirty_label.setText("UNSAVED" if modified else ("SAVED" if self._saved_once else "READY"))
        self.dirty_label.setStyleSheet(
            "color:#dfb86d; background:#2a2318; border-color:#59472a;"
            if modified else ""
        )

    def update_status(self):
        cursor = self.editor.textCursor()
        line = cursor.blockNumber() + 1
        column = cursor.positionInBlock() + 1
        selected = len(cursor.selectedText().replace("\u2029", "\n"))
        characters = max(0, self.editor.document().characterCount() - 1)
        lines = self.editor.blockCount()
        selection_text = f"  Sel {selected}" if selected else ""
        self.status_cursor.setText(f"Ln {line}, Col {column}{selection_text}")
        self.status_stats.setText(f"{lines} lines, {characters} chars")
        self.status_insert.setText("OVR" if self.editor.overwriteMode() else "INS")
        self.status_zoom.setText(f"{self.zoom_level}%")

    def on_save(self):
        self._save_editor(self.editor)

    def _save_editor(self, editor: CodeTextEdit):
        content = self._serialized_text(editor)
        try:
            success, message = editor.save_callback(editor.remote_path, content)
        except Exception as exc:
            success = False
            message = str(exc)
        if success:
            editor.saved_once = True
            editor.document().setModified(False)
            if editor is self.editor:
                self._saved_once = True
                self._update_document_chrome(False)
            self.statusBar().showMessage("Saved to remote server", 3000)
            return True
        self.statusBar().showMessage(f"Save failed: {message}", 7000)
        QMessageBox.warning(self, "Save failed", f"Saving to the remote server failed:\n{message}")
        return False

    def on_save_local(self):
        suggested = os.path.basename(self.editor.remote_path) or "document.txt"
        filename, _ = QFileDialog.getSaveFileName(self, "Save local copy", suggested)
        if not filename:
            return
        try:
            with open(filename, "w", encoding="utf-8", newline="") as file:
                file.write(self._serialized_text())
            self.statusBar().showMessage(f"Saved local copy: {filename}", 4000)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", f"Local save failed:\n{exc}")

    def _serialized_text(self, editor=None):
        editor = editor or self.editor
        text = editor.toPlainText()
        if editor.eol_mode == "CRLF":
            return text.replace("\n", "\r\n")
        return text

    def _confirm_close_editor(self, editor: CodeTextEdit):
        if not editor.document().isModified():
            return True
        filename = os.path.basename(editor.remote_path) or editor.remote_path
        response = QMessageBox.question(
            self,
            "Unsaved changes",
            f"{filename} has unsaved remote changes. Save before closing this tab?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if response == QMessageBox.StandardButton.Save:
            return self._save_editor(editor)
        return response == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)
            if isinstance(editor, CodeTextEdit) and not self._confirm_close_editor(editor):
                event.ignore()
                return
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    def dummy_save(remote_path: str, content: str):
        try:
            filename = os.path.join(tempfile.gettempdir(), "editor_dummy_save.txt")
            with open(filename, "w", encoding="utf-8") as file:
                file.write(content)
            return True, ""
        except Exception as exc:
            return False, str(exc)

    window = TextEditorWindow(
        "/srv/xyra/example.py",
        "def hello(name):\n    print(f'Hello, {name}')\n",
        dummy_save,
    )
    window.show()
    sys.exit(app.exec())
