# Vast DataEngine - Geolocation Example

A [VAST DataEngine](https://kb.vastdata.com/documentation/docs/vast-dataengine-55) serverless function triggered when a photo is uploaded to an S3 bucket. It extracts the image's EXIF data (date, camera, dimensions, GPS coordinates), performs reverse geocoding (city, region, country, continent), and stores the result in a [VastDB](https://vastdata.com/vastdb) table.

> Educational example: it shows how to structure, build, deploy and evolve a VAST DataEngine function with the `vastde` CLI.

## Table of contents

- [How it works](#how-it-works)
- [Repository contents](#repository-contents)
- [⚠️ Security / secrets](#️-security--secrets)
- [Prerequisites](#prerequisites)
- [Get the project](#get-the-project)
- [Configuration](#configuration)
- [Deploy the pipeline: function, trigger & manifest](#deploy-the-pipeline-function-trigger--manifest)
- [Test locally](#test-locally)
- [Troubleshooting](#troubleshooting)
- [Ship a new release of the code](#ship-a-new-release-of-the-code)
- [Manual Docker push (without `--push`)](#manual-docker-push-without---push)
- [Uploading photos to the bucket](#uploading-photos-to-the-bucket)
- [VastDB table schema](#vastdb-table-schema)
- [Official documentation](#official-documentation)

> Setting up the VastDB bucket/schema/table from scratch, or querying it interactively with Trino? See the dedicated [`VASTDB_TRINO.md`](VASTDB_TRINO.md) guide.

## How it works

```
Photo upload (S3 bucket)
        │
        ▼  ("element" trigger on ObjectCreated:*)
VAST DataEngine function (main.py)
        │
        ├─ reads the image from S3 (boto3)
        ├─ extracts EXIF tags (exifread)
        ├─ reverse-geocodes the GPS coordinates (geolocation.py, reverse_geocode)
        └─ inserts a row into VastDB (vastdb / pyarrow)
```

`geolocation.py` holds the pure reverse-geocoding logic (no dependency on VAST DataEngine): Haversine distance, city/country/continent resolution from GPS coordinates, with distance thresholds to avoid returning a nonsensical city or country when the photo was taken over open sea or in a polar region.

`main.py` is the function handler: it reads the S3 event, extracts EXIF data, calls into `geolocation.py`, then writes the result to VastDB (deduplicated on `source_photo`).

## Repository contents

| File | Role |
|---|---|
| `main.py` | Function handler (`init` + `handler`) |
| `geolocation.py` | Reverse geocoding: GPS → city/region/country/continent |
| `project.toml` | Buildpack configuration (schema-version, build variables) |
| `requirements.txt` | Python dependencies |
| `constraints.txt` | Pip version constraints (opentelemetry) |
| `Aptfile` | Additional apt packages (empty here) |
| `customDeps` | Additional custom Python modules (empty here) |
| `config.yaml.example` | Template for the deployed function's non-secret environment variables |
| `config_localrun.yaml.example` | Template for the file used by `vastde functions localrun -c ...` |
| `omgeoloc-secrets.yaml.example` | Template for the secrets bundle (AWS/VastDB credentials) mounted under `/secrets` |
| `manifest.yaml.example` | Template for the pipeline manifest binding the trigger to the function (see [Deploy the pipeline](#deploy-the-pipeline-function-trigger--manifest)) |

The four `*.example` files must be copied **without the `.example` suffix** and filled in with your own values (see [Configuration](#configuration)). The filled-in copies must never be committed — they're listed in `.gitignore`.

## ⚠️ Security / secrets

The Python code (`main.py`, `geolocation.py`) contains **no hardcoded secrets**: AWS/VastDB credentials are read from files mounted under `/secrets`, or, failing that, from environment variables (the `read_secret` function), and endpoints also come from environment variables. That's why these two files can safely stay public as-is.

However, the original `config.yaml`, `config_localrun.yaml`, `omgeoloc-secrets.yaml` and `manifest.yaml` files contained **real values** (AWS and VastDB access/secret keys, an internal IP, an internal hostname, an internal Kubernetes cluster name). They have been removed from the public repository and replaced with `*.example` versions using dummy values (`X.X.X.X`, `xxxxxxxxx`). If you find these files locally, never commit them (they're listed in `.gitignore`).

## Prerequisites

On the machine that will build/deploy/test this function:

- **VAST DataEngine CLI (`vastde`)** installed and **configured** against your VAST DataEngine cluster (see [installation](#official-documentation)).
- **Docker** (used by `vastde functions build`/`localrun` to build and run the function's image).
- Access to an S3 (S3-compatible, exposed by VAST) bucket and a VastDB database, with the associated credentials.
- Python 3.12 locally, only if you want to run/test `geolocation.py` outside the container (the build already bundles its own Python runtime).

## Get the project

```bash
git clone https://github.com/oliviermasson/vast-dataengine-geolocation-example.git
cd vast-dataengine-geolocation-example
```

## Configuration

Copy the templates and fill them in with your own values:

```bash
cp config.yaml.example config.yaml
cp config_localrun.yaml.example config_localrun.yaml
cp omgeoloc-secrets.yaml.example omgeoloc-secrets.yaml
cp manifest.yaml.example manifest.yaml
```

- `config.yaml`: environment variables for the deployed function (S3 endpoint, VastDB endpoint, VastDB bucket/schema/table name). Credentials themselves are provided through the secret described in `omgeoloc-secrets.yaml` and mounted under `/secrets` by VAST DataEngine.
- `omgeoloc-secrets.yaml`: defines the secrets bundle (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `VASTDB_ACCESS_KEY`, `VASTDB_SECRET_KEY`) to create on the VAST DataEngine side and attach to the function/pipeline.
- `config_localrun.yaml`: an "all-in-one" file (endpoints + credentials in plain text) used only for local testing with `vastde functions localrun -c config_localrun.yaml`, since there's no `/secrets` mount locally.
- `manifest.yaml`: the pipeline manifest — wires the trigger to the function, and carries the same environment variables plus a reference to the secret bundle. Used once you deploy for real (see [Deploy the pipeline](#deploy-the-pipeline-function-trigger--manifest)).

## Deploy the pipeline: function, trigger & manifest

In VAST DataEngine, a running deployment is a **pipeline** that wires a **trigger** to one or more **function** revisions, plus the environment variables/secrets/resource limits it runs with. A pipeline is described by a `manifest.yaml` file. This project ships [`manifest.yaml.example`](manifest.yaml.example) as a working template — copy it to `manifest.yaml`, fill in your own values, and never commit the filled-in copy (same rule as the `config*.yaml`/`omgeoloc-secrets.yaml` files, see [Security / secrets](#️-security--secrets)).

These steps assume `vastde` is already installed (see [Prerequisites](#prerequisites)) and pointed at your cluster:

```bash
# Once per machine: configure the CLI
vastde config init
vastde config set --vms-url https://your-vast-cluster.example.com
vastde config set --username <your_user> --password <your_password> --tenant <your_tenant>
vastde config view
```

### 1. Build and register the function

From the project root:

```bash
# Build the function's image + push it to the configured registry
vastde functions build . --handlers main.py --image-tag v1.19 --push

# Register it as a VAST DataEngine function
vastde functions create \
  --name omgeoloc \
  --container-registry <your-registry-name-or-vrn> \
  --artifact-source <image-repo>/omgeoloc \
  --image-tag v1.19 \
  --publish
```

`<your-registry-name-or-vrn>` is a registry already declared on the VAST DataEngine side (`vastde container-registries list` to list, `vastde container-registries link` to add one). This produces a function VRN, e.g. `vast:dataengine:functions:omgeoloc`, at revision `1`.

### 2. Create the trigger

To have the pipeline fire automatically every time a photo is dropped into the S3 bucket:

```bash
vastde triggers create element \
  --name omgeoloc-bucket-trigger \
  --source-bucket <photos-bucket-name> \
  --event ObjectCreated:* \
  --name-suffix .jpg
```

This produces a trigger VRN, e.g. `vast:dataengine:triggers:omgeoloc-bucket-trigger`.

### 3. Fill in the pipeline manifest

Copy the template and edit it:

```bash
cp manifest.yaml.example manifest.yaml
```

[`manifest.yaml.example`](manifest.yaml.example) is a real, working manifest with placeholders for the infra-specific bits. Its blocks map directly to what you just created:

| Block | Role |
|---|---|
| `kubernetes_cluster_vrn` | The compute cluster to deploy on — list yours with `vastde compute-clusters list` |
| `manifest.triggers[]` | Aliases (`name`) pointing at the trigger VRN from step 2 |
| `manifest.function_deployments[]` | Aliases pointing at the function VRN + `revision` from step 1, plus autoscaling (`min/max_concurrency`, `autoscaling_rps_factor`) and resource limits (`min/max_cpu`, `min/max_memory`, `timeout`) |
| `manifest.links[]` | Wires a trigger alias (`source`) to a function alias (`destination`) through a broker `topic`, with delivery settings (`retries`, `events_order`) |
| `manifest.config.secrets[]` | Names of secret bundles to attach — must match the top-level key in a `--secret-file` (see step 4), e.g. `omgeoloc-vastdb-credentials` from `omgeoloc-secrets.yaml` |
| `manifest.config.environment_variables[]` | Same variables as `config.yaml`, but inlined in the manifest instead |

Update `revision` in `function_deployments[]` whenever you publish a new function revision (see [Ship a new release of the code](#ship-a-new-release-of-the-code)).

### 4. Deploy the pipeline (CLI)

```bash
vastde pipelines create \
  --name omgeoloc \
  --config @manifest.yaml \
  --secret-file omgeoloc-secrets.yaml \
  --deploy
```

`--secret-file` uploads `omgeoloc-secrets.yaml` and registers it under the secret name used as its top-level key (`omgeoloc-vastdb-credentials`), matching the reference in `manifest.config.secrets`. `--deploy` activates the pipeline immediately after creation.

Check it came up:

```bash
vastde pipelines get omgeoloc
vastde pipelines list
```

To apply a manifest change later (new function revision, new env var, resized resources), use the same manifest file with:

```bash
vastde pipelines update omgeoloc --config @manifest.yaml --secret-file omgeoloc-secrets.yaml
vastde pipelines deploy omgeoloc
```

### 5. Same thing via the VMS web UI

Every block of `manifest.yaml` has a direct equivalent in the DataEngine section of the VMS web interface — useful if you'd rather click through it than hand-edit YAML:

1. **Functions**: `DataEngine → Functions → + New Function`, pointing at the image you already built and pushed in step 1 (the build/push itself still needs Docker — the UI only registers an existing image, it doesn't build one).
2. **Triggers**: `DataEngine → Triggers → + New Trigger`, type *Element*, same source bucket / event / suffix as step 2.
3. **Pipelines**: `DataEngine → Pipelines → + New Pipeline`. Give it a name (`omgeoloc`), add the trigger and the function+revision from the steps above, draw the link between them and pick the broker topic, then fill in:
   - **Environment variables**: the same key/value pairs as `manifest.config.environment_variables` (or `config.yaml`).
   - **Secrets**: upload/select a secret named `omgeoloc-vastdb-credentials` with the same keys as `omgeoloc-secrets.yaml`.
   - **Resources**: concurrency, CPU, memory and timeout, matching `manifest.function_deployments[].resources`.
4. Click **Deploy** / **Activate**.

Exact menu labels can vary slightly between VMS versions, but the underlying object model (trigger, function revision, link/topic, resources, secrets, env vars) is identical to `manifest.yaml`.

## Test locally

```bash
# Local build (no push)
vastde functions build . --handlers main.py --image-tag dev

# Run the container locally with your test variables/secrets
vastde functions localrun . --config config_localrun.yaml --image-tag dev --port 9373

# In another terminal: send a test event
vastde functions invoke --generate-event --url http://localhost:9373/
```

The `--port` value just needs to be a **free port on your machine** — not already bound by another container or by any other process on the host. Beyond that, any port works, so pick whichever you like; `9373` is used above instead of the more common `8080` because `8080` is frequently already taken by something else on dev machines (another local service, another `localrun`, a proxy, etc.). Whichever port you choose, check it's actually free first:

```bash
# Nothing should be listening on the port yet
lsof -i :9373        # or: ss -ltnp | grep :9373

# And no container should already be bound to it
docker ps --filter "publish=9373"
```

If either command shows something, pick a different port.

## Troubleshooting

**Catch syntax errors before even building.** No need to wait for a full `vastde functions build` to find out you have a typo — a plain Python syntax check is instant:

```bash
python -m py_compile main.py
python -m py_compile geolocation.py
```

This only catches syntax errors (not logic bugs or missing imports at runtime), but it's a fast first check before spending time on a build.

**Inspect a running local container.** While `vastde functions localrun` is up, you can shell into the container to poke around — check that files landed where expected, that dependencies installed correctly, or manually run a snippet of Python:

```bash
docker ps                      # find the container ID/name for the running function
docker exec -it <containerID> /bin/sh   # or /bin/bash if the image has it
```

**Check which environment variables actually reached the container.** Useful when the function behaves as if a variable from `config.yaml`/`config_localrun.yaml` wasn't picked up:

```bash
docker inspect <containerID> --format '{{json .Config.Env}}' | jq
```

This prints every environment variable the container was started with — handy to confirm `S3_ENDPOINT_URL`, `VASTDB_ENDPOINT`, etc. (and, for a real deployment, that the `/secrets`-mounted credentials are where `read_secret()` expects them) actually made it in, rather than guessing from the logs.

## Ship a new release of the code

1. Edit `main.py` and/or `geolocation.py`.
2. Bump the `version` variable at the top of `main.py` (e.g. `v1.19` → `v1.20`) — it's logged on every init/handler call, which makes tracking production versions easier.
3. Rebuild and push the image with the new tag:

   ```bash
   vastde functions build . --handlers main.py --image-tag v1.20 --push
   ```

4. Update the function to point at the new image and publish the revision:

   ```bash
   vastde functions update omgeoloc \
     --container-registry <your-registry-name-or-vrn> \
     --artifact-source <image-repo>/omgeoloc \
     --image-tag v1.20 \
     --publish
   ```

   Without `--publish`, the command creates a new revision without making it active — useful for a canary/manual rollout.
5. Commit the code (never the real `config*.yaml`/`omgeoloc-secrets.yaml` files) and tag the release in Git:

   ```bash
   git add main.py geolocation.py
   git commit -m "Bump function to v1.20"
   git tag v1.20
   git push origin main --tags
   ```

## Manual Docker push (without `--push`)

**First, double-check `--push` is really unavailable** — run `vastde version` and `vastde functions build --help` on the machine you build from. `--push` is present on some CLI builds but not others even within the v5.5.0 line (confirmed missing on a real `v5.5.0-2144029` builder, confirmed present again on `v5.5.0-sp2`), so don't assume it from the version number alone — check `--help` every time.

Note that `vastde functions build` also touches Docker on its own even without `--push`: it uses [Zarf](https://zarf.dev/) internally to stage the image through a short-lived local registry (you may notice a `127.0.0.1:<port>` entry with a `zarf-push` user in `~/.docker/config.json` — that's this local staging step, not the real remote registry, and it's managed automatically). Don't reuse those credentials for anything else.

When `--push` **is** available, `vastde` authenticates to the real remote registry on your behalf using the registry credentials already declared on the VAST DataEngine side (via `vastde container-registries link`, normally done once by an admin) and your own `vastde config` session — you never need to know or type a registry username/password yourself.

Only if your CLI genuinely lacks `--push`, push manually with Docker:

```bash
# 1. Local build only (no --push)
vastde functions build . --handlers main.py --image-tag v1.20

# 2. Find the name/tag of the locally built image
docker images | grep omgeoloc

# 3. Get the real remote registry's credentials — do NOT reuse the local
#    127.0.0.1 zarf-push credentials mentioned above, they won't work here.
vastde container-registries get <your-registry-name-or-vrn>
#    (ask your VAST admin if this doesn't return a username/password/token)

# 4. Log in to that remote registry with the credentials from step 3
docker login <registry>.example.com

# 5. Re-tag the image with the remote registry path
docker tag omgeoloc:v1.20 <registry>.example.com/<image-repo>/omgeoloc:v1.20

# 6. Push the image
docker push <registry>.example.com/<image-repo>/omgeoloc:v1.20

# 7. Then create/update the function as usual
vastde functions update omgeoloc \
  --container-registry <your-registry-name-or-vrn> \
  --artifact-source <image-repo>/omgeoloc \
  --image-tag v1.20 \
  --publish
```

## Uploading photos to the bucket

Replace `<endpoint>`, `<bucket>`, `<access-key>` and `<secret-key>` with your own values (the ones from your real `config.yaml`/`omgeoloc-secrets.yaml`, never the ones from the `.example` files).

### With `s3cmd`

`~/.s3cfg` (excerpt):

```ini
[default]
access_key = <access-key>
secret_key = <secret-key>
host_base = <endpoint>          # e.g. s3.example.com (without http(s)://)
host_bucket = <endpoint>
use_https = True                # False if the endpoint is http://
signature_v2 = False
```

Upload:

```bash
s3cmd put photo.jpg s3://<bucket>/incoming/photo.jpg
s3cmd put ./photos/*.jpg s3://<bucket>/incoming/ --recursive
```

### With `aws s3` (AWS CLI)

```bash
export AWS_ACCESS_KEY_ID=<access-key>
export AWS_SECRET_ACCESS_KEY=<secret-key>

aws s3 --endpoint-url <endpoint> cp photo.jpg s3://<bucket>/incoming/photo.jpg
aws s3 --endpoint-url <endpoint> sync ./photos s3://<bucket>/incoming/
```

Tip: to avoid repeating `--endpoint-url`, you can declare a dedicated profile in `~/.aws/config` with `endpoint_url = <endpoint>` (requires a recent AWS CLI version).

### With S3 Browser (Windows GUI client)

1. **Accounts → Add New Account**.
2. Account type: *S3 Compatible Storage*.
3. **REST Endpoint**: `<endpoint>` (uncheck "Use secure transfer (SSL/TLS)" if the endpoint is `http://`).
4. **Access Key ID** / **Secret Access Key**: your credentials.
5. Once connected, select the `<bucket>` bucket, open/create the `incoming/` folder, then drag & drop your photos to trigger the function.

## VastDB table schema

The function inserts one row per photo into the VastDB table (`VASTDB_BUCKET` / `VASTDB_SCHEMA` / `VASTDB_TABLE`), deduplicated on `source_photo`:

| Column | Type | Description |
|---|---|---|
| `source_photo` | string | S3 URI of the photo (`s3://bucket/key`), dedup key |
| `maker` | string | Camera make/model (EXIF `Make`/`Model`) |
| `date_exif` | date32 | Shot date (EXIF `DateTimeOriginal`/`DateTime`) |
| `width` / `height` | int32 | Image dimensions |
| `gps_lat` / `gps_lon` | float64 | Decimal GPS coordinates |
| `location` | string | Human-readable "City, State, Country (Continent)" summary |
| `city` | string | Nearest city (if within a reasonable radius) |
| `region` | string | State/region |
| `country` | string | Country |
| `continent` | string | Continent |

For step-by-step instructions to create this bucket/schema/table (or your own equivalent, as long as the columns above stay identical) and to query it interactively with Trino, see [`VASTDB_TRINO.md`](VASTDB_TRINO.md).

## Official documentation

- VAST DataEngine CLI (`vastde`): https://github.com/vast-data/dataengine-cli
- CLI releases / binaries: https://github.com/vast-data/dataengine-cli/releases
- Full command reference: https://github.com/vast-data/dataengine-cli/blob/main/docs/references/commands/vastde.md
- VAST DataEngine documentation (VAST knowledge base): https://kb.vastdata.com/documentation/docs/vast-dataengine-55

See also [`MAINTENANCE.md`](MAINTENANCE.md) for this repository's security/release checklist.
