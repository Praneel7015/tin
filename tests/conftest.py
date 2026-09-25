from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

# Windows refuses to create a symlink without Developer Mode or an elevated shell.
_WINDOWS_SYMLINK_PRIVILEGE = 1314


@pytest.fixture
def make_symlink() -> Callable[[Path, Path], None]:
    """Create `link` pointing at `target`, or skip where the OS will not create one.

    A test about refusing symlinks needs a symlink to exist; without the privilege there is
    nothing to refuse, so the case is skipped rather than reported as a product failure.
    """

    def make(link: Path, target: Path) -> None:
        try:
            link.symlink_to(target, target_is_directory=target.is_dir())
        except OSError as error:
            if getattr(error, "winerror", None) != _WINDOWS_SYMLINK_PRIVILEGE:
                raise
            pytest.skip("creating symlinks needs Developer Mode or an elevated shell on Windows")

    return make


@pytest.fixture(autouse=True)
def _settled_switchboard_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test process is always young; only tests about restarts pretend Tin just came up."""
    from tin_lite import activities

    monkeypatch.setattr(activities, "process_uptime_seconds", lambda: 3600.0)
