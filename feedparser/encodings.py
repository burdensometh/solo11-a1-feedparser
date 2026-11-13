# Character encoding routines
# Copyright 2010-2025 Kurt McKee <contactme@kurtmckee.org>
# Copyright 2002-2008 Mark Pilgrim
# All rights reserved.
#
# This file is a part of feedparser.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
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

import codecs
import io
import re
import typing


# Encoding detectors are optional. chardet is preferred when installed so
# that its encoding names and results stay stable, then charset-normalizer
# (a dependency of requests) is used as a fallback.
lazy_encoding_detectors: list[typing.Callable[[bytes], str]] = []

try:
    try:
        import cchardet as chardet  # type: ignore[import]
    except ImportError:
        import chardet  # type: ignore[no-redef]
except ImportError:
    pass
else:

    def lazy_chardet_encoding(data: bytes) -> str:
        return chardet.detect(data)["encoding"] or ""

    lazy_encoding_detectors.append(lazy_chardet_encoding)

try:
    import charset_normalizer as _charset_normalizer
except ImportError:
    pass
else:

    def lazy_charset_normalizer_encoding(data: bytes) -> str:
        try:
            best_match = _charset_normalizer.from_bytes(data).best()
        except Exception:  # noqa: BLE001 - detectors can fail on odd input
            return ""
        if best_match is None:
            return ""
        return best_match.encoding or ""

    lazy_encoding_detectors.append(lazy_charset_normalizer_encoding)


from .exceptions import (  # noqa: E402 - the detectors are independent
    CharacterEncodingOverride,
    CharacterEncodingUnknown,
    FeedparserError,
    NonXMLContentType,
)

# Each marker represents some of the characters of the opening XML
# processing instruction ('<?xm') in the specified encoding.
EBCDIC_MARKER = b"\x4c\x6f\xa7\x94"
UTF16BE_MARKER = b"\x00\x3c\x00\x3f"
UTF16LE_MARKER = b"\x3c\x00\x3f\x00"
UTF32BE_MARKER = b"\x00\x00\x00\x3c"
UTF32LE_MARKER = b"\x3c\x00\x00\x00"

ZERO_BYTES = b"\x00\x00"

# Match the opening XML declaration.
# Example: <?xml version="1.0" encoding="utf-8"?>
RE_XML_DECLARATION = re.compile(r"^<\?xml[^>]*?>")

# Capture the value of the XML processing instruction's encoding attribute.
# Example: <?xml version="1.0" encoding="utf-8"?>
RE_XML_PI_ENCODING = re.compile(rb'^<\?.*encoding=[\'"](.*?)[\'"].*\?>')


def parse_content_type(line: str) -> tuple[str, str]:
    """Parse an HTTP Content-Type header.

    The return value will be a tuple of strings:
    the MIME type, and the value of the "charset" (if any).

    This is a custom replacement for Python's cgi.parse_header().
    The cgi module will be removed in Python 3.13.
    """

    chunks = line.split(";")
    if not chunks:
        return "", ""

    mime_type = chunks[0].strip()
    charset_value = ""
    for chunk in chunks[1:]:
        key, _, value = chunk.partition("=")
        if key.strip().lower() == "charset":
            charset_value = value.strip().strip("\"'")

    return mime_type, charset_value


def _get_header(http_headers: dict[str, str], name: str) -> str:
    """Look up an HTTP header by name, ignoring case."""
    value = http_headers.get(name)
    if value is not None:
        return value
    for header_name, header_value in http_headers.items():
        if header_name.lower() == name:
            return header_value
    return ""


def _detect_bom(data: bytes) -> tuple[str, bytes]:
    """Return the encoding named by a BOM and the data after the BOM."""
    if data[:4] == codecs.BOM_UTF32_BE:
        return "utf-32be", data[4:]
    if data[:4] == codecs.BOM_UTF32_LE:
        return "utf-32le", data[4:]
    if data[:2] == codecs.BOM_UTF16_BE and data[2:4] != ZERO_BYTES:
        return "utf-16be", data[2:]
    if data[:2] == codecs.BOM_UTF16_LE and data[2:4] != ZERO_BYTES:
        return "utf-16le", data[2:]
    if data[:3] == codecs.BOM_UTF8:
        return "utf-8", data[3:]
    return "", data


