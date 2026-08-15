from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
MANIFEST_PATH = FIXTURES / "sdk-parity-v0.1.0.manifest.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_contract_fixture(manifest_path: Path, canonical_path: Path | None = None) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot = manifest_path.parent / manifest["file"]
    actual_digest = sha256(snapshot)
    if actual_digest != manifest["sha256"]:
        raise ValueError(
            f"Vendored fixture digest mismatch: expected {manifest['sha256']}, got {actual_digest}"
        )

    source = manifest["source"]
    if (
        not isinstance(source.get("commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}", source["commit"]) is None
    ):
        raise ValueError("Canonical source commit must be a full Git SHA")

    fixture = json.loads(snapshot.read_text(encoding="utf-8"))
    if fixture["contract"] != manifest["contract"] or fixture["version"] != manifest["version"]:
        raise ValueError("Vendored fixture identity does not match its manifest")

    if canonical_path is not None:
        canonical = canonical_path.resolve()
        if not canonical.is_file():
            raise ValueError(f"Canonical fixture does not exist: {canonical}")
        canonical_digest = sha256(canonical)
        if canonical_digest != actual_digest or canonical.read_bytes() != snapshot.read_bytes():
            raise ValueError(
                "Vendored fixture differs from the supplied sdk-core canonical fixture"
            )

    return actual_digest


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the vendored SDK contract fixture")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST_PATH,
        help="Manifest to verify; defaults to the repository's vendored fixture manifest",
    )
    parser.add_argument(
        "--canonical",
        type=Path,
        help="Optional local path to the sdk-core canonical fixture for byte comparison",
    )
    args = parser.parse_args()

    try:
        actual_digest = verify_contract_fixture(args.manifest, args.canonical)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    print(f"{manifest['contract']} {manifest['version']} verified ({actual_digest})")


if __name__ == "__main__":
    main()
