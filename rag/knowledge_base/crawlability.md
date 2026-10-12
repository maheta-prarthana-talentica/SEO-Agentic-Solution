# Crawlability: robots.txt and sitemaps

## robots.txt
- Place at the site root (`/robots.txt`).
- Use `Disallow` to steer crawl budget away from low-value paths; avoid a site-wide `Disallow: /` on production.
- Declare `Sitemap: https://example.com/sitemap.xml` for discovery.

## sitemap.xml
- Well-formed XML per the sitemaps.org protocol.
- List only canonical, indexable, same-domain URLs.
- Keep in sync with the live route list; stale sitemaps slow discovery of new pages.
