"""Provision the local governed-credential pepper without printing its value."""

import argparse
import json
import os
from pathlib import Path
import secrets


def provision(path, force=False):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    descriptor = os.open(str(path), flags, 0o600)
    try:
        payload = json.dumps(
            {
                "schemaVersion": "memoryendpoints.credential_pepper.v1",
                "credentialPepper": secrets.token_urlsafe(48),
            },
            sort_keys=True,
        ).encode("utf-8")
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=".local-secrets/credential-pepper.json")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    provision(args.path, args.force)
    print("Governed credential pepper provisioned in protected local secret storage.")


if __name__ == "__main__":
    main()
