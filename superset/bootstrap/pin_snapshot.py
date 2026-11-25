"""Resolve a validated publication and prepare local deployment state."""

import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from tempfile import NamedTemporaryFile

BI = Path(__file__).resolve().parents[1]
PUBLICATION = BI.parent / "data/processed/olist"


def read_json(path):
    return json.loads(path.read_bytes())


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    pointer = PUBLICATION / "latest.json"
    with pointer.open("rb") as file:
        manifest_bytes = file.read()
        manifest_timestamp = os.fstat(file.fileno()).st_mtime
    manifest = json.loads(manifest_bytes)
    version = manifest["version"]
    if not re.fullmatch(r"\d{8}T\d{12}Z-[a-f0-9]{8}", version):
        raise ValueError("Unexpected publication version")
    database = f"snapshots/{version}.duckdb"
    quality_path = f"quality/{version}.json"
    if manifest["database"] != database or manifest["quality_report"] != quality_path:
        raise ValueError("Unexpected published artifact paths")
    snapshot = PUBLICATION / database
    quality = read_json(PUBLICATION / quality_path)
    if (quality["version"] != version or not quality["passed"] or snapshot.is_symlink()
            or not snapshot.is_file() or snapshot.stat().st_mode & 0o222):
        raise ValueError("Expected a validated, immutable snapshot")
    receipt = {
        "version": version,
        "container_path": "/warehouse/" + database,
        "sha256": sha256(snapshot),
        "size_bytes": snapshot.stat().st_size,
        "publication_manifest_timestamp": manifest_timestamp,
        "quality": quality,
    }
    if pointer.read_bytes() != manifest_bytes:
        raise RuntimeError("The publication changed while it was being validated. Retry.")
    runtime = BI / ".runtime"
    runtime.mkdir(mode=0o755, exist_ok=True)
    with NamedTemporaryFile(dir=runtime, mode="w", delete=False, encoding="utf-8") as file:
        json.dump(receipt, file, indent=2)
        file.write("\n")
        os.fchmod(file.fileno(), 0o644)
    os.replace(file.name, runtime / "snapshot.json")

    env = BI / ".env"
    if not env.exists():
        fd = os.open(env, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(f"SUPERSET_SECRET_KEY={secrets.token_hex(48)}\n")
            file.write(f"POSTGRES_PASSWORD={secrets.token_hex(24)}\n")
            file.write("SUPERSET_ADMIN_USERNAME=retail_admin\n")
            file.write(f"SUPERSET_ADMIN_PASSWORD={secrets.token_hex(24)}\nSUPERSET_PORT=8088\n")
    if env.is_symlink() or env.stat().st_mode & 0o077:
        raise ValueError("Store .env as a regular file with mode 0600")
    print(f"Pinned {version} · SHA-256 {receipt['sha256']}")


if __name__ == "__main__":
    main()
