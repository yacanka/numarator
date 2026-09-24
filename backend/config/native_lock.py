"""OS-owned single-instance lock, automatically released on process exit."""

import os
from contextlib import contextmanager
from pathlib import Path

from django.core.management.base import CommandError


@contextmanager
def instance_lock(data_dir: Path):
    path = data_dir / '.native.lock'
    if path.is_symlink():
        raise CommandError('Native lock file cannot be a symbolic link')
    with path.open('a+b') as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise CommandError('Another native launcher is using this data directory') from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
