#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$#" -ne 1 ] || [ ! -d "$1" ]; then
  printf 'Usage: %s /absolute/path/to/nine-original-csvs\n' "$0" >&2
  exit 2
fi
source_dir="$(realpath "$1")"
export UV_CACHE_DIR="$PWD/.uv-cache"
mkdir -p data/processed/olist
profile="$(mktemp data/processed/olist/.schema-profile.XXXXXX)"
trap 'rm -f -- "$profile"' EXIT
uv run --locked python -m ingestion.schema_inspector "$source_dir" > "$profile"
mv -- "$profile" data/processed/olist/schema-profile.json
/usr/bin/time -f 'elapsed_seconds=%e peak_rss_kib=%M' \
  uv run --locked python -m etl.pipeline --source "$source_dir" --output data/processed/olist
