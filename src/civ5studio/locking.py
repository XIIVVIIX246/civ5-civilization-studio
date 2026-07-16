"""Crash-releasing, non-blocking file locks for filesystem mutations."""

from __future__ import annotations

from contextlib import AbstractContextManager
import os
from pathlib import Path
import threading
from typing import BinaryIO


class MutationBusyError(RuntimeError):
    pass


_ACTIVE: set[str] = set()
_GUARD = threading.Lock()


class FileMutationLock(AbstractContextManager["FileMutationLock"]):
    """Hold one byte of a project-owned lock file until the operation exits."""

    def __init__(self, path: str | Path, *, label: str = "operation") -> None:
        self.path = Path(path).resolve(strict=False)
        self.label = label
        self._handle: BinaryIO | None = None
        self._key = os.path.normcase(str(self.path))

    def __enter__(self) -> "FileMutationLock":
        with _GUARD:
            if self._key in _ACTIVE:
                raise MutationBusyError(f"Another {self.label} is already running.")
            _ACTIVE.add(self._key)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - exercised by non-Windows CI
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                handle.close()
                raise MutationBusyError(
                    f"Another {self.label} is running in a different process."
                ) from exc
            self._handle = handle
            return self
        except Exception:
            with _GUARD:
                _ACTIVE.discard(self._key)
            raise

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        handle = self._handle
        try:
            if handle is not None:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:  # pragma: no cover - exercised by non-Windows CI
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()
        finally:
            self._handle = None
            with _GUARD:
                _ACTIVE.discard(self._key)
