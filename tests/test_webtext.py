"""Pure/stubbed decoding matrix; remote content never initiates a real fetch."""
import asyncio
import json

import pytest

from workbench.webtext import TextDecodingError, decode_web_text
from workbench.webtools import WebToolError, WebTools


TEXT = "日本語の資料 ①髙﨑 ～ & <確認>"


def decode(data, header="text/html"):
    return decode_web_text(data, header.split(";", 1)[0].strip().lower(), header)


@pytest.mark.parametrize("label", ["Shift_JIS", '"ShIfT_JiS"', "windows-31j", "ms932", "sjis", "cp932", "x-sjis", "csshiftjis", "ms_kanji"])
def test_japanese_windows_charset_aliases_are_explicit(label):
    text, info = decode(TEXT.encode("cp932"), "text/plain; CHARSET = " + label)
    assert text == TEXT
    assert info == {"encoding": "cp932", "encoding_source": "http_charset", "encoding_assumed": False}


@pytest.mark.parametrize("codec,label,text", [
    ("utf-8", "UTF-8", "日本語 😀"), ("euc_jp", "EUC-JP", "日本語"),
    ("iso2022_jp", "ISO-2022-JP", "日本語"), ("cp1252", "windows-1252", "€café“”"),
    ("ascii", "US-ASCII", "plain text"), ("iso8859-1", "ISO-8859-1", "café\x80"),
    ("utf-16-le", "utf-16le", "日本語"), ("utf-16-be", "utf-16be", "日本語"),
])
def test_supported_codec_families(codec, label, text):
    actual, info = decode(text.encode(codec), "text/plain; charset=" + label)
    assert actual == text and info["encoding"] == codec


@pytest.mark.parametrize("mime", ["text/plain", "text/html", "text/markdown", "text/csv"])
def test_undeclared_utf8_is_an_explicit_assumption(mime):
    text, info = decode("日本語 😀".encode(), mime)
    assert text == "日本語 😀"
    assert info == {"encoding": "utf-8", "encoding_source": "default_utf8", "encoding_assumed": True}


