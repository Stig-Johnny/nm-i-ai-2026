#!/bin/bash
# Pre-submission security check — run before uploading any zip
# Usage: ./scripts/check-submission.sh task4/run.py

set -e

FILE="${1:-task4/run.py}"

if [ ! -f "$FILE" ]; then
    echo "❌ File not found: $FILE"
    exit 1
fi

echo "=== Checking $FILE for banned imports ==="

BANNED="os|sys|subprocess|socket|ctypes|builtins|importlib|pickle|marshal|shelve|shutil|yaml|requests|urllib|http\.client|multiprocessing|threading|signal|gc\b|code\b|codeop|pty"

FOUND=0
while IFS= read -r line; do
    # Skip comments
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    # Check imports
    if echo "$line" | grep -qE "^(import|from) ($BANNED)"; then
        echo "❌ BANNED: $line"
        FOUND=1
    fi
done < "$FILE"

# Check banned functions
for func in "eval(" "exec(" "compile(" "__import__"; do
    if grep -q "$func" "$FILE"; then
        echo "❌ BANNED FUNCTION: $func"
        FOUND=1
    fi
done

if [ $FOUND -eq 0 ]; then
    echo "✅ All clean — no banned imports or functions"
else
    echo ""
    echo "⛔ DO NOT SUBMIT — fix banned imports first"
    exit 1
fi
