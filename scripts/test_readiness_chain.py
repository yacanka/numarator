"""Readiness TLS regressions for explicitly trusted CA-signed certificates."""

from __future__ import annotations

import importlib.util
import io
import ipaddress
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.launcher.readiness import Readiness
from scripts.test_runtime import readiness_server


@unittest.skipUnless(importlib.util.find_spec("cryptography"),
                     "CA-signed TLS fixtures require the backend virtual environment")
class SignedCertificateReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        cls.issuer_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Readiness root")])
        issuer_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Readiness issuer")])
        now = datetime.now(timezone.utc)
        cls.issuer = (x509.CertificateBuilder().subject_name(issuer_name).issuer_name(root_name)
                      .public_key(cls.issuer_key.public_key()).serial_number(x509.random_serial_number())
                      .not_valid_before(now - timedelta(days=2)).not_valid_after(now + timedelta(days=90))
                      .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                      .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False,
                          content_commitment=False, data_encipherment=False, key_agreement=False,
                          key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False),
                          critical=True)
                      .add_extension(x509.SubjectKeyIdentifier.from_public_key(cls.issuer_key.public_key()),
                                     critical=False)
                      .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
                                     critical=False)
                      .sign(root_key, hashes.SHA256()))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def leaf(self, name, *, not_before=-1, not_after=30, with_issuer=False):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(self.issuer.subject)
                       .public_key(key.public_key()).serial_number(x509.random_serial_number())
                       .not_valid_before(now + timedelta(days=not_before))
                       .not_valid_after(now + timedelta(days=not_after))
                       .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                       .add_extension(x509.SubjectAlternativeName(
                           [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                       .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                       .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                       .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
                           self.issuer_key.public_key()), critical=False)
                       .sign(self.issuer_key, hashes.SHA256()))
        certificate_file, key_file = self.root / f"{name}.pem", self.root / f"{name}.key"
        pem = certificate.public_bytes(serialization.Encoding.PEM)
        if with_issuer:
            pem += self.issuer.public_bytes(serialization.Encoding.PEM)
        certificate_file.write_bytes(pem)
        key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        key_file.chmod(0o600)
        return certificate_file, key_file

    def check_service(self, server_files, trust_file, *, hostname="127.0.0.1"):
        responses = {"/": (200, b"<html>ready</html>", {}),
                     "/api/v1/auth/csrf/": (200, b'{"success": true}', {})}
        with readiness_server(responses, tls=server_files) as (url, requests), \
                mock.patch("scripts.launcher.readiness.webbrowser.open") as browser, \
                redirect_stdout(io.StringIO()):
            url = url.replace("127.0.0.1", hostname)
            ready = Readiness(url, url, trust_file)()
        if ready:
            self.assertEqual(requests, ["/", "/api/v1/auth/csrf/"])
            browser.assert_called_once_with(url)
        else:
            self.assertEqual(requests, [])
            browser.assert_not_called()
        return ready

    def test_explicit_ca_signed_leaf_without_issuer_is_trusted(self):
        certificate, key = self.leaf("leaf-only")
        self.assertTrue(self.check_service((certificate, key), certificate))

    def test_explicit_leaf_and_intermediate_bundle_without_root_is_trusted(self):
        certificate, key = self.leaf("leaf-chain", with_issuer=True)
        self.assertTrue(self.check_service((certificate, key), certificate))

    def test_another_leaf_from_the_same_issuer_is_not_trusted_by_leaf_only_file(self):
        trusted, _ = self.leaf("trusted")
        other, other_key = self.leaf("other")
        self.assertFalse(self.check_service((other, other_key), trusted))

    def test_trusted_signed_leaf_still_requires_matching_hostname(self):
        certificate, key = self.leaf("hostname")
        self.assertFalse(self.check_service((certificate, key), certificate, hostname="localhost"))

    def test_trusted_signed_leaf_still_requires_current_validity(self):
        for name, not_before, not_after in (("expired", -4, -2), ("future", 2, 4)):
            with self.subTest(name=name):
                certificate, key = self.leaf(name, not_before=not_before, not_after=not_after)
                self.assertFalse(self.check_service((certificate, key), certificate))


if __name__ == "__main__":
    unittest.main()
