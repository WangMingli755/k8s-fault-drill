#!/usr/bin/env python3
"""生成 ingress TLS 演练证书：CA、正常、错误域名、已过期。"""
import datetime as dt
import pathlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

OUT = pathlib.Path(__file__).resolve().parent


def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def save_key(k, name: str) -> None:
    (OUT / name).write_bytes(
        k.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )


def save_cert(c, name: str) -> None:
    (OUT / name).write_bytes(c.public_bytes(serialization.Encoding.PEM))


def make_cert(subject_cn: str, issuer_cert, issuer_key, san: str,
              not_before: dt.datetime, not_after: dt.datetime, is_ca: bool = False):
    k = key()
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_cert.subject if issuer_cert else subject)
        .public_key(k.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
    )
    if san:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False
        )
    cert = builder.sign(issuer_key or k, hashes.SHA256())
    return k, cert


def main() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    ca_key, ca_cert = make_cert(
        "training-lab-ca", None, None, "", now - dt.timedelta(days=1),
        now + dt.timedelta(days=365), is_ca=True,
    )
    save_key(ca_key, "ca.key")
    save_cert(ca_cert, "ca.crt")

    k, c = make_cert("lab-tls.training.local", ca_cert, ca_key, "lab-tls.training.local",
                     now - dt.timedelta(hours=1), now + dt.timedelta(days=30))
    save_key(k, "server.key")
    save_cert(c, "server.crt")

    k, c = make_cert("wrong.example.com", ca_cert, ca_key, "wrong.example.com",
                     now - dt.timedelta(hours=1), now + dt.timedelta(days=30))
    save_key(k, "wrong.key")
    save_cert(c, "wrong.crt")

    k, c = make_cert("lab-tls.training.local", ca_cert, ca_key, "lab-tls.training.local",
                     now - dt.timedelta(days=60), now - dt.timedelta(days=1))
    save_key(k, "expired.key")
    save_cert(c, "expired.crt")

    print(f"证书已生成: {OUT}")
    for n in ("ca.crt", "server.crt", "wrong.crt", "expired.crt"):
        cert = x509.load_pem_x509_certificate((OUT / n).read_bytes())
        print(f"  {n}: CN={cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value} "
              f"not_after={cert.not_valid_after_utc.isoformat()}")


if __name__ == "__main__":
    main()
