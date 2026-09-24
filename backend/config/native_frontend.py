"""Build and verify the frontend artifact for same-origin native production."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from django.core.management.base import CommandError

MANIFEST_NAME = '.native-build.json'


def artifact_hashes(dist: Path) -> dict[str, str]:
    if dist.is_symlink() or not (dist / 'index.html').is_file():
        raise CommandError('Frontend build is missing; use prod --build-frontend')
    hashes = {}
    for path in sorted(dist.rglob('*')):
        if path.is_symlink():
            raise CommandError('Frontend build cannot contain symbolic links')
        if path.is_file():
            with path.open('rb') as source:
                hashes[path.relative_to(dist).as_posix()] = hashlib.file_digest(source, 'sha256').hexdigest()
    if not any(name.startswith('assets/') and name.endswith('.js') for name in hashes):
        raise CommandError('Frontend build has no JavaScript assets')
    return hashes


def verify_frontend(frontend: Path) -> None:
    try:
        manifest = json.loads((frontend / MANIFEST_NAME).read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise CommandError('Native frontend manifest is missing; use prod --build-frontend') from error
    expected = {'profile': 'native-v1', 'files': artifact_hashes(frontend / 'dist')}
    if manifest != expected:
        raise CommandError('Frontend build changed; use prod --build-frontend')


def build_frontend(frontend: Path) -> None:
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not npm:
        raise CommandError('Node.js/npm is required for --build-frontend')
    manifest = frontend / MANIFEST_NAME
    if manifest.is_symlink():
        raise CommandError('Frontend manifest cannot be a symbolic link')
    if (frontend / 'dist').is_symlink():
        raise CommandError('Frontend build directory cannot be a symbolic link')
    # Do not pass production secrets or Django runtime configuration to npm.
    env = {key: value for key, value in os.environ.items() if key.upper() in {
        'PATH', 'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'SYSTEMROOT',
        'COMSPEC', 'PATHEXT', 'TEMP', 'TMP', 'TMPDIR', 'LANG', 'LC_ALL',
    }}
    env.update(VITE_API_BASE_URL='/api/v1', VITE_CSRF_COOKIE_NAME='csrftoken')
    completed = subprocess.run([npm, 'run', 'build'], cwd=frontend, env=env, check=False)
    if completed.returncode:
        raise CommandError('Frontend build failed; production was not started')
    manifest.write_text(json.dumps({
        'profile': 'native-v1', 'files': artifact_hashes(frontend / 'dist'),
    }, sort_keys=True) + '\n', encoding='utf-8')
