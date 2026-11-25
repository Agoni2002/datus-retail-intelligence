"""Versioned, immutable files and an atomically advanced publication manifest."""

import fcntl
import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path


def sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, payload):
    temp = path.with_name(f".{path.name}.tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    sync_directory(path.parent)


class Snapshots:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.manifest = self.directory / "latest.json"
        self.versions = self.directory / "snapshots"
        self.reports = self.directory / "quality"
        self.work = self.directory / ".work"

    @contextmanager
    def writer_lock(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / ".writer.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for directory in (self.versions, self.reports, self.work):
                directory.mkdir(exist_ok=True)
            yield

    def latest(self):
        if not self.manifest.exists():
            return None
        state = json.loads(self.manifest.read_text())
        if not (self.directory / state["database"]).is_file() or not (self.directory / state["quality_report"]).is_file():
            raise RuntimeError("Publication manifest refers to a missing database or quality report")
        return state

    def working_copy(self, previous, version):
        path = self.work / f"{version}.duckdb"
        if previous:
            shutil.copyfile(self.directory / previous["database"], path)
        return path

    def publish(self, working, report, state):
        db = self.versions / f"{report.version}.duckdb"
        report_path = self.reports / f"{report.version}.json"
        with working.open("rb") as stream:
            os.fchmod(stream.fileno(), 0o444)
            os.fsync(stream.fileno())
        # Hard link within the output filesystem avoids replacing an old version.
        os.link(working, db)
        sync_directory(self.versions)
        atomic_json(report_path, report.to_dict())
        published = state | {
            "version": report.version, "database": str(db.relative_to(self.directory)),
            "quality_report": str(report_path.relative_to(self.directory)),
        }
        atomic_json(self.manifest, published)
        return published
