#!/usr/bin/env bash
# Run ON THE SERVER (not your Mac): pulls the latest code from GitHub, rebuilds and restarts the app.
set -euo pipefail
# Wrapped in a function so bash reads the whole script before git updates this file.
main() {
  cd "$(dirname "$0")"
  git fetch origin
  git reset --hard origin/master
  echo "Deploying $(git --no-pager log --oneline -1)"
  docker build -t truck-routing .
  docker rm -f truck-routing 2>/dev/null || true
  docker run -d --name truck-routing --restart unless-stopped -p 80:8000 \
    -e DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(openssl rand -hex 32)}" \
    -e DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-104.207.89.22,localhost}" \
    truck-routing
  echo "Done: http://104.207.89.22"
}
main "$@"
