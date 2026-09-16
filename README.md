# CareRoute — Containerized

Multi-stage Docker build. The build stage installs dependencies into a virtualenv
with compilers available; the final stage copies only that virtualenv plus your
application code into a clean `python:3.12-slim` image. No compilers, no pip
cache, no `.git` in the shipped image. Runs as a non-root `app` user.

Verified: builds clean, serves on port 8000, healthcheck reports `healthy`,
final image 285MB. Compose stack starts healthy, and the dev overlay's live
reload was confirmed by editing a file and watching the response change
without a rebuild.

## One-time PATH setup

The Docker CLI on this machine ships inside Docker Desktop and is not on your
PATH. Add it once:

```bash
echo 'export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

Without this, `docker` is "command not found" — and using the full binary path
alone still fails, because the `docker-credential-desktop` helper must be on
PATH too.

## Dropping your real code in

1. Replace `app/main.py` (and add whatever modules you need) inside `app/`.
2. Put your real dependencies in `requirements.txt`.
3. Keep the ASGI app importable at `app.main:app`, or edit the final `CMD` in
   the Dockerfile to point at your actual entrypoint.

Everything else works unchanged.

## Run it (compose — the normal way)

```bash
docker compose up --build
```

Then in another terminal:

```bash
curl http://localhost:8000/health
```

## Stop and remove

```bash
docker compose down
```

## Live reload while you work

Mounts your local `app/` over the image's copy and restarts uvicorn on every
save, so you can edit code without rebuilding.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

## Follow logs

```bash
docker compose logs -f api
```

## Check status and health

```bash
docker compose ps
```

## Shell into the running container

```bash
docker compose exec api /bin/bash
```

## Adding a database later

`docker-compose.yml` has a commented-out Postgres service and the matching
`depends_on` block. Uncomment both, then `docker compose up --build`. The api
waits for Postgres to report healthy before starting, and `DATABASE_URL` is
already wired to the `db` hostname.

## Plain docker, without compose

```bash
docker build -t careroute:local .
```

```bash
docker run --rm -p 8000:8000 --name careroute careroute:local
```

## Rebuild from scratch (no cache)

```bash
docker compose build --no-cache
```

## Notes on the layer caching

`requirements.txt` is copied and installed *before* your source code is copied.
That ordering means editing your Python files reuses the cached dependency
layer, so rebuilds after a code change take about a second instead of
reinstalling every package.
