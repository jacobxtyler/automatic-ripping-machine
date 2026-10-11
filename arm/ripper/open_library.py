"""Open Library lookup helpers for audiobook metadata."""
import logging
from typing import Optional

import requests


SEARCH_URL = "https://openlibrary.org/search.json"


def parse_search_results(payload: dict) -> list[dict]:
    """
    Normalize Open Library search results into the audiobook fields ARM stores.

    Missing optional fields are returned as empty strings so UI callers can prefill
    only what Open Library actually knows.
    """
    results = []
    for doc in payload.get("docs", []):
        title = doc.get("title") or ""
        authors = doc.get("author_name") or []
        author = authors[0] if authors else ""
        work_key = doc.get("key") or ""
        cover_id = doc.get("cover_i") or ""
        year = doc.get("first_publish_year") or ""

        if not title and not author:
            continue

        results.append({
            "title": str(title),
            "author": str(author),
            "year": str(year),
            "open_library_work_key": str(work_key),
            "cover_id": str(cover_id),
        })
    return results


def search(query: str, limit: int = 5, session=None) -> list[dict]:
    """Search Open Library and return normalized audiobook metadata candidates."""
    if session is None:
        session = requests

    try:
        response = session.get(SEARCH_URL, params={"q": query, "limit": limit}, timeout=10)
        response.raise_for_status()
    except requests.RequestException as error:
        logging.error(f"Open Library lookup failed: {error}")
        return []

    return parse_search_results(response.json())


def first_result(query: str, session=None) -> Optional[dict]:
    """Return the first normalized Open Library result for a query."""
    results = search(query, limit=1, session=session)
    return results[0] if results else None
