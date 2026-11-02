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

# Caddy keeps X-Forwarded-For only from trusted proxies: list one in front of this container here,
# or the backend's per-IP rate limits see the proxy's address instead of the caller's.
if [ -n "${TRUSTED_PROXIES:-}" ]; then
  TRUSTED_PROXIES_OPTION="servers {
		trusted_proxies static $TRUSTED_PROXIES
	}"
else
  TRUSTED_PROXIES_OPTION=
fi
export TRUSTED_PROXIES_OPTION
