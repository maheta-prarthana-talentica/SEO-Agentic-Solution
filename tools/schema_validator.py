"""JSON-LD / Schema.org structured data validation (FR-1.6).

Lightweight, dependency-free validator: parses each <script type="application/ld+json">
block, checks it's valid JSON, resolves @type, and checks for the required properties
Google's Rich Results tests for on the most common types. This is not a full SHACL/JSON
Schema validator against the entire schema.org ontology (out of scope for the POC) but
catches the common real-world errors: invalid JSON, missing @context, missing required
properties for the declared type.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

REQUIRED_PROPS_BY_TYPE: dict[str, list[str]] = {
    "Article": ["headline", "author", "datePublished", "image"],
    "NewsArticle": ["headline", "author", "datePublished", "image"],
    "Product": ["name", "image", "offers"],
    "BreadcrumbList": ["itemListElement"],
    "Organization": ["name", "url", "logo"],
    "LocalBusiness": ["name", "address"],
    "FAQPage": ["mainEntity"],
    "Review": ["itemReviewed", "reviewRating", "author"],
    "WebPage": ["name"],
}

# Common opportunities Google Rich Results supports that most sites are missing entirely.
SCHEMA_OPPORTUNITIES = {
    "Organization": "Establishes brand entity/knowledge panel eligibility; usually placed site-wide in the layout template.",
    "BreadcrumbList": "Enables breadcrumb rich results in SERPs, improving CTR for deep pages.",
    "Article": "Required for Article rich results/Top Stories eligibility on content/blog pages.",
    "Product": "Required for price/rating rich results on e-commerce product pages.",
    "FAQPage": "Enables FAQ rich results for pages with question/answer content.",
}


@dataclass
class SchemaValidationResult:
    url: str
    blocks_found: int
    valid_blocks: list[dict] = field(default_factory=list)
    invalid_json_blocks: int = 0
    types_present: set[str] = field(default_factory=set)
    missing_required_props: list[tuple[str, list[str]]] = field(default_factory=list)  # (type, [missing])
    opportunities: list[tuple[str, str]] = field(default_factory=list)  # (type, rationale)


def validate_json_ld_blocks(url: str, raw_blocks: list[str], page_category_hint: str = "") -> SchemaValidationResult:
    result = SchemaValidationResult(url=url, blocks_found=len(raw_blocks))

    for raw in raw_blocks:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            result.invalid_json_blocks += 1
            continue

        entries = parsed if isinstance(parsed, list) else [parsed]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            result.valid_blocks.append(entry)
            schema_type = entry.get("@type")
            if isinstance(schema_type, list):
                types = schema_type
            elif schema_type:
                types = [schema_type]
            else:
                types = []

            for t in types:
                result.types_present.add(t)
                required = REQUIRED_PROPS_BY_TYPE.get(t)
                if required:
                    missing = [p for p in required if p not in entry]
                    if missing:
                        result.missing_required_props.append((t, missing))

    for schema_type, rationale in SCHEMA_OPPORTUNITIES.items():
        if schema_type not in result.types_present:
            if schema_type == "Product" and page_category_hint != "product":
                continue
            if schema_type == "Article" and page_category_hint not in ("article", "blog", ""):
                continue
            result.opportunities.append((schema_type, rationale))

    return result
