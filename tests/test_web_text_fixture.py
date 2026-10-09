"""Validate the new portable acceptance fixture against the real source decoder."""
import asyncio
import base64
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from workbench.webtools import WebToolError, WebTools


ROOT = Path(__file__).resolve().parents[1]


def test_portable_web_cases_and_driver_protocol(monkeypatch):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is a developer-only fixture dependency')
    dump = subprocess.run([node, '-e', "console.log(JSON.stringify(require('./tools/web_text_fixture.cjs').CASES))"],
                          cwd=ROOT, check=True, text=True, encoding='utf-8', capture_output=True)
    cases = json.loads(dump.stdout)
    results = []
    async def run():
        tools = WebTools({'search': {'enabled': True}})
        for item in cases:
            url = 'http://93.184.216.34/charset/' + item['name']
            async def stub(_url):
                assert _url == url
                return base64.b64decode(item['body']), item['contentType'], url
            monkeypatch.setattr(tools, '_request', stub)
            try:
                result = await tools.execute('web_fetch', {'url': url})
            except WebToolError as error:
                result = {'ok': False, 'error': str(error)}
            results.append({'role': 'tool', 'tool_call_id': 'web-' + item['name'], 'content': json.dumps(result)})
    asyncio.run(run())
    script = """
const assert = require('node:assert/strict');
const {CASES, WebTextFixture, WEB_FINAL} = require('./tools/web_text_fixture.cjs');
const fixture = new WebTextFixture();
const call = (id, name, args) => ({id, name, args});
const completion = (id, calls=[], content='') => ({id,calls,content});
const tools = [{function:{name:'web_fetch'}}];
const first = fixture.answer({tools,messages:[]}, call, completion);
assert.equal(first.calls.length, CASES.length);
for (const item of CASES) {
  let header, bytes;
  fixture.serve({method:'GET',url:'http://93.184.216.34:80/charset/'+item.name,
    headers:{host:'93.184.216.34'}}, {
    writeHead(status, headers){ assert.equal(status,200); header=headers['Content-Type']; },
    end(data){bytes=data;}
  });
  assert.equal(header,item.contentType);
  assert.equal(bytes.toString('base64'),item.body);
}
const result = fixture.answer({tools,messages:MESSAGES}, call, completion);
assert.equal(result.content,WEB_FINAL);
assert.equal(fixture.results.length,CASES.length);
assert.throws(()=>fixture.serve({method:'GET',url:'http://127.0.0.1/private',headers:{host:'127.0.0.1'}},{}));
console.log('fixture verified');
""".replace('MESSAGES', json.dumps(results, ensure_ascii=True))
    verified = subprocess.run([node, '-'], input=script, cwd=ROOT, check=True, text=True,
                              encoding='utf-8', capture_output=True)
    assert verified.stdout.strip() == 'fixture verified'
