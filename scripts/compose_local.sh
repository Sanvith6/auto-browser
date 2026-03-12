#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  while IFS= read -r line; do
    [[ -z "$line" || "${line#\#}" != "$line" || "$line" != *=* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    export "$key=$value"
  done < .env
fi

exec docker compose "$@"
