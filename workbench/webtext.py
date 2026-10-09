"""Conservative, bounded web-text decoding; not a browser encoding detector.

Only fixed standard-library codecs are selectable by remote declarations. No
probabilistic detection, replacement decoding, XML entity expansion or retries.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser


class TextDecodingError(ValueError):
    pass


_ASCII_SPACE = "\t\n\f\r "
_TOKEN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
_RECOVERY = " Use a source with an explicit supported charset or a UTF-8 export."
# Explicit aliases keep Python-version-specific alias tables and arbitrary codecs
# out of the remotely controlled selection. CP932 is the Windows-compatible
# Japanese variant; these decoders do not claim exact WHATWG byte-level parity.
_ALIASES = {
    "utf-8": "utf-8", "utf8": "utf-8", "unicode-1-1-utf-8": "utf-8",
    "utf-16le": "utf-16-le", "utf-16be": "utf-16-be",
    "shift_jis": "cp932", "shift-jis": "cp932", "sjis": "cp932",
    "csshiftjis": "cp932", "ms_kanji": "cp932", "ms932": "cp932",
    "windows-31j": "cp932", "x-sjis": "cp932", "cp932": "cp932",
    "euc-jp": "euc_jp", "cseucpkdfmtjapanese": "euc_jp", "x-euc-jp": "euc_jp",
    "iso-2022-jp": "iso2022_jp", "csiso2022jp": "iso2022_jp",
    "windows-1252": "cp1252", "cp1252": "cp1252", "x-cp1252": "cp1252",
    "ascii": "ascii", "us-ascii": "ascii", "iso-ir-6": "ascii",
    "iso-8859-1": "iso8859-1", "iso8859-1": "iso8859-1", "latin1": "iso8859-1",
    "latin-1": "iso8859-1", "l1": "iso8859-1", "cp819": "iso8859-1",
}


def _codec(label: str, mime: str, source: str) -> str:
    label = label.strip(_ASCII_SPACE)
    if not label or len(label) > 64 or not label.isascii():
        raise TextDecodingError("Web text has an unsupported charset declaration." + _RECOVERY)
    label = label.lower()
    if label == "utf-16":
        if mime == "text/html":
            return "utf-8" if source == "html_meta" else "utf-16-le"
        raise TextDecodingError("UTF-16 web text needs a byte-order mark or an explicit LE/BE charset." + _RECOVERY)
    if label == "x-user-defined" and source == "html_meta":
        return "cp1252"
    codec = _ALIASES.get(label)
    if codec is None:
        raise TextDecodingError("Web text has an unsupported charset declaration." + _RECOVERY)
    if source == "xml_declaration" and codec in {"utf-16-le", "utf-16-be"}:
        raise TextDecodingError("An ASCII XML declaration cannot select UTF-16; use a BOM or HTTP charset." + _RECOVERY)
    if mime == "text/html":
        if codec in {"ascii", "iso8859-1"}:
            return "cp1252"
        if source == "html_meta" and codec in {"utf-16-le", "utf-16-be"}:
            return "utf-8"
    return codec


def _header_charset(value: str) -> str | None:
    """Parse ordinary MIME parameters, rejecting ambiguous/extended charsets.

    Email header parsers can silently repair malformed quotes and interpret
    RFC2231 charset* parameters. Those are deliberately not accepted here.
    """
    if len(value) > 8192 or any(ord(c) < 32 and c != "\t" or ord(c) == 127 for c in value):
        raise TextDecodingError("Web text has a malformed Content-Type header." + _RECOVERY)
    pos = value.find(";")
    if pos < 0:
        return None
    charset = None
    while pos < len(value):
        if value[pos] != ";":
            raise TextDecodingError("Web text has malformed charset parameters." + _RECOVERY)
        pos += 1
        while pos < len(value) and value[pos] in " \t":
            pos += 1
        name = _TOKEN.match(value, pos)
        if name is None:
            raise TextDecodingError("Web text has malformed charset parameters." + _RECOVERY)
        key, pos = name.group().lower(), name.end()
        while pos < len(value) and value[pos] in " \t":
            pos += 1
        if pos == len(value) or value[pos] != "=":
            raise TextDecodingError("Web text has malformed charset parameters." + _RECOVERY)
        pos += 1
        while pos < len(value) and value[pos] in " \t":
            pos += 1
        if pos < len(value) and value[pos] == '"':
            pos += 1
            chars = []
            while pos < len(value) and value[pos] != '"':
                if value[pos] == "\\":
                    pos += 1
                    if pos == len(value):
                        break
                chars.append(value[pos])
                pos += 1
            if pos == len(value):
                raise TextDecodingError("Web text has malformed charset parameters." + _RECOVERY)
            parameter = "".join(chars)
            pos += 1
        else:
            token = _TOKEN.match(value, pos)
            if token is None:
                raise TextDecodingError("Web text has malformed charset parameters." + _RECOVERY)
            parameter, pos = token.group(), token.end()
        while pos < len(value) and value[pos] in " \t":
            pos += 1
        if key.startswith("charset*") or key == "charset" and charset is not None:
            raise TextDecodingError("Web text has ambiguous charset parameters." + _RECOVERY)
        if key == "charset":
            charset = parameter
    return charset


def _meta_attributes(raw: str) -> tuple[dict[str, str | None], set[str]]:
    """Read raw attributes without HTMLParser's attribute entity expansion."""
    pos, attrs, duplicates = 5, {}, set()  # after '<meta', case-insensitive
    while pos < len(raw):
        while pos < len(raw) and raw[pos] in _ASCII_SPACE:
            pos += 1
        if raw[pos:] in {">", "/>"}:
            return attrs, duplicates
        start = pos
        while pos < len(raw) and raw[pos] not in _ASCII_SPACE + "/=>\"'":
            pos += 1
        if pos == start:
            raise TextDecodingError("Web text has a malformed HTML encoding declaration." + _RECOVERY)
        name = raw[start:pos].lower()
        while pos < len(raw) and raw[pos] in _ASCII_SPACE:
            pos += 1
        value = None
        if pos < len(raw) and raw[pos] == "=":
            pos += 1
            while pos < len(raw) and raw[pos] in _ASCII_SPACE:
                pos += 1
            if pos < len(raw) and raw[pos] in "\"'":
                quote, pos = raw[pos], pos + 1
                start = pos
                while pos < len(raw) and raw[pos] != quote:
                    pos += 1
                if pos == len(raw):
                    raise TextDecodingError("Web text has a malformed HTML encoding declaration." + _RECOVERY)
                value, pos = raw[start:pos], pos + 1
            else:
                start = pos
                while pos < len(raw) and raw[pos] not in _ASCII_SPACE + ">":
                    pos += 1
                value = raw[start:pos]
        if name in attrs:
            duplicates.add(name)
        else:
            attrs[name] = value
    raise TextDecodingError("Web text has an incomplete HTML encoding declaration." + _RECOVERY)


