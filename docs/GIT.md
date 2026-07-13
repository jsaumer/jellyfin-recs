# Staging this in your own private Git

This repo is structured to be treated like your other container apps: private
repo, secrets kept out of Git, deployed from the tracked `deploy/docker-compose.yaml`.

## What's tracked vs. ignored

**Committed (safe):** all source, `Dockerfile`, `deploy/docker-compose.yaml`,
`deploy/compose.local.yml`, `deploy/entrypoint.sh`, `.env.example`, `history.example.txt`,
`Makefile`, tests, docs.

**Ignored (never committed — see `.gitignore`):**
- `.env` and any secrets/tokens
- `data/` (runtime recs, approvals, seed marker)
- your real `history.txt` and `jellyfin_recommendations.md` (these are private
  seed data mounted at runtime, not app code)
- library JSON exports (your media inventory stays private)
- Python/OS/editor cruft

The `.env.example` and `history.example.txt` ARE tracked, so a fresh clone shows
the shape of what's needed without leaking anything real.

## Versioning & releasing

This repo uses [Semantic Versioning](https://semver.org). The current version
lives in the `VERSION` file, is surfaced in the dashboard header and the
`/api/recommendations` response, and is baked into the image at build. Changes
are recorded in `CHANGELOG.md` (Keep a Changelog format).

**How a release becomes a deployable image:** pushing a `v*.*.*` git tag triggers
the `.github/workflows/release.yml` Action, which builds the container and
publishes it to **GHCR** (`ghcr.io/jsaumer/jellyfin-recs`) tagged with the
version (e.g. `0.1.0`, `0.1`, and `latest`). No secrets to configure — it uses
the repo's built-in `GITHUB_TOKEN`.

Cut a release:
```bash
make release-minor        # 0.1.0 -> 0.2.0  (or release-patch / release-major)
# edit CHANGELOG.md: move Unreleased items under the new version + date
git add VERSION CHANGELOG.md
git commit -m "Release v0.2.0"
make tag                  # creates the annotated v0.2.0 tag
git push && git push --tags
```
Pushing the tag kicks off the build. Watch it under the repo's **Actions** tab;
when it's green, `ghcr.io/jsaumer/jellyfin-recs:0.2.0` exists.

**Pinning the version your swarm runs:** `deploy/docker-compose.yaml` references
`ghcr.io/jsaumer/jellyfin-recs:0.1.0`. Bump that tag to the new version (or set
the `IMAGE` env var in Komodo) and redeploy. Because the compose pins an exact
version rather than `latest`, deploys are reproducible — you always know what's
running.

**First-time GHCR notes:**
- The published package is **private** by default, matching the repo. Your swarm
  nodes need to authenticate to pull it. On each node (or in your Komodo registry
  config), log in once:
  ```bash
  echo $GHCR_PAT | docker login ghcr.io -u jsaumer --password-stdin
  ```
  where `GHCR_PAT` is a GitHub personal access token with `read:packages`. If you
  deploy the stack by hand, add `--with-registry-auth` so Swarm distributes the
  credential to all nodes.
- Alternatively, make the package public in its GHCR settings and no auth is
  needed to pull.

## First push

The repo is already initialized with an initial commit tagged `v0.1.0` on the
`main` branch. Just add your remote and push:

```bash
cd jellyfin-recs
# Create an EMPTY private repo on GitHub first (no README/license), then:
git remote add origin git@github.com:you/jellyfin-recs.git
git push -u origin main
git push origin v0.1.0        # push the release tag too
```

If you're starting from the zip (no `.git` yet), initialize first:
```bash
git init && git add . && git commit -m "Initial release v0.1.0" && git branch -M main
git tag -a v0.1.0 -m "Release v0.1.0"
```

Confirm the ignores held before pushing anything sensitive:
```bash
git status --ignored        # .env, data/, real seed files should show as ignored
git ls-files | grep -E '\.env$|history\.txt$|jellyfin_(movies|shows|cartoons)' \
  && echo "WARNING: private file staged!" || echo "clean"
```

## Where secrets live (not in Git)

Same as your other stacks: Komodo stages the `.env` / injects the environment
at deploy time. Git only holds `.env.example` as documentation. Nothing in the
repo contains a real key.

## Deploy flow (matches your other apps)

The tracked `deploy/docker-compose.yaml` is the source of truth. Typical loop:

```bash
make build                 # docker build -t jellyfin-recs:latest .
make push IMAGE=...        # if you use a registry your swarm pulls from
make deploy                # docker stack deploy -c deploy/docker-compose.yaml jellyfin-recs
make logs                  # follow it
```

Or, if Komodo deploys from the Git repo directly, just push to `main` and let
Komodo pull `deploy/docker-compose.yaml` and redeploy — the same GitOps pattern as your other
services. The image reference in `deploy/docker-compose.yaml` (`${IMAGE:-jellyfin-recs:latest}`)
lets you pin a registry tag via env without editing the file.

## CI

`.github/workflows/ci.yml` (and a `.gitea/workflows/` copy) run lint + smoke
tests on every push — no secrets required, since the tests use fake data and
never touch live services. This catches regressions before they reach a deploy.

## Updating the running service after a change

```bash
make build && make redeploy      # rebuild image, force rolling update
```
`update_config: order: stop-first` in `deploy/docker-compose.yaml` releases the NFS mount
cleanly before the new task starts.

## Handling the private seed data

Because `jellyfin_recommendations.md` and `history.txt` are gitignored, they
live only on the NFS path, not in the repo:
```
/mnt/nfs/container/jellyfin-recs/data/jellyfin_recommendations.md
/mnt/nfs/container/jellyfin-recs/data/history.txt
```
Seed them there once (see DOCKER.md). After first boot the app maintains its own
state in that same dir, so the master file becomes optional going forward.
