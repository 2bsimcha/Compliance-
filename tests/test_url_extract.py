"""Tests for URL intake: detection, HTML->text, and fetch-then-extract.

The fetch is mocked — external hosts are unreachable in CI/sandbox, and we're testing our
logic, not the network.
"""
from app.engine import extract
from app.engine.extract import html_to_text, looks_like_url

SAMPLE_HTML = """
<html><head>
  <title>Acme Plush Dino Toy</title>
  <meta name="description" content="Soft plush dinosaur toy for toddlers ages 2 and up." />
  <meta property="og:description" content="Made of polyester fabric with printed eyes." />
  <style>.x{color:red}</style>
</head><body>
  <script>var a = 1;</script>
  <h1>Plush Dino</h1>
  <p>A cuddly plush toy. Materials: polyester. Contains a button cell battery.</p>
</body></html>
"""


def test_looks_like_url():
    assert looks_like_url("https://acme.com/product/123")
    assert looks_like_url("http://example.org/x")
    # Prose that merely mentions a URL is not a bare URL.
    assert not looks_like_url("a plush toy, see https://acme.com")
    assert not looks_like_url("plush dinosaur toy for ages 2")
    assert not looks_like_url("")


def test_html_to_text_pulls_title_meta_and_body():
    text = html_to_text(SAMPLE_HTML)
    assert "Acme Plush Dino Toy" in text          # <title>
    assert "toddlers ages 2" in text              # meta description
    assert "polyester" in text                    # og + body
    assert "button cell battery" in text          # body
    assert "var a = 1" not in text                # script stripped
    assert "color:red" not in text                # style stripped


def test_url_source_is_fetched_then_extracted(monkeypatch):
    monkeypatch.setattr(extract, "fetch_url_text", lambda url, **kw: html_to_text(SAMPLE_HTML))
    attrs = extract.extract_attributes("https://acme.com/plush-dino", use_llm=False)
    # Extraction ran on the FETCHED page text, not the bare URL string.
    assert attrs["_fetched_url"] == "https://acme.com/plush-dino"
    assert "_fetch_error" not in attrs
    assert attrs["product_category"] == "toy"
    assert "synthetic_fabric" in attrs["materials"]   # polyester
    assert attrs["has_button_batteries"] is True


def test_url_fetch_failure_degrades_gracefully(monkeypatch):
    def boom(url, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(extract, "fetch_url_text", boom)
    attrs = extract.extract_attributes("https://blocked.example/x", use_llm=False)
    assert attrs["_fetched_url"] == "https://blocked.example/x"
    assert "connection refused" in attrs["_fetch_error"]
    # Never raises; falls back to analyzing the raw input.
    assert attrs["_source"] == "heuristic"


def test_plain_description_not_treated_as_url(monkeypatch):
    # If a plain description were mistaken for a URL, this would try to fetch.
    monkeypatch.setattr(extract, "fetch_url_text", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not fetch")))
    attrs = extract.extract_attributes("painted plastic toy for ages 2 years", use_llm=False)
    assert "_fetched_url" not in attrs
    assert attrs["product_category"] == "toy"
