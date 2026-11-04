#!/usr/bin/env bash
# Offline test suite: stdlib unittest only. The only server is tests/fake_jev.py on 127.0.0.1.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m unittest discover -s tests -v
