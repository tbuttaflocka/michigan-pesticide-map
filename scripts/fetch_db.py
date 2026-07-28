#!/usr/bin/env python3
"""Download the pre-built SQLite database from its GitHub Release asset.

The database (data/michigan_pesticides.sqlite, ~90 MB) is too large to commit to
git, so it lives as a Release asset under a fixed tag (`data`) and is fetched at
build time on Render — and once, on demand, for local development.

Usage
-----
    python scripts/fetch_db.py               # always (re)download, verify, replace
    python scripts/fetch_db.py --if-missing  # download only if the DB is absent
    python scripts/fetch_db.py --force       # alias for the default (always)

Behaviour
---------
* Downloads to a temp file, verifies it, then atomically moves it into place, so
  a partial download never clobbers a good database.
* Verification: the file must be at least MIN_BYTES, and — if a `.sha256` sidecar
  asset is published alongside — its SHA-256 must match. A truncated download,
  an HTML error page, or a corrupt transfer all fail the check.
* Exits non-zero and prints to stderr on ANY failure, so the Render build stops
  loudly instead of deploying a broken app with a missing/partial database.

Configuration (env overrides, all optional)
-------------------------------------------
    DB_RELEASE_URL          Full URL to the database asset.
    DB_RELEASE_SHA256_URL   Full URL to the SHA-256 sidecar (defaults to
                            DB_RELEASE_URL + ".sha256").
"""
import argparse
import hashlib
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

# --- Where the database must land ------------------------------------------
# Import the app's own DB_PATH so this script and the app can never disagree
# about the location. Fall back to the conventional path if the package can't
# be imported (e.g. run in isolation), so the script still works standalone.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
try:
    from app.config import DB_PATH  # type: ignore
except Exception:  # pragma: no cover - defensive fallback
    DB_PATH = _REPO_ROOT / "data" / "michigan_pesticides.sqlite"

# --- Release location -------------------------------------------------------
# Fixed tag `data`: the asset is REPLACED on each data refresh, so this URL is
# stable forever and the build command never has to change.
_DEFAULT_URL = (
    "https://github.com/tbuttaflocka/michigan-pesticide-map"
    "/releases/download/data/michigan_pesticides.sqlite"
)
DB_URL = os.environ.get("DB_RELEASE_URL", _DEFAULT_URL)
SHA256_URL = os.environ.get("DB_RELEASE_SHA256_URL", DB_URL + ".sha256")

# Sanity floor. The DB is ~90 MB and only grows; anything under this is a
# truncated transfer or an error page masquerading as the file.
MIN_BYTES = 50 * 1024 * 1024

_UA = {"User-Agent": "michigan-pesticide-map-fetch-db/1.0"}


def _log(msg: str) -> None:
    print(f"[fetch_db] {msg}", flush=True)


def _die(msg: str) -> "None":
    print(f"[fetch_db] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def _fetch_expected_sha256() -> "str | None":
    """Return the published SHA-256, or None if no sidecar is available."""
    try:
        req = urllib.request.Request(SHA256_URL, headers=_UA)
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            _log("no .sha256 sidecar published; verifying by size only")
            return None
        _log(f"could not fetch checksum ({exc}); verifying by size only")
        return None
    except urllib.error.URLError as exc:
        _log(f"could not fetch checksum ({exc}); verifying by size only")
        return None
    # Accept either a bare hash or the `sha256sum` format: "<hash>  <filename>".
    token = text.split()[0] if text else ""
    if len(token) == 64 and all(c in "0123456789abcdefABCDEF" for c in token):
        return token.lower()
    _log("checksum sidecar was malformed; verifying by size only")
    return None


def _download(dest: Path) -> "tuple[int, str]":
    """Stream the DB to `dest`, returning (bytes_written, sha256_hexdigest)."""
    hasher = hashlib.sha256()
    written = 0
    req = urllib.request.Request(DB_URL, headers=_UA)
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            fh.write(chunk)
            hasher.update(chunk)
            written += len(chunk)
    return written, hasher.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--if-missing",
        action="store_true",
        help="Skip the download when a plausibly-sized DB already exists.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Always download (the default); kept for explicitness.",
    )
    args = parser.parse_args()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if args.if_missing and DB_PATH.exists():
        size = DB_PATH.stat().st_size
        if size >= MIN_BYTES:
            _log(f"database already present ({size:,} bytes) at {DB_PATH}; skipping.")
            return
        _log(f"existing database looks truncated ({size:,} bytes); re-downloading.")

    expected = _fetch_expected_sha256()

    _log(f"downloading {DB_URL}")
    _log(f"        ->  {DB_PATH}")

    # Temp file in the same directory so os.replace() is atomic (same filesystem).
    fd, tmp_name = tempfile.mkstemp(
        dir=str(DB_PATH.parent), prefix=".michigan_pesticides.", suffix=".download"
    )
    os.close(fd)
    tmp = Path(tmp_name)

    try:
        try:
            written, actual = _download(tmp)
        except (urllib.error.URLError, OSError) as exc:
            _die(f"download failed: {exc}")

        if written < MIN_BYTES:
            _die(
                f"downloaded file is too small ({written:,} bytes, expected "
                f">= {MIN_BYTES:,}). The asset is likely missing or the URL "
                f"returned an error page. URL: {DB_URL}"
            )

        if expected is not None and actual != expected:
            _die(
                "checksum mismatch - download is corrupt or the sidecar is "
                f"stale.\n  expected sha256: {expected}\n  actual   sha256: {actual}"
            )

        os.replace(tmp, DB_PATH)  # atomic swap into place
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass

    verified = "sha256 verified" if expected is not None else "size verified"
    _log(f"done: {written:,} bytes, {verified}.")


if __name__ == "__main__":
    main()
