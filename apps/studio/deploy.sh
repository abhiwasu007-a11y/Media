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
for V in AMW_SECRET_BFL_API_KEY AMW_SECRET_PIXABAY_API_KEY; do
  if ! grep -q "^$V=.\+" .env; then
    read -rsp "$V (Enter to skip): " X; echo
    [ -n "$X" ] && setvar "$V" "$X"; unset X
  fi
done
if grep -q '^CF_TUNNEL_TOKEN=.\+' .env; then setvar COMPOSE_PROFILES named; else setvar COMPOSE_PROFILES quick; fi
chmod 600 .env
mkdir -p data/jobs
[ -f ~/sample-001-seneca-job.zip ] && unzip -oq ~/sample-001-seneca-job.zip -d data/jobs/
chown -R 10001 data
docker compose --profile quick --profile named rm -sf tunnel tunnel-named >/dev/null 2>&1
docker compose up -d --build --remove-orphans --force-recreate
echo "== waiting for the app =="
for i in $(seq 30); do curl -sf http://127.0.0.1:8080/healthz >/dev/null && break; sleep 2; done
if curl -sf http://127.0.0.1:8080/healthz; then echo; echo "APP OK"; else
  echo "APP NOT UP. Logs:"; docker compose logs --tail 20 studio; exit 0; fi
echo "== phone link =="
PUB=$(grep '^AMW_PUBLIC_URL=' .env | cut -d= -f2-)
if grep -q '^COMPOSE_PROFILES=named' .env; then
  URL=$PUB
  [ -z "$URL" ] && echo "permanent tunnel on: set AMW_PUBLIC_URL in .env to have the link checked here"
else
  for i in $(seq 30); do
    URL=$(docker compose logs tunnel 2>/dev/null | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1)
    [ -n "$URL" ] && break; sleep 2
  done
  echo "(temporary link: it changes when the tunnel restarts)"
fi
if [ -n "$URL" ]; then
  echo "$URL"; sleep 10
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$URL/healthz")
  if [ "$CODE" = "200" ]; then echo "LINK OK (checked from the server)"; else
    echo "LINK NOT REACHABLE YET (HTTP $CODE). Tunnel log:"; docker compose logs --tail 15 tunnel tunnel-named 2>/dev/null; fi
fi
echo "user: owner   password: the one in $APP/.env"
