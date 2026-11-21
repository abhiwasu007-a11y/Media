#!/usr/bin/env bash
# One-shot install / update of AMW Studio on the server. Safe to re-run: keeps .env and data/.
# Never exits the calling shell on an error (no `set -e`), prints what it found instead.
APP=/opt/amw-studio
BRANCH=${BRANCH:-ccr-b1e90a39-0g1b1l}
mkdir -p "$APP" && cd "$APP" || exit 0
echo "== last log lines (if an old container exists) =="
docker compose logs --tail 5 studio 2>/dev/null | tail -5
echo "== fetching code ($BRANCH) =="
rm -rf /tmp/amw-media
if git clone -q -b "$BRANCH" --depth 1 https://github.com/abhiwasu007-a11y/Media.git /tmp/amw-media; then
  cp -r /tmp/amw-media/apps/studio/. "$APP"/ && rm -rf /tmp/amw-media
else
  echo "git clone failed: check the network"; exit 0
fi
[ -f .env ] || cp .env.example .env
setvar() {  # write NAME=value without sed, so any character in the value is safe
  grep -v "^$1=" .env > .env.new; printf '%s=%s\n' "$1" "$2" >> .env.new; mv .env.new .env
}
if ! grep -q '^AMW_DASHBOARD_PASSWORD=..........' .env; then
  read -rsp "Dashboard password (letters and numbers, at least 10): " P; echo
  setvar AMW_DASHBOARD_PASSWORD "$P"; unset P
fi
if ! grep -q '^AMW_SECRET_ANTHROPIC_API_KEY=sk-' .env; then
  read -rsp "Anthropic API key (Enter to skip for now): " K; echo
  [ -n "$K" ] && setvar AMW_SECRET_ANTHROPIC_API_KEY "$K"; unset K
fi
chmod 600 .env
mkdir -p data/jobs
[ -f ~/sample-001-seneca-job.zip ] && unzip -oq ~/sample-001-seneca-job.zip -d data/jobs/
chown -R 10001 data
docker compose up -d --build --remove-orphans
echo "== waiting for the app =="
for i in $(seq 30); do curl -sf http://127.0.0.1:8080/healthz >/dev/null && break; sleep 2; done
if curl -sf http://127.0.0.1:8080/healthz; then echo; echo "APP OK"; else
  echo "APP NOT UP. Logs:"; docker compose logs --tail 20 studio; exit 0; fi
echo "== phone link =="
for i in $(seq 30); do
  URL=$(docker compose logs tunnel 2>/dev/null | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1)
  [ -n "$URL" ] && break; sleep 2
done
echo "${URL:-no link yet: run  docker compose logs tunnel | grep trycloudflare}"
echo "user: owner   password: the one in $APP/.env"
