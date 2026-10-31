from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ragnoz import corpus as corpus_module
from ragnoz.corpus import download_revision_corpus, html_to_text, load_revision_manifest


def test_html_to_text_strips_tags_and_collapses_whitespace():
    markup = "<html><body><p>Hello   world</p><p>Second   paragraph</p></body></html>"
    assert html_to_text(markup) == "Hello world Second paragraph"


def test_html_to_text_skips_script_style_and_table_content():
    markup = "<div>Before<script>var x = 1;</script><style>.a{}</style><table><tr><td>cell</td></tr></table>After</div>"
    result = html_to_text(markup)
    assert "var x" not in result
    assert "cell" not in result
    assert "Before" in result
    assert "After" in result


def test_html_to_text_handles_nested_skip_tags_correctly():
    markup = "<p>Keep<script>drop<noscript>also drop</noscript>still drop</script>Keep again</p>"
    result = html_to_text(markup)
    assert "drop" not in result
    assert "also drop" not in result
    assert "Keep" in result
    assert "Keep again" in result


def test_load_revision_manifest_reads_list(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps([{"lang": "en", "revid": "1", "pageid": "2", "title": "T"}]), encoding="utf-8")
    manifest = load_revision_manifest(manifest_path)
    assert manifest == [{"lang": "en", "revid": "1", "pageid": "2", "title": "T"}]


def test_load_revision_manifest_rejects_non_list(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(TypeError):
        load_revision_manifest(manifest_path)


_RealClient = httpx.Client


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    monkeypatch.setattr(corpus_module.httpx, "Client",
                        lambda *args, **kwargs: _RealClient(*args, **{**kwargs, "transport": transport}))


def test_download_revision_corpus_happy_path_writes_pages_and_attribution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    html = f"<html><body><p>{'A' * 150}</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    monkeypatch.setattr(corpus_module.time, "sleep", lambda seconds: None)
    manifest = [{"lang": "en", "revid": "123", "pageid": "456", "title": "Test Page"}]
    output = download_revision_corpus(manifest, tmp_path)
    assert output.name == "pages.json"
    pages = json.loads(output.read_text(encoding="utf-8"))
    assert len(pages) == 1
    assert pages[0]["doc_id"] == "en_456"
    assert pages[0]["source_url"] == "https://en.wikipedia.org/w/index.php?oldid=123"
    assert len(pages[0]["text"]) >= 100
    attribution = tmp_path / "ATTRIBUTION.md"
    assert attribution.exists()
    assert "CC BY-SA" in attribution.read_text(encoding="utf-8")
    assert "Test Page" in attribution.read_text(encoding="utf-8")


def test_download_revision_corpus_retries_on_429_honoring_retry_after_header(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    html = f"<p>{'B' * 150}</p>"
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, text=html)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    sleeps: list[float] = []
    monkeypatch.setattr(corpus_module.time, "sleep", sleeps.append)
    manifest = [{"lang": "en", "revid": "1", "pageid": "2", "title": "T"}]
    download_revision_corpus(manifest, tmp_path)
    assert calls["n"] == 2
    assert 2.0 in sleeps


def test_download_revision_corpus_falls_back_to_backoff_on_malformed_retry_after(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    html = f"<p>{'C' * 150}</p>"
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "not-a-number"})
        return httpx.Response(200, text=html)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    sleeps: list[float] = []
    monkeypatch.setattr(corpus_module.time, "sleep", sleeps.append)
    manifest = [{"lang": "en", "revid": "1", "pageid": "2", "title": "T"}]
    download_revision_corpus(manifest, tmp_path)
    assert calls["n"] == 2
    assert 5.0 in sleeps  # min(5 * 2**0, 60) exponential-backoff fallback


def test_download_revision_corpus_raises_after_exhausting_429_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    monkeypatch.setattr(corpus_module.time, "sleep", lambda seconds: None)
    manifest = [{"lang": "en", "revid": "1", "pageid": "2", "title": "T"}]
    with pytest.raises(httpx.HTTPStatusError):
        download_revision_corpus(manifest, tmp_path)


def test_download_revision_corpus_raises_immediately_on_non_429_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    manifest = [{"lang": "en", "revid": "1", "pageid": "2", "title": "T"}]
    with pytest.raises(httpx.HTTPStatusError):
        download_revision_corpus(manifest, tmp_path)


def test_download_revision_corpus_rejects_near_empty_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<p>too short</p>")

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    manifest = [{"lang": "en", "revid": "1", "pageid": "2", "title": "T"}]
    with pytest.raises(ValueError, match="boş görünüyor"):
        download_revision_corpus(manifest, tmp_path)
