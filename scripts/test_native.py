"""Native production regressions; requires setup --environment production."""

from __future__ import annotations

import ipaddress
import http.cookiejar
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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
            password = secrets.token_urlsafe(32)
            bootstrap = subprocess.run(
                [sys.executable, 'manage.py', 'migrate', '--noinput'], cwd=backend, env=env,
                capture_output=True, text=True)
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
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
