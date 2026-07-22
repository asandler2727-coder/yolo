#!/usr/bin/env python3
"""Provision physical pre-seal Arrow files for the Family B dev replay.

The mixed source files are scanned with an Arrow predicate. Only the filtered
pre-seal table is written to the destination; pandas is never used here.
Phase-0 never calls this builder automatically.
"""

import argparse
import json
import os
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.ipc as ipc

from sealed_io import SealBreachError, _sha256


DEFAULT_SOURCE = Path("user_data/data/kraken")
DEFAULT_DEST = Path("user_data/data/kraken-dev-before-2025-09-01")
DEFAULT_SEAL = pd.Timestamp("2025-09-01", tz="UTC")


def build_dev_dataset(source_dir, dest_dir, seal_ts=DEFAULT_SEAL):
    source_dir = Path(source_dir).resolve()
    dest_dir = Path(dest_dir).resolve()
    seal_ts = pd.Timestamp(seal_ts)
    if source_dir == dest_dir:
        raise ValueError("source and dev-only destination must differ")
    sources = sorted(source_dir.glob("*-15m.feather"))
    if not sources:
        raise FileNotFoundError(f"no source candle files in {source_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)

    prior = {}
    manifest_path = dest_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            old = json.loads(manifest_path.read_text())
            if old.get("seal_ts") == seal_ts.isoformat():
                prior = old.get("files", {})
        except json.JSONDecodeError:
            prior = {}

    expected_names = {p.name for p in sources}
    stale = {p.name for p in dest_dir.glob("*-15m.feather")} - expected_names
    if stale:
        raise SealBreachError(
            "dev-only destination has stale files; inspect manually: "
            + ", ".join(sorted(stale)[:10])
        )

    records = {}
    arrow_seal = pa.scalar(
        seal_ts.to_pydatetime(), type=pa.timestamp("ms", tz="UTC")
    )
    for source in sources:
        source_hash = _sha256(source)
        dest = dest_dir / source.name
        old_record = prior.get(source.name, {})
        if (
            dest.is_file()
            and old_record.get("source_sha256") == source_hash
            and old_record.get("dev_sha256") == _sha256(dest)
        ):
            records[source.name] = old_record
            continue

        dataset = ds.dataset(str(source), format="ipc")
        if "date" not in dataset.schema.names:
            raise SealBreachError(f"source lacks date column: {source.name}")
        table = dataset.to_table(filter=ds.field("date") < arrow_seal)
        if table.num_rows and pc.max(table["date"]).as_py() >= seal_ts.to_pydatetime():
            raise SealBreachError(f"Arrow filter admitted sealed row: {source.name}")

        temp = dest.with_suffix(dest.suffix + ".tmp")
        with pa.OSFile(str(temp), "wb") as sink:
            with ipc.new_file(sink, table.schema) as writer:
                writer.write_table(table)
        os.replace(temp, dest)
        records[source.name] = {
            "source_sha256": source_hash,
            "dev_sha256": _sha256(dest),
            "dev_rows": table.num_rows,
        }

    manifest = {
        "schema_version": 1,
        "seal_ts": seal_ts.isoformat(),
        "source_dir": str(source_dir),
        "files": records,
    }
    temp_manifest = manifest_path.with_suffix(".json.tmp")
    temp_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(temp_manifest, manifest_path)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--seal", default=DEFAULT_SEAL.isoformat())
    args = parser.parse_args()
    manifest = build_dev_dataset(args.source, args.dest, pd.Timestamp(args.seal))
    print(
        f"Built/validated {len(manifest['files'])} physical dev-only files "
        f"before {manifest['seal_ts']}"
    )


if __name__ == "__main__":
    main()
