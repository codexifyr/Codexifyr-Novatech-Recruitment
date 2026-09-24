#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

command -v node >/dev/null || { echo "Node.js is required: https://nodejs.org"; exit 1; }
command -v npm >/dev/null || { echo "npm is required"; exit 1; }
command -v python3 >/dev/null || { echo "Python 3.12 is required"; exit 1; }
node -e "const [major,minor]=process.versions.node.split('.').map(Number);process.exit(major>22||(major===22&&minor>=12)?0:1)" || { echo "Node.js 22.12 or newer is required"; exit 1; }

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env. Add Supabase, n8n and Gmail values before live integration."
fi

python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install --disable-pip-version-check -r backend/requirements.txt
(cd frontend && npm install)

export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:8000/api/v1}"

(cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --env-file ../.env) &
backend_pid=$!
(cd frontend && npm run dev) &
frontend_pid=$!
trap 'kill "$backend_pid" "$frontend_pid" 2>/dev/null || true' EXIT INT TERM

echo "NovaTech is starting at http://localhost:3000"
wait
