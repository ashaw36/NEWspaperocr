"""Persistent task storage for the OCR workflow."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

TASK_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskNotFoundError(FileNotFoundError):
    pass


class TaskStore:
    """Stores one manifest per task and writes updates atomically."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def create(self, source_name: str, options: Dict[str, Any]) -> Dict[str, Any]:
        task_id = uuid.uuid4().hex
        now = utc_now()
        task = {
            "id": task_id,
            "source_name": source_name,
            "status": "queued",
            "stage": "layout",
            "progress": {"current": 0, "total": 0, "message": "等待版面分析"},
            "options": options,
            "pages": [],
            "confirmed": False,
            "created_at": now,
            "updated_at": now,
            "error": None,
        }
        self.task_dir(task_id).mkdir(parents=True, exist_ok=False)
        self.save(task)
        return task

    def validate_id(self, task_id: str) -> str:
        if not TASK_ID_RE.fullmatch(task_id or ""):
            raise TaskNotFoundError(task_id)
        return task_id

    def task_dir(self, task_id: str) -> Path:
        self.validate_id(task_id)
        return self.root / task_id

    def manifest_path(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "task.json"

    def load(self, task_id: str) -> Dict[str, Any]:
        path = self.manifest_path(task_id)
        if not path.exists():
            raise TaskNotFoundError(task_id)
        with self._lock, path.open("r", encoding="utf-8") as stream:
            return json.load(stream)

    def save(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task = deepcopy(task)
        task["updated_at"] = utc_now()
        path = self.manifest_path(task["id"])
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with self._lock:
            try:
                with temp_path.open("w", encoding="utf-8") as stream:
                    json.dump(task, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                for attempt in range(6):
                    try:
                        os.replace(temp_path, path)
                        break
                    except PermissionError:
                        if attempt == 5:
                            # Some Windows preview/indexing processes open JSON files
                            # without delete sharing. The file remains writable, but an
                            # atomic replace is impossible until that handle is released.
                            with path.open("w", encoding="utf-8") as stream:
                                json.dump(task, stream, ensure_ascii=False, indent=2)
                                stream.flush()
                                os.fsync(stream.fileno())
                            break
                        time.sleep(0.05 * (2**attempt))
            finally:
                temp_path.unlink(missing_ok=True)
        return task

    def update(self, task_id: str, **changes: Any) -> Dict[str, Any]:
        with self._lock:
            task = self.load(task_id)
            task.update(changes)
            return self.save(task)

    def list_recent(self, limit: int = 20) -> Iterable[Dict[str, Any]]:
        manifests = sorted(
            self.root.glob("*/task.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for path in manifests[:limit]:
            try:
                with path.open("r", encoding="utf-8") as stream:
                    yield json.load(stream)
            except (OSError, json.JSONDecodeError):
                continue
