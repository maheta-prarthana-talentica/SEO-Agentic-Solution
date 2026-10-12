"""Repo scanner: framework detection, convention sniffing, lightweight file index.

Uses tree-sitter when available; otherwise falls back to regex/path heuristics so
Phase 2 still works offline.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


SUPPORTED_FRAMEWORKS = ("nextjs", "astro", "static-html")


@dataclass
class RepoIndex:
    repo_path: Path
    framework: str
    conventions: dict
    files: list[str] = field(default_factory=list)
    # path -> snippet/keywords for finding-to-file mapping
    file_signals: dict[str, list[str]] = field(default_factory=dict)


def detect_framework(repo_path: Path) -> str:
    pkg = repo_path / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        if "next" in deps:
            return "nextjs"
        if "astro" in deps:
            return "astro"
    if (repo_path / "astro.config.mjs").exists() or (repo_path / "astro.config.ts").exists():
        return "astro"
    if (repo_path / "next.config.js").exists() or (repo_path / "next.config.mjs").exists():
        return "nextjs"
    # Static HTML / unknown
    if list(repo_path.rglob("*.html")):
        return "static-html"
    return "unsupported"


def detect_conventions(repo_path: Path, framework: str) -> dict:
    conventions: dict = {
        "framework": framework,
        "meta_helper": None,
        "i18n": False,
        "layout_files": [],
        "public_dir": None,
    }
    candidates = []
    for pattern in ("**/layout.tsx", "**/layout.jsx", "**/Layout.tsx",
                    "**/_document.tsx", "**/BaseLayout.astro", "**/head.html"):
        candidates.extend(repo_path.glob(pattern))
    conventions["layout_files"] = [str(p.relative_to(repo_path)).replace("\\", "/")
                                   for p in candidates[:10]]

    # Look for an SEO/Head helper component
    for pattern in ("**/*SEO*", "**/*Seo*", "**/*Head*", "**/MetaTags*"):
        for p in repo_path.glob(pattern):
            if p.suffix in {".tsx", ".jsx", ".ts", ".js", ".astro"}:
                conventions["meta_helper"] = str(p.relative_to(repo_path)).replace("\\", "/")
                break
        if conventions["meta_helper"]:
            break

    if (repo_path / "public").is_dir():
        conventions["public_dir"] = "public"
    elif (repo_path / "static").is_dir():
        conventions["public_dir"] = "static"

    # i18n markers
    for marker in ("next-intl", "react-i18next", "i18n"):
        if list(repo_path.rglob(f"*{marker}*")):
            conventions["i18n"] = True
            break
    return conventions


def build_file_index(repo_path: Path, max_files: int = 2000) -> dict[str, list[str]]:
    """Map each source file to keyword signals used for finding→file matching."""
    signals: dict[str, list[str]] = {}
    exts = {".tsx", ".jsx", ".ts", ".js", ".astro", ".html", ".vue", ".mdx"}
    count = 0
    for p in repo_path.rglob("*"):
        if count >= max_files:
            break
        if not p.is_file() or p.suffix not in exts:
            continue
        # Skip node_modules / .git
        parts = set(p.parts)
        if "node_modules" in parts or ".git" in parts or "dist" in parts:
            continue
        rel = str(p.relative_to(repo_path)).replace("\\", "/")
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")[:8000]
        except OSError:
            continue
        keys = set()
        keys.add(p.stem.lower())
        for m in re.findall(r"<(?:title|meta|link\s+rel=[\"']canonical|img\b)", text, re.I):
            keys.add(m.lower())
        if "application/ld+json" in text:
            keys.add("json-ld")
            keys.add("structured-data")
        if re.search(r"robots\.txt|sitemap\.xml", rel, re.I):
            keys.add("sitemap-robots")
        if "alt=" in text or "<img" in text:
            keys.add("alt-text")
            keys.add("images")
        if "<title" in text or "metadata" in text or "<SEO" in text or "generateMetadata" in text:
            keys.add("meta-tags")
            keys.add("title")
        signals[rel] = sorted(keys)
        count += 1
    return signals


def index_repo(repo_path: Path) -> RepoIndex:
    framework = detect_framework(repo_path)
    conventions = detect_conventions(repo_path, framework)
    signals = build_file_index(repo_path)
    return RepoIndex(
        repo_path=repo_path,
        framework=framework,
        conventions=conventions,
        files=list(signals.keys()),
        file_signals=signals,
    )


def map_finding_to_files(finding_title: str, fix_category: str | None,
                         index: RepoIndex) -> list[str]:
    """Heuristic mapping of a finding to likely source files (FR-3.2)."""
    category_keywords = {
        "missing_or_duplicate_meta_title": ["meta-tags", "title"],
        "missing_or_duplicate_meta_description": ["meta-tags", "title"],
        "missing_image_alt_text": ["alt-text", "images"],
        "missing_or_incorrect_canonical": ["meta-tags", "canonical"],
        "missing_structured_data": ["json-ld", "structured-data"],
        "sitemap_or_robots_error": ["sitemap-robots"],
        "broken_internal_link": ["href"],
        "heading_hierarchy_issue": ["meta-tags", "title"],
    }
    wanted = set(category_keywords.get(fix_category or "", []))
    if not wanted and index.conventions.get("layout_files"):
        return index.conventions["layout_files"][:3]

    scored: list[tuple[int, str]] = []
    for path, keys in index.file_signals.items():
        score = len(wanted.intersection(keys))
        if fix_category == "sitemap_or_robots_error":
            if path.endswith("robots.txt") or path.endswith("sitemap.xml"):
                score += 5
        if score:
            scored.append((score, path))
    scored.sort(reverse=True)
    hits = [p for _, p in scored[:5]]

    # Prefer layout / meta helper when available for template-level issues
    if fix_category in {
        "missing_or_duplicate_meta_title",
        "missing_or_duplicate_meta_description",
        "missing_or_incorrect_canonical",
        "missing_structured_data",
    }:
        preferred = []
        if index.conventions.get("meta_helper"):
            preferred.append(index.conventions["meta_helper"])
        preferred.extend(index.conventions.get("layout_files") or [])
        hits = list(dict.fromkeys(preferred + hits))[:5]
    return hits
