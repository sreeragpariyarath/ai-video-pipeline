from __future__ import annotations

from datetime import date

from .evidence_schemas import ExtractedContent


# Very short extraction results are almost always navigation or boilerplate.
_MIN_TEXT_CHARS = 40


def _load_trafilatura():
    try:
        import trafilatura
    except ImportError as exc:
        raise RuntimeError(
            "trafilatura is not installed. Run `pip install -r requirements.txt`, "
            "or use MockEvidenceExtraction for offline runs."
        ) from exc
    return trafilatura


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def extract_article(html: str, url: str) -> ExtractedContent | None:
    """Extract clean article text; return None when nothing usable remains."""
    if not isinstance(html, str) or not html.strip():
        return None
    trafilatura = _load_trafilatura()
    try:
        doc = trafilatura.bare_extraction(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            with_metadata=True,
            # Extensive search invents dates from stray years in body text.
            date_extraction_params={"extensive_search": False},
        )
    except Exception:
        return None
    if doc is None:
        return None
    text = (doc.text or "").strip()
    if len(text) < _MIN_TEXT_CHARS:
        return None
    title = (doc.title or "").strip() or None
    return ExtractedContent(
        title=title,
        text=text,
        published_date=_parse_date(doc.date),
        extractor="trafilatura",
    )