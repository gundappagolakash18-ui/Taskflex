#!/bin/sh
# Renders the nginx config for the current platform.
# Render injects PORT; BACKEND_URL points at the API (https in production).
set -e

: "${PORT:=80}"

BACKEND_URL="${BACKEND_URL:-http://${BACKEND_HOSTPORT:-backend:8000}}"
BACKEND_URL="${BACKEND_URL%/}"
BACKEND_HOST="${BACKEND_URL#*://}"
BACKEND_HOST="${BACKEND_HOST%%/*}"

case "$BACKEND_URL" in
    https://*)
        HOST_HEADER="$BACKEND_HOST"
        CLIENT_PROTO="https"
        ;;
    *)
        HOST_HEADER='$host'
        CLIENT_PROTO='$scheme'
        ;;
esac

RESOLVER=$(awk '/^[[:space:]]*nameserver/{print $2; exit}' /etc/resolv.conf 2>/dev/null || true)
[ -n "$RESOLVER" ] || RESOLVER=127.0.0.11

sed -i \
    -e "s|__PORT__|${PORT}|g" \
    -e "s|__BACKEND_URL__|${BACKEND_URL}|g" \
    -e "s|__BACKEND_HOST__|${BACKEND_HOST}|g" \
    -e "s|__HOST_HEADER__|${HOST_HEADER}|g" \
    -e "s|__CLIENT_PROTO__|${CLIENT_PROTO}|g" \
    -e "s|__RESOLVER__|${RESOLVER}|g" \
    /etc/nginx/conf.d/default.conf

echo "==> TASKFLEX web: listening on :${PORT}, proxying to ${BACKEND_URL} (dns ${RESOLVER})"
