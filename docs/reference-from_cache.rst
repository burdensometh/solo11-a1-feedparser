``from_cache``
==================

A boolean value indicating whether the result was reused from a previous
download instead of being parsed again.

feedparser makes conditional HTTP requests using the ETag and Last-Modified
values from a previous response.  When the web server answers with status
code ``304`` (Not Modified), the previously parsed feed is returned with
``from_cache`` set to ``True``.  Otherwise ``from_cache`` is ``False``.

The purpose of conditional requests is explained more fully in
:ref:`http.etag`.

.. tip::

    ``from_cache`` is only ``True`` when the feed was retrieved from a web
    server that answered a conditional request with status code ``304``.
    If the feed was parsed from a local file or from a string in memory,
    ``from_cache`` will be ``False``.
