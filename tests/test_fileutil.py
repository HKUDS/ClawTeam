"""Tests for clawteam.fileutil — atomic writes and advisory file locking."""

from __future__ import annotations

import threading
from pathlib import Path

from clawteam.fileutil import atomic_write_text, file_locked


class TestAtomicWriteText:

    def test_creates_file(self, tmp_path: Path):
        target = tmp_path / "out.json"
        atomic_write_text(target, '{"ok": true}')
        assert target.read_text() == '{"ok": true}'

    def test_creates_parent_dirs(self, tmp_path: Path):
        target = tmp_path / "a" / "b" / "c.json"
        atomic_write_text(target, "hello")
        assert target.read_text() == "hello"

    def test_overwrites_existing(self, tmp_path: Path):
        target = tmp_path / "data.json"
        target.write_text("old")
        atomic_write_text(target, "new")
        assert target.read_text() == "new"

    def test_no_leftover_tmp_on_success(self, tmp_path: Path):
        target = tmp_path / "clean.json"
        atomic_write_text(target, "data")
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_cleans_up_on_error(self, tmp_path: Path, monkeypatch):
        """If os.replace fails the temp file is removed."""
        target = tmp_path / "fail.json"

        def failing_replace(src, dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr("os.replace", failing_replace)

        try:
            atomic_write_text(target, "data")
        except OSError:
            pass

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []
        assert not target.exists()

    def test_concurrent_writes_no_collision(self, tmp_path: Path):
        """Multiple threads writing to the same path never produce a corrupt file."""
        target = tmp_path / "shared.json"
        errors: list[Exception] = []

        def writer(value: int):
            try:
                for _ in range(20):
                    atomic_write_text(target, f'{{"v": {value}}}')
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        content = target.read_text()
        assert content.startswith('{"v":')


class TestFileLocked:

    def test_serialises_concurrent_updates(self, tmp_path: Path):
        """Two threads incrementing a shared counter never lose an update."""
        counter_path = tmp_path / "counter.json"
        counter_path.write_text("0")
        iterations = 50

        def increment():
            for _ in range(iterations):
                with file_locked(counter_path):
                    val = int(counter_path.read_text())
                    counter_path.write_text(str(val + 1))

        t1 = threading.Thread(target=increment)
        t2 = threading.Thread(target=increment)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert int(counter_path.read_text()) == iterations * 2

    def test_creates_lock_sidecar(self, tmp_path: Path):
        target = tmp_path / "data.json"
        target.write_text("{}")
        with file_locked(target):
            lock_file = Path(str(target) + ".lock")
            assert lock_file.exists()

    def test_lock_released_after_context(self, tmp_path: Path):
        """After exiting the context, another lock acquisition succeeds immediately."""
        target = tmp_path / "release.json"
        target.write_text("{}")

        with file_locked(target):
            pass

        acquired = threading.Event()

        def try_lock():
            with file_locked(target):
                acquired.set()

        t = threading.Thread(target=try_lock)
        t.start()
        t.join(timeout=2.0)
        assert acquired.is_set()

    def test_lock_released_on_exception(self, tmp_path: Path):
        """Lock is released even when the body raises."""
        target = tmp_path / "exc.json"
        target.write_text("{}")

        try:
            with file_locked(target):
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        acquired = threading.Event()

        def try_lock():
            with file_locked(target):
                acquired.set()

        t = threading.Thread(target=try_lock)
        t.start()
        t.join(timeout=2.0)
        assert acquired.is_set()
