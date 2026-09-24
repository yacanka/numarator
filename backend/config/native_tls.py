"""Validate the server's TLS identity before any database migration."""

import ipaddress
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from django.core.management.base import CommandError


def validate_tls(certificate_file: Path, key_file: Path, host: str) -> None:
    try:
        certificate = x509.load_pem_x509_certificate(certificate_file.read_bytes())
        private_key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
        encoding = serialization.Encoding.DER
        key_format = serialization.PublicFormat.SubjectPublicKeyInfo
        if certificate.public_key().public_bytes(encoding, key_format) != private_key.public_key().public_bytes(encoding, key_format):
            raise ValueError
        san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if ipaddress.IPv4Address(host) not in san.get_values_for_type(x509.IPAddress):
            raise ValueError
        now = datetime.now(timezone.utc)
        if not certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc - timedelta(days=1):
            raise ValueError
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certificate_file, key_file)
    except (OSError, ValueError, TypeError, x509.ExtensionNotFound, UnsupportedAlgorithm) as error:
        raise CommandError(
            'TLS identity is invalid: require matching PEM certificate/key, host IP SAN, '
            'and at least one day of remaining validity'
        ) from error
