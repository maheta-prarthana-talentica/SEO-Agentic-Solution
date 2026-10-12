# Structured data (JSON-LD / Schema.org)

Structured data helps search engines understand entities and can unlock rich results.

## Best practices
- Prefer JSON-LD in a `<script type="application/ld+json">` block.
- Include `@context` and a valid `@type`.
- Populate required properties for the chosen type (e.g. Article needs headline, author, datePublished, image).
- Site-wide Organization schema belongs in the shared layout.
- BreadcrumbList should reflect the visible navigation hierarchy.

## Validation
- Malformed JSON silently fails — always ensure the block parses.
- Incomplete types (missing required props) will not qualify for rich results.
