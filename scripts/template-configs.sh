#!/usr/bin/env sh
set -eu

TEMPLATE_GLOBS=${TEMPLATE_GLOBS:-"*.yml:*.yaml"}

printf "%s" "$TEMPLATE_GLOBS" | tr ':' '\n' | while IFS= read -r g; do
  find /app -type f -name "$g" -exec sh -c '
    f="$1"
    tmp="${f}.tmp"
    envsubst < "$f" > "$tmp" && mv "$tmp" "$f"
  ' sh {} \;
done

exec "$@"
