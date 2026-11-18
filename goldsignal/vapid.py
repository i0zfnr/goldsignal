import argparse
from base64 import urlsafe_b64encode
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


def generate(path):
    private = ec.generate_private_key(ec.SECP256R1())
    with path.open("xb") as file:
        file.write(private.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()))
    public = private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return urlsafe_b64encode(public).rstrip(b"=").decode()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Write a new Web Push private key and print its public key.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print("VAPID_PUBLIC_KEY=" + generate(args.path))
