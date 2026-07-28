#!/usr/bin/env python3
"""Publish the pre-built SQLite database as a GitHub Release asset.

Run this AFTER refreshing the data locally (`python refresh_data.py`). It:

  1. Computes the database's SHA-256 and writes a `.sha256` sidecar next to it.
  2. If the GitHub CLI (`gh`) is installed and authenticated, creates the fixed
     `data` release if needed and uploads BOTH files, replacing the previous
     copies (`--clobber`). The download URL stays constant, so Render's build
     command never changes.
  3. If `gh` is unavailable, prints step-by-step instructions to do the upload
     through the GitHub web UI, including the exact URL the build expects.

Usage
-----
    python scripts/publish_db.py            # sidecar + upload (or instructions)
    python scripts/publish_db.py --sidecar-only   # just (re)write the .sha256
"""
import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
try:
    from app.config import DB_PATH  # type: ignore
except Exception:  # pragma: no cover
    DB_PATH = _REPO_ROOT / "data" / "michigan_pesticides.sqlite"

TAG = "data"
REPO = "tbuttaflocka/michigan-pesticide-map"
ASSET_URL = (
    f"https://github.com/{REPO}/releases/download/{TAG}/{DB_PATH.name}"
)


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 256), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _write_sidecar(db: Path, digest: str) -> Path:
    sidecar = db.with_name(db.name + ".sha256")
    # sha256sum format so `sha256sum -c` and fetch_db.py both accept it.
    sidecar.write_text(f"{digest}  {db.name}\n", encoding="utf-8")
    return sidecar


def _gh_release_exists() -> bool:
    result = subprocess.run(
        ["gh", "release", "view", TAG, "--repo", REPO],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _manual_instructions(db: Path, sidecar: Path, digest: str) -> None:
    size_mb = db.stat().st_size / (1024 * 1024)
    print(
        "\n"
        "==================================================================\n"
        " gh CLI not found - upload the database manually (one-time setup,\n"
        " then just re-attach on each refresh).\n"
        "==================================================================\n"
        f"\nFiles ready to upload (in {db.parent}):\n"
        f"  - {db.name}          ({size_mb:.1f} MB)\n"
        f"  - {sidecar.name}   (SHA-256 sidecar)\n"
        f"\nSHA-256: {digest}\n"
        "\nFIRST TIME (create the release):\n"
        f"  1. Go to https://github.com/{REPO}/releases/new\n"
        f"  2. In 'Choose a tag', type:  {TAG}   then click "
        "'Create new tag: data on publish'.\n"
        "  3. Title it e.g. 'Prebuilt database'.\n"
        f"  4. Drag BOTH files ({db.name} and {sidecar.name}) into the\n"
        "     'Attach binaries' box.\n"
        "  5. Click 'Publish release'.\n"
        "\nEVERY REFRESH AFTER THAT (replace the asset):\n"
        f"  1. Go to https://github.com/{REPO}/releases/tag/{TAG}\n"
        "  2. Click the pencil (Edit).\n"
        f"  3. Delete the old {db.name} and {sidecar.name} assets, then drag\n"
        "     the new ones in. Click 'Update release'.\n"
        "\nThe build downloads from this fixed URL (never changes):\n"
        f"  {ASSET_URL}\n"
        "\nTIP: install the GitHub CLI (https://cli.github.com) and run this\n"
        "     script again to make future uploads a single command.\n"
        "==================================================================\n"
    )


def _gh_upload(db: Path, sidecar: Path) -> None:
    if not _gh_release_exists():
        print(f"[publish_db] creating release '{TAG}'...")
        subprocess.run(
            [
                "gh", "release", "create", TAG,
                "--repo", REPO,
                "--title", "Prebuilt database",
                "--notes", "Pre-built SQLite database, replaced on each data refresh.",
                str(db), str(sidecar),
            ],
            check=True,
        )
    else:
        print(f"[publish_db] uploading assets to existing release '{TAG}'...")
        subprocess.run(
            [
                "gh", "release", "upload", TAG,
                "--repo", REPO,
                "--clobber",
                str(db), str(sidecar),
            ],
            check=True,
        )
    print(f"[publish_db] done. Asset URL: {ASSET_URL}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sidecar-only",
        action="store_true",
        help="Only (re)write the .sha256 sidecar; do not upload.",
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(
            f"[publish_db] ERROR: database not found at {DB_PATH}. "
            "Run `python refresh_data.py` first.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[publish_db] hashing {DB_PATH.name} ...")
    digest = _sha256(DB_PATH)
    sidecar = _write_sidecar(DB_PATH, digest)
    print(f"[publish_db] sha256 = {digest}")
    print(f"[publish_db] wrote {sidecar}")

    if args.sidecar_only:
        return

    if shutil.which("gh"):
        try:
            _gh_upload(DB_PATH, sidecar)
        except subprocess.CalledProcessError as exc:
            print(
                f"[publish_db] ERROR: gh upload failed ({exc}). "
                "Falling back to manual instructions below.",
                file=sys.stderr,
            )
            _manual_instructions(DB_PATH, sidecar, digest)
            sys.exit(1)
    else:
        _manual_instructions(DB_PATH, sidecar, digest)


if __name__ == "__main__":
    main()
