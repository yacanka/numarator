"""Native runtime child: validate, prepare, and serve HTTPS under one data lock."""

import argparse
import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError

from .native_frontend import build_frontend, verify_frontend
from .native_lock import instance_lock


def prepare(args, settings) -> None:
    from .native_tls import validate_tls

    validate_tls(args.tls_cert_file, args.tls_key_file, settings.HOST)
    call_command('check', deploy=True, fail_level='WARNING')
    call_command('makemigrations', check=True, dry_run=True, interactive=False)
    frontend = settings.FRONTEND_DIST.parent
    if args.build_frontend:
        build_frontend(frontend)
    verify_frontend(frontend)
    if args.migrate:
        call_command('migrate', interactive=False)
    call_command('migrate', check_unapplied=True, interactive=False)
    if not args.check:
        call_command('collectstatic', interactive=False, verbosity=0)


def serve(args, settings) -> None:
    import uvicorn
    from .native_asgi import application

    print(f'Ready: {settings.CSRF_TRUSTED_ORIGINS[0]} (Ctrl+C to stop)', flush=True)
    # A single worker and serialized Django views are part of the SQLite contract.
    uvicorn.run(
        application, host=settings.HOST, port=settings.PORT, workers=1,
        ssl_certfile=str(args.tls_cert_file), ssl_keyfile=str(args.tls_key_file),
        proxy_headers=False, server_header=False, lifespan='off',
        ws='none', access_log=False, timeout_keep_alive=5,
        timeout_graceful_shutdown=10, limit_concurrency=64,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tls-cert-file', type=Path, required=True)
    parser.add_argument('--tls-key-file', type=Path, required=True)
    parser.add_argument('--migrate', action='store_true')
    parser.add_argument('--build-frontend', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if os.environ.get('DJANGO_SETTINGS_MODULE') != 'config.settings.native':
        parser.error('use launcher.py prod to select the native profile')
    if args.check and (args.migrate or args.build_frontend):
        parser.error('--check cannot migrate or build')
    try:
        import django
        django.setup()
        from django.conf import settings
        from .settings.native_environment import data_dir
        with instance_lock(data_dir):
            prepare(args, settings)
            if args.check:
                print('[ok] native production checks completed')
            else:
                serve(args, settings)
        return 0
    except (CommandError, ImproperlyConfigured, OSError) as error:
        print(f'[error] {error}', file=sys.stderr)
        return 1
    except ImportError:
        print('[error] Production dependencies are missing; run launcher.py setup --environment production', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
