"""Local TLS identities; only public certificates cross device boundaries."""
import datetime as dt
import hashlib
import os
import stat
import tempfile
import fcntl
from pathlib import Path
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID


def fingerprint(pem):
    cert = x509.load_pem_x509_certificate(pem.encode())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def private_path(path, directory=False):
    path = Path(path)
    st = path.lstat()
    if (st.st_uid != os.getuid() or st.st_mode & 0o077
            or (not stat.S_ISDIR(st.st_mode) if directory else not stat.S_ISREG(st.st_mode))):
        raise ValueError('unsafe_private_path')


def private_read(path, limit=65536, *, systemd_credentials=False):
    path = Path(path)
    special = False
    if systemd_credentials and os.environ.get('CREDENTIALS_DIRECTORY'):
        directory = Path(os.environ['CREDENTIALS_DIRECTORY']).resolve()
        st = path.lstat()
        special = (str(directory).startswith('/run/credentials/')
                   and path.resolve().parent == directory
                   and stat.S_ISREG(st.st_mode) and st.st_uid == 0
                   and not st.st_mode & 0o227
                   and bool(os.statvfs(path).f_flag & os.ST_RDONLY))
    if not special:
        private_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as file:
        raw = file.read(limit+1)
    if len(raw) > limit:
        raise ValueError('private_file_too_large')
    return raw.decode()


def private_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        private_path(path)
    fd, temporary = tempfile.mkstemp(prefix='.session-peer-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def initialize(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_path(root, True)
    fd = os.open(root/'identity.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        private_path(root/'identity.lock')
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _initialize(root)


def _initialize(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_path(root, True)
    keypath, certpath = root / 'identity.key', root / 'identity.pem'
    if keypath.exists() or certpath.exists():
        if not keypath.exists() or not certpath.exists():
            raise ValueError('Incomplete identity; do not replace a partially stored key')
        private_path(keypath)
        certificate = private_read(certpath)
        key = serialization.load_pem_private_key(private_read(keypath).encode(), password=None)
        cert = x509.load_pem_x509_certificate(certificate.encode())
        if cert.public_key().public_numbers() != key.public_key().public_numbers():
            raise ValueError('identity_key_mismatch')
        return fingerprint(certificate)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'session-peer-device')])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-dt.timedelta(minutes=1)).not_valid_after(now+dt.timedelta(days=365))
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
    ctx.set_alpn_protocols(['session-peer-device-v1'])
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
