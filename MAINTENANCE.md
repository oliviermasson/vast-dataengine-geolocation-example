# Repository maintenance

Short checklist for anyone (human or Claude Code agent) working on this repository.

## Before every commit / push

- [ ] `git status`: make sure none of these files is tracked/staged: `config.yaml`, `config_localrun.yaml`, `omgeoloc-secrets.yaml`, `manifest.yaml` (they're in `.gitignore`, but an accidental `git add -f` is still possible).
- [ ] Never paste an internal IP, an internal hostname, or an access/secret key directly into `main.py`, `geolocation.py`, `README.md`, or any other tracked file. If an example is needed, use `X.X.X.X` for an IP and `xxxxxxxxx` for a key (see the `*.example` files).
- [ ] If one of the `*.example` files needs to change shape (e.g. a new env var), mirror the change in the corresponding real file AND in `README.md`.

## Releasing a new version of the function

See the ["Ship a new release of the code"](README.md#ship-a-new-release-of-the-code) section of the README. Summary:

1. Edit `main.py` / `geolocation.py`.
2. Bump the `version` variable in `main.py`.
3. `vastde functions build . --handlers main.py --image-tag vX.Y --push` (or manual Docker build+push if `--push` is unavailable, see README).
4. `vastde functions update omgeoloc --image-tag vX.Y --publish`.
5. Git commit + tag (`git tag vX.Y`) + push.

## Secret rotation

The credentials that were present in the old `config_localrun.yaml` and `omgeoloc-secrets.yaml` files (before they were removed from Git tracking) should be treated as potentially exposed if they were ever pushed to any repository, even a private one. If in doubt, regenerate:

- the AWS S3 access/secret key on the VAST side,
- the VastDB access/secret key on the VAST side,

then update only the local, untracked copies (`config_localrun.yaml`, `omgeoloc-secrets.yaml`) and the secret deployed on VAST DataEngine.

## Files that must never be committed

| File | Contains |
|---|---|
| `config.yaml` | S3 endpoint, VastDB endpoint (internal infra) |
| `config_localrun.yaml` | Endpoints + AWS & VastDB access/secret keys in plain text |
| `omgeoloc-secrets.yaml` | AWS & VastDB access/secret keys in plain text |
| `manifest.yaml` | Internal Kubernetes cluster name, internal endpoint/IP (in its inlined environment variables) |

Each of these four files has a tracked `*.example` counterpart that serves as documentation/template.
