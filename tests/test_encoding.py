import codecs
import glob
import os

import pytest

import feedparser
import feedparser.encodings

from .helpers import (
    fail_unless_eval,
    get_file_contents,
    get_http_test_data,
    get_test_data,
)

encoding_files = glob.glob(os.path.join(".", "tests", "encoding", "*.xml"))
local_files = [file for file in encoding_files if "http" not in file]
http_files = [file for file in encoding_files if "http" in file]


def test_doctype_replacement():
    """
    Ensure that non-ASCII-compatible encodings don't hide disallowed ENTITY declarations
    """

    doc = """<?xml version="1.0" encoding="utf-16be"?>
    <!DOCTYPE feed [
        <!ENTITY exponential1 "bogus ">
        <!ENTITY exponential2 "&exponential1;&exponential1;">
        <!ENTITY exponential3 "&exponential2;&exponential2;">
    ]>
    <feed><title type="html">&exponential3;</title></feed>"""
    doc = codecs.BOM_UTF16_BE + doc.encode("utf-16be")
    result = feedparser.parse(doc)
    assert result["feed"]["title"] == "&amp;exponential3"


def test_gb2312_converted_to_gb18030_in_xml_encoding():
    # \u55de was chosen because it exists in gb18030 but not gb2312
    feed = """<?xml version="1.0" encoding="gb2312"?>
            <feed><title>\u55de</title></feed>"""
    result = feedparser.parse(
        feed.encode("gb18030"), response_headers={"Content-Type": "text/xml"}
    )
    assert result.encoding == "gb18030"


CJK_FEED = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<rss version="2.0"><channel>'
    "<title>\u4e2d\u6587\u6807\u9898</title>"
    "<description>\u8fd9\u662f\u4e00\u4e2a\u6d4b\u8bd5\u8ba2\u9605\u6e90\uff0c"
    "\u5305\u542b\u8db3\u591f\u7684\u4e2d\u6587\u5185\u5bb9\u4ee5\u4fbf\u7f16\u7801"
    "\u68c0\u6d4b\u5668\u8bc6\u522b\u3002</description>"
    "</channel></rss>"
)


@pytest.mark.parametrize(
    "response_headers",
    (
        {},
        {"Content-Type": "application/rss+xml"},
        {"Content-Type": "application/rss+xml; charset=utf-8"},
        {"Content-Type": "text/xml"},
        {"Content-Type": "text/xml; charset=utf-8"},
    ),
)
def test_gbk_declared_as_utf8_is_detected(response_headers):
    """A GBK document that claims to be UTF-8 must not stay mojibake.

    The declared encoding cannot decode the data, so the encoding is
    detected instead of falling back to a single-byte encoding such as
    windows-1252 that decodes anything.
    """
    result = feedparser.parse(CJK_FEED.encode("gbk"), response_headers=response_headers)

    assert result["feed"]["title"] == "\u4e2d\u6587\u6807\u9898"
    assert result["feed"]["description"].startswith(
        "\u8fd9\u662f\u4e00\u4e2a\u6d4b\u8bd5\u8ba2\u9605\u6e90"
    )
    # Different detectors name the same encoding differently.
    assert result.encoding.lower() in {"gb18030", "gbk", "gb2312"}
    # The declared encoding was wrong, so this is reported.
    assert result.bozo is True
    assert isinstance(result.bozo_exception, feedparser.CharacterEncodingOverride)


@pytest.mark.parametrize(
    "bom, encoding",
    (
        (codecs.BOM_UTF8, "utf-8"),
        (codecs.BOM_UTF16_LE, "utf-16le"),
        (codecs.BOM_UTF16_BE, "utf-16be"),
        (codecs.BOM_UTF32_LE, "utf-32le"),
        (codecs.BOM_UTF32_BE, "utf-32be"),
    ),
)
@pytest.mark.parametrize(
    "response_headers",
    ({}, {"Content-Type": "text/xml"}, {"Content-Type": "application/rss+xml"}),
)
def test_bom_without_declaration(bom, encoding, response_headers):
    """A BOM is honored, and the BOM never leaks into the parsed values."""
    feed = (
        '<rss version="2.0">'
        "<channel><title>\u4e2d\u6587\u6807\u9898</title></channel></rss>"
    )
    data = bom + feed.encode(encoding)

    result = feedparser.parse(data, response_headers=response_headers)

    assert result["feed"]["title"] == "\u4e2d\u6587\u6807\u9898"
    assert not result["feed"]["title"].startswith("\ufeff")
    assert result.encoding == encoding
    # With no other declaration there is nothing to conflict with.
    assert result.bozo is False


def test_bom_takes_precedence_over_xml_declaration():
    feed = '<rss version="2.0"><channel><title>caf\u00e9</title></channel></rss>'
    data = codecs.BOM_UTF8 + feed.encode("utf-8")

    result = feedparser.parse(
        data,
        response_headers={"Content-Type": "application/rss+xml; charset=iso-8859-1"},
    )

    assert result["feed"]["title"] == "caf\u00e9"
    assert result.encoding == "utf-8"
    assert result.bozo is True
    assert isinstance(result.bozo_exception, feedparser.CharacterEncodingOverride)
    assert "byte order mark" in str(result.bozo_exception)


def test_xml_declaration_takes_precedence_over_http_header():
    feed = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<rss version="2.0"><channel><title>caf\u00e9</title></channel></rss>'
    )

    result = feedparser.parse(
        feed.encode("utf-8"),
        response_headers={"Content-Type": "text/xml; charset=iso-8859-1"},
    )

    assert result["feed"]["title"] == "caf\u00e9"
    assert result.encoding == "utf-8"
    assert result.bozo is True
    assert isinstance(result.bozo_exception, feedparser.CharacterEncodingOverride)
    assert "XML declaration" in str(result.bozo_exception)


