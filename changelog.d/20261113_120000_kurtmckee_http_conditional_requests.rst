Added
-----

*   Make conditional HTTP requests automatically.
    feedparser now stores the ``ETag`` and ``Last-Modified`` values from
    each response and sends them back as ``If-None-Match`` and
    ``If-Modified-Since`` request headers the next time the same URL is
    requested.

    When the server answers ``304 Not Modified``, the previously parsed
    result is returned instead of downloading and re-parsing the feed again.
    Such results are marked with the new ``from_cache`` key.
