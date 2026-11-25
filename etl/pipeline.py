"""Build, validate and publish a retail warehouse from a complete Olist extract."""

import argparse
import hashlib
import json
import os
import shutil
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import duckdb

from etl.config import ROOT, Settings
from etl.incremental import apply_extract, read_watermarks, record_watermarks
from etl.reconciliation import reconcile
from etl.snapshot import Snapshots, atomic_json
from ingestion.contract import SOURCES, source_filename
from ingestion.olist_loader import source_hashes
from quality.checks import stage, validate_sources
from quality.reports import QualityFailure, Report

SQL_FILES = tuple(sorted((ROOT / "warehouse").glob("*/*.sql"), key=lambda p: p.name))


def model_signature(settings):
    sha = hashlib.sha256(json.dumps(asdict(settings), default=str, sort_keys=True).encode())
    paths = [*SQL_FILES, ROOT / "metrics/calculations.sql"]
    for folder in ("etl", "quality", "ingestion"):
        paths.extend((ROOT / folder).glob("*.py"))
    for path in sorted(paths):
        sha.update(str(path.relative_to(ROOT)).encode())
        sha.update(path.read_bytes())
    return sha.hexdigest()


class PipelineFailure(RuntimeError):
    pass


def run(source: Path, output: Path, settings: Settings | None = None):
    settings = settings or Settings.load(ROOT / "configs/warehouse.yml")
    source = source.resolve()
    snapshots = Snapshots(output)
    with snapshots.writer_lock():
        previous = snapshots.latest()
        version = f"{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}-{uuid4().hex[:8]}"
        report = Report(version)
        working = snapshots.work / f"{version}.duckdb"
        inputs = snapshots.work / f"{version}-inputs"
        phase = "source preflight"
        try:
            hashes = source_hashes(source)
            signature = model_signature(settings)
            if previous and previous["source_sha256"] == hashes and previous["model_signature"] == signature:
                return previous | {"outcome": "unchanged"}

            # Copy only changed inputs. Recheck the whole extract before publishing
            # to detect edits while this invocation was reading it.
            phase = "copy changed inputs"
            inputs.mkdir()
            previous_hashes = previous["source_sha256"] if previous else {}
            for name in SOURCES:
                if hashes[name] != previous_hashes.get(name):
                    filename = source_filename(name)
                    shutil.copyfile(source / filename, inputs / filename)
                    with (inputs / filename).open("rb") as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() != hashes[name]:
                            raise ValueError(f"{name}: source changed during ingest")
            phase = "ODS ingestion"
            snapshots.working_copy(previous, version)
            with closing(duckdb.connect(str(working), config={
                "memory_limit": settings.memory_limit, "threads": str(settings.threads),
                "temp_directory": str(snapshots.work / f"{version}-spill"),
            })) as conn:
                conn.execute("BEGIN")
                conn.execute(SQL_FILES[0].read_text())
                if read_watermarks(conn) != previous_hashes:
                    raise ValueError("Snapshot database and manifest watermarks disagree")
                changed = apply_extract(conn, inputs, hashes)
                phase = "typed staging"
                stage(conn, report)
                report.require_pass()
                phase = "source validation"
                validate_sources(conn, report, settings)
                report.require_pass()
                settings.prepare_sql(conn)
                for path in SQL_FILES[1:]:
                    phase = f"warehouse SQL {path.name}"
                    conn.execute(path.read_text())
                phase = "reconciliation"
                reconcile(conn, report, settings)
                report.require_pass()
                record_watermarks(conn, changed, hashes, version)
                conn.execute("COMMIT")
                conn.execute("CHECKPOINT")
            phase = "source verification"
            if hashes != source_hashes(source):
                raise ValueError("Source extract changed during the run")
            phase = "publication"
            state = snapshots.publish(working, report, {
                "source_sha256": hashes, "model_signature": signature, "changed_sources": changed,
                "previous_version": previous["version"] if previous else None,
            })
            return state | {"outcome": "published"}
        except Exception as error:
            # Do not include DuckDB's offending CSV record in the report or CLI.
            if not isinstance(error, QualityFailure):
                report.add("pipeline.failure", 1, detail=type(error).__name__)
                report.add("pipeline.failed_phase", 1, detail=phase)
            failure_path = snapshots.reports / f"{version}.failed.json"
            atomic_json(failure_path, report.to_dict())
            summary = str(error) if isinstance(error, QualityFailure) else type(error).__name__
            raise PipelineFailure(f"Build failed ({summary}). Quality report at {failure_path}") from error
        finally:
            working.unlink(missing_ok=True)
            working.with_suffix(".duckdb.wal").unlink(missing_ok=True)
            shutil.rmtree(inputs, ignore_errors=True)
            shutil.rmtree(snapshots.work / f"{version}-spill", ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(os.getenv("OLIST_SOURCE_DIR", ROOT / "data/raw")))
    parser.add_argument("--output", type=Path, default=Path(os.getenv("RETAIL_OUTPUT_DIR", ROOT / "data/processed")))
    parser.add_argument("--config", type=Path, default=ROOT / "configs/warehouse.yml")
    args = parser.parse_args()
    try:
        result = run(args.source, args.output, Settings.load(args.config))
    except (PipelineFailure, ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
