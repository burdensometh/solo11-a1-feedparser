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

from __future__ import annotations

import copy
import threading
import typing

import requests

from .datetimes import _parse_date

# HTTP "Accept" header to send to servers when downloading feeds.
ACCEPT_HEADER: str = (
    "application/atom+xml"
    ",application/rdf+xml"
    ",application/rss+xml"
    ",application/x-netcdf"
    ",application/xml"
    ";q=0.9,text/xml"
    ";q=0.2,*/*"
    ";q=0.1"
)

# Parsed results from recent requests, keyed by URL.
# Keeping the results around allows a "304 Not Modified" response
# to be answered with the previously parsed feed instead of downloading
# and re-parsing content that hasn't changed.
CACHE_MAX_SIZE: int = 32
_CACHE: dict[str, dict[str, typing.Any]] = {}
_CACHE_LOCK = threading.Lock()


def copy_result(result: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """
    Return a copy of a parse result that shares no mutable values.

    Cached results are copied on the way in and on the way out so that
    callers can modify a result without affecting the cache, or each other.
    Exception instances (like ``SAXParseException``) cannot always be
    copied, so those are shared.
    """

    def copy_value(value: typing.Any) -> typing.Any:
        if isinstance(value, dict):
            copied = type(value)()
            for key, item in value.items():
                dict.__setitem__(copied, key, copy_value(item))
            return copied
        if isinstance(value, list):
            return [copy_value(item) for item in value]
        try:
            return copy.deepcopy(value)
        except Exception:
            return value

    return copy_value(result)


def get_cached_result(url: str) -> dict[str, typing.Any] | None:
    """Return the most recent parsed result for *url*, if it is cached."""
    with _CACHE_LOCK:
        cached = _CACHE.get(url)
        return copy_result(cached) if cached is not None else None


def update_cache(url: str, result: dict[str, typing.Any]) -> None:
    """Remember *result* if it can be reused for conditional requests."""

    if not (result.get("etag") or result.get("modified")):
        # Without validators a conditional request is impossible,
        # so there is nothing to gain by keeping the result around.
        with _CACHE_LOCK:
            _CACHE.pop(url, None)
        return

    copied = copy_result(result)
    with _CACHE_LOCK:
        # Move a re-cached URL to the end so the oldest entries go first.
        _CACHE.pop(url, None)
        _CACHE[url] = copied
        while len(_CACHE) > CACHE_MAX_SIZE:
            del _CACHE[next(iter(_CACHE))]


def get(
    url: str,
    result: dict[str, typing.Any],
    cached_result: dict[str, typing.Any] | None = None,
) -> bytes:
    request_headers = {"Accept": ACCEPT_HEADER}

    # Build a conditional request from the validators in the result
    # dictionary (as the caller may have set them) or, failing that,
    # from the previous response for the same URL.
    etag = result.get("etag") or (cached_result or {}).get("etag")
    modified = result.get("modified") or (cached_result or {}).get("modified")
    if etag:
        request_headers["If-None-Match"] = etag
    if modified:
        request_headers["If-Modified-Since"] = modified
    is_conditional = bool(etag or modified)

    try:
        response = requests.get(
            url,
            headers=request_headers,
            timeout=10,
        )
    except requests.RequestException as exception:
        result["bozo"] = True
        result["bozo_exception"] = exception
        return b""

    # Lowercase the HTTP header keys for comparisons per RFC 2616.
    result["headers"] = {k.lower(): v for k, v in response.headers.items()}

    # save HTTP headers
    if "etag" in result["headers"]:
        result["etag"] = result["headers"]["etag"]
    if "last-modified" in result["headers"]:
        modified = result["headers"]["last-modified"]
        if modified:
            result["modified"] = modified
            result["modified_parsed"] = _parse_date(modified)
    result["href"] = response.url
    result["status"] = response.status_code

    if response.status_code == 304 and is_conditional:
        # The server confirmed the feed hasn't changed, so there is no body
        # to parse. The caller returns the cached result instead.
        result["from_cache"] = True

    return response.content
