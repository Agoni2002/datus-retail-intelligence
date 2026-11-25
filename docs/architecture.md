# Warehouse architecture and publication

```mermaid
flowchart LR
    A[Complete Olist CSV extract] --> B[Header validation and source hashes]
    B --> C[ODS text tables]
    C --> D[Typed staging and deduplication]
    D --> E[DWD facts and dimensions]
    E --> F[DWS rollups]
    F --> G[ADS serving tables]
    G --> H[Quality and reconciliation gate]
    H --> I[Immutable versioned DuckDB]
    I --> J[Atomic latest.json]
    J --> K[Read-only readers]
```

## Incremental loading

Each invocation receives an authoritative full CSV for every source. It hashes the bytes and replaces only ODS tables whose input changed. It then rebuilds typed staging and dependent warehouse layers in one transaction. This recomputation handles corrected and removed rows, retroactive dimensions, multiple snapshots of the same extract, and late events older than the high water mark. There is no row-level CDC and the model does not maintain slowly changing dimension history.

`control.source_watermark` records the last accepted file hash, ODS row count, version, and monotonic maximum observed event timestamp where the source exposes one. It is diagnostic, since Olist lacks a reliable source-wide modification timestamp. Changed bytes govern reloading and the watermark table stays inside the transaction. A signature of runtime settings and transformation code also forces a rebuild when semantics change. An unchanged invocation returns the existing version without creating a second snapshot.

A project-local writer lock serializes invocations per output directory. A candidate builds from a writable copy of the last published file, separate from the file opened by readers. Changed inputs are copied and verified against their original hashes, and the extract is checked again before publication. Supply completed, quiescent extracts when handing files to ETL.

## Publication and recovery

A version uses a UTC timestamp and a random suffix. The pipeline runs all error-severity checks, commits, checkpoints, and closes DuckDB. It marks the closed file read-only, publishes it under `snapshots/<version>.duckdb`, and writes `quality/<version>.json`. Atomically replacing `latest.json` makes the pair visible to consumers. The database, reports, and manifest are within one local filesystem. Permission bits supplement the reader's explicit DuckDB read-only connection.

The manifest contains relative paths, source hashes, the prior version, and changed-source names. Consumers resolve it once per run or connection pool and open the versioned file. A previous reader can retain its older snapshot while another run advances the pointer. Read-only mounts and DuckDB read-only connections are appropriate for services.

On a failed build, `quality/<version>.failed.json` records the failed gates, and the previous pointer and watermarks remain the reference for the retry. A crash after publishing the immutable files and before advancing the pointer can leave an unreferenced version, which readers ignore. Crashes can also leave files under `.work/`. Retain old versions until readers are drained. Operators can later prune unreferenced artifacts under the same writer lock. Disk planning must cover a working copy, spill space, retained snapshots, and any temporary input copies.

Moving this protocol to replicated or object storage would require a publication design suited to that store. It currently relies on local Linux file locks, atomic rename, and filesystem sync.
