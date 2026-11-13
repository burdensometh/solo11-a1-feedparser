.. _http.etag:

ETag and Last-Modified Headers
==============================

ETags and Last-Modified headers are two ways that feed publishers can save
bandwidth, but they only work if clients take advantage of them.
:program:`Universal Feed Parser` gives you the ability to take advantage of
these features, but you must use them properly.

The basic concept is that a feed publisher may provide a special
:abbr:`HTTP (Hypertext Transfer Protocol)` header, called an ETag, when it
publishes a feed.  You should send this ETag back to the server on subsequent
requests.  If the feed has not changed since the last time you requested it,
the server will return a special :abbr:`HTTP (Hypertext Transfer Protocol)`
status code (``304``) and no feed data.

feedparser does this automatically.  It remembers the ETag and Last-Modified
values from each response, sends them back as ``If-None-Match`` and
``If-Modified-Since`` request headers the next time the same URL is requested,
and reuses the previously parsed result when the server answers ``304``.
Reused results are marked with ``from_cache``.

Using ETags to reduce bandwidth
-------------------------------

..  code-block:: pycon

    >>> import feedparser
    >>> d = feedparser.parse('$READTHEDOCS_CANONICAL_URL/examples/atom10.xml')
    >>> d.etag
    '"6c132-941-ad7e3080"'
    >>> d.from_cache
    False
    >>> # The second request is made conditionally, automatically.
    >>> d2 = feedparser.parse('$READTHEDOCS_CANONICAL_URL/examples/atom10.xml')
    >>> d2.status
    304
    >>> d2.from_cache
    True
    >>> # The previously parsed feed is returned instead of being parsed again.
    >>> d2.feed.title
    'Sample Feed'

There is a related concept which accomplishes the same thing, but slightly
differently.  In this case, the server publishes the last-modified date of the
feed in the :abbr:`HTTP (Hypertext Transfer Protocol)` header.  You can send
this back to the server on subsequent requests, and if the feed has not
changed, the server will return :abbr:`HTTP (Hypertext Transfer Protocol)`
status code ``304`` and no feed data.


Using Last-Modified headers to reduce bandwidth
-----------------------------------------------

..  code-block:: pycon

    >>> import feedparser
    >>> d = feedparser.parse('$READTHEDOCS_CANONICAL_URL/examples/atom10.xml')
    >>> d.modified
    Fri, 11 Jun 2012 23:00:34 GMT
    >>> d.modified_parsed
    (2004, 6, 11, 23, 0, 34, 4, 163, 0)
    >>> d2 = feedparser.parse('$READTHEDOCS_CANONICAL_URL/examples/atom10.xml')
    >>> d2.status
    304
    >>> d2.from_cache
    True

Clients should support both ETag and Last-Modified headers, as some servers support one but not the other.


.. important::

    If you do not support ETag and Last-Modified headers, you will repeatedly
    download feeds that have not changed.  This wastes your bandwidth and the
    publisher's bandwidth, and the publisher may ban you from accessing their
    server.


.. note::

    Conditional requests are made automatically when feedparser knows
    the ETag or Last-Modified value from a previous response for the same URL.
    Validators are stored in the result dictionary, and recent results
    (up to ``feedparser.http.CACHE_MAX_SIZE`` URLs) are kept so a ``304``
    response can be answered with the previously parsed feed.

    To avoid a conditional request for a URL, use an HTTP client like
    the ``requests`` package to request the URL yourself and pass
    the content to :func:`feedparser.parse`.


.. seealso::

    * `HTTP Conditional Get For RSS Hackers <http://fishbowl.pastiche.org/2002/10/21/http_conditional_get_for_rss_hackers>`_
    * `HTTP Web Services <http://diveintopython.org/http_web_services/>`_
