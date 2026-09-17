"""Local TLS identities; only public certificates cross device boundaries."""
import datetime as dt
import hashlib
import os
from pathlib import Path
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID


def fingerprint(pem):
    cert = x509.load_pem_x509_certificate(pem.encode())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def private_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(text)
    os.chmod(path, 0o600)


def initialize(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    keypath, certpath = root / 'identity.key', root / 'identity.pem'
    if keypath.exists() or certpath.exists():
        if not keypath.exists() or not certpath.exists():
            raise ValueError('Incomplete identity; do not replace a partially stored key')
        return fingerprint(certpath.read_text())
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'session-peer-69-device')])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-dt.timedelta(minutes=1)).not_valid_after(now+dt.timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False, key_agreement=False,
                key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH,
                                                ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    private_write(keypath, key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
    private_write(certpath, cert.public_bytes(serialization.Encoding.PEM).decode())
    return fingerprint(certpath.read_text())


def context(root, server, trusted, present=True):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    ctx.set_alpn_protocols(['session-peer-69-v1'])
    if not server:
        # Trust is the explicitly invited device certificate, not public DNS.
        ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_OPTIONAL if server else ssl.CERT_REQUIRED
    if trusted:
        ctx.load_verify_locations(cadata='\n'.join(trusted))
    if server or present:
        ctx.load_cert_chain(str(Path(root)/'identity.pem'), str(Path(root)/'identity.key'))
    if server:
        ctx.num_tickets = 0
    return ctx