@pytest.mark.parametrize("bom,codec", [(b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")])
def test_bom_is_removed_and_overrides_header_and_meta(bom, codec):
    source = '<meta charset="utf-7"><p>日本語</p>\ufeff'
    text, info = decode(bom + source.encode(codec), 'text/html; charset="unknown-malformed')
    assert text == source  # only the leading BOM is removed
    assert info == {"encoding": codec, "encoding_source": "bom", "encoding_assumed": False}


@pytest.mark.parametrize("header", [
    'text/html; note="a;b;charset=cp932"; CHARSET="utf-8"',
    'text/html; note="a\\\";charset=cp932"; charset=utf-8',
    'text/html; note="a\\\\b"; charset=utf-8',
])
def test_quoted_parameter_delimiters_do_not_select_charset(header):
    text, info = decode("日本語".encode(), header)
    assert text == "日本語" and info["encoding"] == "utf-8"


@pytest.mark.parametrize("suffix", [
    ';charset="utf-8', ';charset=', ';charset=""', ';charset', ';charset=utf-8 garbage',
    ';charset=utf-8;charset=shift_jis', ';charset=utf-8;charset=utf-8',
    ";charset*=UTF-8''utf-8", ';charset*0=utf-8', ';charset=utf-8\r\nBad: yes',
    ';charset=utf-8\x00', ';' + 'x' * 8200 + '=a',
])
def test_malformed_and_ambiguous_parameters_fail(suffix):
    with pytest.raises(TextDecodingError, match="charset|Content-Type"):
        decode(b"secret body", "text/html" + suffix)


@pytest.mark.parametrize("label", ["utf-7", "UTF-32", "unicode_escape", "raw_unicode_escape", "base64_codec", "rot_13", "replacement", "unknown", "ｕｔｆ８", "x" * 65])
def test_untrusted_labels_cannot_select_arbitrary_python_codecs(label):
    with pytest.raises(TextDecodingError, match="unsupported|malformed") as error:
        decode(b"private-response-marker", "text/plain; charset=" + label)
    assert "private-response-marker" not in str(error.value)
    assert "UTF-8 export" in str(error.value)


@pytest.mark.parametrize("markup", [
    '<meta charset="Shift_JIS">', "<META CHARSET='windows-31j'>", '<meta charset=cp932>',
    '<meta http-equiv="Content-Type" content="text/html; charset=Shift_JIS">',
    '<meta content="text/html; charset=Shift_JIS" HTTP-EQUIV="content-type">',
    '<meta charset=Shift_JIS content="text/html; charset=utf-8" http-equiv=content-type>',
    '<meta content="text/html; charset=utf-8" charset=Shift_JIS http-equiv=content-type>',
])
def test_real_early_html_meta_selects_japanese(markup):
    data = (markup + '<p>日本語</p>').encode("cp932")
    text, info = decode(data)
    assert text.endswith('<p>日本語</p>')
    assert info == {"encoding": "cp932", "encoding_source": "html_meta", "encoding_assumed": False}


@pytest.mark.parametrize("wrapper", ["<!--{}-->", *['<' + tag + '>{}</' + tag + '>' for tag in
    ["script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript", "template"]],
    '<script/>{}</script>', '<textarea/>{}</textarea>', '<template/>{}</template>',
    '<div title=\'{}\'></div>',
])
def test_meta_decoys_in_comments_attributes_raw_or_inert_content_are_ignored(wrapper):
    data = (wrapper.format('<meta charset="utf-7">') + '<meta charset=utf-8>日本語').encode()
    text, info = decode(data)
    assert '日本語' in text
    expected_source = "html_meta" if wrapper.startswith(("<!--", "<div")) else "default_utf8"
    assert info["encoding"] == "utf-8" and info["encoding_source"] == expected_source


def test_plaintext_never_exits_for_later_meta_and_meta_name_does_not_declare():
    for data in [b'<plaintext><meta charset="utf-7"></plaintext><meta charset="cp932">',
                 b'<meta name=charset content=utf-7>', b'<meta content="text/html; charset=utf-7">']:
        _, info = decode(data)
        assert info["encoding_source"] == "default_utf8"


def test_http_precedes_meta_and_first_selected_meta_wins():
    data = b'<meta charset="utf-7">' + '日本語'.encode()
    assert decode(data, 'text/html; charset=utf-8')[1]["encoding_source"] == "http_charset"
    data = b'<meta charset=utf-8><meta charset=cp932>' + '日本語'.encode()
    assert decode(data)[1]["encoding"] == "utf-8"
    with pytest.raises(TextDecodingError, match="unsupported"):
        decode(data, 'text/html; charset=unknown')


def test_complete_meta_tag_must_fit_first_1024_bytes():
    tag = b'<meta charset=cp932>'
    for last_byte, expected in [(1024, "html_meta"), (1025, "default_utf8")]:
        data = b" " * (last_byte - len(tag)) + tag + b"ascii"
        assert decode(data)[1]["encoding_source"] == expected
    assert decode(b" " * 1024 + tag)[1]["encoding_source"] == "default_utf8"


@pytest.mark.parametrize("markup", ['<meta charset=utf-8 charset=utf-8>', '<meta charset=utf-8 charset=cp932>',
    '<meta http-equiv=content-type http-equiv=content-type content="text/html;charset=utf-8">',
    '<meta charset="u&#116;f-8">', '<meta charset=utf-7>', '<meta charset>', '<meta charset="">'])
def test_ambiguous_unsupported_and_entity_obfuscated_meta_fails(markup):
    with pytest.raises(TextDecodingError):
        decode(markup.encode())


@pytest.mark.parametrize("label", ["utf-16", "utf-16le", "utf-16be"])
def test_html_meta_utf16_is_utf8_but_http_is_utf16(label):
    data = ('<meta charset=' + label + '>日本語').encode()
    assert decode(data)[1]["encoding"] == "utf-8"
    codec = "utf-16-be" if label.endswith("be") else "utf-16-le"
    assert decode("日本語".encode(codec), "text/html;charset=" + label)[0] == "日本語"


def test_html_legacy_latin_labels_and_x_user_defined_meta_are_browser_compatible():
    for label in ["iso-8859-1", "latin1", "us-ascii"]:
        assert decode(b"\x80", "text/html;charset=" + label)[0] == "€"
    assert decode(b'<meta charset=x-user-defined>\x80')[0].endswith("€")
    with pytest.raises(TextDecodingError):
        decode(b"x", "text/plain;charset=x-user-defined")


def test_xml_uses_declaration_never_html_meta_and_has_a_defined_default():
    declaration = '<?xml version="1.0" encoding="Shift_JIS" standalone="yes"?>'
    data = (declaration + '<html><meta charset="utf-7"/>日本語</html>').encode("cp932")
    text, info = decode(data, "application/xhtml+xml")
    assert '日本語' in text and info["encoding_source"] == "xml_declaration"
    data = '<html><meta charset="cp932"/>日本語</html>'.encode()
    assert decode(data, "application/xhtml+xml")[1] == {"encoding": "utf-8", "encoding_source": "xml_default", "encoding_assumed": False}
    assert decode(b'<?xml version="1.0" encoding="unknown"?>', "application/xhtml+xml;charset=utf-8")[1]["encoding_source"] == "http_charset"
    assert decode(b'<?xml-stylesheet href="x"?>', "application/xhtml+xml")[1]["encoding_source"] == "xml_default"


@pytest.mark.parametrize("declaration", [b'<?xml encoding="cp932"?>', b'<?xml version="1.0" encoding="utf-7"?>',
    b'<?xml version="1.0" encoding="utf-8" encoding="cp932"?>', b'<?xml version="1.0"' + b' ' * 1024 + b'?>',
    b'<?xml version="1.0" encoding="\xff"?>'])
def test_invalid_or_oversized_xml_declarations_fail(declaration):
    with pytest.raises(TextDecodingError):
        decode(declaration, "application/xhtml+xml")


def test_xml_dtd_and_external_entities_are_only_untrusted_text():
    data = b'<?xml version="1.0"?><!DOCTYPE x SYSTEM "file:///secret"><x>&xxe;</x>'
    assert decode(data, "application/xhtml+xml")[0] == data.decode()


@pytest.mark.parametrize("suffix", ["", ";charset=cp932", ";charset=utf-7", ';charset="malformed'])
def test_json_utf8_ignores_charset_and_accepts_utf8_bom(suffix):
    body = '{"text":"日本語"}'
    for prefix in [b"", b"\xef\xbb\xbf"]:
        text, info = decode(prefix + body.encode(), "application/json" + suffix)
        assert text == body
        assert info == {"encoding": "utf-8", "encoding_source": "json_utf8", "encoding_assumed": False}


@pytest.mark.parametrize("data,header", [
    (b"\xff", "text/plain;charset=utf-8"), (b"\x82", "text/html;charset=Shift_JIS"),
    (b"\xff\xfeA", "text/plain"), (b"\xfe\xff\x00", "text/plain"),
    ('{"x":"日本語"}'.encode("cp932"), "application/json;charset=cp932"),
    (b"\xff\xfe" + '{}'.encode("utf-16-le"), "application/json"),
    (b"\xff\xfe\x00\x00A\x00\x00\x00", "text/plain"), (b"\x00\x00\xfe\xff\x00\x00\x00A", "text/plain"),
    ("日本語".encode("utf-16-le"), "text/plain;charset=utf-16"),
    (b"A\x00B\x00", "text/plain"), (b"<\x00?\x00x\x00", "application/xhtml+xml"),
])
def test_malformed_unsupported_or_uncertain_bytes_fail(data, header):
    with pytest.raises(TextDecodingError) as error:
        decode(data, header)
    assert "UTF-8 export" in str(error.value)
    assert "codec can't decode" not in str(error.value)


def test_literal_replacement_character_is_valid_source_not_a_decode_error():
    assert decode("valid �".encode())[0] == "valid �"


async def _fetch(monkeypatch, data, header):
    tools = WebTools({"search": {"enabled": True}})
    async def stub(url):
        assert url == "https://requested.invalid/"
        return data, header, "https://final.invalid/source"
    monkeypatch.setattr(tools, "_request", stub)
    return await tools.execute("web_fetch", {"url": "https://requested.invalid/"})


@pytest.mark.parametrize("length", [0, 199999, 200000, 200001])
def test_cleaned_output_bound_and_provenance(monkeypatch, length):
    result = asyncio.run(_fetch(monkeypatch, ('\x01' * 250000 + '字' * length).encode(), 'text/plain;charset=utf-8'))
    assert result["text"] == '字' * min(length, 200000)
    assert result["truncated"] is (length > 200000)
    assert result["untrusted"] is True and result["url"] == "https://final.invalid/source"
    serialized = json.dumps(result, ensure_ascii=False)
    assert serialized.index('"encoding_source"') < serialized.index('"text"')
    assert '"encoding_source"' in serialized[:12000]


def test_fetch_extracts_decoded_japanese_and_flushes_trailing_text(monkeypatch):
    data = '<h1>日本語</h1><script>do_bad()</script><p>①髙﨑</p>trailing &incomplete'
    result = asyncio.run(_fetch(monkeypatch, data.encode('cp932'), 'text/html;charset=Shift_JIS'))
    assert '日本語' in result["text"] and '①髙﨑' in result["text"] and 'do_bad' not in result["text"]
    assert result["text"].endswith('trailing &incomplete')
    assert result["encoding"] == 'cp932' and result["content_type"] == 'text/html'


def test_fetch_decoding_failure_is_web_tool_error_without_secret_body(monkeypatch):
    with pytest.raises(WebToolError, match="selected supported charset") as error:
        asyncio.run(_fetch(monkeypatch, b'secret-body-123\xff', 'text/plain;charset=utf-8'))
    assert 'secret-body-123' not in str(error.value)


def test_html_character_limit_is_after_extraction(monkeypatch):
    data = '<script>' + 'a' * 200001 + '</script><p>ok</p>'
    result = asyncio.run(_fetch(monkeypatch, data.encode(), 'text/html;charset=utf-8'))
    assert result["text"] == '\nok' and result["truncated"] is False


def test_non_ascii_label_cannot_lowercase_into_allowlist():
    with pytest.raises(TextDecodingError, match="unsupported"):
        decode(b"abc", 'text/plain; charset="ms_Kanji"')


@pytest.mark.parametrize("label", ["UTF-16LE", "UTF-16BE"])
@pytest.mark.parametrize("suffix", [b"", b" "])
def test_ascii_xml_prolog_cannot_switch_to_utf16(label, suffix):
    body = ('<?xml version="1.0" encoding="' + label + '"?><html>x</html>').encode() + suffix
    with pytest.raises(TextDecodingError, match="ASCII XML declaration"):
        decode(body, "application/xhtml+xml")


@pytest.mark.parametrize("codec", ["utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"])
def test_bomless_json_other_unicode_encodings_cannot_masquerade_as_utf8(monkeypatch, codec):
    with pytest.raises(WebToolError, match="NUL bytes"):
        asyncio.run(_fetch(monkeypatch, '{"secret":"plain"}'.encode(codec), "application/json"))
    assert decode(b'{"escaped":"\\u0000"}', "application/json")[0] == '{"escaped":"\\u0000"}'


def test_double_escaped_script_does_not_expose_fake_meta():
    body = '<script><!--<script></script><meta charset=windows-1252></script><p>日本語</p>'
    text, info = decode(body.encode())
    assert text == body and info["encoding_source"] == "default_utf8"


@pytest.mark.parametrize("tag", ["script", "style", "textarea", "title", "template", "xmp", "iframe", "noembed", "noframes", "noscript"])
def test_self_closing_nonvoid_tag_cannot_expose_fake_meta(tag):
    body = '<' + tag + '/><meta charset=windows-1252></' + tag + '><p>日本語</p>'
    text, info = decode(body.encode())
    assert text == body and info["encoding_source"] == "default_utf8"
