#!/usr/bin/env python3
"""Hybrid tag discovery and suggestions for qs-wallpaper-picker.

Standard-library only. Searches a local persistent tag cache instantly,
fetches Wallhaven tag search results when needed, and atomically updates
the local dictionary so discovery grows over time without bloat.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Mapping

USER_AGENT = "qs-wallpaper-picker/3.0"
SEARCH_URL = "https://wallhaven.cc/tag/search"
DEFAULT_TIMEOUT = 2.5
MAX_SUGGESTIONS = 8

SEED_TERMS = (
    "anime", "nature", "car", "game", "cyberpunk", "space", "fantasy",
    "movie", "landscape", "dark", "city", "girl", "neon", "pixel art",
    "scifi", "vampire", "the", "cat", "minimalism", "digital art"
)


def get_cache_path(env: Mapping[str, str] | None = None) -> Path:
    env_map = os.environ if env is None else env
    base = env_map.get("XDG_CACHE_HOME")
    cache_root = Path(base) if base else Path.home() / ".cache"
    return cache_root / "wallpaper_picker" / "tags_cache.json"


def load_cache(cache_path: Path) -> dict[str, str]:
    if not cache_path.is_file():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        tags = data.get("tags", {})
        if isinstance(tags, dict):
            return {str(k): str(v).strip() for k, v in tags.items() if str(v).strip()}
    except Exception:
        pass
    return {}


def save_cache(cache_path: Path, tags: dict[str, str]) -> None:
    from contextlib import suppress

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile(
        "w",
        dir=cache_path.parent,
        encoding="utf-8",
        delete=False,
    )
    try:
        with temp_file:
            json.dump({"tags": tags}, temp_file, ensure_ascii=False, indent=2)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_file.name, cache_path)
    except Exception:
        with suppress(OSError):
            temp_file.close()
        with suppress(OSError):
            os.unlink(temp_file.name)


def fetch_remote_tags(term: str, timeout: float = DEFAULT_TIMEOUT) -> list[tuple[str, str]]:
    from html import unescape

    clean_term = term.strip()
    if not clean_term:
        return []
    url = f"{SEARCH_URL}?{urllib.parse.urlencode({'q': clean_term})}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            page_html = resp.read().decode("utf-8", errors="ignore")
        raw_matches = re.findall(
            r'href="https://wallhaven\.cc/tag/(\d+)"[^>]*>([^<]+)</a>',
            page_html,
        )
        return [
            (tid, unescape(name).strip())
            for tid, name in raw_matches
            if unescape(name).strip()
        ]
    except Exception:
        return []


def rank_matches(term: str, tags: dict[str, str], limit: int = MAX_SUGGESTIONS) -> list[tuple[str, str]]:
    t_lower = term.strip().lower()
    if not t_lower:
        return []

    scored = []
    for tid, name in tags.items():
        n_lower = name.lower()
        if t_lower not in n_lower:
            continue
        if n_lower == t_lower:
            tier = 0
        elif n_lower.startswith(t_lower):
            tier = 1
        elif f" {t_lower}" in n_lower or f"({t_lower}" in n_lower:
            tier = 2
        else:
            tier = 3
        scored.append((tier, len(name), name.lower(), tid, name))

    scored.sort()
    return [(tid, name) for _, _, _, tid, name in scored[:limit]]


def suggest_tags(
    query_raw: str,
    cache_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    allow_network: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
    limit: int = MAX_SUGGESTIONS,
) -> list[tuple[str, str]]:
    # Strip prefixes like #, tag:, id:
    term = re.sub(r"^(?:#|tag[:/]|id:)", "", query_raw.strip(), flags=re.IGNORECASE).strip()
    if not term:
        return []

    target_cache = cache_path or get_cache_path(env)
    tags = load_cache(target_cache)
    initial_matches = rank_matches(term, tags, limit=limit)

    # If we have enough exact or prefix matches, we don't strictly need network,
    # but querying online broadens cache if network allowed.
    needs_network = allow_network and len(term) >= 2 and len(initial_matches) < limit

    if needs_network:
        remote = fetch_remote_tags(term, timeout=timeout)
        if remote:
            new_discovered = False
            for tid, name in remote:
                if tid not in tags or tags[tid] != name:
                    tags[tid] = name
                    new_discovered = True
            if new_discovered:
                save_cache(target_cache, tags)
            return rank_matches(term, tags, limit=limit)

    return initial_matches


def seed_tags(cache_path: Path | None = None, env: Mapping[str, str] | None = None) -> int:
    target_cache = cache_path or get_cache_path(env)
    tags = load_cache(target_cache)
    added = 0
    for term in SEED_TERMS:
        remote = fetch_remote_tags(term, timeout=DEFAULT_TIMEOUT)
        for tid, name in remote:
            if tid not in tags:
                tags[tid] = name
                added += 1
    if added > 0:
        save_cache(target_cache, tags)
    return added


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wallhaven Tag Suggestions")
    parser.add_argument("query", nargs="?", default="", help="Prefix or tag term to suggest")
    parser.add_argument("--seed", action="store_true", help="Pre-seed cache with popular tags")
    parser.add_argument("--limit", type=int, default=MAX_SUGGESTIONS, help="Max suggestions")
    parser.add_argument("--offline", action="store_true", help="Do not query remote endpoint")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.seed:
        count = seed_tags()
        print(f"Seeded {count} new tags.")
        return 0

    if not args.query:
        return 0

    results = suggest_tags(
        args.query,
        allow_network=not args.offline,
        limit=args.limit,
    )
    for tid, name in results:
        print(f"{tid}|{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