class _MetaEncoding(HTMLParser):
    # Stop at raw/inert content: HTMLParser does not implement the browser script
    # double-escape state machine, so resuming afterwards could select a decoy.
    # This is a conservative head-prefix scan, not the WHATWG prescanner.
    _RAW = {"script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript", "plaintext"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.codec: str | None = None
        self.stopped = False

    def handle_starttag(self, tag, attrs):
        if self.codec is not None or self.stopped:
            return
        if tag in self._RAW or tag == "template":
            self.stopped = True
        elif tag == "meta":
            values, duplicates = _meta_attributes(self.get_starttag_text())
            if "charset" in values:
                label = values["charset"]
            elif (values.get("http-equiv") or "").lower() == "content-type" and "content" in values:
                label = _header_charset(values["content"] or "")
                if label is None:
                    return
            else:
                return
            if duplicates & {"charset", "http-equiv", "content"}:
                raise TextDecodingError("Web text has an ambiguous HTML encoding declaration." + _RECOVERY)
            self.codec = _codec(label or "", "text/html", "html_meta")

    def handle_startendtag(self, tag, attrs):
        # HTML self-closing syntax does not close raw-text/template elements.
        self.handle_starttag(tag, attrs)



def _html_codec(data: bytes) -> str | None:
    parser = _MetaEncoding()
    parser.feed(data[:1024].decode("latin1"))  # byte-preserving ASCII markup scan
    # Do not close: a tag incomplete at the bound cannot declare an encoding.
    return parser.codec


_XML_DECL = re.compile(
    r"<\?xml[\t\r\n ]+version[\t\r\n ]*=[\t\r\n ]*(?P<vq>['\"])1\.[01](?P=vq)"
    r"(?:[\t\r\n ]+encoding[\t\r\n ]*=[\t\r\n ]*(?P<eq>['\"])(?P<encoding>[A-Za-z][A-Za-z0-9._-]*)(?P=eq))?"
    r"(?:[\t\r\n ]+standalone[\t\r\n ]*=[\t\r\n ]*(?P<sq>['\"])(?:yes|no)(?P=sq))?[\t\r\n ]*\?>"
)


def _xml_codec(data: bytes) -> str | None:
    if not data.startswith(b"<?xml") or data[5:6] not in {b" ", b"\t", b"\r", b"\n"}:
        return None
    end = data[:1024].find(b"?>")
    if end < 0:
        raise TextDecodingError("Web text has an incomplete or oversized XML declaration." + _RECOVERY)
    try:
        declaration = data[:end + 2].decode("ascii")
    except UnicodeDecodeError:
        declaration = ""
    match = _XML_DECL.fullmatch(declaration)
    if not match:
        raise TextDecodingError("Web text has a malformed XML encoding declaration." + _RECOVERY)
    label = match.group("encoding")
    return _codec(label, "application/xhtml+xml", "xml_declaration") if label else None


def decode_web_text(data: bytes, mime: str, content_type: str) -> tuple[str, dict]:
    """Decode once and identify the actual codec and why it was selected."""
    if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        raise TextDecodingError("UTF-32 web text is not supported." + _RECOVERY)
    bom = next(((prefix, codec) for prefix, codec in (
        (b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")
    ) if data.startswith(prefix)), None)
    if mime == "application/json":
        if bom and bom[1] != "utf-8":
            raise TextDecodingError("JSON web text must use UTF-8." + _RECOVERY)
        codec, source = "utf-8", "json_utf8"
    elif bom:
        codec, source = bom[1], "bom"
    else:
        label = _header_charset(content_type)
        if label is not None:
            codec, source = _codec(label, mime, "http_charset"), "http_charset"
        elif mime == "text/html" and (found := _html_codec(data)):
            codec, source = found, "html_meta"
        elif mime == "application/xhtml+xml":
            found = _xml_codec(data)
            codec, source = (found, "xml_declaration") if found else ("utf-8", "xml_default")
        else:
            codec, source = "utf-8", "default_utf8"
    if source in {"default_utf8", "xml_default", "json_utf8"} and b"\x00" in data:
        raise TextDecodingError("Web text contains NUL bytes inconsistent with its UTF-8 default; its encoding is uncertain." + _RECOVERY)
    payload = data[len(bom[0]):] if bom else data
    try:
        text = payload.decode(codec, "strict")
    except UnicodeDecodeError:
        # Never echo response bytes, remote labels or Python exception payloads.
        raise TextDecodingError(f"Web text could not be decoded with the selected supported charset ({codec}; {source})." + _RECOVERY) from None
    return text, {"encoding": codec, "encoding_source": source, "encoding_assumed": source == "default_utf8"}
