#!/bin/sh
# Fix volume permissions if mounted as root
if [ "$(stat -c '%U' /app/data 2>/dev/null)" != "botuser" ]; then
    chown -R botuser:botuser /app/data 2>/dev/null || true
fi
exec gosu botuser python bot.py
