# CareRoute — Containerized

Multi-stage Docker build. The build stage installs dependencies into a virtualenv
with compilers available; the final stage copies only that virtualenv plus your
application code into a clean `python:3.12-slim` image. No compilers, no pip
cache, no `.git` in the shipped image. Runs as a non-root `app` user.

Verified: builds clean, serves on port 8000, healthcheck reports `healthy`,
final image 285MB.

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

## Build

```bash
docker build -t careroute:local .
```

## Run

```bash
docker run --rm -p 8000:8000 --name careroute careroute:local
```

Then in another terminal:

```bash
curl http://localhost:8000/health
```

## Run in the background

```bash
docker run -d -p 8000:8000 --name careroute careroute:local
```

## Follow logs

```bash
docker logs -f careroute
```

## Check health status

```bash
docker inspect --format '{{.State.Health.Status}}' careroute
```

## Shell into the running container

```bash
docker exec -it careroute /bin/bash
```

## Stop and remove

```bash
docker rm -f careroute
```

## Rebuild from scratch (no cache)

```bash
docker build --no-cache -t careroute:local .
```

## Notes on the layer caching

`requirements.txt` is copied and installed *before* your source code is copied.
That ordering means editing your Python files reuses the cached dependency
layer, so rebuilds after a code change take about a second instead of
reinstalling every package.
