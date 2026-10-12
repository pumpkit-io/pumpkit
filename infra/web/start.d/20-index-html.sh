# Sourced by start.sh, after 10-site-address.sh has checked PUBLIC_URL. Fills the built
# index.html and sitemap.xml with PUBLIC_URL and writes robots.txt from ALLOW_SEARCH_INDEXING.

public_url=${PUBLIC_URL%/}
# Escape the characters sed treats specially in a replacement with | as the delimiter.
public_url_sed=$(printf '%s' "$public_url" | sed 's/[\\&|]/\\&/g')

case "${ALLOW_SEARCH_INDEXING:-false}" in
  true) robots_meta='index,follow' ;;
  false) robots_meta='noindex,nofollow' ;;
  *)
    echo "ALLOW_SEARCH_INDEXING must be true or false, not '$ALLOW_SEARCH_INDEXING'" >&2
    exit 1
    ;;
esac

sed -e "s|__PUBLIC_URL__|$public_url_sed|g" \
  -e "s|<meta name=\"robots\" content=\"noindex,nofollow\"|<meta name=\"robots\" content=\"$robots_meta\"|" \
  /etc/pumpkit/templates/index.html >/srv/index.html
sed -e "s|__PUBLIC_URL__|$public_url_sed|g" /etc/pumpkit/templates/sitemap.xml >/srv/sitemap.xml

if [ "$robots_meta" = 'index,follow' ]; then
  cat >/srv/robots.txt <<ROBOTS
User-agent: *
Allow: /
Disallow: /home
Disallow: /billing

Sitemap: $public_url/sitemap.xml
ROBOTS
else
  printf 'User-agent: *\nDisallow: /\n' >/srv/robots.txt
fi