def test_http_charset_used_when_nothing_else_is_declared():
    feed = '<rss version="2.0"><channel><title>caf\u00e9</title></channel></rss>'

    result = feedparser.parse(
        feed.encode("iso-8859-1"),
        response_headers={"Content-Type": "application/rss+xml; charset=iso-8859-1"},
    )

    assert result["feed"]["title"] == "caf\u00e9"
    assert result.encoding == "iso-8859-1"
    assert result.bozo is False


def test_conflicting_declarations_are_reported_as_warning():
    """Conflicts win by precedence and are reported via bozo_exception."""
    feed = (
        '<?xml version="1.0" encoding="iso-8859-1"?>'
        '<rss version="2.0"><channel><title>caf\u00e9</title></channel></rss>'
    )

    result = feedparser.parse(
        feed.encode("iso-8859-1"),
        response_headers={"Content-Type": "application/rss+xml; charset=utf-8"},
    )

    assert result["feed"]["title"] == "caf\u00e9"
    assert result.encoding == "iso-8859-1"
    assert result.bozo is True
    exception_text = str(result.bozo_exception)
    assert "conflicting encodings" in exception_text
    assert "iso-8859-1" in exception_text
    assert "utf-8" in exception_text


def test_undetectable_data_falls_back_to_utf8_with_replacement(monkeypatch):
    """If no detector can decode the data, replace the bad bytes as utf-8."""
    # Disable the optional detectors so the fallback is reached. A detector
    # can decode almost anything because single-byte encodings accept every
    # byte, so this path is otherwise unreachable.
    monkeypatch.setattr(feedparser.encodings, "lazy_encoding_detectors", [])

    data = (
        b'<rss version="2.0"><channel>'
        b"<title>bad \xff\xfe bytes</title></channel></rss>"
    )

    result = feedparser.parse(data, response_headers={"Content-Type": "text/xml"})

    assert result.encoding == "utf-8"
    assert "\ufffd" in result["feed"]["title"]
    assert result.bozo is True
    assert isinstance(result.bozo_exception, feedparser.CharacterEncodingUnknown)


@pytest.mark.parametrize("file", local_files)
def test_local_encoding_file(file):
    data, text = get_file_contents(file)
    description, eval_string, skip_unless = get_test_data(file, text)
    assert eval(skip_unless)
    fail_unless_eval(file, eval_string)


@pytest.mark.parametrize("file", http_files)
def test_http_encoding_file(file):
    data, text = get_file_contents(file)
    url, description, eval_string, skip_unless = get_http_test_data(file, data, text)
    fail_unless_eval(url, eval_string)


@pytest.mark.parametrize(
    "encoding",
    (
        "437",
        "850",
        "852",
        "855",
        "857",
        "860",
        "861",
        "862",
        "863",
        "865",
        "866",
        "cp037",
        "cp1125",
        "cp1250",
        "cp1251",
        "cp1252",
        "cp1253",
        "cp1254",
        "cp1255",
        "cp1256",
        "cp1257",
        "cp1258",
        "cp437",
        "cp500",
        "cp737",
        "cp775",
        "cp850",
        "cp852",
        "cp855",
        "cp856",
        "cp857",
        "cp860",
        "cp861",
        "cp862",
        "cp863",
        "cp864",
        "cp865",
        "cp866",
        "cp874",
        "cp875",
        "cp_is",
        "csibm037",
        "csibm500",
        "csibm855",
        "csibm857",
        "csibm860",
        "csibm861",
        "csibm863",
        "csibm864",
        "csibm865",
        "csibm866",
        "cskoi8r",
        "cspc775baltic",
        "cspc850multilingual",
        "cspc862latinhebrew",
        "cspc8codepage437",
        "cspcp852",
        "ebcdic-cp-be",
        "ebcdic-cp-ca",
        "ebcdic-cp-ch",
        "ebcdic-cp-nl",
        "ebcdic-cp-us",
        "ebcdic-cp-wt",
        "ebcdic_cp_be",
        "ebcdic_cp_ca",
        "ebcdic_cp_ch",
        "ebcdic_cp_nl",
        "ebcdic_cp_us",
        "ebcdic_cp_wt",
        "ibm037",
        "ibm039",
        "ibm1140",
        "ibm437",
        "ibm500",
        "ibm775",
        "ibm850",
        "ibm852",
        "ibm855",
        "ibm857",
        "ibm860",
        "ibm861",
        "ibm862",
        "ibm863",
        "ibm864",
        "ibm865",
        "ibm866",
        "koi8-r",
        "koi8-t",
        "koi8-u",
        "mac-cyrillic",
        "maccentraleurope",
        "maccyrillic",
        "macgreek",
        "maciceland",
        "macintosh",
        "maclatin2",
        "macroman",
        "macturkish",
        "windows-1250",
        "windows-1251",
        "windows-1252",
        "windows-1253",
        "windows-1254",
        "windows-1255",
        "windows-1256",
        "windows-1257",
        "windows-1258",
        "windows_1250",
        "windows_1251",
        "windows_1252",
        "windows_1253",
        "windows_1254",
        "windows_1255",
        "windows_1256",
        "windows_1257",
        "windows_1258",
    ),
)
def test_encoding(encoding):
    """The XML encoding declaration must be found and honored in binary content."""
    expected = b"\x80".decode(encoding)
    data = f"""
        <?xml version="1.0" encoding="{encoding}"?>
        <feed version="0.3" xmlns="http://purl.org/atom/ns#">
        <title>{expected}</title>
        </feed>
    """

    result = feedparser.parse(data.strip().encode(encoding))
    assert result["encoding"] == encoding
    assert result["feed"]["title"] == expected
