"""Native production regressions; requires setup --environment production."""

from __future__ import annotations

import ipaddress
import http.cookiejar
import io
import json
import os
import secrets
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.core.management.base import CommandError

from config.native_frontend import MANIFEST_NAME, artifact_hashes, verify_frontend
from config.native_lock import instance_lock
from config.native_runtime import prepare
from config.native_tls import validate_tls


def tls_files(root, host='127.0.0.1', days=30):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Native regression')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(days=2))
                   .not_valid_after(now + timedelta(days=days))
                   .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host))]), critical=False)
                   .sign(key, hashes.SHA256()))
    cert_file, key_file = root / 'server.crt', root / 'server.key'
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    key_file.chmod(0o600)
    return cert_file, key_file


def frontend_fixture(root):
    frontend = root / 'frontend'
    assets = frontend / 'dist' / 'assets'
    assets.mkdir(parents=True)
    (assets / 'app.js').write_text('/* native regression */', encoding='utf-8')
    (frontend / 'dist' / 'index.html').write_text(
        '<!doctype html><div id="app"></div><script src="/assets/app.js"></script>', encoding='utf-8')
    (frontend / MANIFEST_NAME).write_text(json.dumps({
        'profile': 'native-v1', 'files': artifact_hashes(frontend / 'dist'),
    }), encoding='utf-8')
    return frontend


class TLSAndArtifactTests(unittest.TestCase):
    def test_tls_requires_matching_key_san_and_valid_dates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cert, key = tls_files(root)
            validate_tls(cert, key, '127.0.0.1')
            with self.assertRaises(CommandError):
                validate_tls(cert, key, '127.0.0.2')
            other = root / 'other'
            other.mkdir()
            _, other_key = tls_files(other)
            with self.assertRaises(CommandError):
                validate_tls(cert, other_key, '127.0.0.1')
            cert, key = tls_files(root, days=-1)
            with self.assertRaises(CommandError):
                validate_tls(cert, key, '127.0.0.1')

    def test_artifact_rejects_missing_modified_and_symlinked_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            frontend = frontend_fixture(Path(temporary))
            verify_frontend(frontend)
            asset = frontend / 'dist/assets/app.js'
            asset.write_text('modified', encoding='utf-8')
            with self.assertRaises(CommandError):
                verify_frontend(frontend)
            asset.unlink()
            with self.assertRaises(CommandError):
                verify_frontend(frontend)
            asset.symlink_to(frontend / 'dist/index.html')
            with self.assertRaises(CommandError):
                verify_frontend(frontend)

    def test_data_lock_rejects_second_instance_and_releases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with instance_lock(root):
                with self.assertRaises(CommandError):
                    with instance_lock(root):
                        self.fail('second instance entered')
            with instance_lock(root):
                pass


class StartupTests(unittest.TestCase):
    def args(self, **overrides):
        return SimpleNamespace(tls_cert_file=Path('cert'), tls_key_file=Path('key'),
                               **{'check': False, 'migrate': False, 'build_frontend': False, **overrides})

    @mock.patch('config.native_runtime.verify_frontend')
    @mock.patch('config.native_runtime.call_command')
    @mock.patch('config.native_tls.validate_tls')
    def test_normal_start_checks_pending_migrations_without_applying(self, tls, command, frontend):
        prepare(self.args(), SimpleNamespace(HOST='127.0.0.1', FRONTEND_DIST=Path('frontend/dist')))
        migration_calls = [call for call in command.call_args_list if call.args[0] == 'migrate']
        self.assertEqual(len(migration_calls), 1)
        self.assertTrue(migration_calls[0].kwargs['check_unapplied'])

    @mock.patch('config.native_runtime.build_frontend', side_effect=CommandError('build failed'))
    @mock.patch('config.native_runtime.call_command')
    @mock.patch('config.native_tls.validate_tls')
    def test_failed_build_never_migrates_or_collects_static(self, tls, command, build):
        with self.assertRaises(CommandError):
            prepare(self.args(migrate=True, build_frontend=True),
                    SimpleNamespace(HOST='127.0.0.1', FRONTEND_DIST=Path('frontend/dist')))
        self.assertFalse(any(call.args[0] in ('migrate', 'collectstatic') for call in command.call_args_list))

    @mock.patch('config.native_runtime.call_command')
    @mock.patch('config.native_tls.validate_tls', side_effect=CommandError('bad TLS'))
    def test_invalid_tls_stops_before_database_commands(self, tls, command):
        with self.assertRaises(CommandError):
            prepare(self.args(migrate=True), SimpleNamespace(HOST='127.0.0.1'))
        command.assert_not_called()

    def test_native_middleware_serializes_concurrent_requests(self):
        from config.native_serialization import SerializedRequestsMiddleware
        active = 0
        peak = 0
        guard = threading.Lock()

        def view(request):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with guard:
                active -= 1
            return 'OK'

        middleware = SerializedRequestsMiddleware(view)
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(middleware, range(8))), ['OK'] * 8)
        self.assertEqual(peak, 1)


