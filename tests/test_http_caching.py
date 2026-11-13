from __future__ import annotations

import pytest
import responses

import feedparser
import feedparser.http

FEED_URL = "https://example.com/feed.xml"
FEED_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Example feed</title>
    <item><title>Example entry</title></item>
  </channel>
</rss>
"""
MODIFIED = "Fri, 11 Jun 2004 23:00:34 GMT"


@pytest.fixture(autouse=True)
def clear_http_cache():
    feedparser.http._CACHE.clear()
    yield
    feedparser.http._CACHE.clear()


def test_fresh_response_is_not_from_cache():
    with responses.RequestsMock() as mock:
        mock.get(
            FEED_URL,
            body=FEED_XML,
            headers={"ETag": '"abc"', "Last-Modified": MODIFIED},
            content_type="application/rss+xml",
        )

        result = feedparser.parse(FEED_URL)

    assert result.status == 200
    assert result.from_cache is False
    assert result.etag == '"abc"'
    assert result.modified == MODIFIED
    assert result.feed.title == "Example feed"
    assert result.entries[0].title == "Example entry"


def test_second_request_is_conditional_and_uses_cached_result():
    with responses.RequestsMock() as mock:
        mock.get(
            FEED_URL,
            body=FEED_XML,
            headers={"ETag": '"abc"', "Last-Modified": MODIFIED},
            content_type="application/rss+xml",
        )
        mock.get(FEED_URL, body=b"", status=304)
        mock.get(FEED_URL, body=b"", status=304)

        first = feedparser.parse(FEED_URL)
        second = feedparser.parse(FEED_URL)
        conditional_request = mock.calls[1].request
        reused_title = second.entries[0].title

        # The caller gets a copy, not the cached object itself.
        second.entries[0].title = "Changed"
        third = feedparser.parse(FEED_URL)

    assert conditional_request.headers["If-None-Match"] == first.etag
    assert conditional_request.headers["If-Modified-Since"] == first.modified

    # The feed content was reused instead of being parsed again.
    assert second.status == 304
    assert second.from_cache is True
    assert second.etag == '"abc"'
    assert second.modified == MODIFIED
    assert second.feed.title == "Example feed"
    assert reused_title == "Example entry"

    # Mutating a returned result does not affect the cached copy.
    assert feedparser.http.get_cached_result(FEED_URL)["entries"][0].title == (
        "Example entry"
    )
    assert third.from_cache is True
    assert third.entries[0].title == "Example entry"


def test_etag_only():
    with responses.RequestsMock() as mock:
        mock.get(
            FEED_URL,
            body=FEED_XML,
            headers={"ETag": '"abc"'},
            content_type="application/rss+xml",
        )
        mock.get(FEED_URL, body=b"", status=304)

        first = feedparser.parse(FEED_URL)
        second = feedparser.parse(FEED_URL)
        headers = mock.calls[1].request.headers
    assert headers["If-None-Match"] == '"abc"'
    assert "If-Modified-Since" not in headers
    assert second.from_cache is True
    assert second.status == 304
    assert "modified_parsed" not in second
    assert first.entries


def test_last_modified_only():
    with responses.RequestsMock() as mock:
        mock.get(
            FEED_URL,
            body=FEED_XML,
            headers={"Last-Modified": MODIFIED},
            content_type="application/rss+xml",
        )
        mock.get(FEED_URL, body=b"", status=304)

        feedparser.parse(FEED_URL)
        second = feedparser.parse(FEED_URL)
        headers = mock.calls[1].request.headers
    assert headers["If-Modified-Since"] == MODIFIED
    assert "If-None-Match" not in headers
    assert second.from_cache is True
    assert second.status == 304
    assert second.feed.title == "Example feed"


def test_no_validators_means_no_conditional_request():
    with responses.RequestsMock() as mock:
        mock.get(FEED_URL, body=FEED_XML, content_type="application/rss+xml")
        mock.get(FEED_URL, body=FEED_XML, content_type="application/rss+xml")

        first = feedparser.parse(FEED_URL)
        second = feedparser.parse(FEED_URL)
        headers = mock.calls[1].request.headers
    assert "If-None-Match" not in headers
    assert "If-Modified-Since" not in headers
    assert first.from_cache is False
    assert second.from_cache is False


def test_changed_feed_replaces_cached_result():
    changed_feed = FEED_XML.replace(b"Example entry", b"Updated entry")

    with responses.RequestsMock() as mock:
        mock.get(
            FEED_URL,
            body=FEED_XML,
            headers={"ETag": '"abc"'},
            content_type="application/rss+xml",
        )
        mock.get(FEED_URL, body=changed_feed, headers={"ETag": '"def"'})
        mock.get(FEED_URL, body=b"", status=304)

        first = feedparser.parse(FEED_URL)
        second = feedparser.parse(FEED_URL)
        third = feedparser.parse(FEED_URL)
        second_headers = mock.calls[1].request.headers
        third_headers = mock.calls[2].request.headers

    assert first.entries[0].title == "Example entry"
    assert second.from_cache is False
    assert second.etag == '"def"'
    assert second.entries[0].title == "Updated entry"
    assert second_headers["If-None-Match"] == '"abc"'
    assert third_headers["If-None-Match"] == '"def"'
    assert third.from_cache is True
    assert third.entries[0].title == "Updated entry"


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(feedparser.http, "CACHE_MAX_SIZE", 2)

    with responses.RequestsMock() as mock:
        for index in range(3):
            url = f"https://example.com/feed{index}.xml"
            mock.get(
                url,
                body=FEED_XML,
                headers={"ETag": f'"{index}"'},
                content_type="application/rss+xml",
            )
            feedparser.parse(url)

    assert feedparser.http.get_cached_result("https://example.com/feed0.xml") is None
    assert feedparser.http.get_cached_result("https://example.com/feed1.xml")
    assert feedparser.http.get_cached_result("https://example.com/feed2.xml")


def test_non_http_input_is_not_cached():
    feedparser.parse(FEED_XML)

    assert feedparser.http._CACHE == {}


def test_result_without_validators_is_not_cached():
    with responses.RequestsMock() as mock:
        mock.get(
            FEED_URL,
            body=FEED_XML,
            headers={"ETag": '"abc"'},
            content_type="application/rss+xml",
        )
        mock.get(FEED_URL, body=FEED_XML, content_type="application/rss+xml")

        feedparser.parse(FEED_URL)
        feedparser.parse(FEED_URL)

    # The second response had no ETag or Last-Modified, so the stale
    # entry was dropped instead of being reused.
    assert feedparser.http.get_cached_result(FEED_URL) is None


def test_unexpected_304_without_cached_result():
    with responses.RequestsMock() as mock:
        mock.get(FEED_URL, body=b"", status=304)

        result = feedparser.parse(FEED_URL)

    assert result.status == 304
    assert result.from_cache is False
    assert result.feed == {}
    assert result.entries == []
