# Copyright 2010-2025 Kurt McKee <contactme@kurtmckee.org>
# Copyright 2002-2008 Mark Pilgrim
# All rights reserved.
#
# This file is a part of feedparser.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS 'AS IS'
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import re
import urllib.parse
import xml.sax.saxutils

from .html import BaseHTMLProcessor

# If you want feedparser to allow all URL schemes, set this to ()
# List culled from Python's urlparse documentation at:
#   http://docs.python.org/library/urlparse.html
# as well as from "URI scheme" at Wikipedia:
#   https://secure.wikimedia.org/wikipedia/en/wiki/URI_scheme
# Many more will likely need to be added!
ACCEPTABLE_URI_SCHEMES = (
    "file",
    "ftp",
    "gopher",
    "h323",
    "hdl",
    "http",
    "https",
    "imap",
    "magnet",
    "mailto",
    "mms",
    "news",
    "nntp",
    "prospero",
    "rsync",
    "rtsp",
    "rtspu",
    "sftp",
    "shttp",
    "sip",
    "sips",
    "snews",
    "svn",
    "svn+ssh",
    "telnet",
    "wais",
    # Additional common-but-unofficial schemes
    "aim",
    "callto",
    "cvs",
    "facetime",
    "feed",
    "git",
    "gtalk",
    "irc",
    "ircs",
    "irc6",
    "itms",
    "mms",
    "msnim",
    "skype",
    "ssh",
    "smb",
    "svn",
    "ymsg",
)

_urifixer = re.compile("^([A-Za-z][A-Za-z0-9+-.]*://)(/*)(.*?)")

# Relative references are only completed when the result is an HTTP(S) URL.
# Other protocols are discarded so that e.g. a `javascript:` reference cannot
# sneak into a value through a crafted base URI.
COMPLETED_URI_SCHEMES = ("http", "https")

_uri_scheme = re.compile("^[A-Za-z][A-Za-z0-9+.-]*:")


def _get_uri_scheme(uri):
    match = _uri_scheme.match(uri.strip())
    return match.group(0)[:-1].lower() if match else ""


def _is_relative_reference(uri):
    """Return whether *uri* is a relative reference (it has no scheme)."""

    return not _uri_scheme.match(uri.strip())


def _is_completed_scheme_allowed(uri):
    """Return whether a completed reference may use the *uri*'s scheme.

    Emptying :data:`ACCEPTABLE_URI_SCHEMES` is the documented way to allow
    every protocol, so the HTTP(S)-only rule only applies while the list is
    not empty.
    """

    if not ACCEPTABLE_URI_SCHEMES:
        return True
    return _get_uri_scheme(uri) in COMPLETED_URI_SCHEMES


class URITracker:
    """Collect results while relative URI references are completed.

    :ivar discarded_uris: The number of references that were discarded
        because completing them produced a non-HTTP(S) URI.
    :ivar relative_uris: A mapping of each completed URI to the original
        relative reference, so callers can still see what the feed wrote.
    """

    def __init__(self):
        self.discarded_uris = 0
        self.relative_uris = {}

    def record(self, original, resolved):
        if original and resolved and _is_relative_reference(original):
            self.relative_uris.setdefault(resolved, original)

    def discard(self, original):
        self.discarded_uris += 1


def resolve_uri_reference(base, value, tracker=None):
    """Complete a single URI reference against *base*.

    Absolute references are returned unchanged, so identifiers that use
    non-HTTP schemes (such as ``tag:`` or ``urn:``) are not affected.

    Relative references are joined with *base*.  When the join does not
    produce an absolute reference -- because there is no base, or because
    the base is itself relative -- there is nothing to complete them with,
    so the original relative reference is preserved.  Completed references
    must use the ``http`` or ``https`` scheme; anything else is discarded
    (an empty string is returned) and counted in *tracker*.  Emptying
    :data:`ACCEPTABLE_URI_SCHEMES` allows every protocol, as documented for
    that variable.

    :type base: str
    :type value: str
    :type tracker: URITracker | None
    :rtype: str
    """

    if not isinstance(value, str):
        return value
    if not _is_relative_reference(value):
        # Absolute references are not completed, but they keep the historical
        # normalization performed by :func:`_urljoin` (e.g. ``http:///host``).
        return _urljoin(base, value)
    if not base:
        return value
    resolved = _urljoin(base, value)
    if not resolved:
        return value
    if not _get_uri_scheme(resolved):
        # The join did not complete the reference.  When the base itself is
        # relative, the reference simply remains relative; when the base is
        # absolute, the reference could not be built into a usable URI.
        if _get_uri_scheme(base):
            if tracker is not None:
                tracker.discard(value)
            return ""
        return value
    if not _is_completed_scheme_allowed(resolved):
        if tracker is not None:
            tracker.discard(value)
        return ""
    if tracker is not None:
        tracker.record(value, resolved)
    return resolved


def resolve_base_href(document_base, href):
    """Resolve a ``<base href>`` value into the base for the document.

    The document base element is the preferred base for relative references.
    A relative ``href`` is itself resolved against *document_base*.  When the
    result is not an HTTP(S) URI no usable base is returned and the caller
    keeps the base it already had.

    :rtype: str
    """

    if not href:
        return ""
    if _is_relative_reference(href):
        if not document_base:
            return ""
        resolved = _urljoin(document_base, href)
    else:
        resolved = href
    if not resolved or not _get_uri_scheme(resolved):
        return ""
    if not _is_completed_scheme_allowed(resolved):
        return ""
    return resolved


