from datetime import date

from orchestrator.html_extraction import extract_article


URL = "https://example.com/streaming-prices"

ARTICLE_HTML = """
<html>
<head>
<title>Streaming Prices Climb Again</title>
<meta property="article:published_time" content="2026-06-15">
</head>
<body>
<nav>Home About Contact Subscribe Newsletter Menu</nav>
<div class="ads">BUY NOW limited offer advertisement banner</div>
<article>
<h1>Streaming Prices Climb Again</h1>
<p>Streaming prices rose 12 percent in 2026 according to a new industry report.
Households now pay more for streaming bundles than for basic cable packages in
many metropolitan markets, reversing a decade-long trend.</p>
<p>The report attributes the increase to content spending and the fragmentation
of exclusive licensing deals across competing platforms. Analysts expect further
consolidation as consumers push back against rising monthly bills.</p>
<p>Regulators have begun reviewing bundle pricing disclosures, while consumer
groups recommend auditing subscriptions quarterly to cancel unused services.</p>
</article>
<footer>Copyright 2026 Example Media. Privacy policy. Terms of service.</footer>
</body>
</html>
"""


def test_extracts_title_and_text():
    content = extract_article(ARTICLE_HTML, URL)
    assert content is not None
    assert content.title == "Streaming Prices Climb Again"
    assert "Streaming prices rose 12 percent in 2026" in content.text
    assert content.extractor == "trafilatura"


def test_removes_boilerplate():
    content = extract_article(ARTICLE_HTML, URL)
    assert content is not None
    assert "Newsletter Menu" not in content.text
    assert "BUY NOW" not in content.text
    assert "Privacy policy" not in content.text


def test_extracts_published_date():
    content = extract_article(ARTICLE_HTML, URL)
    assert content is not None
    assert content.published_date == date(2026, 6, 15)


def test_missing_date_is_none():
    html = ARTICLE_HTML.replace(
        '<meta property="article:published_time" content="2026-06-15">', ""
    )
    content = extract_article(html, URL)
    assert content is not None
    assert content.published_date is None


def test_empty_html_returns_none():
    assert extract_article("", URL) is None
    assert extract_article("   \n  ", URL) is None


def test_non_article_page_returns_none():
    html = "<html><body><nav>Home About</nav><footer>Copyright</footer></body></html>"
    assert extract_article(html, URL) is None


def test_malformed_html_handled():
    content = extract_article("<html><body><p>unclosed", URL)
    assert content is None or content.text


def test_deterministic():
    first = extract_article(ARTICLE_HTML, URL)
    second = extract_article(ARTICLE_HTML, URL)
    assert first == second