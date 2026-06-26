"""Network-mocked tests for pipeline.veracity.probe (deep-link policy)."""

from __future__ import annotations

import httpx

from pipeline.veracity.probe import probe_url


def test_banned_search_host_no_network() -> None:
    r = probe_url("https://www.google.com/search?q=box+office")
    assert r.verdict == "BANNED"
    assert r.status is None


def test_bare_domain_is_not_deep() -> None:
    r = probe_url("https://example.com")
    assert r.verdict == "NOT_DEEP"


def test_offline_skips_network_for_deep_url() -> None:
    r = probe_url("https://www.pewresearch.org/a/b.html", offline=True)
    assert r.verdict == "SKIPPED_OFFLINE"
    assert r.is_deep is True


def test_deep_url_2xx_passes(httpx_mock) -> None:
    url = "https://www.pewresearch.org/short-reads/2025/10/29/trust.html"
    httpx_mock.add_response(
        url=url, status_code=200, content=b"56% of US adults trust national news"
    )
    with httpx.Client() as client:
        r = probe_url(url, client=client)
    assert r.verdict == "PASS"
    assert r.status == 200
    assert r.content_sha256 is not None


def test_allow_listed_bot_block(httpx_mock) -> None:
    url = "https://variety.com/2025/film/news/conclave-100m.html"
    httpx_mock.add_response(url=url, status_code=403)
    with httpx.Client() as client:
        r = probe_url(url, client=client)
    assert r.verdict == "BOT_BLOCK"


def test_non_allow_listed_404_fails(httpx_mock) -> None:
    url = "https://random-blog.example.org/posts/dead-link"
    httpx_mock.add_response(url=url, status_code=404)
    with httpx.Client() as client:
        r = probe_url(url, client=client)
    assert r.verdict == "FAIL"


def test_youtube_oembed_path(httpx_mock) -> None:
    watch = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    # probe builds the oembed URL and GETs it
    httpx_mock.add_response(
        url="https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DdQw4w9WgXcQ&format=json",
        status_code=200,
        json={"title": "x"},
    )
    with httpx.Client() as client:
        r = probe_url(watch, client=client)
    assert r.verdict == "PASS"


def test_network_error_becomes_error_verdict(httpx_mock) -> None:
    url = "https://www.boxofficemojo.com/title/tt1587310/"
    httpx_mock.add_exception(httpx.ConnectError("boom"), url=url)
    with httpx.Client() as client:
        r = probe_url(url, client=client)
    assert r.verdict == "ERROR"
    assert r.error == "ConnectError"
