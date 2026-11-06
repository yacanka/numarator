"""Docker deployment regressions; Docker cases use only disposable fixtures.

Run with backend/.venv/bin/python -m unittest scripts.test_deployment.
Docker cases require a reachable daemon and local nginx:1.27-alpine and
node:22-bookworm-slim images. They never mount application data or real secrets.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[1]


class CommandTests(unittest.TestCase):
    def run_backend_command(self, failing_step=''):
        compose = yaml.safe_load((ROOT / 'backend/docker/docker-compose.yml').read_text())
        command = compose['services']['backend']['command']
        arguments = shlex.split(command) if isinstance(command, str) else command
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            log = directory / 'commands.jsonl'
            for executable in ('python', 'gunicorn'):
                path = directory / executable
                path.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
from pathlib import Path
with open(os.environ['TEST_COMMAND_LOG'], 'a') as log:
    log.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]]) + '\\n')
raise SystemExit(7 if os.environ['TEST_FAIL_STEP'] in sys.argv[1:] else 0)
''')
                path.chmod(0o700)
            result = subprocess.run(arguments, cwd=directory, capture_output=True, text=True,
                                    env={**os.environ, 'PATH': str(directory) + os.pathsep + os.environ['PATH'],
                                         'TEST_COMMAND_LOG': str(log), 'TEST_FAIL_STEP': failing_step})
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            return result, calls

    def test_backend_start_passes_all_options_to_one_server_process(self):
        result, calls = self.run_backend_command()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[:2], [
            ['python', 'manage.py', 'migrate', '--no-input'],
            ['python', 'manage.py', 'collectstatic', '--no-input'],
        ])
        self.assertEqual(calls[2], [
            'gunicorn', 'config.wsgi:application', '--bind', '0.0.0.0:8000',
            '--workers', '4', '--worker-class', 'gthread', '--threads', '4',
            '--timeout', '30', '--max-requests', '1000', '--max-requests-jitter', '100',
            '--access-logfile', '-', '--error-logfile', '-',
        ])
        self.assertEqual(len(calls), 3)

    def test_failed_preparation_never_starts_server(self):
        for step, expected_calls in [('migrate', 1), ('collectstatic', 2)]:
            with self.subTest(step=step):
                result, calls = self.run_backend_command(step)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(calls), expected_calls)
                self.assertTrue(all(call[0] == 'python' for call in calls))


class ProductionProxyTests(unittest.TestCase):
    def test_trusted_https_proxy_avoids_redirect_loop_and_keeps_secure_cookies(self):
        script = '''
import json
from django.conf import settings
from django.http import HttpResponse
from django.middleware.security import SecurityMiddleware
from django.test import RequestFactory
middleware = SecurityMiddleware(lambda request: HttpResponse('OK'))
results = []
for scheme in ('https', 'http', None):
    headers = {'HTTP_HOST': 'localhost'}
    if scheme:
        headers['HTTP_X_FORWARDED_PROTO'] = scheme
    response = middleware(RequestFactory().get('/api/v1/formats/', **headers))
    results.append([response.status_code, response.get('Location'), response.get('Strict-Transport-Security')])
print(json.dumps({'responses': results, 'cookies': [settings.AUTH_COOKIE_SECURE,
                  settings.CSRF_COOKIE_SECURE, settings.SESSION_COOKIE_SECURE]}))
'''
        environment = {key: value for key, value in os.environ.items() if key in ('PATH', 'SYSTEMROOT')}
        environment.update(DJANGO_SETTINGS_MODULE='config.settings.production',
                           SECRET_KEY=secrets.token_urlsafe(64), DEBUG='True', AUTH_COOKIE_SECURE='False')
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT / 'backend',
                                env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['responses'][0][0], 200)
        self.assertIn('max-age=', data['responses'][0][2])
        self.assertEqual([row[0] for row in data['responses'][1:]], [301, 301])
        self.assertEqual(data['cookies'], [True, True, True])


def docker(*arguments, timeout=90):
    return subprocess.run(['docker', *arguments], capture_output=True, text=True,
                          check=True, timeout=timeout).stdout.strip()


class DockerFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('docker'):
            raise unittest.SkipTest('Docker CLI is unavailable')
        try:
            docker('info', '--format', '{{.ServerVersion}}', timeout=10)
        except (subprocess.SubprocessError, OSError) as error:
            raise unittest.SkipTest('Docker daemon is unavailable; run these isolated tests with Docker access') from error

    def test_build_context_excludes_local_secrets_and_keeps_required_sources(self):
        fixtures = {
            'backend': {
                'keep': ['requirements/base.txt', 'manage.py', 'config/settings/base.py', 'apps/core/models.py'],
                'exclude': ['.env', '.dev-secret-key', 'db.sqlite3', 'docker/.env', 'docker/ssl/server.key',
                            '.venv/token', 'logs/app.log', 'media/customer.pdf', 'config/.env.local',
                            'apps/core/private.pem', 'config/__pycache__/settings.pyc'],
            },
            'frontend': {
                'keep': ['package.json', 'package-lock.json', 'index.html', 'src/main.ts',
                         'vite.config.ts', 'tsconfig.json', 'nginx.conf', 'public/logo.svg'],
                'exclude': ['.env', '.env.production', '.npmrc', 'node_modules/token', 'dist/private.js',
                            '.native-build.json', 'src/.env.local', 'src/private.pem', '.DS_Store'],
            },
        }
        for side, cases in fixtures.items():
            with self.subTest(side=side), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                ignore = ROOT / side / '.dockerignore'
                if ignore.is_file():
                    shutil.copyfile(ignore, directory / '.dockerignore')
                for name in cases['keep'] + cases['exclude']:
                    path = directory / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('synthetic fixture, never a real credential')
                (directory / 'Dockerfile').write_text('FROM scratch\nCOPY . /\n')
                tag = 'numarator-test-context:' + uuid.uuid4().hex
                archive_path = directory.parent / (directory.name + '.tar')
                try:
                    docker('build', '--network=none', '--no-cache', '-t', tag, str(directory))
                    docker('image', 'save', '-o', str(archive_path), tag)
                    names = set()
                    with tarfile.open(archive_path) as archive:
                        manifest = json.load(archive.extractfile('manifest.json'))
                        for layer in manifest[0]['Layers']:
                            with tarfile.open(fileobj=io.BytesIO(archive.extractfile(layer).read())) as contents:
                                names.update(member.name.rstrip('/') for member in contents.getmembers())
                    for name in cases['keep']:
                        self.assertIn(name, names)
                    for name in cases['exclude']:
                        self.assertNotIn(name, names)
                finally:
                    subprocess.run(['docker', 'image', 'rm', '-f', tag], capture_output=True)
                    archive_path.unlink(missing_ok=True)

    def test_gateway_serves_tls_spa_assets_and_overwrites_forwarded_scheme(self):
        for image in ('nginx:1.27-alpine', 'node:22-bookworm-slim'):
            try:
                docker('image', 'inspect', image)
            except subprocess.CalledProcessError as error:
                self.skipTest(f'Pull {image} before running the Docker HTTPS smoke test')
        from scripts.test_native import tls_files

        suffix = uuid.uuid4().hex[:12]
        network = 'numarator-test-' + suffix
        containers = []
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            ssl_directory = directory / 'ssl'
            ssl_directory.mkdir()
            cert, key = tls_files(ssl_directory)
            dist = directory / 'dist'
            (dist / 'assets').mkdir(parents=True)
            (dist / 'index.html').write_text('<html>deployment fixture</html>')
            (dist / 'assets/app.js').write_text('/* deployment fixture */')
            (directory / 'backend.js').write_text('''
require('http').createServer((request, response) => {
  response.setHeader('Content-Type', 'application/json');
  response.end(JSON.stringify({path: request.url, scheme: request.headers['x-forwarded-proto']}));
}).listen(8000, '0.0.0.0');
''')
            docker('network', 'create', network)
            try:
                backend = 'numarator-test-backend-' + suffix
                containers.append(backend)
                docker('create', '--name', backend, '--network', network, '--network-alias', 'backend',
                       'node:22-bookworm-slim', 'node', '/fixture.js')
                docker('cp', str(directory / 'backend.js'), f'{backend}:/fixture.js')
                docker('start', backend)
                frontend = 'numarator-test-frontend-' + suffix
                containers.append(frontend)
                frontend_config = ROOT / 'frontend/nginx.conf'
                docker('create', '--name', frontend, '--network', network, '--network-alias', 'frontend',
                       'nginx:1.27-alpine')
                if frontend_config.is_file():
                    docker('cp', str(frontend_config), f'{frontend}:/etc/nginx/conf.d/default.conf')
                docker('cp', str(dist) + '/.', f'{frontend}:/usr/share/nginx/html')
                docker('start', frontend)
                gateway = 'numarator-test-gateway-' + suffix
                containers.append(gateway)
                docker('create', '--name', gateway, '--network', network,
                       '-p', '127.0.0.1::443', '-p', '127.0.0.1::80', 'nginx:1.27-alpine')
                docker('cp', str(ROOT / 'backend/docker/nginx.conf'), f'{gateway}:/etc/nginx/nginx.conf')
                docker('cp', str(ssl_directory), f'{gateway}:/etc/nginx/ssl')
                docker('start', gateway)
                docker('exec', frontend, 'nginx', '-t')
                docker('exec', gateway, 'nginx', '-t')
                ports = json.loads(docker('inspect', gateway))[0]['NetworkSettings']['Ports']
                port = ports['443/tcp'][0]['HostPort']
                base = f'https://127.0.0.1:{port}'
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                    urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(cert))))
                for attempt in range(50):
                    try:
                        with opener.open(base + '/formats/new', timeout=2) as response:
                            self.assertEqual(response.read(), b'<html>deployment fixture</html>')
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if attempt == 49:
                            raise
                        time.sleep(0.1)
                with opener.open(base + '/assets/app.js', timeout=5) as response:
                    self.assertEqual(response.read(), b'/* deployment fixture */')
                class NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, request, response, code, message, headers, new_url):
                        return None

                http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
                with self.assertRaises(urllib.error.HTTPError) as redirect:
                    http.open(f'http://127.0.0.1:{ports["80/tcp"][0]["HostPort"]}/formats/new', timeout=5)
                self.assertEqual(redirect.exception.code, 301)
                self.assertEqual(redirect.exception.headers['Location'], 'https://127.0.0.1/formats/new')
                redirect.exception.close()
                with self.assertRaises(urllib.error.HTTPError) as error:
                    opener.open(base + '/assets/missing.js', timeout=5)
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
                for path in ('/api/v1/auth/csrf/', '/admin/login/'):
                    request = urllib.request.Request(base + path, headers={'X-Forwarded-Proto': 'http'})
                    with opener.open(request, timeout=5) as response:
                        self.assertEqual(json.load(response), {'path': path, 'scheme': 'https'})
            except Exception as error:
                logs = []
                for container in containers:
                    result = subprocess.run(['docker', 'logs', container], capture_output=True, text=True)
                    logs.append(container + ':\n' + result.stdout + result.stderr)
                detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
                raise AssertionError(detail + '\n' + '\n'.join(logs)) from error
            finally:
                for container in reversed(containers):
                    subprocess.run(['docker', 'rm', '-f', container], capture_output=True)
                subprocess.run(['docker', 'network', 'rm', network], capture_output=True)


if __name__ == '__main__':
    unittest.main()
