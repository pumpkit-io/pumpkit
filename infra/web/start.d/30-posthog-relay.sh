# Sourced by start.sh. Turns the PostHog relay on by putting its snippet where the Caddyfile imports from;
# it is removed otherwise, since a restarted container keeps its files.

relay_import_dir=/etc/caddy/site.d
mkdir -p "$relay_import_dir"
rm -f "$relay_import_dir/posthog-relay.caddy"

case "${POSTHOG_RELAY:-false}" in
  true)
    cp /etc/pumpkit/snippets/posthog-relay.caddy "$relay_import_dir/"
    ;;
  false) ;;
  *)
    echo "POSTHOG_RELAY must be true or false, got: $POSTHOG_RELAY" >&2
    exit 1
    ;;
esac
