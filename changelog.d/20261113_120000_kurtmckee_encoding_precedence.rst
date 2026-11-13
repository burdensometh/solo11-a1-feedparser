Fixed
-----

*   Determine the character encoding by a fixed precedence: the byte order
    mark first, then the XML declaration, then the HTTP Content-Type
    ``charset`` parameter. Conflicting declarations are reported through
    ``bozo_exception`` instead of silently changing the encoding.
*   Auto-detect the encoding when the declared encoding cannot decode the
    document, so feeds that are really GBK but declare utf-8 are no longer
    parsed as mojibake.
*   Strip a byte order mark that precedes the start of the document or an
    XML declaration, so it never appears in the parsed values.
*   Decode undecodable documents as utf-8 and replace the invalid bytes.
