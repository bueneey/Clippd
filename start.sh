#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/onchainclipping.com/onchainclipping.com"
echo "start PORT=${PORT:-unset} railway=${RAILWAY_ENVIRONMENT:-none}" >&2
exec python3 -u server.py
