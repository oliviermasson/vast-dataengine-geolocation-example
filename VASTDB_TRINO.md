# VastDB: database setup and querying via Trino

This document covers two things that are deliberately kept out of `README.md`:

1. How to create the VastDB **bucket** (`omgeolocdb`), **schema** (`geoloc`) and **table** (`geoloc`) that this function writes to.
2. How to query that table interactively with the **VAST connector for Trino**.

> **The names `omgeolocdb` / `geoloc` / `geoloc` are just examples.** You are free to use your own bucket/schema/table names — just set `VASTDB_BUCKET` / `VASTDB_SCHEMA` / `VASTDB_TABLE` accordingly in `config.yaml` / `config_localrun.yaml` (see the main [`README.md`](README.md#configuration)). The one thing that **must not change** is the table's **column list — same names, same types** as below, since `main.py`'s `store_photo_metadata()` writes a row with this exact fixed shape and will fail on any mismatch.

## Table of contents

- [1. Creating the database, schema and table](#1-creating-the-database-schema-and-table)
- [2. Querying via the VAST connector for Trino](#2-querying-via-the-vast-connector-for-trino)
- [Official documentation](#official-documentation)

## 1. Creating the database, schema and table

### Prerequisites

- A VAST cluster user that:
  - has the **"Allow Create Bucket"** option enabled (User Management → Users → edit the user),
  - has an **S3 access key / secret key** generated for it (same "Create new key" button).
- Ideally, a dedicated **Virtual IP pool** for database access (recommended by VAST, not strictly required for a test setup).
- `pip install vastdb` (already in `requirements.txt`) if you create the table via Python, as done below.

### Step 1 — Create the database (VMS UI)

A "VAST Database" is, under the hood, an S3 bucket / Element Store view with the database capability enabled.

1. In the VMS web UI, go to **Database → VAST DB**.
2. Click **+ New Database**.
3. Fill in:
   - **Database Name**: e.g. `omgeolocdb` (must follow S3 bucket naming rules — lowercase, no underscores, etc.) — pick any name you want.
   - **Path**: where the underlying view is created.
   - **Policy name**: an S3 policy granting your user access.
   - **Database owner**: the user created/selected above.
4. Click **Create**.

### Step 2 — Add a schema

1. Select the database you just created in the database tree.
2. Click **+ Add Schema**.
3. Enter a schema name, e.g. `geoloc` (again, any name works).
4. Click **Create**.

### Step 3 — Create the `geoloc` table with the right columns

Table creation is most reliably done with the VastDB Python SDK, by defining an explicit [pyarrow](https://arrow.apache.org/docs/python/) schema. This mirrors exactly what `main.py`'s `store_photo_metadata()` expects:

```python
# create_table.py — run once to provision the table
import pyarrow as pa
import vastdb

session = vastdb.connect(
    endpoint="http://<vastdb-endpoint>",     # same value as VASTDB_ENDPOINT
    access="<vastdb-access-key>",             # same value as VASTDB_ACCESS_KEY
    secret="<vastdb-secret-key>",             # same value as VASTDB_SECRET_KEY
)

BUCKET = "omgeolocdb"   # <- rename freely, must match VASTDB_BUCKET
SCHEMA = "geoloc"       # <- rename freely, must match VASTDB_SCHEMA
TABLE = "geoloc"        # <- rename freely, must match VASTDB_TABLE

# Column names/types below must stay identical to what main.py writes.
COLUMNS = pa.schema([
    ("source_photo", pa.string()),   # s3://bucket/key of the photo, dedup key
    ("maker", pa.string()),          # camera make/model
    ("date_exif", pa.date32()),      # shot date
    ("width", pa.int32()),
    ("height", pa.int32()),
    ("gps_lat", pa.float64()),
    ("gps_lon", pa.float64()),
    ("location", pa.string()),       # "City, State, Country (Continent)"
    ("city", pa.string()),
    ("region", pa.string()),
    ("country", pa.string()),
    ("continent", pa.string()),
])

with session.transaction() as tx:
    bucket = tx.bucket(BUCKET)
    schema = bucket.schema(SCHEMA, fail_if_missing=False) or bucket.create_schema(SCHEMA)
    table = schema.create_table(TABLE, COLUMNS)
    print(f"Created table {BUCKET}/{SCHEMA}/{TABLE} with columns: {table.columns()}")
```

Run it once:

```bash
python create_table.py
```

### Step 4 — Point the function at it

If you used the example names as-is, nothing else to do — they match the defaults in `config.yaml.example` / `main.py`. If you renamed the bucket/schema/table, update `VASTDB_BUCKET` / `VASTDB_SCHEMA` / `VASTDB_TABLE` in your `config.yaml` and `config_localrun.yaml` (see [`README.md`](README.md#configuration)).

### Verifying the table

```python
with session.transaction() as tx:
    schema = tx.bucket("omgeolocdb").schema("geoloc")
    print(schema.tablenames())               # -> ['geoloc']
    print(schema.table("geoloc").columns())   # -> the 12 columns above
```

## 2. Querying via the VAST connector for Trino

[Trino](https://trino.io/) with the VAST connector lets you run interactive SQL against the `geoloc` table without writing any Python — handy to browse the geolocated photos or build a quick report.

### Compatibility

Pick the Trino/connector image version matching your VAST cluster version:

| Trino image tag | Compatible VAST cluster |
|---|---|
| 375 | 4.7+ |
| 420 | 5.0+ |
| 429 | 5.1+ |
| 443 | 5.2+ |
| 462 | 5.3+ |
| 475 | 5.4+ |

### Prerequisites

- Docker installed, with permission to start containers.
- A VAST identity policy granting database access, and an S3 access key/secret key for a user covered by that policy (same credentials as `VASTDB_ACCESS_KEY`/`VASTDB_SECRET_KEY` work fine).

### Configuration — `vast.properties`

Create a `vast.properties` file (replace the placeholders with your real endpoints and credentials — never commit this file, same rule as `config.yaml`/`omgeoloc-secrets.yaml`):

```properties
connector.name=vast
endpoint=http://X.X.X.1
data_endpoints=http://X.X.X.1,http://X.X.X.2,http://X.X.X.3,http://X.X.X.4,http://X.X.X.5,http://X.X.X.6
access_key_id=xxxxxxxxx
secret_access_key=xxxxxxxxx
region=us-east-1

num_of_splits=12
num_of_subsplits=4

vast.http-client.request-timeout=60m
vast.http-client.idle-timeout=60m

enable_custom_schema_separator=true
custom_schema_separator=|
expression_projection_pushdown=true
complex_predicate_pushdown=true
```

#### `endpoint` vs. `data_endpoints`

- **`endpoint`**: a single URL used for control-plane calls (listing schemas/tables, metadata).
- **`data_endpoints`**: a **comma-separated list of VIPs** used for the actual data-path reads once a query is split into tasks.

**Why list several `data_endpoints` instead of one:** a VAST cluster exposes its data path through a pool of Virtual IPs (VIPs), spread across the CNodes' NICs. If you only configure one VIP, every Trino worker hits that single IP — creating an avoidable bottleneck on one node, and a hard failure (until DNS/VIP failover kicks in) if that specific CNode goes down or is rebooted during an upgrade. Listing **all (or several) CNode VIPs** in `data_endpoints` lets the connector spread requests across them, so:
  - throughput scales with the number of CNodes actually participating instead of being capped by one node's NIC,
  - traffic isn't pinned to a node that might disappear (VIPs themselves can also move between CNodes on failover, but only helps if clients aren't hardcoded to a single one).

  The example above lists 6 VIPs, matching a 6-CNode cluster — adjust the list to the VIPs of your own cluster (`data_endpoints=http://<vip-1>,http://<vip-2>,...`).

#### Sizing `num_of_splits` / `num_of_subsplits`

- **`num_of_splits`**: how many parallel tasks Trino itself splits a scan into across the row-ID space of the table. VAST's own tuning guidance targets roughly **4 million rows per split**, and recommends a split count divisible by your number of Trino workers.
- **`num_of_subsplits`**: how many further sub-tasks each split is divided into **once it reaches a CNode**, to use that node's multiple cores. Recommended to be divisible by the number of cores per CNode.

The values above (`num_of_splits=12`, `num_of_subsplits=4`) are what a small lab cluster (6 CNodes) uses in practice — they're deliberately modest since a small/test table doesn't need the generic default of 64/10 splits. Tune both up as your cluster and table size grow; there's no universal correct value, size them for your own cluster and data volume.

### Running Trino

```bash
docker run \
  --name trino \
  -p 8080:8080 -d \
  -v ./vast.properties:/etc/trino/catalog/vast.properties:ro \
  --platform linux/amd64 \
  vastdataorg/trino-vast:429   # pick the tag matching your VAST cluster, see table above
```

Open a SQL shell in the running container:

```bash
docker exec -it trino trino
```

### Example queries against this project's table

The `enable_custom_schema_separator`/`custom_schema_separator=|` setting above lets you address `bucket|schema` as one catalog "schema" in Trino:

```sql
-- List schemas (bucket|schema pairs) known to the connector
SHOW SCHEMAS FROM vast;

-- Select the omgeolocdb bucket / geoloc schema (use your own names if renamed)
USE vast."omgeolocdb|geoloc";

-- List tables
SHOW TABLES;

-- Inspect the columns
SHOW COLUMNS FROM geoloc;

-- Browse recent photos with a known location
SELECT source_photo, date_exif, city, country, continent
FROM geoloc
WHERE city IS NOT NULL
ORDER BY date_exif DESC
LIMIT 20;

-- Count photos per country
SELECT country, count(*) AS photos
FROM geoloc
WHERE country IS NOT NULL
GROUP BY country
ORDER BY photos DESC;
```

## Official documentation

- Managing Databases (create a VastDB database/schema from the VMS UI): https://kb.vastdata.com/documentation/docs/managing-databases-4
- Configuring the VAST Cluster for Database Access: https://kb.vastdata.com/documentation/docs/configuring-the-vast-cluster-for-database-access-55-1
- VastDB Python SDK docs: https://vastdb-sdk.readthedocs.io/
- VastDB Python SDK source (GitHub): https://github.com/vast-data/vastdb_sdk
- Installing and Configuring the VAST Connector for Trino: https://kb.vastdata.com/documentation/docs/installing-and-configuring-the-vast-connector-for-trino
- VAST Trino Docker image: https://hub.docker.com/r/vastdataorg/trino-vast
- VAST DataEngine documentation: https://kb.vastdata.com/documentation/docs/vast-dataengine-55