def convert_to_utf8(
    http_headers: dict[str, str],
    data: bytes,
    result: dict[str, typing.Any],
) -> bytes:
    """Detect and convert the character encoding to UTF-8.

    The encoding is determined in a fixed order of precedence:

    #. the byte order mark (BOM) at the start of the document,
    #. the encoding named in the XML declaration,
    #. the ``charset`` parameter of the HTTP Content-Type header.

    The first of these sources that is present wins. When they disagree,
    the earliest source still wins, and the conflict is recorded: the
    ``bozo`` bit is set and ``bozo_exception`` is a
    :class:`~feedparser.exceptions.CharacterEncodingOverride` that names
    the conflicting sources.

    If no source names the encoding, or if the named encodings cannot
    decode the data, the encoding is auto-detected. If the data still
    cannot be decoded, it is decoded as UTF-8 and the invalid bytes are
    replaced.

    """

    # This is so much trickier than it sounds, it's not even funny.
    #
    # RFC 3023 lets the HTTP charset override the XML declaration for
    # text/xml media types, and lets the XML declaration override the
    # charset for application/*+xml media types. In practice that ordering
    # garbles feeds that declare one encoding in the body while the server
    # sends another in the header. RFC 7303, which supersedes RFC 3023,
    # also gives the BOM precedence over the charset parameter. The
    # precedence used here is fixed instead: BOM, then XML declaration,
    # then HTTP header.

    # Check for BOMs first, and remove the BOM bytes from the data.
    bom_encoding, data = _detect_bom(data)

    # Check for the characters '<?xm' in several encodings. These are not
    # BOMs, so the data is left untouched. The information is only used to
    # read the XML declaration; it never outranks a declared encoding.
    sniffed_encoding = ""
    if not bom_encoding:
        if data[:4] == EBCDIC_MARKER:
            sniffed_encoding = "cp037"
        elif data[:4] == UTF16BE_MARKER:
            sniffed_encoding = "utf-16be"
        elif data[:4] == UTF16LE_MARKER:
            sniffed_encoding = "utf-16le"
        elif data[:4] == UTF32BE_MARKER:
            sniffed_encoding = "utf-32be"
        elif data[:4] == UTF32LE_MARKER:
            sniffed_encoding = "utf-32le"

    # Broken feeds may start with whitespace before the BOM or the XML
    # declaration. Strip it, then look for a BOM again. This is only done
    # for ASCII-compatible encodings: in UTF-16 and UTF-32 a single
    # character spans several bytes that are not ASCII.
    ascii_compatible = bom_encoding in ("", "utf-8") and sniffed_encoding == ""
    if ascii_compatible:
        stripped = data.lstrip(b" \t\r\n")
        if len(stripped) != len(data):
            data = stripped
            if not bom_encoding:
                bom_encoding, data = _detect_bom(data)

    # Capture the encoding named in the XML declaration. Decode enough of
    # the document with the encoding identified above to be able to use an
    # ASCII-compatible regular expression on it.
    tempdata = data
    try:
        if bom_encoding:
            tempdata = data.decode(bom_encoding).encode("utf-8")
        elif sniffed_encoding:
            tempdata = data.decode(sniffed_encoding).encode("utf-8")
    except UnicodeDecodeError:
        xml_encoding_match = None
    else:
        xml_encoding_match = RE_XML_PI_ENCODING.match(tempdata)

    xml_encoding = ""
    if xml_encoding_match:
        xml_encoding = xml_encoding_match.groups()[0].decode("utf-8").lower()
        # Normalize the xml_encoding if necessary.
        if (bom_encoding or sniffed_encoding) and (
            xml_encoding
            in (
                "u16",
                "utf-16",
                "utf16",
                "utf_16",
                "u32",
                "utf-32",
                "utf32",
                "utf_32",
                "iso-10646-ucs-2",
                "iso-10646-ucs-4",
                "csucs4",
                "csunicode",
                "ucs-2",
                "ucs-4",
            )
        ):
            xml_encoding = bom_encoding or sniffed_encoding

    # Find the HTTP Content-Type and, hopefully, a character encoding
    # provided by the server. Only an explicit "charset" parameter declares
    # an encoding; the default implied by the media type is only used to
    # decode the data when no source declares an encoding.
    # Header names are case-insensitive, and the headers may not have been
    # lowercased already (for example, when passed by the caller).
    content_type_header = _get_header(http_headers, "content-type")
    http_content_type, http_encoding = parse_content_type(content_type_header)

    acceptable_content_type = 0
    application_content_types = (
        "application/xml",
        "application/xml-dtd",
        "application/xml-external-parsed-entity",
    )
    text_content_types = ("text/xml", "text/xml-external-parsed-entity")
    json_content_types = ("application/feed+json", "application/json")
    json = False
    if http_content_type in application_content_types or (
        http_content_type.startswith("application/")
        and http_content_type.endswith("+xml")
    ):
        acceptable_content_type = 1
        default_encoding = "utf-8"
    elif http_content_type in text_content_types or (
        http_content_type.startswith("text/") and http_content_type.endswith("+xml")
    ):
        acceptable_content_type = 1
        default_encoding = "us-ascii"
    elif http_content_type in json_content_types or (
        not http_content_type and data and data.lstrip().startswith(b"{")
    ):
        http_content_type = json_content_types[0]
        acceptable_content_type = 1
        json = True
        default_encoding = "utf-8"  # RFC 7159, 8.1.
    elif http_content_type.startswith("text/"):
        default_encoding = "us-ascii"
    elif http_headers and not _get_header(http_headers, "content-type"):
        default_encoding = "iso-8859-1"
    else:
        default_encoding = "utf-8"

    # gb18030 is a superset of gb2312 and gbk, so always replace them
    # with gb18030 for greater compatibility.
    if default_encoding.lower() in ("gb2312", "gbk"):
        default_encoding = "gb18030"
    if xml_encoding.lower() in ("gb2312", "gbk"):
        xml_encoding = "gb18030"
    if http_encoding.lower() in ("gb2312", "gbk"):
        http_encoding = "gb18030"

    error: FeedparserError | None = None

    if http_headers and (not acceptable_content_type):
        if _get_header(http_headers, "content-type"):
            msg = "%s is not an accepted media type" % content_type_header
        else:
            msg = "no Content-type specified"
        error = NonXMLContentType(msg)

    # The order of this tuple defines the precedence: the BOM first, then
    # the XML declaration, then the HTTP Content-Type header.
    declared_sources = tuple(
        (source, encoding)
        for source, encoding in (
            ("byte order mark", bom_encoding),
            ("XML declaration", xml_encoding),
            ("HTTP Content-Type header", http_encoding),
        )
        if encoding
    )
    declared_encoding = declared_sources[0][1] if declared_sources else ""

    # Try the declared encodings in precedence order. If nothing declares an
    # encoding, or the declared encoding cannot decode the data, detect the
    # encoding. The media type's default encoding is a last resort before
    # falling back to utf-8 with replacement: it accepts almost any byte
    # sequence, so it must not be used while detection may still succeed.
    decoded_encoding = ""
    text = ""
    tried_encodings: list[str] = []

    def try_encoding(proposed_encoding: str) -> bool:
        nonlocal text, decoded_encoding
        normalized = _normalize_encoding_name(proposed_encoding)
        if normalized in tried_encodings:
            return False
        tried_encodings.append(normalized)
        try:
            text = data.decode(proposed_encoding)
        except (UnicodeDecodeError, LookupError):
            return False
        decoded_encoding = proposed_encoding
        return True

    for _, encoding in declared_sources:
        if try_encoding(encoding):
            break

    if not decoded_encoding and any(
        not _encoding_names_differ(encoding, "utf-8")
        for _, encoding in declared_sources
    ):
        # The document says it is utf-8 but contains invalid bytes. If only a
        # small share of the non-ASCII bytes are invalid, the declared
        # encoding is probably right and the bad bytes are replaced; this
        # keeps the rest of the document readable. If most of the non-ASCII
        # bytes are invalid, the declaration is probably wrong (for example,
        # a GBK document that claims to be utf-8), and detection is used.
        replaced_text = data.decode("utf-8", errors="replace")
        invalid_count = replaced_text.count("�")
        non_ascii_count = sum(byte > 0x7F for byte in data)
        if invalid_count <= max(1, non_ascii_count // 4):
            decoded_encoding = "utf-8"
            text = replaced_text
            error = CharacterEncodingOverride(
                "document declared as utf-8, but contains invalid bytes; "
                "decoded as utf-8 and replaced them"
            )

    if not decoded_encoding:
        # When the document is plain ASCII, every ASCII-compatible encoding
        # decodes it identically; report the media type's default encoding
        # rather than the detector's name for ASCII, to match the default
        # implied by the media type.
        if all(byte < 0x80 for byte in data):
            try_encoding(default_encoding)

    if not decoded_encoding and not declared_sources:
        # Nothing declares an encoding. A strict utf-8 decode is a strong
        # signal that the document is utf-8; prefer it over detectors,
        # which can misidentify utf-8 text as a legacy encoding.
        try_encoding("utf-8")

    if not decoded_encoding and sniffed_encoding:
        try_encoding(sniffed_encoding)

    if not decoded_encoding:
        for detect_encoding in lazy_encoding_detectors:
            detected_encoding = detect_encoding(data)
            if detected_encoding and try_encoding(detected_encoding):
                break

    if not decoded_encoding:
        try_encoding(default_encoding)

    if not decoded_encoding:
        # Nothing could decode the data. Decode as UTF-8 and replace the
        # invalid bytes; this always succeeds.
        decoded_encoding = "utf-8"
        text = data.decode("utf-8", errors="replace")
        if error is None:
            error = CharacterEncodingUnknown(
                "document encoding unknown, and auto-detection failed; "
                "decoded as utf-8 and replaced invalid bytes"
            )

    if not json:
        text = _replace_xml_declaration(text)

    # Drop any leading byte order mark that survived decoding, for example
    # when text input starts with U+FEFF. This keeps a stray character out
    # of the parsed values.
    text = text.lstrip("﻿")

    data = text.encode("utf-8")

    if error is None:
        declared_encoding = declared_sources[0][1] if declared_sources else ""
        conflict = _describe_encoding_conflict(declared_sources, decoded_encoding)
        if declared_encoding and _encoding_names_differ(
            decoded_encoding, declared_encoding
        ):
            # The highest-precedence declared encoding could not decode the
            # data, so a lower-precedence source (or detection) was used.
            error = CharacterEncodingOverride(
                conflict
                or "document declared as %s, but parsed as %s"
                % (declared_encoding, decoded_encoding)
            )
        elif conflict:
            # The declared sources disagree, but the winning one was used.
            error = CharacterEncodingOverride(conflict)
        elif not declared_encoding and _encoding_names_differ(
            decoded_encoding, default_encoding
        ):
            # No encoding was declared, so the encoding implied by the
            # media type was expected, but it could not decode the data.
            error = CharacterEncodingOverride(
                "document declared as %s, but parsed as %s"
                % (default_encoding, decoded_encoding)
            )

    result["content-type"] = http_content_type  # for selecting the parser
    result["encoding"] = decoded_encoding
    if error:
        result["bozo"] = True
        result["bozo_exception"] = error
    return data


def _replace_xml_declaration(text: str) -> str:
    """Rewrite the XML declaration to say the text is now utf-8."""
    new_declaration = """<?xml version='1.0' encoding='utf-8'?>"""
    if RE_XML_DECLARATION.search(text):
        return RE_XML_DECLARATION.sub(new_declaration, text)
    return new_declaration + "\n" + text


def _normalize_encoding_name(encoding: str) -> str:
    """Return a canonical codec name, for comparing encodings."""
    try:
        name = codecs.lookup(encoding).name
    except LookupError:
        return encoding.lower()
    # gb18030 is a superset of these encodings and is used in their place.
    if name in ("gb2312", "gbk"):
        return "gb18030"
    return name


def _encoding_names_differ(first: str, second: str) -> bool:
    return _normalize_encoding_name(first) != _normalize_encoding_name(second)


def _describe_encoding_conflict(
    declared_sources: typing.Sequence[tuple[str, str]],
    decoded_encoding: str,
) -> str:
    """Describe declared sources that disagree, and the outcome."""
    if len(declared_sources) < 2:
        return ""
    winner_source, winner_encoding = declared_sources[0]
    differing = [
        "%s (%s)" % (encoding, source)
        for source, encoding in declared_sources[1:]
        if _encoding_names_differ(encoding, winner_encoding)
    ]
    if not differing:
        return ""
    if _encoding_names_differ(decoded_encoding, winner_encoding):
        # The highest-precedence declaration could not decode the document,
        # so a lower-precedence one was used.
        return (
            "document declares conflicting encodings: %s; parsed as %s "
            "instead of %s from the %s"
            % (
                ", ".join(
                    "%s (%s)" % (encoding, source)
                    for source, encoding in declared_sources
                ),
                decoded_encoding,
                winner_encoding,
                winner_source,
            )
        )
    return (
        "document declares conflicting encodings; using %s from the %s, "
        "which takes precedence over %s"
        % (winner_encoding, winner_source, ", ".join(differing))
    )


# How much to read from a binary file in order to detect encoding.
# In initial tests, 4k was enough for ~160 mostly-English feeds;
# 64k seems like a safe margin.
CONVERT_FILE_PREFIX_LEN = 2**16

# How much to read from a text file, and use as an utf-8 bytes prefix.
# Note that no encoding detection is needed in this case.
CONVERT_FILE_STR_PREFIX_LEN = 2**13

CONVERT_FILE_TEST_CHUNK_LEN = 2**16


def convert_file_to_utf8(
    http_headers, file, result, optimistic_encoding_detection=True
):
    """Like convert_to_utf8(), but for a stream.

    Unlike convert_to_utf8(), do not read the entire file in memory;
    instead, return a text stream that decodes it on the fly.
    This should consume significantly less memory,
    because it avoids (repeatedly) converting the entire file contents
    from bytes to str and back.

    To detect the encoding, only a prefix of the file contents is used.
    In rare cases, the wrong encoding may be detected for this prefix;
    use optimistic_encoding_detection=False to use the entire file contents
    (equivalent to a plain convert_to_utf8() call).

    Args:
        http_headers (dict): The response headers.
        file (IO[bytes] or IO[str]): A read()-able (binary) stream.
        result (dict): The result dictionary.
        optimistic_encoding_detection (bool):
            If true, use only a prefix of the file content to detect encoding.

    Returns:
        StreamFactory: a stream factory, with the detected encoding set, if any

    """
    # Currently, this wraps convert_to_utf8(), because the logic is simply
    # too complicated to ensure it's re-implemented correctly for a stream.
    # That said, it should be possible to change the implementation
    # transparently (not sure it's worth it, though).

    # If file is a text stream, we don't need to detect encoding;
    # we still need a bytes prefix to run functions on for side effects:
    # convert_to_utf8() to sniff / set result['content-type'], and
    # replace_doctype() to extract safe_entities.

    if isinstance(file.read(0), str):
        prefix = file.read(CONVERT_FILE_STR_PREFIX_LEN).encode("utf-8")
        prefix = convert_to_utf8(http_headers, prefix, result)
        result["encoding"] = "utf-8"
        return StreamFactory(prefix, file, "utf-8")

    # Remember where the file starts so the raw content can be re-read
    # if the encoding detected from the prefix fails for the rest of it.
    try:
        initial_offset: int | None = file.tell()
    except (OSError, AttributeError):
        initial_offset = None

    if optimistic_encoding_detection:
        prefix = convert_file_prefix_to_utf8(http_headers, file, result)
        factory = StreamFactory(prefix, file, result.get("encoding"))

        # Before returning factory, ensure the entire file can be decoded;
        # if it cannot, fall back to convert_to_utf8().
        #
        # Not doing this means feedparser.parse() may raise UnicodeDecodeError
        # instead of setting bozo_exception to CharacterEncodingOverride,
        # breaking the 6.x API.

        try:
            text_file = factory.get_text_file()
        except MissingEncoding:
            return factory
        try:
            # read in chunks to limit memory usage
            while text_file.read(CONVERT_FILE_TEST_CHUNK_LEN):
                pass
        except UnicodeDecodeError:
            # Fall back to convert_to_utf8() on the original bytes.
            # The prefix returned by convert_file_prefix_to_utf8() has
            # already been converted to utf-8, so it must not be reused.
            if initial_offset is not None:
                try:
                    file.seek(initial_offset)
                except OSError:
                    file = factory.get_binary_file()
            else:
                file = factory.get_binary_file()
        else:
            return factory

    # this shouldn't increase memory usage if file is BytesIO,
    # since BytesIO does copy-on-write; https://bugs.python.org/issue22003
    data = convert_to_utf8(http_headers, file.read(), result)

    # note that data *is* the prefix
    return StreamFactory(data, io.BytesIO(b""), result.get("encoding"))


def convert_file_prefix_to_utf8(
    http_headers,
    file: typing.IO[bytes],
    result,
    *,
    prefix_len: int = CONVERT_FILE_PREFIX_LEN,
    read_to_ascii_len: int = 2**8,
) -> bytes:
    """Like convert_to_utf8(), but only use the prefix of a binary file.

    Set result like convert_to_utf8() would.

    Return the updated prefix, as bytes.

    """
    # This is complicated by convert_to_utf8() detecting the wrong encoding
    # if we have only part of the bytes that make a code-point:
    #
    # '😀'.encode('utf-8')      -> utf-8
    # '😀'.encode('utf-8')[:-1] -> windows-1252 + bozo

    prefix = file.read(prefix_len - 1)

    # reading up to after an ASCII byte increases
    # the likelihood of being on a code point boundary
    prefix += read_to_after_ascii_byte(file, read_to_ascii_len)

    # call convert_to_utf8() up to 4 times,
    # to make sure we eventually land on a code point boundary
    candidates = []
    for attempt in range(4):
        byte = file.read(1)

        # we're at the end of the file, and the loop already ran once
        if not byte and attempt != 0:
            break

        prefix += byte

        fake_result: typing.Any = {}
        converted_prefix = convert_to_utf8(http_headers, prefix, fake_result)

        # an encoding was detected successfully, keep it
        if not fake_result.get("bozo"):
            break

        candidates.append((file.tell(), converted_prefix, fake_result))

    # no encoding was detected successfully, pick the "best" one
    else:

        def key(candidate):
            *_, result = candidate

            exc = result.get("bozo_exception")
            exc_score = 0
            if isinstance(exc, NonXMLContentType):
                exc_score = 20
            elif isinstance(exc, CharacterEncodingOverride):
                exc_score = 10

            return (
                exc_score,
                # prefer utf- encodings to anything else
                result.get("encoding").startswith("utf-"),
            )

        candidates.sort(key=key)
        offset, converted_prefix, fake_result = candidates[-1]

        file.seek(offset)

    result.update(fake_result)
    return converted_prefix


def read_to_after_ascii_byte(file: typing.IO[bytes], max_len: int) -> bytes:
    offset = file.tell()
    buffer = b""

    for _ in range(max_len):
        byte = file.read(1)

        # end of file, nothing to do
        if not byte:
            break

        buffer += byte

        # we stop after a ASCII character
        if byte < b"\x80":
            break

    # couldn't find an ASCII character, reset the file to the original offset
    else:
        file.seek(offset)
        return b""

    return buffer


class MissingEncoding(io.UnsupportedOperation):
    pass


class StreamFactory:
    """Decode on the fly a binary stream that *may* have a known encoding.

    If the underlying stream is seekable, it is possible to call
    the get_{text,binary}_file() methods more than once.

    """

    def __init__(self, prefix: bytes, file, encoding=None):
        self.prefix = prefix
        self.file = ResetFileWrapper(file)
        self.encoding = encoding
        self.should_reset = False

    def get_text_file(self, fallback_encoding=None, errors="strict"):
        encoding = self.encoding or fallback_encoding
        if encoding is None:
            raise MissingEncoding("cannot create text stream without encoding")

        if isinstance(self.file.read(0), str):
            file = PrefixFileWrapper(self.prefix.decode(encoding), self.file)
        else:
            file = PrefixFileWrapper(
                self.prefix.decode("utf-8", errors),
                codecs.getreader(encoding)(self.file, errors),
            )

        self.reset()
        return file

    def get_binary_file(self):
        if isinstance(self.file.read(0), str):
            raise io.UnsupportedOperation(
                "underlying stream is text, not binary"
            ) from None

        file = PrefixFileWrapper(self.prefix, self.file)

        self.reset()
        return file

    def get_file(self):
        try:
            return self.get_text_file()
        except MissingEncoding:
            return self.get_binary_file()

    def reset(self):
        if self.should_reset:
            self.file.reset()
        self.should_reset = True


class ResetFileWrapper:
    """Given a seekable file, allow reading its content again
    (from the current position) by calling reset().

    """

    def __init__(self, file):
        self.file = file
        try:
            self.file_initial_offset = file.tell()
        except OSError:
            self.file_initial_offset = None

    def read(self, size=-1):
        return self.file.read(size)

    def reset(self):
        # raises io.UnsupportedOperation if the underlying stream is not seekable
        self.file.seek(self.file_initial_offset)


class PrefixFileWrapper:
    """Stitch a (possibly modified) prefix and a file into a new file object.

    >>> file = io.StringIO('abcdef')
    >>> file.read(2)
    'ab'
    >>> wrapped = PrefixFileWrapper(file.read(2).upper(), file)
    >>> wrapped.read()
    'CDef'

    """

    def __init__(self, prefix, file):
        self.prefix = prefix
        self.file = file
        self.offset = 0

    def read(self, size=-1):
        buffer = self.file.read(0)

        if self.offset < len(self.prefix):
            if size < 0:
                chunk = self.prefix[self.offset :]
            else:
                chunk = self.prefix[self.offset : self.offset + size]
                size -= len(chunk)
            buffer += chunk
            self.offset += len(chunk)

        while True:
            chunk = self.file.read(size)
            if not chunk:
                break
            buffer += chunk
            self.offset += len(chunk)

            if size <= 0:
                break

            size -= len(chunk)

        return buffer

    def close(self):
        # do not touch the underlying stream
        pass
