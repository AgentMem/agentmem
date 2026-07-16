"""Drive an interactive CLI through a pty and watch its transcript, not its screen.

Claude Code is an Ink TUI, so the screen is animation; the transcript JSONL it
writes is the ground truth. Idle means the transcript stopped growing.
"""

from __future__ import annotations

import fcntl
import json
import os
import pty
import select
import struct
import subprocess
import termios
import time
from pathlib import Path
from typing import Any


class Driver:
    def __init__(
        self,
        cmd: list[str],
        transcript: Path,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        cols: int = 140,
        rows: int = 40,
    ) -> None:
        self.cmd = cmd
        self.transcript = Path(transcript)
        self.cwd = cwd
        self.env = env
        self.cols = cols
        self.rows = rows
        self.screen_tail = ""
        self._master: int | None = None
        self._proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        self._master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))
        env = dict(self.env or os.environ)
        env.setdefault("TERM", "xterm-256color")
        self._proc = subprocess.Popen(
            self.cmd,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=self.cwd,
            env=env,
            start_new_session=True,
        )
        os.close(slave)

    def send(self, text: str) -> None:
        assert self._master is not None, "start() first"
        os.write(self._master, text.encode() + b"\r")

    def _drain(self) -> None:
        """The child blocks once the pty buffer fills, so someone must keep reading."""
        assert self._master is not None
        while True:
            r, _, _ = select.select([self._master], [], [], 0)
            if not r:
                return
            try:
                chunk = os.read(self._master, 65536)
            except OSError:
                return
            if not chunk:
                return
            self.screen_tail = (self.screen_tail + chunk.decode(errors="replace"))[-4000:]

    def _stat(self) -> tuple[int, float]:
        try:
            st = self.transcript.stat()
            return st.st_size, st.st_mtime
        except FileNotFoundError:
            return -1, 0.0

    def wait_idle(self, *, quiet: float = 6.0, timeout: float = 900.0) -> None:
        """Idle = the transcript exists and has not changed for `quiet` seconds."""
        deadline = time.monotonic() + timeout
        last = self._stat()
        settled = time.monotonic()
        while time.monotonic() < deadline:
            self._drain()
            if self._proc is not None and self._proc.poll() is not None:
                raise RuntimeError(f"process exited; screen tail:\n{self.screen_tail[-800:]}")
            now = self._stat()
            if now != last:
                last, settled = now, time.monotonic()
            elif last[0] > 0 and time.monotonic() - settled >= quiet:
                return
            time.sleep(0.25)
        raise TimeoutError(f"no idle within {timeout}s; screen tail:\n{self.screen_tail[-800:]}")

    def entries(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            text = self.transcript.read_text(errors="replace")
        except FileNotFoundError:
            return out
        for line in text.splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def boundaries(self) -> int:
        return sum(1 for e in self.entries() if e.get("subtype") == "compact_boundary")

    def compact(self, *, timeout: float = 600.0) -> None:
        """Send /compact and wait for the boundary marker, then for idle."""
        before = self.boundaries()
        self.send("/compact")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._drain()
            if self.boundaries() > before:
                self.wait_idle(quiet=4.0, timeout=timeout)
                return
            time.sleep(0.5)
        raise TimeoutError(f"no compact_boundary within {timeout}s: {self.screen_tail[-400:]}")

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._master is not None:
            os.close(self._master)
            self._master = None