class PreparationRuntimeTests(unittest.TestCase):
    def run_runtime(self, root, flags, *, prepare, admin, serve):
        from config.native_runtime import main

        arguments = ['native_runtime', '--tls-cert-file', 'cert', '--tls-key-file', 'key', *flags]
        modules = {
            'config.settings.native_environment': SimpleNamespace(data_dir=root),
            'config.initial_admin': SimpleNamespace(ensure_initial_admin=admin),
        }
        with mock.patch.dict(os.environ, {'DJANGO_SETTINGS_MODULE': 'config.settings.native'}), \
                mock.patch.dict(sys.modules, modules), mock.patch.object(sys, 'argv', arguments), \
                mock.patch('django.setup'), mock.patch('django.conf.settings', SimpleNamespace()), \
                mock.patch('config.native_runtime.prepare', side_effect=prepare), \
                mock.patch('config.native_runtime.serve', side_effect=serve), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main()

    def test_preparation_and_admin_share_data_lock_and_never_serve(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = []

            def assert_locked(event):
                with self.assertRaises(CommandError):
                    with instance_lock(root):
                        self.fail('preparation released the data lock')
                events.append(event)

            result = self.run_runtime(
                root, ['--prepare-only', '--ensure-admin', '--migrate'],
                prepare=lambda *_: assert_locked('prepare'),
                admin=lambda: assert_locked('admin'),
                serve=lambda *_: self.fail('preparation started HTTPS'))
            self.assertEqual(result, 0)
            self.assertEqual(events, ['prepare', 'admin'])
            with instance_lock(root):
                pass

    def test_invalid_preparation_combinations_fail_before_preparing(self):
        for flags in (['--ensure-admin'], ['--check', '--prepare-only'],
                      ['--check', '--prepare-only', '--ensure-admin']):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(SystemExit) as error:
                    self.run_runtime(
                        Path(temporary), flags,
                        prepare=lambda *_: self.fail('invalid arguments prepared data'),
                        admin=lambda: self.fail('invalid arguments created an admin'),
                        serve=lambda *_: self.fail('invalid arguments served HTTPS'))
                self.assertEqual(error.exception.code, 2)

    def test_failed_preparation_does_not_create_admin_or_serve_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def fail_prepare(*_):
                raise CommandError('preparation failed')

            self.assertEqual(self.run_runtime(
                root, ['--prepare-only', '--ensure-admin'], prepare=fail_prepare,
                admin=lambda: self.fail('admin created after failed preparation'),
                serve=lambda *_: self.fail('HTTPS served after failed preparation')), 1)
            with instance_lock(root):
                pass

    def test_interrupted_preparation_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def interrupt(*_):
                raise KeyboardInterrupt

            result = self.run_runtime(
                root, ['--prepare-only', '--ensure-admin'], prepare=interrupt,
                admin=lambda: self.fail('admin created after interrupted preparation'),
                serve=lambda *_: self.fail('interrupted preparation started HTTPS'))
            self.assertEqual(result, 130)
            with instance_lock(root):
                pass

    @mock.patch('config.native_runtime.verify_frontend')
    @mock.patch('config.native_runtime.call_command')
    @mock.patch('config.native_tls.validate_tls')
    def test_preparation_collects_static_after_successful_migrations(self, tls, command, frontend):
        args = SimpleNamespace(tls_cert_file=Path('cert'), tls_key_file=Path('key'),
                               check=False, migrate=True, build_frontend=False,
                               prepare_only=True, ensure_admin=False)
        prepare(args, SimpleNamespace(HOST='127.0.0.1', FRONTEND_DIST=Path('frontend/dist')))
        operations = [call.args[0] for call in command.call_args_list]
        self.assertEqual(operations[-3:], ['migrate', 'migrate', 'collectstatic'])


class InitialAdminTests(unittest.TestCase):
    def run_admin_script(self, script):
        setup = '''
import secrets
from unittest import mock
from django.conf import settings
settings.configure(
    SECRET_KEY=secrets.token_urlsafe(48),
    INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes'],
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)
import django
django.setup()
from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.auth import get_user_model
call_command('migrate', interactive=False, verbosity=0)
from config.initial_admin import ensure_initial_admin
User = get_user_model()
'''
        completed = subprocess.run(
            [sys.executable, '-c', setup + textwrap.dedent(script)], cwd=ROOT / 'backend',
            capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_existing_active_superuser_is_preserved_without_prompt(self):
        self.run_admin_script('''
            User.objects.create_superuser('existing-admin', password=None)
            before = list(User.objects.values())
            with mock.patch('builtins.input', side_effect=AssertionError('unexpected prompt')):
                ensure_initial_admin()
            assert list(User.objects.values()) == before
        ''')

    def test_missing_active_superuser_is_created_interactively_without_changing_accounts(self):
        self.run_admin_script('''
            User.objects.create_superuser('disabled-admin', password=None, is_active=False)
            User.objects.create_user('ordinary-user', password=None, is_staff=True)
            before = list(User.objects.values())
            password = secrets.token_urlsafe(32)
            with mock.patch('sys.stdin.isatty', return_value=True), \\
                    mock.patch('builtins.input', side_effect=['bootstrap-admin', '']), \\
                    mock.patch('getpass.getpass', return_value=password):
                ensure_initial_admin()
            admin = User.objects.get(username='bootstrap-admin')
            assert admin.is_active and admin.is_superuser and admin.check_password(password)
            assert list(User.objects.exclude(pk=admin.pk).values()) == before
            with mock.patch('builtins.input', side_effect=AssertionError('unexpected prompt')):
                ensure_initial_admin()
            assert User.objects.count() == 3
        ''')

    def test_noninteractive_skip_is_reported_as_failure(self):
        self.run_admin_script('''
            with mock.patch('sys.stdin.isatty', return_value=False):
                try:
                    ensure_initial_admin()
                except CommandError:
                    pass
                else:
                    raise AssertionError('missing admin was reported as prepared')
            assert User.objects.count() == 0
        ''')

    def test_module_initializes_the_settings_selected_by_the_caller(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'initial_admin_test_settings.py').write_text('''
import os
import secrets
SECRET_KEY = secrets.token_urlsafe(48)
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes']
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3',
                         'NAME': os.environ['INITIAL_ADMIN_TEST_DATABASE']}}
''', encoding='utf-8')
            env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'initial_admin_test_settings',
                   'INITIAL_ADMIN_TEST_DATABASE': str(root / 'users.sqlite3'),
                   'PYTHONPATH': os.pathsep.join((str(root), str(ROOT / 'backend')))}
            bootstrap = subprocess.run(
                [sys.executable, '-c', 'import django; django.setup(); '
                 'from django.core.management import call_command; '
                 'call_command("migrate", interactive=False, verbosity=0); '
                 'from django.contrib.auth import get_user_model; '
                 'get_user_model().objects.create_superuser("existing-admin", password=None)'],
                cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stdout + bootstrap.stderr)
            completed = subprocess.run(
                [sys.executable, '-m', 'config.initial_admin'], cwd=root, env=env,
                capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            with sqlite3.connect(root / 'users.sqlite3') as database:
                self.assertEqual(database.execute(
                    'SELECT username, is_active, is_superuser FROM auth_user').fetchall(),
                    [('existing-admin', 1, 1)])


class HTTPSIntegrationTests(unittest.TestCase):
    def test_real_https_spa_static_api_host_checks_and_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            backend = source / 'backend'
            shutil.copytree(ROOT / 'backend', backend, ignore=shutil.ignore_patterns(
                '.venv', '__pycache__', '.env', '.dev-secret-key', '*.sqlite3', 'logs', 'staticfiles', 'media'))
            frontend_fixture(source)
            cert, key = tls_files(root)
            env_file = root / 'production.env'
            env_file.write_text(f'SECRET_KEY={secrets.token_urlsafe(64)}\nNUMARATOR_DATA_DIR={root / "data"}\n')
            env_file.chmod(0o600)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.settings.native',
                   'NUMARATOR_ENV_FILE': str(env_file), 'NUMARATOR_HOST': '127.0.0.1',
                   'NUMARATOR_PORT': str(port)}
            env.pop('SECRET_KEY', None)
            env.pop('NUMARATOR_DATA_DIR', None)
            command = [sys.executable, '-m', 'config.native_runtime', '--tls-cert-file', str(cert),
                       '--tls-key-file', str(key)]
            # Without explicit migration, startup must fail without applying the schema.
            pending = subprocess.run([*command, '--check'], cwd=backend, env=env, capture_output=True, text=True)
            self.assertNotEqual(pending.returncode, 0)
            self.assertIn('Unapplied database migrations', pending.stderr)
            self.assertIn('--migrate', pending.stderr)
            with sqlite3.connect(root / 'data/numarator.sqlite3') as database:
                self.assertEqual(database.execute('SELECT name FROM sqlite_master WHERE type = \'table\'').fetchall(), [])
            password = secrets.token_urlsafe(32)
            prepared = subprocess.run(
                [*command, '--prepare-only', '--migrate'], cwd=backend, env=env,
                capture_output=True, text=True, timeout=30)
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            self.assertTrue((root / 'data/staticfiles/admin/css/base.css').is_file())
            bootstrap = subprocess.run(
                [sys.executable, 'manage.py', 'shell', '-c',
                 "import os, json; from django.contrib.auth import get_user_model; "
                 "from apps.formats.models import DocumentFormat; "
                 "user = get_user_model().objects.create_user('native-regression', password=os.environ['TEST_PASSWORD']); "
                 "print(json.dumps([str(DocumentFormat.objects.create(code=code, name=code, status='active', "
                 "created_by=user, segments_config=[{'type':'static','order':1,'config':{'value':code}}, "
                 "{'type':'sequence','order':2,'config':{'padding':4}}]).id) for code in ('FIRST','SECOND')]))"],
                cwd=backend, env={**env, 'TEST_PASSWORD': password}, capture_output=True, text=True)
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
            format_ids = json.loads(bootstrap.stdout.splitlines()[-1])
            log = root / 'server.log'
            context = ssl.create_default_context(cafile=str(cert))
            cookies = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                urllib.request.HTTPCookieProcessor(cookies),
                                                urllib.request.HTTPSHandler(context=context))
            url = f'https://127.0.0.1:{port}'
            with log.open('w') as output:
                server = subprocess.Popen([*command, '--migrate'], cwd=backend, env=env,
                                          stdout=output, stderr=subprocess.STDOUT)
                try:
                    for _ in range(150):
                        if server.poll() is not None:
                            self.fail(log.read_text())
                        try:
                            with opener.open(url + '/login', timeout=1) as response:
                                self.assertIn(b'id="app"', response.read())
                            break
                        except (urllib.error.URLError, TimeoutError):
                            time.sleep(0.1)
                    else:
                        self.fail('HTTPS did not become ready: ' + log.read_text())
                    for path in ('/', '/formats/00000000-0000-0000-0000-000000000001/edit',
                                 '/assets/app.js', '/static/admin/css/base.css'):
                        with opener.open(url + path, timeout=5) as response:
                            self.assertEqual(response.status, 200)
                            self.assertIn('max-age=', response.headers['Strict-Transport-Security'])
                    for path, expected in [('/api/missing', 404), ('/assets/missing.js', 404),
                                           ('/media/private.txt', 404), ('/api/v1/formats/', 401)]:
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            opener.open(url + path, timeout=5)
                        self.assertEqual(error.exception.code, expected)
                        error.exception.close()
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        opener.open(urllib.request.Request(url + '/', headers={'Host': 'untrusted.invalid'}), timeout=5)
                    self.assertEqual(error.exception.code, 400)
                    error.exception.close()
                    with opener.open(url + '/api/v1/auth/csrf/', timeout=5) as response:
                        self.assertEqual(response.status, 200)
                    csrf = next(cookie for cookie in cookies if cookie.name == 'csrftoken')
                    self.assertTrue(csrf.secure)
                    credentials = json.dumps({'username': 'native-regression', 'password': password}).encode()
                    login = urllib.request.Request(url + '/api/v1/auth/token/', data=credentials,
                        headers={'Content-Type': 'application/json', 'X-CSRFToken': csrf.value, 'Origin': url})
                    with opener.open(login, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                    auth = next(cookie for cookie in cookies if cookie.name == 'dn_access')
                    self.assertTrue(auth.secure)
                    self.assertTrue(auth.has_nonstandard_attr('HttpOnly'))
                    with opener.open(url + '/api/v1/auth/me/', timeout=5) as response:
                        self.assertEqual(response.status, 200)
                    bad_origin = urllib.request.Request(url + '/api/v1/auth/token/', data=credentials,
                        headers={'Content-Type': 'application/json', 'X-CSRFToken': csrf.value,
                                 'Origin': 'https://untrusted.invalid'})
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        opener.open(bad_origin, timeout=5)
                    # Auth endpoints already report CSRF failures as serializer errors (400).
                    self.assertEqual(error.exception.code, 400)
                    self.assertIn(b'CSRF', error.exception.read())
                    error.exception.close()
                    cookie_header = '; '.join(f'{cookie.name}={cookie.value}' for cookie in cookies)

                    def generate_number(index):
                        client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                            urllib.request.HTTPSHandler(context=context))
                        request = urllib.request.Request(
                            url + f'/api/v1/formats/{format_ids[index % 2]}/generate/', data=b'{}',
                            headers={'Content-Type': 'application/json', 'Cookie': cookie_header,
                                     'X-CSRFToken': csrf.value, 'Origin': url})
                        with client.open(request, timeout=10) as response:
                            return json.load(response)['data']

                    with ThreadPoolExecutor(max_workers=8) as pool:
                        numbers = list(pool.map(generate_number, range(8)))
                    self.assertEqual(len({item['document_number'] for item in numbers}), 8)
                    for prefix in ('FIRST', 'SECOND'):
                        self.assertEqual(sorted(item['sequence_value'] for item in numbers
                                                if item['document_number'].startswith(prefix)), [1, 2, 3, 4])
                    request = urllib.request.Request(url + '/login', headers={'X-Forwarded-Proto': 'http'})
                    with opener.open(request, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait()
            checked = subprocess.run([*command, '--check'], cwd=backend, env=env, capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertTrue((root / 'data/numarator.sqlite3').is_file())
            self.assertFalse((backend / 'db.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()
