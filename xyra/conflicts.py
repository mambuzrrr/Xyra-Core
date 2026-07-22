"""Shared conflict decisions and presentation for file operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QToolButton,
    QVBoxLayout, QWidget,
)


class ConflictAction(str, Enum):
    CANCEL = "cancel"
    SKIP = "skip"
    REPLACE = "replace"


@dataclass(frozen=True)
class ConflictEntry:
    path: str
    is_dir: bool = False
    size: int | None = None
    modified: float | int | None = None


@dataclass(frozen=True)
class ConflictDecision:
    action: ConflictAction
    apply_to_all: bool = False


def format_size(entry: ConflictEntry) -> str:
    if entry.is_dir:
        return "Folder"
    if entry.size is None:
        return "Unknown"
    size = max(0, int(entry.size))
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def format_modified(value: float | int | None) -> str:
    if value is None:
        return "Unknown"
    try:
        return datetime.fromtimestamp(float(value)).strftime("%d.%m.%Y  %H:%M:%S")
    except (OverflowError, OSError, TypeError, ValueError):
        return "Unknown"


class ConflictDialog(QDialog):
    """One consistent, explicit overwrite decision for all file actions."""

    def __init__(
        self,
        operation: str,
        source: ConflictEntry,
        target: ConflictEntry,
        parent=None,
        *,
        allow_apply_to_all: bool = False,
    ):
        super().__init__(parent)
        self._action = ConflictAction.CANCEL
        self._allow_apply_to_all = bool(allow_apply_to_all)
        self.setWindowTitle(f"{operation} conflict")
        self.setModal(True)
        self.setMinimumWidth(590)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        title = QLabel("An item already exists at the destination")
        title.setObjectName("conflictTitle")
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: #f3f1ed;")
        layout.addWidget(title)

        detail = QLabel(
            "Compare both items before replacing. Xyra will keep the existing "
            "item unless you explicitly choose Replace."
        )
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #bdb8af;")
        layout.addWidget(detail)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        cards.addWidget(self._entry_card("SOURCE", source), 1)
        cards.addWidget(self._entry_card("DESTINATION", target), 1)
        layout.addLayout(cards)

        type_warning = source.is_dir != target.is_dir
        if type_warning:
            warning = QLabel(
                "The item types differ. Replacing will remove the existing "
                f"{'folder' if target.is_dir else 'file'} after the new item is ready."
            )
            warning.setWordWrap(True)
            warning.setStyleSheet(
                "background: rgba(244, 199, 107, 0.10); color: #f4c76b; "
                "border: 1px solid rgba(244, 199, 107, 0.28); "
                "border-radius: 8px; padding: 9px;"
            )
            layout.addWidget(warning)

        self.apply_all = QCheckBox("Use this decision for all remaining conflicts")
        self.apply_all.setVisible(allow_apply_to_all)
        layout.addWidget(self.apply_all)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = self._button("Cancel")
        skip = self._button("Skip")
        replace = self._button("Replace", danger=True)
        cancel.clicked.connect(lambda: self._finish(ConflictAction.CANCEL))
        skip.clicked.connect(lambda: self._finish(ConflictAction.SKIP))
        replace.clicked.connect(lambda: self._finish(ConflictAction.REPLACE))
        buttons.addWidget(cancel)
        buttons.addWidget(skip)
        buttons.addWidget(replace)
        layout.addLayout(buttons)

    @staticmethod
    def _button(text: str, *, danger: bool = False) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumSize(92, 36)
        if danger:
            button.setStyleSheet(
                "QToolButton { background: rgba(229, 143, 152, 0.14); "
                "color: #f0a2aa; border: 1px solid rgba(229, 143, 152, 0.42); "
                "border-radius: 8px; padding: 7px 14px; font-weight: 700; }"
                "QToolButton:hover { background: rgba(229, 143, 152, 0.24); }"
            )
        return button

    @staticmethod
    def _entry_card(label: str, entry: ConflictEntry) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            "QWidget { background: rgba(255, 255, 255, 0.035); "
            "border: 1px solid rgba(255, 255, 255, 0.10); border-radius: 9px; }"
            "QLabel { background: transparent; border: none; border-radius: 0; }"
        )
        grid = QGridLayout(card)
        grid.setContentsMargins(13, 11, 13, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)

        heading = QLabel(label)
        heading.setStyleSheet("color: #d8c39a; font-size: 10px; font-weight: 800;")
        grid.addWidget(heading, 0, 0, 1, 2)

        path = QLabel(entry.path)
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path.setStyleSheet("color: #f3f1ed; font-weight: 650;")
        grid.addWidget(path, 1, 0, 1, 2)

        rows = (
            ("Type", "Folder" if entry.is_dir else "File"),
            ("Size", format_size(entry)),
            ("Modified", format_modified(entry.modified)),
        )
        for row, (name, value) in enumerate(rows, start=2):
            key = QLabel(name)
            key.setStyleSheet("color: #8f8b84;")
            val = QLabel(value)
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            val.setStyleSheet("color: #cfcac1;")
            grid.addWidget(key, row, 0)
            grid.addWidget(val, row, 1)
        return card

    def _finish(self, action: ConflictAction):
        self._action = action
        self.accept()

    def decision(self) -> ConflictDecision:
        accepted = self.exec() == QDialog.DialogCode.Accepted
        action = self._action if accepted else ConflictAction.CANCEL
        return ConflictDecision(
            action=action,
            apply_to_all=accepted and self._allow_apply_to_all and self.apply_all.isChecked(),
        )
