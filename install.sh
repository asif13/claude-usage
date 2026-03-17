#!/usr/bin/env bash
# install.sh — Set up Claude Code Usage menu bar app as a macOS login item
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$SCRIPT_DIR/claude_usage_bar.py"
PLIST_LABEL="com.claude.usagebar"
PLIST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
LOG="/tmp/claude-usagebar.log"

# ── Find a framework Python (required for Cocoa/rumps) ────────────────────────
find_python() {
    for candidate in \
        /opt/homebrew/bin/python3 \
        /usr/local/bin/python3 \
        /usr/bin/python3 \
        python3
    do
        if command -v "$candidate" &>/dev/null; then
            framework=$("$candidate" -c "import sysconfig; print(sysconfig.get_config_var('PYTHONFRAMEWORK') or '')" 2>/dev/null)
            if [ "$framework" = "Python" ]; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    # Fallback: use whatever python3 is on PATH (may work on newer macOS)
    if command -v python3 &>/dev/null; then
        echo "python3"
        return 0
    fi
    echo ""
}

echo "==> Detecting Python..."
PYTHON=$(find_python)
if [ -z "$PYTHON" ]; then
    echo "ERROR: No suitable Python found. Install Python from python.org or via Homebrew."
    exit 1
fi
echo "    Using: $PYTHON ($($PYTHON --version))"

echo "==> Installing dependencies..."
"$PYTHON" -m pip install --quiet --upgrade rumps "pyobjc-framework-Cocoa>=10.0"

echo "==> Verifying import..."
"$PYTHON" -c "import rumps; print('    rumps OK:', rumps.__version__)"

# ── Stop existing instance if running ─────────────────────────────────────────
if launchctl list "$PLIST_LABEL" &>/dev/null; then
    echo "==> Stopping existing instance..."
    launchctl unload "$PLIST" 2>/dev/null || true
fi

# ── Write LaunchAgent plist ───────────────────────────────────────────────────
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$APP</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG</string>
    <key>StandardErrorPath</key>
    <string>$LOG</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
PLIST_EOF

echo "==> Loading LaunchAgent (starts now + auto-starts on login)..."
launchctl load "$PLIST"

echo ""
echo "Done! The ◆ icon should appear in your menu bar within a few seconds."
echo "Logs: tail -f $LOG"
echo "To uninstall: ./uninstall.sh"
