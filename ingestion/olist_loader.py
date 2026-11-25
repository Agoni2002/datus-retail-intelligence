"""Strict headers and lossless ODS loads from the published Olist CSV layout."""

import csv
import hashlib
from pathlib import Path

from ingestion.contract import SOURCES, identifier, source_filename


class SourceError(ValueError):
    pass


def csv_header(path: Path, name: str) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        header = next(csv.reader(file), [])
    expected = set(SOURCES[name].columns)
    if len(set(header)) != len(header) or set(header) != expected:
        raise SourceError(
            f"{name}: header drift. Missing {sorted(expected - set(header))}; "
            f"unexpected {sorted(set(header) - expected)}; duplicate header: {len(set(header)) != len(header)}"
        )
    return header


def source_hashes(directory: Path) -> dict[str, str]:
    result = {}
    for name in SOURCES:
        path = directory / source_filename(name)
        csv_header(path, name)
        with path.open("rb") as file:
            result[name] = hashlib.file_digest(file, "sha256").hexdigest()
    return result


def load_table(conn, directory: Path, name: str) -> None:
    path = directory / source_filename(name)
    header = csv_header(path, name)
    columns = ", ".join(map(identifier, SOURCES[name].columns))
    # Explicit column schema permits header-only CSVs and avoids data-dependent
    # type inference or delimiter/quote guessing on small partitions.
    csv_types = {column: "VARCHAR" for column in header}
    conn.execute(
        f"""CREATE OR REPLACE TABLE ods.{name} AS
            SELECT {columns}
            FROM read_csv(?, columns=?, header=true, delim=',', quote='"',
                          escape='"', strict_mode=true, null_padding=false)""",
        [str(path), csv_types],
    )
