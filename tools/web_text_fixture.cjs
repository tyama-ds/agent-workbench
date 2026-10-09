/* Deterministic loopback proxy payloads for frozen-EXE acceptance. No forwarding. */
'use strict';
const assert = require('node:assert/strict');
const WEB_TASK = '[PORTABLE SYNTHETIC] Decode declared web charsets';
const WEB_FINAL = '[SYNTHETIC] Strict web text decoding verified.';
const CASES = [
  {
    "name": "cp932",
    "body": "k/qWe4zqIIdA7uDtlQ==",
    "contentType": "text/plain; charset=Shift_JIS",
    "text": "\u65e5\u672c\u8a9e \u2460\u9ad9\ufa11",
    "encoding": "cp932",
    "source": "http_charset"
  },
  {
    "name": "cp932-meta",
    "body": "PG1ldGEgY2hhcnNldD13aW5kb3dzLTMxaj48cD6T+pZ7jOo8L3A+",
    "contentType": "text/html",
    "text": "\n\u65e5\u672c\u8a9e",
    "encoding": "cp932",
    "source": "html_meta"
  },
  {
    "name": "euc-jp",
    "body": "xvzL3Ljs",
    "contentType": "text/plain; charset=euc-jp",
    "text": "\u65e5\u672c\u8a9e",
    "encoding": "euc_jp",
    "source": "http_charset"
  },
  {
    "name": "iso-2022-jp",
    "body": "GyRCRnxLXDhsGyhC",
    "contentType": "text/plain; charset=iso-2022-jp",
    "text": "\u65e5\u672c\u8a9e",
    "encoding": "iso2022_jp",
    "source": "http_charset"
  },
  {
    "name": "utf8-bom",
    "body": "77u/5pel5pys6KqeIPCfmIA=",
    "contentType": "text/plain",
    "text": "\u65e5\u672c\u8a9e \ud83d\ude00",
    "encoding": "utf-8",
    "source": "bom"
  },
  {
    "name": "utf16le-bom",
    "body": "//7lZSxnnoo=",
    "contentType": "text/plain",
    "text": "\u65e5\u672c\u8a9e",
    "encoding": "utf-16-le",
    "source": "bom"
  },
  {
    "name": "utf16be",
    "body": "ZeVnLIqe",
    "contentType": "text/plain; charset=utf-16be",
    "text": "\u65e5\u672c\u8a9e",
    "encoding": "utf-16-be",
    "source": "http_charset"
  },
  {
    "name": "windows-1252",
    "body": "gCBjYWbp",
    "contentType": "text/plain; charset=windows-1252",
    "text": "\u20ac caf\u00e9",
    "encoding": "cp1252",
    "source": "http_charset"
  },
  {
    "name": "latin1",
    "body": "Y2Fm6Q==",
    "contentType": "text/plain; charset=iso-8859-1",
    "text": "caf\u00e9",
    "encoding": "iso8859-1",
    "source": "http_charset"
  },
  {
    "name": "ascii",
    "body": "QVNDSUkgb25seQ==",
    "contentType": "text/plain; charset=us-ascii",
    "text": "ASCII only",
    "encoding": "ascii",
    "source": "http_charset"
  },
  {
    "name": "malformed",
    "body": "c3ludGhldGljLXNlY3JldC1tYXJrZXL/",
    "contentType": "text/plain; charset=utf-8",
    "error": true
  }
];
const pageUrl = item => 'http://93.184.216.34/charset/' + item.name;

class WebTextFixture {
  constructor() { this.requests = []; this.stage = 0; this.results = []; }
  serve(req, res) {
    assert.equal(req.method, 'GET');
    const url = new URL(req.url);
    assert.equal(url.origin, 'http://93.184.216.34');
    assert.equal(req.headers.host, '93.184.216.34');
    const item = CASES.find(candidate => pageUrl(candidate) === url.href);
    assert(item, 'Unexpected proxy request; fixture never forwards');
    this.requests.push(url.href);
    res.writeHead(200, {'Content-Type': item.contentType});
    res.end(Buffer.from(item.body, 'base64'));
  }
  answer(body, call, completion) {
    assert(body.tools.some(tool => tool.function?.name === 'web_fetch'));
    if (this.stage++ === 0) {
      assert(!body.messages.some(message => message.role === 'tool'));
      return completion('web-1', CASES.map(item => call('web-' + item.name, 'web_fetch', {url: pageUrl(item)})));
    }
    assert.equal(this.stage, 2, 'Exactly two synthetic provider calls');
    const messages = body.messages.filter(message => message.role === 'tool');
    assert.equal(messages.length, CASES.length);
    for (const item of CASES) {
      const result = JSON.parse(messages.find(message => message.tool_call_id === 'web-' + item.name).content);
      if (item.error) {
        assert.equal(result.ok, false);
        assert.match(result.error, /selected supported charset/);
        assert.doesNotMatch(result.error, /synthetic-secret-marker/);
      } else {
        assert.notEqual(result.ok, false, JSON.stringify(result));
        assert.equal(result.url, pageUrl(item));
        assert.equal(result.text, item.text);
        assert.equal(result.encoding, item.encoding);
        assert.equal(result.encoding_source, item.source);
        assert.equal(result.encoding_assumed, false);
        assert.equal(result.truncated, false);
        assert.equal(result.untrusted, true);
      }
      this.results.push({name: item.name, ...result});
    }
    assert.deepEqual(this.requests, CASES.map(pageUrl), 'All bytes came from this loopback proxy');
    return completion('web-2', [], WEB_FINAL);
  }
}
module.exports = {CASES, WEB_TASK, WEB_FINAL, WebTextFixture};
