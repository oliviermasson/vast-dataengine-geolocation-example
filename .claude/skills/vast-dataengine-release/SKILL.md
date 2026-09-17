---
name: vast-dataengine-release
description: Procedure to build, deploy, and publish a new release of this repository's "omgeoloc" VAST DataEngine function (EXIF/GPS geolocation into VastDB), and to check for secrets before any commit.
---

# Releasing the omgeoloc function (VAST DataEngine)

This skill describes the procedure to follow in this repository (`vast-dataengine-geolocation-example`) to:
1. build and publish a new version of the function,
2. verify secret hygiene before committing/pushing.

Refer to `README.md` (sections "Create the function on VAST DataEngine", "Ship a new release of the code", "Manual Docker push") and to `MAINTENANCE.md` for the full details; this file is only an operational cheat sheet for an agent.

## Before anything else: check for secrets

Never commit `config.yaml`, `config_localrun.yaml`, or `omgeoloc-secrets.yaml` (the real files, with real values). They're in `.gitignore`. Before a commit:

```bash
git status
git diff --cached -- config.yaml config_localrun.yaml omgeoloc-secrets.yaml
```

If any of these files shows up as staged, unstage it before continuing. Never introduce an internal IP / internal hostname / plaintext access-key / secret-key into a tracked file (`main.py`, `geolocation.py`, `README.md`, etc.) — use `X.X.X.X` / `xxxxxxxxx` like in the `*.example` files.

## Release steps

1. Edit `main.py` and/or `geolocation.py`.
2. Bump the `version` variable at the top of `main.py` (e.g. `v1.19` → `v1.20`).
3. Build and push the image:
   ```bash
   vastde functions build . --handlers main.py --image-tag vX.Y --push
   ```
   First verify with `vastde functions build --help` whether `--push` is really unavailable (it's been present since v5.5.0). If it's genuinely missing, build without `--push` and push manually with Docker instead (see README, "Manual Docker push" section) — get the real remote registry credentials via `vastde container-registries get <name>`, never reuse the local `127.0.0.1:<port>` `zarf-push` credentials that `vastde functions build` stages images through internally.
4. Publish the new function revision:
   ```bash
   vastde functions update omgeoloc \
     --container-registry <registry> \
     --artifact-source <image-repo>/omgeoloc \
     --image-tag vX.Y \
     --publish
   ```
5. Commit only the code (never the real config files):
   ```bash
   git add main.py geolocation.py
   git commit -m "Bump function to vX.Y"
   git tag vX.Y
   git push origin main --tags
   ```

## Notes

- The exact `vastde` commands (available flags) may vary depending on the CLI version installed on the machine — check `vastde functions build --help` / `vastde functions update --help` if a command fails.
- `vastde functions localrun . --config config_localrun.yaml --image-tag <tag> --port 8080` lets you test locally before publishing.
