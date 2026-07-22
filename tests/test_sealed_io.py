import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "path_analysis"))
from sealed_io import SealBreachError, load_dev_feather, validate_dev_dataset


SEAL = pd.Timestamp("2025-09-01", tz="UTC")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frame(dates):
    return pd.DataFrame({
        "date": pd.DatetimeIndex(dates),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "volume": 10.0,
    })


def _write_dataset(root, dates):
    root.mkdir()
    candle = root / "BTC_USD-15m.feather"
    _frame(dates).to_feather(candle)
    manifest = {
        "schema_version": 1,
        "seal_ts": SEAL.isoformat(),
        "files": {
            candle.name: {
                "source_sha256": "synthetic-source",
                "dev_sha256": _sha(candle),
                "dev_rows": len(dates),
            }
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return candle


def test_valid_physical_dev_dataset_loads(tmp_path):
    root = tmp_path / "dev"
    candle = _write_dataset(
        root, pd.date_range("2025-08-31 22:00", periods=4, freq="15min", tz="UTC")
    )
    validate_dev_dataset(root, SEAL, verify_hashes=True)
    out = load_dev_feather(candle, SEAL)
    assert out["date"].max() < SEAL


def test_loader_refuses_raw_or_unmanifested_directory(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    candle = raw / "BTC_USD-15m.feather"
    _frame([pd.Timestamp("2025-08-31", tz="UTC")]).to_feather(candle)
    with pytest.raises(SealBreachError, match="manifest"):
        load_dev_feather(candle, SEAL)


def test_loader_rejects_manifested_file_containing_sealed_row(tmp_path):
    root = tmp_path / "dev"
    candle = _write_dataset(
        root,
        [pd.Timestamp("2025-08-31 23:45", tz="UTC"), SEAL],
    )
    # Keep the manifest hash valid so this exercises the timestamp tripwire,
    # not merely the tamper check.
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][candle.name]["dev_sha256"] = _sha(candle)
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(SealBreachError, match="at/after"):
        load_dev_feather(candle, SEAL)


def test_builder_materializes_only_preseal_rows_and_is_idempotent(tmp_path):
    from build_dev_dataset import build_dev_dataset

    source = tmp_path / "raw"
    source.mkdir()
    raw = source / "BTC_USD-15m.feather"
    _frame([
        pd.Timestamp("2025-08-31 23:30", tz="UTC"),
        pd.Timestamp("2025-08-31 23:45", tz="UTC"),
        SEAL,
        pd.Timestamp("2025-09-01 00:15", tz="UTC"),
    ]).to_feather(raw)
    dest = tmp_path / "dev"

    first = build_dev_dataset(source, dest, SEAL)
    first_hash = first["files"][raw.name]["dev_sha256"]
    second = build_dev_dataset(source, dest, SEAL)

    assert second["files"][raw.name]["dev_sha256"] == first_hash
    out = load_dev_feather(dest / raw.name, SEAL)
    assert list(out["date"]) == [
        pd.Timestamp("2025-08-31 23:30", tz="UTC"),
        pd.Timestamp("2025-08-31 23:45", tz="UTC"),
    ]
