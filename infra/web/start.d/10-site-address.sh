# Sourced by start.sh. An http PUBLIC_URL is served as plain HTTP on any host, which compose
# publishes on HTTP_PORT; an https one gets a certificate for its host, with ACME_EMAIL if set.

case "${PUBLIC_URL:-}" in
  http://*)
    SITE_ADDRESS=:80
    ;;
  https://*)
    SITE_ADDRESS=${PUBLIC_URL%/}
    ;;
  *)
    echo "PUBLIC_URL must be an http:// or https:// origin, such as http://localhost:8080" >&2
    exit 1
    ;;
esac
export SITE_ADDRESS

if [ -n "${ACME_EMAIL:-}" ]; then
  ACME_EMAIL_OPTION="email $ACME_EMAIL"
else
  ACME_EMAIL_OPTION=
fi
export ACME_EMAIL_OPTION

# Caddy replaces X-Forwarded-For with the address it was reached from, unless that address is a
# trusted proxy. Another proxy in front of this container lists its address here to keep the
# caller's real address for the backend's per-IP rate limits.
if [ -n "${TRUSTED_PROXIES:-}" ]; then
  TRUSTED_PROXIES_OPTION="servers {
		trusted_proxies static $TRUSTED_PROXIES
	}"
else
  TRUSTED_PROXIES_OPTION=
fi
export TRUSTED_PROXIES_OPTION
