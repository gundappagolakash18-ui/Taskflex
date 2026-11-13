#!/bin/sh
# Renders the nginx config for the current platform.
# Render injects PORT (usually 10000) and we supply BACKEND_HOSTPORT.
set -e

: "${PORT:=80}"
: "${BACKEND_HOSTPORT:=backend:8000}"

sed -i "s|__PORT__|${PORT}|g; s|__BACKEND_HOSTPORT__|${BACKEND_HOSTPORT}|g" \
    /etc/nginx/conf.d/default.conf

echo "==> TASKFLEX web: listening on :${PORT}, proxying to ${BACKEND_HOSTPORT}"
