.. _advanced.encoding:

Character Encoding Detection
============================

`RFC 3023 <http://www.ietf.org/rfc/rfc3023.txt>`_ defines the interaction
between :abbr:`XML (Extensible Markup Language)` and :abbr:`HTTP (Hypertext Transfer Protocol)`
as it relates to character encoding.  :abbr:`XML (Extensible Markup Language)`
and :abbr:`HTTP (Hypertext Transfer Protocol)` have different ways of
specifying character encoding and different defaults in case no encoding is
specified, and determining which value takes precedence depends on a variety of
factors.


Introduction to Character Encoding
----------------------------------

In :abbr:`XML (Extensible Markup Language)`, the character encoding is optional
and may be given in the :abbr:`XML (Extensible Markup Language)` declaration in
the first line of the document, like this:

..  code-block:: xml

    <?xml version="1.0" encoding="utf-8"?>

If no encoding is given, :abbr:`XML (Extensible Markup Language)` supports the
use of a Byte Order Mark to identify the document as some flavor of UTF-32,
UTF-16, or UTF-8.  `Section F of the XML specification <http://www.w3.org/TR/REC-xml/#sec-guessing-no-ext-info>`_
outlines the process for determining the character encoding based on unique
properties of the Byte Order Mark in the first two to four bytes of the
document.

If no encoding is specified and no Byte Order Mark is present, :abbr:`XML (Extensible Markup Language)`
defaults to UTF-8.

:abbr:`HTTP (Hypertext Transfer Protocol)` uses :abbr:`MIME` to define a method
of specifying the character encoding, as part of the Content-Type :abbr:`HTTP (Hypertext Transfer Protocol)`
header, which looks like this:

..  code-block:: text

    Content-Type: text/html; charset="utf-8"


If no charset is specified, :abbr:`HTTP (Hypertext Transfer Protocol)` defaults
to iso-8859-1, but only for text/* media types. For other media types, the
default encoding is undefined, which is where :abbr:`RFC (Request For Comments)` 3023 comes in.

According to :abbr:`RFC (Request For Comments)` 3023, if the media type given
in the Content-Type :abbr:`HTTP (Hypertext Transfer Protocol)` header is
application/xml, application/xml-dtd, application/xml-external-parsed-entity,
or any one of the subtypes of application/xml such as application/atom+xml or
application/rss+xml or even application/rdf+xml, then the encoding is


#. the encoding given in the ``charset`` parameter of the Content-Type :abbr:`HTTP (Hypertext Transfer Protocol)` header, or

#. the encoding given in the encoding attribute of the :abbr:`XML (Extensible Markup Language)` declaration within the document, or

#. utf-8.


On the other hand, if the media type given in the Content-Type
:abbr:`HTTP (Hypertext Transfer Protocol)` header is text/xml,
text/xml-external-parsed-entity, or a subtype like text/AnythingAtAll+xml, then
the encoding attribute of the :abbr:`XML (Extensible Markup Language)`
declaration within the document is ignored completely, and the encoding is


#. the encoding given in the charset parameter of the Content-Type :abbr:`HTTP (Hypertext Transfer Protocol)` header, or

#. us-ascii.

..  note::

    :program:`Universal Feed Parser` does not follow the :abbr:`RFC (Request For Comments)` 3023 ordering shown above.
    See :ref:`advanced.encoding.incorrect` for the ordering it does use.


.. _advanced.encoding.incorrect:

Handling Incorrectly-Declared Encodings
---------------------------------------

:program:`Universal Feed Parser` determines the character encoding in a fixed
order of precedence:

#. the byte order mark (BOM) at the start of the document,

#. the encoding named in the encoding attribute of the :abbr:`XML (Extensible Markup Language)` declaration,

#. the encoding given in the ``charset`` parameter of the Content-Type :abbr:`HTTP (Hypertext Transfer Protocol)` header.

The first of these sources that declares an encoding wins. When they
disagree, the conflict is recorded: the ``bozo`` bit is set to ``1`` and
``bozo_exception`` is set to ``feedparser.CharacterEncodingOverride``, whose
message names the conflicting sources. This fixed ordering deliberately
departs from :abbr:`RFC (Request For Comments)` 3023, in which the
Content-Type ``charset`` parameter overrides the :abbr:`XML (Extensible Markup Language)`
declaration for text/xml media types. In practice many feeds declare their
encoding correctly in the document while the server sends a generic or
incorrect Content-Type. :abbr:`RFC (Request For Comments)` 7303, which
supersedes :abbr:`RFC (Request For Comments)` 3023, likewise gives the byte
order mark precedence.

If none of the sources declares an encoding, or if the declared encodings
cannot decode the document, the encoding is auto-detected. Detection uses
`chardet <https://github.com/chardet/chardet>`_ if it is installed, and
`charset-normalizer <https://github.com/jawah/charset_normalizer>`_ otherwise.
When :program:`Universal Feed Parser` has to use an encoding other than the
declared one, it sets the ``bozo`` bit to ``1`` and sets ``bozo_exception``
to ``feedparser.CharacterEncodingOverride``.

As a last resort, the document is decoded as utf-8 and any invalid bytes are
replaced with ``�`` (U+FFFD). In this case the ``bozo`` bit is set to ``1``
and ``bozo_exception`` is set to ``feedparser.CharacterEncodingUnknown``.


Handling Incorrectly-Declared Media Types
-----------------------------------------

:abbr:`RFC (Request For Comments)` 3023 only applies when the feed is served
over :abbr:`HTTP (Hypertext Transfer Protocol)` with a Content-Type that
declares the feed to be some kind of :abbr:`XML (Extensible Markup Language)`.
However, some web servers are severely misconfigured and serve feeds with a
Content-Type of text/plain, application/octet-stream, or some completely bogus
media type.

:program:`Universal Feed Parser` will attempt to parse such feeds, but it will
set the ``bozo`` bit to ``1`` and set ``bozo_exception`` to
``feedparser.NonXMLContentType``.


.. seealso::

    * `RFC 3023 <http://www.ietf.org/rfc/rfc3023.txt>`_

    * `Section F of the XML specification <http://www.w3.org/TR/REC-xml/#sec-guessing-no-ext-info>`_

    * `On the well-formedness of XML documents served as text/plain <http://www.imc.org/atom-syntax/mail-archive/msg05575.html>`_
