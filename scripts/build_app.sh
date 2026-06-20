#!/usr/bin/env bash
#
# Build a double-clickable macOS .app bundle for Tintin's AI Chess Analysis.
#
#   ./scripts/build_app.sh
#
# Produces  dist/Tintin's AI Chess Analysis.app  — drag it to /Applications and double-click.
#
# This is "Option A": a thin wrapper bundle. The .app embeds a read-only copy of the project
# under Contents/Resources/repo and ships a launcher that, on first run, installs uv + Stockfish
# (idempotent), builds the Python environment in a WRITABLE support dir (so the bundle itself
# stays immutable), then serves the board in app mode. Closing the browser tab quits it
# (app-liveness watchdog), exactly like the .command launcher.
#
# Not self-contained like a PyInstaller build: it still needs the network on first run to fetch
# uv + Python + Stockfish, and the in-browser chat still needs the user's own `claude` CLI.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

APP_NAME="Tintin's AI Chess Analysis"
BUNDLE_ID="com.thedarktintin.chessanalysis"
VERSION="1.0"

# Build the bundle at the repo root so it's easy to find / double-click (gitignored).
DIST="$REPO_ROOT"
APP="$DIST/$APP_NAME.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RES="$CONTENTS/Resources"
REPO_IN_APP="$RES/repo"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$1"; }
info() { printf '\033[34m›\033[0m %s\n' "$1"; }

bold "Building $APP_NAME.app"

# 1) Clean + scaffold the bundle layout. -----------------------------------------------
# Once a .app has been launched, macOS tags it with `com.apple.provenance` and App Management
# protection blocks Terminal from deleting/overwriting its contents (EPERM on rm). Renaming the
# bundle to a NON-.app path is a parent-dir op that's still allowed, and the renamed dir is no
# longer treated as an app, so it can then be removed. So: rename-out-of-the-way, then delete.
if [ -e "$APP" ]; then
  info "Removing previous bundle…"
  OLD="$DIST/.old-$$.tmp"
  if mv "$APP" "$OLD" 2>/dev/null && rm -rf "$OLD" 2>/dev/null; then
    ok "Previous bundle removed"
  else
    rm -rf "$OLD" 2>/dev/null || true
    echo "ERROR: couldn't remove the existing bundle at:" >&2
    echo "  $APP" >&2
    echo "macOS App Management protection is blocking it. Either:" >&2
    echo "  • drag '$APP_NAME.app' to the Trash in Finder and re-run this script, or" >&2
    echo "  • grant your terminal 'App Management' permission in" >&2
    echo "    System Settings → Privacy & Security → App Management, then re-run." >&2
    exit 1
  fi
fi
mkdir -p "$MACOS" "$RES" "$REPO_IN_APP"

# 2) Copy the project in, excluding dev/local/generated junk. ---------------------------
# We need: server/, frontend/, scripts/, pyproject.toml, uv.lock. We deliberately drop the
# venv, git, caches, local data, and the dist dir we're writing into.
info "Copying project into the bundle…"
rsync -a \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude '.chess-review/' \
  --exclude '.pytest_cache/' \
  --exclude '.mypy_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '__pycache__/' \
  --exclude '*.py[cod]' \
  --exclude '.DS_Store' \
  --exclude '.claude/' \
  --exclude 'dist/' \
  --exclude 'node_modules/' \
  --exclude "$APP_NAME.app/" \
  "$REPO_ROOT"/ "$REPO_IN_APP"/
ok "Project copied"

# 3) Info.plist. -----------------------------------------------------------------------
ICON_LINE=""
if [ -f "$REPO_ROOT/assets/AppIcon.icns" ]; then
  cp "$REPO_ROOT/assets/AppIcon.icns" "$RES/AppIcon.icns"
  ICON_LINE='	<key>CFBundleIconFile</key>
	<string>AppIcon</string>'
  ok "Bundled custom icon (assets/AppIcon.icns)"
elif [ -f "$REPO_ROOT/assets/app_icon.png" ] && command -v iconutil >/dev/null 2>&1 && command -v sips >/dev/null 2>&1; then
  info "Generating AppIcon.icns from assets/app_icon.png…"
  ICONSET="$(mktemp -d)/AppIcon.iconset"
  mkdir -p "$ICONSET"
  for SZ in 16 32 64 128 256 512; do
    sips -z "$SZ" "$SZ"       "$REPO_ROOT/assets/app_icon.png" --out "$ICONSET/icon_${SZ}x${SZ}.png"   >/dev/null
    sips -z $((SZ*2)) $((SZ*2)) "$REPO_ROOT/assets/app_icon.png" --out "$ICONSET/icon_${SZ}x${SZ}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$RES/AppIcon.icns"
  ICON_LINE='	<key>CFBundleIconFile</key>
	<string>AppIcon</string>'
  ok "Generated icon from assets/app_icon.png"
else
  info "No icon found — using the default app icon. Add assets/AppIcon.icns or assets/app_icon.png to customise."
fi

cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key>
	<string>$APP_NAME</string>
	<key>CFBundleDisplayName</key>
	<string>$APP_NAME</string>
	<key>CFBundleIdentifier</key>
	<string>$BUNDLE_ID</string>
	<key>CFBundleVersion</key>
	<string>$VERSION</string>
	<key>CFBundleShortVersionString</key>
	<string>$VERSION</string>
	<key>CFBundleExecutable</key>
	<string>launcher</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
$ICON_LINE
	<key>LSMinimumSystemVersion</key>
	<string>11.0</string>
	<key>NSHighResolutionCapable</key>
	<true/>
</dict>
</plist>
PLIST
ok "Wrote Info.plist"

# 4) The launcher (Contents/MacOS/launcher). -------------------------------------------
# Runs when the .app is double-clicked. A GUI launch has a minimal PATH and NO terminal, so we:
#   - add the usual Homebrew / uv locations to PATH ourselves,
#   - log to a file (there's no console to print to),
#   - report fatal setup errors with a native dialog (osascript).
cat > "$MACOS/launcher" <<'LAUNCHER'
#!/bin/bash
# Tintin's AI Chess Analysis — .app launcher. Generated by scripts/build_app.sh.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../Resources/repo" && pwd)"

# Writable runtime home OUTSIDE the (read-only) bundle: the Python env + all user data live here,
# so the bundle stays immutable and your games/settings survive an app update.
SUPPORT="$HOME/Library/Application Support/Tintin AI Chess Analysis"
ENV_DIR="$SUPPORT/venv"
DATA_DIR="$SUPPORT/data"
LOG="$SUPPORT/launch.log"
mkdir -p "$SUPPORT" "$DATA_DIR"

# No console on a GUI launch — capture everything to a log file.
exec >>"$LOG" 2>&1
echo "=== launch $(date) ==="

# GUI launches get a bare PATH (no Homebrew, no ~/.local/bin). Add the usual spots so uv, brew,
# stockfish and claude are found.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin:/usr/bin:/bin:/usr/sbin:/sbin"

HOST="${CHESS_WEB_HOST:-127.0.0.1}"
PORT="${CHESS_WEB_PORT:-8765}"
URL="http://${HOST}:${PORT}"

die() {  # show a native error dialog, then exit non-zero
  /usr/bin/osascript -e "display dialog \"$1\" with title \"Tintin's AI Chess Analysis\" buttons {\"OK\"} default button \"OK\" with icon caution" >/dev/null 2>&1 || true
  exit 1
}

# Already running? Just (re)open the browser and stop — don't start a second server.
if curl -fsS "${URL}/api/app-config" >/dev/null 2>&1; then
  echo "Already running — opening ${URL}"
  open "$URL" || true
  exit 0
fi

# 1) uv — manages Python + deps (self-contained; no pre-existing Python needed).
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh \
    || die "Could not install 'uv'. Check your internet connection and open the app again."
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || die "'uv' was installed but isn't on PATH. Open a Terminal, run: curl -LsSf https://astral.sh/uv/install.sh | sh"

# 2) Stockfish — the chess engine (not a pip package).
if ! command -v stockfish >/dev/null 2>&1; then
  echo "Installing Stockfish…"
  if command -v brew >/dev/null 2>&1; then
    brew install stockfish || die "Could not install Stockfish via Homebrew. See $LOG."
  else
    die "Stockfish isn't installed and Homebrew wasn't found. Install Homebrew from https://brew.sh and reopen the app, or download Stockfish from https://stockfishchess.org/download/."
  fi
fi

# 3) Build the Python environment in the writable support dir (NOT inside the bundle).
export UV_PROJECT_ENVIRONMENT="$ENV_DIR"
echo "Syncing Python environment into $ENV_DIR …"
# --no-install-project: install only the locked DEPENDENCIES, not the project package itself.
#   run_web.py imports server.* via sys.path, so the package never needs building/installing — and
#   skipping it means uv writes NOTHING inside the (read-only, App-Management-protected) bundle.
# --frozen: never touch uv.lock (which lives in the read-only bundle).
( cd "$REPO" && uv sync --frozen --no-install-project ) \
  || die "Could not set up the Python environment. See $LOG."

# 4) Serve the board in app mode. Run the venv's python directly (no terminal, shallow process
#    tree) so closing the browser tab — or quitting the app — stops the server cleanly.
export CHESS_APP_MODE=1
export CHESS_DATA_DIR="$DATA_DIR"
export PYTHONDONTWRITEBYTECODE=1   # don't try to write .pyc into the read-only bundle
echo "Starting board at ${URL}"
cd "$REPO"
exec "$ENV_DIR/bin/python" "$REPO/scripts/run_web.py" --serve
LAUNCHER
chmod +x "$MACOS/launcher"
ok "Wrote launcher"

# 5) Tag the bundle so Finder/LaunchServices picks it up immediately. -------------------
touch "$APP"

echo
bold "Done."
echo "Built: $APP"
echo
echo "Try it:   open \"$APP\""
echo "Install:  drag it into /Applications (then double-click)."
echo "First open may need right-click → Open (unsigned app)."
echo "Logs:     ~/Library/Application Support/Tintin AI Chess Analysis/launch.log"
