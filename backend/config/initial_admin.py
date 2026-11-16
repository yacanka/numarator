"""Create an initial administrator interactively without changing existing users."""

import sys

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError


def ensure_initial_admin() -> None:
    """Prompt for a superuser only when none is active; fail if creation is skipped."""
    users = get_user_model()._default_manager
    if users.filter(is_active=True, is_superuser=True).exists():
        return
    call_command('createsuperuser', interactive=True)
    if not users.filter(is_active=True, is_superuser=True).exists():
        raise CommandError('An active superuser is required; rerun setup in an interactive terminal')


def main() -> int:
    """Initialize Django with the settings selected by the calling launcher."""
    import django

    try:
        django.setup()
        ensure_initial_admin()
        return 0
    except (CommandError, ImproperlyConfigured) as error:
        print(f'[error] {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
