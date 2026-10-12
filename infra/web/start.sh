#!/bin/sh
# The web image's entrypoint: sources each start.d step in name order, then runs the command (Caddy).
# Steps are sourced so they can export settings for the Caddyfile; a failing step stops the container.
set -eu

for step in /etc/pumpkit/start.d/*.sh; do
  [ -e "$step" ] || continue
  . "$step"
done

exec "$@"
