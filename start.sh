#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/onchainclipping.com/onchainclipping.com"
exec python3 server.py
