#!/usr/bin/env bash
# Runs ON the server over SSH (see .github/workflows/deploy.yml). Updates the
# checkout, installs dependencies if they changed, applies the new .env if one
# was uploaded, restarts the service and verifies it came up.
#
# Never touches data/ (database, backups, OAuth tokens): data/ is gitignored, so
# `git reset --hard` leaves it alone, and `git clean` below only removes
# untracked leftovers and explicitly excludes data/, .env, .env.bak, .venv. Fails loudly (non-zero exit) on
# any problem so the Actions job goes red.
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/PyxeeTB}"
SERVICE="${SERVICE:-pyxeetb}"
BRANCH="${BRANCH:-main}"
NEW_ENV="/tmp/pyxeetb-new.env"

cd "$APP_DIR" || { echo "ERROR: $APP_DIR does not exist"; exit 1; }
[ -d .git ] || { echo "ERROR: $APP_DIR is not a git checkout"; exit 1; }
[ -d data ] || { echo "ERROR: $APP_DIR/data is missing — refusing to deploy over a half-set-up install"; exit 1; }

echo "== data/ before: $(du -sk data | cut -f1) KiB, $(find data -type f | wc -l) files"

echo "== updating $BRANCH"
old_rev="$(git rev-parse HEAD)"
git fetch --quiet origin "$BRANCH" </dev/null
git reset --hard "origin/$BRANCH"
git clean -fd -e data -e .env -e .env.bak -e .venv -e logs
new_rev="$(git rev-parse HEAD)"
echo "   $old_rev -> $new_rev"

if [ -f "$NEW_ENV" ]; then
  echo "== replacing .env (DEPLOY_ENV secret); previous kept as .env.bak"
  if [ -f .env ]; then cp -p .env .env.bak && chmod 600 .env.bak; fi
  install -m 600 "$NEW_ENV" .env
  rm -f "$NEW_ENV"
else
  echo "== .env left as it is (no DEPLOY_ENV secret)"
fi

if [ ! -d .venv ]; then
  echo "== creating virtualenv"
  python3 -m venv .venv
  need_deps=1
elif [ "$old_rev" != "$new_rev" ] && ! git diff --quiet "$old_rev" "$new_rev" -- requirements.txt; then
  need_deps=1
else
  need_deps=0
fi
if [ "$need_deps" = 1 ]; then
  echo "== installing requirements"
  timeout 240 .venv/bin/pip install --quiet -r requirements.txt </dev/null
else
  echo "== requirements unchanged"
fi

echo "== config check"
# Validates .env and imports the new code. A failure here stops the deploy BEFORE
# the running service is touched.
if ! .venv/bin/python bot.py --check-config </dev/null; then
  echo "ERROR: config check failed with the new code/.env — not restarting"
  exit 1
fi

if grep -Eq '^TWITCH_PUBLIC_BASE_URL=.+' .env 2>/dev/null; then
  echo "NOTICE: .env sets TWITCH_PUBLIC_BASE_URL — !commands uses that instead of the GitHub Pages default. Remove the line to use Pages."
fi

echo "== restarting $SERVICE"
sudo -n systemctl restart "$SERVICE" || { echo "ERROR: systemctl restart failed (is passwordless sudo set for it? see README)"; exit 1; }
sleep 5
if ! systemctl is-active --quiet "$SERVICE"; then
  echo "ERROR: $SERVICE is not active after restart"
  sudo -n journalctl -u "$SERVICE" -n 40 --no-pager || true
  exit 1
fi
echo "== $SERVICE is active"
echo "== data/ after:  $(du -sk data | cut -f1) KiB, $(find data -type f | wc -l) files"
