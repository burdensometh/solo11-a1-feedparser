import io

import pytest

import feedparser
import feedparser.urls

BASE_URI = "http://d.test/d/f.ext"


@pytest.mark.parametrize(
    "base, uri, expected_uri, description",
    (
        (
            "http://d.test/feed/",
            "images/a.png",
            "http://d.test/feed/images/a.png",
            "relative",
        ),
        (
            "http://d.test/feed/",
            "/images/a.png",
            "http://d.test/images/a.png",
            "root-relative",
        ),
        (
            "http://d.test/feed/",
            "https://cdn.test/a.png",
            "https://cdn.test/a.png",
            "absolute",
        ),
        ("http://d.test/feed/", "", "http://d.test/feed/", "empty points at the base"),
        ("", "images/a.png", "images/a.png", "no base"),
        ("", "/images/a.png", "/images/a.png", "no base, root-relative"),
    ),
)
def test_resolve_uri_reference(base, uri, expected_uri, description):
    assert feedparser.urls.resolve_uri_reference(base, uri) == expected_uri, description


def test_resolve_uri_reference_allows_every_scheme(monkeypatch):
    """Setting ACCEPTABLE_URI_SCHEMES to () allows every protocol."""

    monkeypatch.setattr(feedparser.urls, "ACCEPTABLE_URI_SCHEMES", ())
    assert (
        feedparser.urls.resolve_uri_reference("file:///tmp/base/", "images/a.png")
        == "file:///tmp/base/images/a.png"
    )


@pytest.mark.parametrize(
    "base, uri, expected_uri",
    (
        # A completed reference must be an HTTP(S) URL.
        ("javascript:alert(1)", "images/a.png", ""),
        ("file:///tmp/base/", "images/a.png", ""),
        # Absolute references are returned unchanged (with the historical
        # repair of extra slashes after the scheme).
        ("http://d.test/feed/", "magnet:?xt=1", "magnet:?xt=1"),
        ("http://d.test/feed/", "javascript:alert(1)", "javascript:alert(1)"),
        ("http://d.test/feed/", "http:///other.test/a.png", "http://other.test/a.png"),
    ),
)
def test_resolve_uri_reference_drops_non_http_results(base, uri, expected_uri):
    assert feedparser.urls.resolve_uri_reference(base, uri) == expected_uri


def test_resolve_uri_reference_counts_discarded_uris():
    tracker = feedparser.urls.URITracker()
    assert (
        feedparser.urls.resolve_uri_reference("javascript:alert(1)", "a.png", tracker)
        == ""
    )
    assert feedparser.urls.resolve_uri_reference("file:///tmp/", "b.png", tracker) == ""
    assert tracker.discarded_uris == 2
    assert not tracker.relative_uris


def test_resolve_uri_reference_keeps_original_relative_path():
    tracker = feedparser.urls.URITracker()
    assert (
        feedparser.urls.resolve_uri_reference(
            "http://d.test/feed/", "images/a.png", tracker
        )
        == "http://d.test/feed/images/a.png"
    )
    assert tracker.relative_uris == {"http://d.test/feed/images/a.png": "images/a.png"}
    assert tracker.discarded_uris == 0


@pytest.mark.parametrize(
    "document_base, href, expected_base",
    (
        ("http://d.test/feed/", "http://cdn.test/assets/", "http://cdn.test/assets/"),
        ("http://d.test/feed/", "assets/", "http://d.test/feed/assets/"),
        ("http://d.test/feed/", "/assets/", "http://d.test/assets/"),
        # A base that is not HTTP(S) cannot be used.
        ("http://d.test/feed/", "javascript:alert(1)", ""),
        ("http://d.test/feed/", "file:///tmp/", ""),
        # A relative base without a document base cannot be resolved.
        ("", "assets/", ""),
    ),
)
def test_resolve_base_href(document_base, href, expected_base):
    assert feedparser.urls.resolve_base_href(document_base, href) == expected_base


