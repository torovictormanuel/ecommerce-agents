#!/bin/bash
# Startup script for cloud deployments (Render, Railway, etc.)
# Writes Google credentials from env var to a temp file if present.
if [ -n "$GOOGLE_CREDENTIALS_JSON" ]; then
    echo "$GOOGLE_CREDENTIALS_JSON" > /tmp/google-credentials.json
    export SHEETS_CREDENTIALS_PATH=/tmp/google-credentials.json
fi

exec uvicorn src.api.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --log-level info \
    --workers 1
