#!/usr/bin/env sh
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python) || { echo "Python 3.9+ não encontrado"; exit 1; }
[ -f config/proxy_local.sh ] && . config/proxy_local.sh
exec "$PY" backend/cli.py coletar "$@"
