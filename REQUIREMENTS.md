# Requirements and Running Auto Browser

## Requirements (local run)

- Docker Engine with the Docker Compose v2 plugin (`docker compose`).
- Git (to clone the repo).
- Optional: GNU Make (for `make up`, `make doctor`, and `make down`).
- Optional: Python 3.10+ and pip (for `make lint` / `make test-local`).
- Optional: `jq` (for pretty-printing curl responses in examples).

## Quickstart (Docker Compose)

```bash
git clone https://github.com/LvcidPsyche/auto-browser.git
cd auto-browser
docker compose up --build
```

Optional setup:

```bash
cp .env.example .env
make doctor
```

Open:

- API docs: `http://127.0.0.1:8000/docs`
- Operator dashboard: `http://127.0.0.1:8000/dashboard`
- Visual takeover: `http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale`

All published ports bind to `127.0.0.1` by default.

## Stop the stack

```bash
docker compose down
```

## Codespaces

If you prefer a hosted setup, use GitHub Codespaces from the repo page. The stack boots automatically and the dashboard/noVNC ports will be forwarded.