def _urljoin(base, uri):
    uri = _urifixer.sub(r"\1\3", uri)
    try:
        uri = urllib.parse.urljoin(base, uri)
    except ValueError:
        uri = ""
    return uri


def make_safe_absolute_uri(base, rel=None):
    # bail if ACCEPTABLE_URI_SCHEMES is empty
    if not ACCEPTABLE_URI_SCHEMES:
        return _urljoin(base, rel or "")
    if not base:
        return rel or ""
    if not rel:
        try:
            scheme = urllib.parse.urlparse(base)[0]
        except ValueError:
            return ""
        if not scheme or scheme in ACCEPTABLE_URI_SCHEMES:
            return base
        return ""
    uri = _urljoin(base, rel)
    if uri.strip().split(":", 1)[0] not in ACCEPTABLE_URI_SCHEMES:
        return ""
    return uri


class RelativeURIResolver(BaseHTMLProcessor):
    relative_uris = {
        ("a", "href"),
        ("applet", "codebase"),
        ("area", "href"),
        ("audio", "src"),
        ("blockquote", "cite"),
        ("body", "background"),
        ("del", "cite"),
        ("form", "action"),
        ("frame", "longdesc"),
        ("frame", "src"),
        ("iframe", "longdesc"),
        ("iframe", "src"),
        ("head", "profile"),
        ("img", "longdesc"),
        ("img", "src"),
        ("img", "usemap"),
        ("input", "src"),
        ("input", "usemap"),
        ("ins", "cite"),
        ("link", "href"),
        ("object", "classid"),
        ("object", "codebase"),
        ("object", "data"),
        ("object", "usemap"),
        ("q", "cite"),
        ("script", "src"),
        ("source", "src"),
        ("video", "poster"),
        ("video", "src"),
    }

    def __init__(self, baseuri, encoding, _type, tracker=None):
        BaseHTMLProcessor.__init__(self, encoding, _type)
        self.baseuri = baseuri or ""
        self.tracker = tracker
        # The effective base declared by a <base href="..."> element, if any.
        self.base_element = ""

    def set_base_element(self, href):
        """Use *href* from a ``<base>`` element as the preferred base.

        A relative ``href`` is resolved against the document base (the feed
        URL or ``xml:base``).  When it cannot produce an HTTP(S) URI the
        document base stays in effect.
        """

        self.base_element = resolve_base_href(self.baseuri, href)
        if self.base_element and self.tracker is not None:
            self.tracker.record(href, self.base_element)

    @property
    def effective_base(self):
        return self.base_element or self.baseuri

    def resolve_uri(self, uri):
        value = uri.strip()
        if not value:
            # An empty reference points at the base itself, as before.
            return _urljoin(self.effective_base, value)

        scheme = _get_uri_scheme(value)
        if scheme:
            # Absolute references are never completed.  Keep the legacy
            # safety check for schemes that are not explicitly allowed.
            if ACCEPTABLE_URI_SCHEMES and scheme not in ACCEPTABLE_URI_SCHEMES:
                if self.tracker is not None:
                    self.tracker.discard(value)
                return ""
            # Keep the historical repair of malformed absolute URIs.
            return _urljoin(self.effective_base, value)

        return resolve_uri_reference(self.effective_base, value, self.tracker)

    def unknown_starttag(self, tag, attrs):
        attrs = self.normalize_attrs(attrs)
        if tag == "base":
            # The base element's own href is resolved against the document
            # base so the markup keeps a usable absolute reference.
            attrs = [
                (
                    key,
                    (
                        self._resolve_base_element_href(value)
                        if key == "href" and value.strip()
                        else value
                    ),
                )
                for key, value in attrs
            ]
            super().unknown_starttag(tag, attrs)
            return
        rewritten = []
        for key, value in attrs:
            if (tag, key) in self.relative_uris:
                # Call unconditionally: a discarded reference resolves to an
                # empty string, which must not fall back to the original.
                value = self.resolve_uri(value)
            rewritten.append((key, value))
        super().unknown_starttag(tag, rewritten)

    def _resolve_base_element_href(self, href):
        """Return *href* made absolute against the document base."""

        return resolve_base_href(self.baseuri, href.strip()) or href


_comment = re.compile(r"<!--.*?-->", re.DOTALL)
_base_element = re.compile(
    r"<((?:[A-Za-z][\w.-]*:)?base)(?=[\s/>])([^>]*)>", re.IGNORECASE | re.DOTALL
)
_href_attribute = re.compile(
    r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.IGNORECASE
)


def find_base_href(html_source):
    """Return the href of the first ``<base>`` element, if any.

    The value is returned exactly as written, with entity references decoded.
    Comments are skipped so that a commented-out base element is ignored.
    Resolution happens in :func:`resolve_base_href`.
    """

    for match in _base_element.finditer(_comment.sub("", html_source)):
        if match.group(1).lower().split(":")[-1] != "base":
            continue
        href_match = _href_attribute.search(match.group(2))
        if href_match:
            href = next(group for group in href_match.groups() if group is not None)
            return xml.sax.saxutils.unescape(href, {'"': "&quot;", "'": "&apos;"})
    return ""


def resolve_relative_uris(html_source, base_uri, encoding, type_, tracker=None):
    p = RelativeURIResolver(base_uri, encoding, type_, tracker)
    base_href = find_base_href(html_source)
    if base_href:
        p.set_base_element(base_href)
    p.feed(html_source)
    return p.output()
