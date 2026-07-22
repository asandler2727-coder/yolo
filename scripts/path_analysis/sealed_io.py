"""Fail-closed I/O primitives for research data with a frozen holdout."""

import hashlib
import json
from pathlib import Path

import pandas as pd


class SealBreachError(RuntimeError):
    """Raised when a research path observes a candle at/after its seal."""


def validate_dev_dataset(data_dir, seal_ts, verify_hashes=True):
    """Validate the physical dev-only dataset and return its manifest."""
    data_dir = Path(data_dir)
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SealBreachError(f"dev-only manifest missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SealBreachError(f"invalid dev-only manifest: {manifest_path}") from exc

    if manifest.get("schema_version") != 1:
        raise SealBreachError("unsupported dev-only manifest schema")
    recorded_seal = pd.Timestamp(manifest.get("seal_ts"))
    if recorded_seal != pd.Timestamp(seal_ts):
        raise SealBreachError(
            f"dev-only manifest seal mismatch: {recorded_seal} != {seal_ts}"
        )
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise SealBreachError("dev-only manifest contains no candle files")

    physical = {p.name for p in data_dir.glob("*-15m.feather")}
    if physical != set(files):
        raise SealBreachError("dev-only manifest/file set mismatch")
    if verify_hashes:
        for name, record in files.items():
            if _sha256(data_dir / name) != record.get("dev_sha256"):
                raise SealBreachError(f"dev-only file hash mismatch: {name}")
    return manifest


def load_dev_feather(path, seal_ts):
    """Load one manifest-pinned physical dev file and trip on sealed rows."""
    path = Path(path)
    manifest = validate_dev_dataset(path.parent, seal_ts, verify_hashes=False)
    record = manifest["files"].get(path.name)
    if record is None:
        raise SealBreachError(f"file absent from dev-only manifest: {path.name}")
    if _sha256(path) != record.get("dev_sha256"):
        raise SealBreachError(f"dev-only file hash mismatch: {path.name}")

    frame = pd.read_feather(path)
    if "date" not in frame:
        raise SealBreachError(f"dev-only candle file lacks date column: {path.name}")
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    if len(frame) != record.get("dev_rows"):
        raise SealBreachError(f"dev-only row-count mismatch: {path.name}")
    if len(frame) and frame["date"].max() >= pd.Timestamp(seal_ts):
        raise SealBreachError(f"dev-only file contains candle at/after seal: {path.name}")
    return frame


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
