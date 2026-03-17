#!/usr/bin/env bash
# uninstall.sh — Remove Claude Code Usage menu bar app
PLIST_LABEL="com.claude.usagebar"
PLIST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

echo "==> Unloading LaunchAgent..."
launchctl unload "$PLIST" 2>/dev/null || true

echo "==> Removing plist..."
rm -f "$PLIST"

echo "==> Killing any running instance..."
pkill -f "claude_usage_bar.py" 2>/dev/null || true

echo "Done. Claude Usage Bar has been removed."
