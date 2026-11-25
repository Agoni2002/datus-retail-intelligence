"""File-level change detection and per-source watermarks for full CSV extracts."""

from ingestion.contract import SOURCES
from ingestion.olist_loader import load_table


def read_watermarks(conn):
    return dict(conn.execute("SELECT source_name, sha256 FROM control.source_watermark").fetchall())


def apply_extract(conn, directory, hashes):
    previous = read_watermarks(conn)
    changed = [name for name, sha in hashes.items() if previous.get(name) != sha]
    for name in changed:
        load_table(conn, directory, name)
    return changed


def record_watermarks(conn, changed, hashes, version):
    for name in changed:
        dates = SOURCES[name].newest
        watermark = f"max(greatest({', '.join(dates)}))" if dates else "NULL::TIMESTAMP"
        event_at = conn.execute(f"SELECT {watermark} FROM stg_{name}").fetchone()[0]
        count = conn.execute(f"SELECT count(*) FROM ods.{name}").fetchone()[0]
        conn.execute("""
            INSERT INTO control.source_watermark VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_name) DO UPDATE SET
                sha256 = excluded.sha256, source_rows = excluded.source_rows,
                event_watermark = greatest(source_watermark.event_watermark, excluded.event_watermark),
                last_changed_version = excluded.last_changed_version
        """, [name, hashes[name], count, event_at, version])
