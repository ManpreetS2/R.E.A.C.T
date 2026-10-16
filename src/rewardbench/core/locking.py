"""Cross-process and in-process exclusion for one experiment run."""

from __future__ import annotations

import os
import threading
from pathlib import Path

_registry_guard = threading.Lock()
_thread_locks: dict[str, threading.Lock] = {}


class ExperimentBusy(Exception):
    """Another process already holds this experiment's run lock."""


class ExperimentRunLock:
    """Hold one experiment until ``run`` returns.

    Threads in this process share a lock keyed by the database directory and
    experiment id. Separate processes take an exclusive file lock as well.
    The file lock is released when the process exits, including after a crash.
    """

    def __init__(self, experiment_id: str, directory: Path | None = None) -> None:
        self.experiment_id = experiment_id
        self.directory = None if directory is None else Path(directory)
        self._thread = _thread_lock(self._key())
        self._handle = None
        self._held = False

    def __enter__(self) -> ExperimentRunLock:
        self.acquire(blocking=True)
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    def acquire(self, *, blocking: bool = True) -> None:
        if blocking:
            self._thread.acquire()
        elif not self._thread.acquire(blocking=False):
            raise ExperimentBusy(f"experiment {self.experiment_id} is already running")
        try:
            if self.directory is not None:
                self.directory.mkdir(parents=True, exist_ok=True)
                path = self.directory / f"{self.experiment_id}.lock"
                handle = open(path, "a+b")
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                try:
                    _lock_file(handle, blocking=blocking)
                except Exception:
                    handle.close()
                    raise
                self._handle = handle
            self._held = True
        except Exception:
            self._thread.release()
            raise

    def release(self) -> None:
        if not self._held:
            return
        handle = self._handle
        self._handle = None
        self._held = False
        try:
            if handle is not None:
                try:
                    _unlock_file(handle)
                finally:
                    handle.close()
        finally:
            self._thread.release()

    def _key(self) -> str:
        if self.directory is None:
            return self.experiment_id
        return f"{self.directory.resolve()}:{self.experiment_id}"


def _thread_lock(key: str) -> threading.Lock:
    with _registry_guard:
        lock = _thread_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _thread_locks[key] = lock
        return lock


def _lock_file(handle, *, blocking: bool) -> None:
    if os.name == "nt":
        import msvcrt

        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        try:
            msvcrt.locking(handle.fileno(), mode, 1)
        except OSError as exc:
            raise ExperimentBusy("experiment run lock is held by another process") from exc
        return
    import fcntl

    flags = fcntl.LOCK_EX
    if not blocking:
        flags |= fcntl.LOCK_NB
    try:
        fcntl.flock(handle.fileno(), flags)
    except OSError as exc:
        raise ExperimentBusy("experiment run lock is held by another process") from exc


def _unlock_file(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
