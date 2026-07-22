"""Thread-safe transfer queue and its compact dashboard dialog."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


TransferRunner = Callable[[Callable[[int, int], None], threading.Event], None]
FINAL_STATES = {"completed", "failed", "cancelled"}


@dataclass
class TransferJob:
    direction: str
    name: str
    source: str
    target: str
    runner: TransferRunner
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "queued"
    done: int = 0
    total: int = 0
    speed: float = 0.0
    eta: float | None = None
    error: str = ""
    attempt: int = 1
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    last_emit_at: float = 0.0

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "direction": self.direction,
            "name": self.name,
            "source": self.source,
            "target": self.target,
            "status": self.status,
            "done": self.done,
            "total": self.total,
            "speed": self.speed,
            "eta": self.eta,
            "error": self.error,
            "attempt": self.attempt,
        }


class TransferQueue(QObject):
    """Runs a bounded number of transfers and keeps their observable state."""

    jobs_changed = pyqtSignal(object)
    job_finished = pyqtSignal(object)

    def __init__(self, parent=None, *, max_active: int = 1):
        super().__init__(parent)
        self.max_active = max(1, int(max_active))
        self._jobs: list[TransferJob] = []
        self._lock = threading.RLock()
        self._active = 0
        self._closed = False

    def enqueue(self, *, direction: str, name: str, source: str, target: str, runner: TransferRunner) -> str:
        job = TransferJob(direction, name, source, target, runner)
        with self._lock:
            if self._closed:
                raise RuntimeError("Transfer queue is closed.")
            self._jobs.append(job)
        self._emit_changed()
        self._pump()
        return job.id

    def snapshots(self) -> list[dict]:
        with self._lock:
            return [job.snapshot() for job in self._jobs]

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {
                "active": sum(job.status == "running" for job in self._jobs),
                "queued": sum(job.status == "queued" for job in self._jobs),
                "failed": sum(job.status == "failed" for job in self._jobs),
            }

    def cancel(self, job_id: str) -> bool:
        changed = False
        with self._lock:
            job = self._find(job_id)
            if job is None or job.status in FINAL_STATES:
                return False
            job.cancel_event.set()
            if job.status == "queued":
                job.status = "cancelled"
                job.finished_at = time.time()
            changed = True
        if changed:
            self._emit_changed()
            self._pump()
        return changed

    def retry(self, job_id: str) -> bool:
        with self._lock:
            job = self._find(job_id)
            if job is None or job.status not in {"failed", "cancelled"}:
                return False
            job.status = "queued"
            job.done = 0
            job.total = 0
            job.speed = 0.0
            job.eta = None
            job.error = ""
            job.attempt += 1
            job.started_at = None
            job.finished_at = None
            job.cancel_event = threading.Event()
        self._emit_changed()
        self._pump()
        return True

    def clear_finished(self):
        with self._lock:
            self._jobs = [job for job in self._jobs if job.status not in FINAL_STATES]
        self._emit_changed()

    def cancel_all(self):
        with self._lock:
            changed = False
            for job in self._jobs:
                if job.status not in {"queued", "running"}:
                    continue
                job.cancel_event.set()
                if job.status == "queued":
                    job.status = "cancelled"
                    job.finished_at = time.time()
                changed = True
        if changed:
            self._emit_changed()
            self._pump()
        return changed

    def shutdown(self):
        with self._lock:
            self._closed = True
            for job in self._jobs:
                if job.status in {"queued", "running"}:
                    job.cancel_event.set()
                    if job.status == "queued":
                        job.status = "cancelled"
        self._emit_changed()

    def _find(self, job_id: str) -> TransferJob | None:
        return next((job for job in self._jobs if job.id == job_id), None)

    def _emit_changed(self):
        self.jobs_changed.emit(self.snapshots())

    def _pump(self):
        starting = []
        with self._lock:
            if self._closed:
                return
            while self._active < self.max_active:
                job = next((entry for entry in self._jobs if entry.status == "queued"), None)
                if job is None:
                    break
                job.status = "running"
                job.started_at = time.monotonic()
                job.finished_at = None
                job.last_emit_at = 0.0
                self._active += 1
                starting.append(job)
        if starting:
            self._emit_changed()
        for job in starting:
            threading.Thread(
                target=self._run_job,
                args=(job,),
                name=f"xyra-transfer-{job.id[:8]}",
                daemon=True,
            ).start()

    def _run_job(self, job: TransferJob):
        def progress(done: int, total: int):
            now = time.monotonic()
            with self._lock:
                if job.status != "running":
                    return
                job.done = max(0, int(done))
                job.total = max(0, int(total))
                elapsed = max(0.001, now - (job.started_at or now))
                job.speed = job.done / elapsed
                remaining = max(0, job.total - job.done)
                job.eta = remaining / job.speed if job.total > 0 and job.speed > 0 else None
                should_emit = now - job.last_emit_at >= 0.1 or (job.total > 0 and job.done >= job.total)
                if should_emit:
                    job.last_emit_at = now
            if should_emit:
                self._emit_changed()

        error = ""
        try:
            job.runner(progress, job.cancel_event)
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__

        with self._lock:
            if job.cancel_event.is_set():
                job.status = "cancelled"
                job.error = ""
            elif error:
                job.status = "failed"
                job.error = error
            else:
                job.status = "completed"
                if job.total > 0:
                    job.done = job.total
                    job.eta = 0.0
            job.finished_at = time.time()
            self._active = max(0, self._active - 1)
            snapshot = job.snapshot()

        self._emit_changed()
        self.job_finished.emit(snapshot)
        self._pump()


def _format_bytes(value: float) -> str:
    size = max(0.0, float(value or 0))
    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.0f} {units[index]}" if index == 0 else f"{size:.1f} {units[index]}"


class TransferCenterDialog(QDialog):
    def __init__(self, queue: TransferQueue, parent=None):
        super().__init__(parent)
        self.queue = queue
        self.setWindowTitle("Transfers")
        self.resize(900, 430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        self.summary = QLabel("No transfers")
        self.summary.setStyleSheet("font-size: 13px; font-weight: 700; color: #dedbd5;")
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(("Type", "Name", "Status", "Progress", "Speed / ETA", "Destination"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 82)
        self.table.setColumnWidth(1, 190)
        self.table.setColumnWidth(2, 105)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 145)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget { background:#101012; alternate-background-color:#151517; "
            "border:1px solid #303034; border-radius:10px; gridline-color:#29292c; }"
            "QTableWidget::item { padding:7px; border:none; }"
            "QTableWidget::item:selected { background:#302c25; color:#ffffff; }"
            "QHeaderView::section { background:#1c1c1f; color:#aaa69f; border:none; "
            "border-bottom:1px solid #343438; padding:8px; font-weight:700; }"
        )
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel selected")
        self.retry_button = QPushButton("Retry selected")
        self.clear_button = QPushButton("Clear finished")
        row.addWidget(self.cancel_button)
        row.addWidget(self.retry_button)
        row.addWidget(self.clear_button)
        row.addStretch()
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.close)
        row.addWidget(close_buttons)
        layout.addLayout(row)

        self.cancel_button.clicked.connect(self._cancel_selected)
        self.retry_button.clicked.connect(self._retry_selected)
        self.clear_button.clicked.connect(self.queue.clear_finished)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.queue.jobs_changed.connect(self.refresh)
        self.refresh(self.queue.snapshots())

    def _selected_id(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def _cancel_selected(self):
        job_id = self._selected_id()
        if job_id:
            self.queue.cancel(job_id)

    def _retry_selected(self):
        job_id = self._selected_id()
        if job_id:
            self.queue.retry(job_id)

    def _update_buttons(self):
        job_id = self._selected_id()
        selected = next((job for job in self.queue.snapshots() if job["id"] == job_id), None)
        status = selected["status"] if selected else ""
        self.cancel_button.setEnabled(status in {"queued", "running"})
        self.retry_button.setEnabled(status in {"failed", "cancelled"})

    def refresh(self, jobs):
        selected_id = self._selected_id()
        self.table.setRowCount(len(jobs))
        selected_row = -1
        for row, job in enumerate(jobs):
            direction = "Upload" if job["direction"] == "upload" else "Download"
            type_item = QTableWidgetItem(direction)
            type_item.setData(Qt.ItemDataRole.UserRole, job["id"])
            self.table.setItem(row, 0, type_item)
            self.table.setItem(row, 1, QTableWidgetItem(job["name"]))

            status = job["status"].capitalize()
            if job["attempt"] > 1:
                status += f" · try {job['attempt']}"
            status_item = QTableWidgetItem(status)
            status_item.setToolTip(job["error"] or status)
            self.table.setItem(row, 2, status_item)

            if job["total"] > 0:
                percent = min(100, int(job["done"] * 100 / job["total"]))
                progress = f"{percent}%  ·  {_format_bytes(job['done'])}"
            elif job["status"] == "completed":
                progress = "Done"
            else:
                progress = "Waiting…" if job["status"] == "queued" else _format_bytes(job["done"])
            self.table.setItem(row, 3, QTableWidgetItem(progress))

            speed = ""
            if job["speed"] > 0 and job["status"] == "running":
                speed = f"{_format_bytes(job['speed'])}/s"
                if job["eta"] is not None:
                    speed += f"  ·  {max(0, int(job['eta']))}s"
            self.table.setItem(row, 4, QTableWidgetItem(speed))
            destination = QTableWidgetItem(job["target"])
            destination.setToolTip(f"{job['source']}  →  {job['target']}")
            self.table.setItem(row, 5, destination)
            if job["id"] == selected_id:
                selected_row = row

        counts = self.queue.counts()
        self.summary.setText(
            f"{counts['active']} active   ·   {counts['queued']} queued   ·   {counts['failed']} failed"
        )
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        self._update_buttons()
