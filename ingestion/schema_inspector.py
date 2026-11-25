"""Inspect original CSVs without building or publishing a warehouse."""

import argparse
import json
from pathlib import Path

import duckdb

from ingestion.contract import (
    OPTIONAL_RELATIONSHIPS, REAL, RELATIONSHIPS, SOURCES, TEXT, identifier, text_value, typed_value,
)
from ingestion.olist_loader import load_table


def inspect(directory: Path) -> dict:
    result = {"tables": {}, "candidate_relationships": []}
    with duckdb.connect(config={"memory_limit": "512MB", "threads": "2"}) as conn:
        conn.execute("CREATE SCHEMA ods")
        for name, source in SOURCES.items():
            load_table(conn, directory, name)
            stats = []
            count_columns = ", ".join(f"count({identifier(c)})" for c in source.columns)
            count, *non_null = conn.execute(f"SELECT count(*), {count_columns} FROM ods.{name}").fetchone()
            for (column, expected), present in zip(source.columns.items(), non_null, strict=True):
                expression = typed_value(column, expected)
                bad = f"{text_value(column)} IS NOT NULL AND ({expression}) IS NULL"
                if expected == REAL:
                    bad = f"({bad}) OR NOT isfinite({expression})"
                invalid = 0 if expected == TEXT else conn.execute(
                    f"SELECT count(*) FROM ods.{name} WHERE {bad}"
                ).fetchone()[0]
                stats.append({"name": column, "ods_type": "VARCHAR", "expected_type": expected,
                              "null_ratio": (count - present) / count if count else None, "invalid_casts": invalid})
            keys = ", ".join(map(identifier, source.key))
            duplicates = conn.execute(f"""
                SELECT count(*), coalesce(sum(n - 1), 0) FROM
                (SELECT count(*) n FROM ods.{name} GROUP BY {keys} HAVING count(*) > 1)
            """).fetchone()
            result["tables"][name] = {"rows": count, "columns": stats, "candidate_key": list(source.key),
                                      "duplicate_key_groups": duplicates[0], "duplicate_rows": duplicates[1]}
        for source, column, target, target_column in RELATIONSHIPS + OPTIONAL_RELATIONSHIPS:
            child_key = typed_value(column, SOURCES[source].columns[column])
            parent_key = typed_value(target_column, SOURCES[target].columns[target_column])
            orphans = conn.execute(f"""
                WITH child AS (SELECT {child_key} AS key FROM ods.{source}),
                     parent AS (SELECT {parent_key} AS key FROM ods.{target})
                SELECT count(*) FROM child ANTI JOIN parent USING (key) WHERE child.key IS NOT NULL
            """).fetchone()[0]
            result["candidate_relationships"].append({"from": f"{source}.{column}", "to": f"{target}.{target_column}",
                                                       "unmatched_nonnull_rows": orphans})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.source), indent=2))


if __name__ == "__main__":
    main()