def test_find_base_href():
    assert (
        feedparser.urls.find_base_href('<base href="http://cdn.test/a/">')
        == "http://cdn.test/a/"
    )
    assert (
        feedparser.urls.find_base_href("<base href='http://cdn.test/a/'>")
        == "http://cdn.test/a/"
    )
    assert (
        feedparser.urls.find_base_href("<base href=http://cdn.test/a/>")
        == "http://cdn.test/a/"
    )
    # Entities are decoded.
    assert (
        feedparser.urls.find_base_href('<base href="http://cdn.test/?a=1&amp;b=2">')
        == "http://cdn.test/?a=1&b=2"
    )
    # The first base element wins.
    assert (
        feedparser.urls.find_base_href(
            '<base href="http://one.test/"><base href="http://two.test/">'
        )
        == "http://one.test/"
    )
    # Commented-out and unrelated elements are ignored.
    assert not feedparser.urls.find_base_href(
        '<!-- <base href="http://evil.test/"> --><img src="a.png">'
    )
    assert not feedparser.urls.find_base_href("<basefont>")
    assert not feedparser.urls.find_base_href('<base target="_blank">')


HTML_BASE_URI = "http://d.test/feed/index.html"


def _resolve(html_source, base_uri=HTML_BASE_URI, tracker=None, **kwargs):
    return feedparser.urls.resolve_relative_uris(
        html_source, base_uri, "utf-8", "text/html", tracker, **kwargs
    )


def test_resolve_relative_uris_uses_base_element():
    output = _resolve(
        '<base href="http://cdn.test/assets/"><img src="a.png">'
        '<a href="/x">x</a><link href="c.css">'
    )
    assert output == (
        '<base href="http://cdn.test/assets/" />'
        '<img src="http://cdn.test/assets/a.png" />'
        '<a href="http://cdn.test/x">x</a>'
        '<link href="http://cdn.test/assets/c.css" />'
    )


def test_resolve_relative_uris_relative_base_element():
    output = _resolve('<base href="assets/"><img src="a.png">')
    assert output == (
        '<base href="http://d.test/feed/assets/" />'
        '<img src="http://d.test/feed/assets/a.png" />'
    )


def test_resolve_relative_uris_base_element_used_regardless_of_position():
    # A <base> element applies to the whole document, not only to the
    # markup that follows it.
    output = _resolve(
        '<img src="a.png"><base href="http://cdn.test/assets/"><img src="b.png">'
    )
    assert output == (
        '<img src="http://cdn.test/assets/a.png" />'
        '<base href="http://cdn.test/assets/" />'
        '<img src="http://cdn.test/assets/b.png" />'
    )


def test_resolve_relative_uris_unusable_base_element_falls_back():
    # When the base element cannot produce an HTTP(S) URL the feed URL is
    # still the base, and the unusable href is kept verbatim.
    output = _resolve('<base href="javascript:alert(1)"><img src="a.png">')
    assert output == (
        '<base href="javascript:alert(1)" />' '<img src="http://d.test/feed/a.png" />'
    )


def test_resolve_relative_uris_without_base():
    # Without a base the relative references are preserved as written.
    output = _resolve('<img src="images/a.png"><a href="/x">x</a>', base_uri="")
    assert output == '<img src="images/a.png" /><a href="/x">x</a>'


def test_resolve_relative_uris_discards_and_counts():
    tracker = feedparser.urls.URITracker()
    output = _resolve(
        '<img src="javascript:evil()"><img src="data:image/png;base64,AA">'
        '<img src="a.png">',
        tracker=tracker,
    )
    assert output == (
        '<img src="" /><img src="" />' '<img src="http://d.test/feed/a.png" />'
    )
    assert tracker.discarded_uris == 2
    assert tracker.relative_uris == {"http://d.test/feed/a.png": "a.png"}


def test_resolve_relative_uris_empty_reference_keeps_base():
    # An empty reference points at the base itself and is never discarded.
    output = _resolve('<a href="">x</a>')
    assert output == '<a href="http://d.test/feed/index.html">x</a>'


def test_resolve_relative_uris_absolute_references_are_untouched():
    output = _resolve(
        '<a href="mailto:a@b.test">m</a><img src="magnet:?xt=1">'
        '<a href="https://cdn.test/x">x</a>'
    )
    assert output == (
        '<a href="mailto:a@b.test">m</a><img src="magnet:?xt=1" />'
        '<a href="https://cdn.test/x">x</a>'
    )


def _parse(feed_xml, response_headers=None, **kwargs):
    return feedparser.parse(
        io.StringIO(feed_xml), response_headers=response_headers, **kwargs
    )


FEED_WITH_BASE_ELEMENT = """
<rss version="2.0">
<channel>
<title>Example feed</title>
<item>
<title>Example item</title>
<description><![CDATA[<base href="http://cdn.test/assets/"><img src="a.png">]]></description>
</item>
</channel>
</rss>
"""


