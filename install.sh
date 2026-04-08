#!/usr/bin/env bash
# claudepulse installer
# Usage: curl -fsSL https://raw.githubusercontent.com/ColdDesertLab/claudepulse/main/install.sh | bash
set -euo pipefail

REPO="https://github.com/ColdDesertLab/claudepulse.git"
DEST="${CLAUDEPULSE_HOME:-$HOME/.claudepulse}"
BIN_DIR="${CLAUDEPULSE_BIN:-$HOME/.local/bin}"
BIN="$BIN_DIR/claudepulse"

mkdir -p "$BIN_DIR"

# Migrate legacy claudetally install, if present
LEGACY_DEST="$HOME/.claudetally"
LEGACY_BIN="$BIN_DIR/claudetally"
if [ -d "$LEGACY_DEST" ] && [ ! -d "$DEST" ]; then
  echo "Migrating $LEGACY_DEST -> $DEST ..."
  mv "$LEGACY_DEST" "$DEST"
fi
if [ -e "$LEGACY_BIN" ]; then
  echo "Removing legacy launcher $LEGACY_BIN ..."
  rm -f "$LEGACY_BIN"
fi

if [ -d "$DEST/.git" ]; then
  echo "Updating $DEST ..."
  git -C "$DEST" remote set-url origin "$REPO"
  git -C "$DEST" fetch --quiet origin main
  git -C "$DEST" checkout --quiet main
  git -C "$DEST" reset --hard --quiet origin/main
else
  echo "Cloning into $DEST ..."
  git clone --quiet "$REPO" "$DEST"
fi

cat > "$BIN" <<'EOF'
#!/usr/bin/env bash
# claudepulse launcher (auto-updates from origin/main)
set -euo pipefail
DEST="${CLAUDEPULSE_HOME:-$HOME/.claudepulse}"
if [ "${CLAUDEPULSE_NO_UPDATE:-0}" != "1" ]; then
  git -C "$DEST" fetch --quiet origin main 2>/dev/null || true
  git -C "$DEST" reset --hard --quiet origin/main 2>/dev/null || true
fi
exec python3 "$DEST/cli.py" "${@:-dashboard}"
EOF
chmod +x "$BIN"

echo ""
echo "Installed: $BIN"
case ":$PATH:" in
  *":$BIN_DIR:"*) echo "PATH: ok" ;;
  *) echo "NOTE: add to PATH ->  export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
echo "Run: claudepulse            (defaults to dashboard)"
echo "     claudepulse <command>"
