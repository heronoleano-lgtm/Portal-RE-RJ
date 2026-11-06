#!/usr/bin/env sh
cd "$(dirname "$0")"
exec "$(command -v python3 || command -v python)" -m unittest discover -s tests -t . -v