def test_parse_uses_base_element():
    result = _parse(
        FEED_WITH_BASE_ELEMENT,
        response_headers={"content-location": "http://d.test/feed.xml"},
        sanitize_html=False,
    )
    assert result.entries[0].description == (
        '<base href="http://cdn.test/assets/" />'
        '<img src="http://cdn.test/assets/a.png" />'
    )


def test_parse_discards_non_http_uris_and_counts():
    result = _parse(
        """
        <rss version="2.0">
        <channel>
        <item>
        <title>Example item</title>
        <description><![CDATA[
        <a href="javascript:evil()">bad</a>
        <a href="data:text/html;base64,AA">bad</a>
        <img src="images/a.png">
        ]]></description>
        </item>
        </channel>
        </rss>
        """,
        response_headers={"content-location": "http://d.test/feed/"},
    )
    assert '<a href="">bad</a>' in result.entries[0].description
    assert '<img src="http://d.test/feed/images/a.png" />' in (
        result.entries[0].description
    )
    assert result.discarded_uris == 2


def test_parse_keeps_original_relative_paths():
    result = _parse(
        """
        <rss version="2.0">
        <channel>
        <item>
        <title>Example item</title>
        <link>/relative/link</link>
        <description><![CDATA[<img src="images/a.png">]]></description>
        </item>
        </channel>
        </rss>
        """,
        response_headers={"content-location": "http://d.test/feed/"},
    )
    assert result.entries[0].link == "http://d.test/relative/link"
    assert "http://d.test/feed/images/a.png" in result.entries[0].description
    assert result.relative_uris == {
        "http://d.test/relative/link": "/relative/link",
        "http://d.test/feed/images/a.png": "images/a.png",
    }


def test_parse_relative_references_without_base_are_untouched():
    result = _parse("""
        <rss version="2.0">
        <channel>
        <item>
        <title>Example item</title>
        <link>/relative/link</link>
        <description><![CDATA[<img src="images/a.png">]]></description>
        </item>
        </channel>
        </rss>
        """)
    assert result.entries[0].link == "/relative/link"
    assert result.entries[0].description == '<img src="images/a.png" />'


def test_parse_resolve_relative_uris_off_keeps_markup():
    result = _parse(
        """
        <rss version="2.0">
        <channel>
        <item>
        <description><![CDATA[<img src="images/a.png">]]></description>
        </item>
        </channel>
        </rss>
        """,
        response_headers={"content-location": "http://d.test/feed/"},
        resolve_relative_uris=False,
    )
    assert result.entries[0].description == '<img src="images/a.png" />'


def test_parse_completes_uri_attributes():
    result = _parse(
        """
        <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
        <channel>
        <item>
        <enclosure url="media/a.mp3" length="1" type="audio/mpeg"/>
        <media:content url="media/b.mp4" type="video/mp4"/>
        <media:thumbnail url="thumb.jpg"/>
        </item>
        </channel>
        </rss>
        """,
        response_headers={"content-location": "http://d.test/feed/"},
    )
    assert result.entries[0].enclosures[0].href == "http://d.test/feed/media/a.mp3"
    assert result.entries[0]["media_content"][0]["url"] == (
        "http://d.test/feed/media/b.mp4"
    )
    assert result.entries[0]["media_thumbnail"][0]["url"] == (
        "http://d.test/feed/thumb.jpg"
    )


def test_parse_completes_json_feed_uris():
    result = _parse(
        """
        {
            "version": "https://jsonfeed.org/version/1",
            "title": "Example feed",
            "home_page_url": "/home",
            "items": [
                {
                    "id": "1",
                    "url": "posts/1",
                    "content_html": "<img src='a.png'>",
                    "attachments": [
                        {"url": "media/a.mp3", "mime_type": "audio/mpeg"}
                    ]
                }
            ]
        }
        """,
        response_headers={"content-location": "http://d.test/feed.json"},
    )
    assert result.feed.link == "http://d.test/home"
    assert result.entries[0].link == "http://d.test/posts/1"
    assert result.entries[0]["content"]["value"] == (
        '<img src="http://d.test/a.png" />'
    )
    # JSON Feed attachments are stored directly, without a ``links`` list
    # for FeedParserDict's ``enclosures`` alias to derive from.
    assert dict(result.entries[0])["enclosures"][0]["href"] == (
        "http://d.test/media/a.mp3"
    )
