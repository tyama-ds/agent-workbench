/* Development-only acceptance of the extracted Windows ONEDIR distribution.
 * Run with WORKBENCH_PORTABLE_ZIP=<absolute built ZIP> (preferred), or
 * WORKBENCH_PORTABLE_EXE=<absolute extracted AgentWorkbench.exe>.
 * Playwright/Node belong to this driver. The application child gets neither Node,
 * Python nor the checkout on PATH, and uses only its normal production CLI/API.
 */
'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {createRequire} = require('node:module');

const MODEL = 'portable-synthetic-model';
const OFFICE_TASK = '[PORTABLE SYNTHETIC] Office round-trip 日本語';
const STOP_TASK = '[PORTABLE SYNTHETIC] Hold request until stopped';
const FINAL_TEXT = '[SYNTHETIC] DOCX / XLSX / PPTX の作成・読み取り・編集と拒否範囲を確認しました。';
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha256 = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const normalized = value => path.resolve(value).toLowerCase();
const redact = value => String(value).replace(/#token=[A-Za-z0-9_-]+/g, '#token=[redacted]');

async function until(check, label, timeout = 30000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const result = await check();
    if (result) return result;
    await wait(75);
  }
  throw new Error('Timed out: ' + label);
}

function cleanEnvironment(sandbox) {
  // Construct, rather than filter, the environment so future CI credentials,
  // proxies, Python installs and provider keys cannot leak into the app child.
  const systemRoot = process.env.SystemRoot || process.env.SYSTEMROOT;
  assert(systemRoot && path.isAbsolute(systemRoot), 'Windows SystemRoot is required');
  const userProfile = path.join(sandbox, 'empty user 日本語 & !');
  const temp = path.join(sandbox, 'temp 日本語 & !');
  const local = path.join(userProfile, 'AppData', 'Local');
  const roaming = path.join(userProfile, 'AppData', 'Roaming');
  for (const directory of [temp, local, roaming]) fs.mkdirSync(directory, {recursive: true});
  const environment = {
    SystemRoot: systemRoot, WINDIR: systemRoot, OS: 'Windows_NT',
    ComSpec: path.join(systemRoot, 'System32', 'cmd.exe'),
    PATH: [path.join(systemRoot, 'System32'), systemRoot].join(path.delimiter),
    PATHEXT: '.COM;.EXE;.BAT;.CMD', TEMP: temp, TMP: temp,
    USERPROFILE: userProfile, LOCALAPPDATA: local, APPDATA: roaming,
  };
  assert(!Object.keys(environment).some(key => /python|virtual_env|conda|api.?key|proxy/i.test(key)));
  return environment;
}

function request(origin, route, options = {}) {
  return new Promise((resolve, reject) => {
    const data = options.body === undefined ? undefined : JSON.stringify(options.body);
    const headers = {...(data === undefined ? {} : {'Content-Type': 'application/json'}), ...options.headers};
    const req = http.request(origin + route, {method: options.method || 'GET', headers, agent: false}, res => {
      let raw = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { raw += chunk; });
      res.on('end', () => {
        let json;
        try { json = JSON.parse(raw); } catch { /* Static assets are not JSON. */ }
        resolve({status: res.statusCode, headers: res.headers, raw, json});
      });
    });
    req.setTimeout(15000, () => req.destroy(new Error('HTTP request timeout: ' + route)));
    req.on('error', reject);
    req.end(data);
  });
}

function launch(executable, stateDirectory, environment, cwd, port = 0) {
  const args = ['--no-browser', '--port', String(port), '--state-dir', stateDirectory];
  const child = spawn(executable, args, {cwd, env: environment, shell: false, windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe']});
  const processInfo = {child, args, stdout: '', stderr: '', error: null, exited: false, closed: false};
  child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
  child.stdout.on('data', chunk => { processInfo.stdout += chunk; });
  child.stderr.on('data', chunk => { processInfo.stderr += chunk; });
  child.on('error', error => { processInfo.error = error; });
  child.on('exit', () => { processInfo.exited = true; });
  child.on('close', () => { processInfo.closed = true; });
  return processInfo;
}

async function launchUrl(processInfo) {
  return until(() => {
    if (processInfo.error) throw processInfo.error;
    if (processInfo.exited) throw new Error('EXE exited before launch: ' + redact(processInfo.stderr));
    return processInfo.stdout.match(/http:\/\/127\.0\.0\.1:\d+\/#token=[A-Za-z0-9_-]+/)?.[0];
  }, 'packaged EXE launch URL', 60000);
}

async function terminate(processInfo) {
  if (!processInfo || processInfo.closed || processInfo.error) return;
  // Node's Windows kill terminates the process; it is not a Ctrl+C simulation.
  if (!processInfo.exited) processInfo.child.kill();
  await until(() => processInfo.closed, 'EXE process termination', 15000);
}

function runCommand(command, args, environment, cwd, timeout = 30000) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {cwd, env: environment, shell: false, windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe']});
    let stdout = '', stderr = '';
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => { stdout += chunk; });
    child.stderr.on('data', chunk => { stderr += chunk; });
    const timer = setTimeout(() => child.kill(), timeout);
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('close', code => {
      clearTimeout(timer);
      if (code !== 0) reject(new Error(path.basename(command) + ' failed (' + code + '): ' + redact(stderr)));
      else resolve({stdout, stderr});
    });
  });
}

async function prepareBundle(sandbox, environment, report) {
  const archive = process.env.WORKBENCH_PORTABLE_ZIP;
  let install;
  if (archive) {
    assert(path.isAbsolute(archive), 'WORKBENCH_PORTABLE_ZIP must be absolute');
    const digest = sha256(archive);
    const checksum = fs.readFileSync(archive + '.sha256', 'ascii').trim();
    assert.equal(checksum, digest + '  ' + path.basename(archive), 'Built ZIP checksum sidecar');
    const destination = path.join(sandbox, '展開 ZIP 日本語 & !');
    const quoted = value => "'" + value.replace(/'/g, "''") + "'";
    const script = "$ErrorActionPreference = 'Stop'; Expand-Archive -LiteralPath " + quoted(archive) +
      ' -DestinationPath ' + quoted(destination);
    const powershell = path.join(environment.SystemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
    await runCommand(powershell, ['-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
      Buffer.from(script, 'utf16le').toString('base64')], environment, sandbox, 120000);
    install = path.join(destination, 'AgentWorkbench');
    report.archive = {path: archive, sha256: digest, checksumVerified: true, extractedBy: 'Windows Expand-Archive'};
  } else {
    const input = process.env.WORKBENCH_PORTABLE_EXE;
    assert(input && path.isAbsolute(input), 'Set an absolute WORKBENCH_PORTABLE_ZIP or WORKBENCH_PORTABLE_EXE');
    assert.equal(path.basename(input).toLowerCase(), 'agentworkbench.exe');
    install = path.join(sandbox, 'アプリ portable & !');
    fs.cpSync(path.dirname(input), install, {recursive: true, errorOnExist: true, force: false});
    report.extractedInput = input;
  }
  const executable = path.join(install, 'AgentWorkbench.exe');
  assert.equal(fs.readFileSync(executable).subarray(0, 2).toString(), 'MZ', 'Expected real Windows executable');
  assert(fs.statSync(path.join(install, '_internal')).isDirectory(), 'Expected ONEDIR _internal');
  const manifest = JSON.parse(fs.readFileSync(path.join(install, 'build-manifest.json'), 'utf8'));
  if (process.env.GITHUB_SHA) assert.equal(manifest.source_sha, process.env.GITHUB_SHA, 'Bundle source matches the tested CI commit');
  assert.equal(manifest.platform, 'windows'); assert.equal(manifest.architecture, 'x64');
  assert.equal(manifest.bundle_mode, 'onedir'); assert.equal(manifest.signed, false);
  assert(Array.isArray(manifest.files) && manifest.files.length > 0);
  for (const entry of manifest.files) {
    assert(entry.path && !path.isAbsolute(entry.path) && !entry.path.split(/[\\/]/).includes('..'), 'Safe manifest path');
    const file = path.join(install, entry.path);
    assert.equal(fs.statSync(file).size, entry.size, entry.path);
    assert.equal(sha256(file), entry.sha256, entry.path);
  }
  const actualFiles = [];
  const visit = directory => {
    for (const entry of fs.readdirSync(directory, {withFileTypes: true})) {
      assert(!entry.isSymbolicLink(), 'Bundle cannot contain links');
      const file = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(file);
      else {
        assert(entry.isFile(), 'Bundle must contain ordinary files');
        actualFiles.push(path.relative(install, file).split(path.sep).join('/'));
      }
    }
  };
  visit(install);
  assert.deepEqual(actualFiles.sort(), [...manifest.files.map(entry => entry.path), 'build-manifest.json'].sort(),
    'Archive file set must match the manifest exactly');
  assert(!actualFiles.some(file => /(^|\/)(node_modules|tests|\.venv)\//i.test(file)), 'No development dependency folders in bundle');
  report.manifest = {version: manifest.version, sourceSha: manifest.source_sha,
    filesVerified: manifest.files.length, unsigned: true};
  return {install, executable, manifest};
}

async function rejectsOccupiedPort(executable, state, environment, cwd, port) {
  const attempt = launch(executable, state, environment, cwd, port);
  try {
    await until(() => {
      if (attempt.error) throw attempt.error;
      return attempt.closed;
    }, 'occupied-port failure', 30000);
    assert.equal(attempt.child.exitCode, 1, redact(attempt.stderr));
    assert.match(attempt.stderr, /--port/);
    assert.doesNotMatch(attempt.stderr, /Traceback|UnicodeEncodeError/);
    assert.doesNotMatch(attempt.stdout, /#token=/, 'Failed launch cannot issue a bootstrap link');
    assert(!fs.existsSync(state), 'Port rejection must precede state-directory creation');
    return {exitCode: attempt.child.exitCode, diagnostic: redact(attempt.stderr.trim())};
  } finally { await terminate(attempt); }
}

async function duplicateLaunch(executable, state, environment, cwd, port) {
  const attempt = launch(executable, state, environment, cwd, port);
  try {
    await until(() => {
      if (attempt.error) throw attempt.error;
      return attempt.closed;
    }, 'duplicate-launch guard', 30000);
    assert.equal(attempt.child.exitCode, 0, redact(attempt.stderr));
    assert.match(attempt.stdout, port ? /already starting\/running/ : /already running with a dynamic port/);
    assert.doesNotMatch(attempt.stdout, /#token=/, 'Duplicate launch cannot issue a second bootstrap token');
    assert.equal(attempt.stderr, '');
    return {exitCode: attempt.child.exitCode, diagnostic: redact(attempt.stdout.trim())};
  } finally { await terminate(attempt); }
}

function call(id, name, args) {
  return {id, type: 'function', function: {name, arguments: JSON.stringify(args)}};
}

function completion(index, calls = [], content = '[SYNTHETIC] Portable acceptance fixture.') {
  return {id: 'chatcmpl-portable-' + index, object: 'chat.completion', created: 1, model: MODEL,
    choices: [{index: 0, message: {role: 'assistant', content, ...(calls.length ? {tool_calls: calls} : {})},
      finish_reason: calls.length ? 'tool_calls' : 'stop'}],
    usage: {prompt_tokens: 1, completion_tokens: 1, total_tokens: 2}};
}

class OfficeFixture {
  constructor(workspace, protectedDirectories, report) {
    this.files = Object.fromEntries(['docx', 'xlsx', 'pptx'].map(kind =>
      [kind, path.join(workspace, '成果 日本語 & !.' + kind)]));
    this.protectedDirectories = protectedDirectories;
    this.report = report;
    this.stage = 0;
    this.previousCalls = [];
    this.created = {};
    this.edited = {};
    this.results = new Map();
    this.pendingStops = new Set();
    this.stopRequests = 0;
    this.cancelledStops = 0;
    this.errors = [];
  }

  result(id) {
    assert(this.results.has(id), 'Missing actual tool result: ' + id);
    return this.results.get(id);
  }

  verifyWrite(kind, prefix, operation) {
    const result = this.result(prefix + '-' + kind);
    assert.notEqual(result.ok, false, JSON.stringify(result));
    assert.equal(normalized(result.path), normalized(this.files[kind]));
    assert.equal(result.operation, operation);
    assert.match(result.sha256, /^[a-f0-9]{64}$/);
    assert.equal(result.sha256, sha256(this.files[kind]));
    assert.equal(result.bytes, fs.statSync(this.files[kind]).size);
    assert.equal(fs.readFileSync(this.files[kind]).subarray(0, 2).toString(), 'PK', 'Real Office ZIP package');
    return result;
  }

  reads(prefix) {
    return Object.entries(this.files).map(([kind, file]) => call(prefix + '-' + kind, kind + '_read',
      {path: file, ...(kind === 'xlsx' ? {sheet: 'Sheet', range: 'A1:B2'} : {})}));
  }

  edits(prefix, hashes, text) {
    return [
      call(prefix + '-docx', 'docx_edit', {path: this.files.docx, expected_sha256: hashes.docx.sha256,
        operations: [{type: 'replace_paragraph', index: 0, text}]}),
      call(prefix + '-xlsx', 'xlsx_write', {path: this.files.xlsx, expected_sha256: hashes.xlsx.sha256,
        cells: [{sheet: 'Sheet', cell: 'A1', value: text}]}),
      call(prefix + '-pptx', 'pptx_edit', {path: this.files.pptx, expected_sha256: hashes.pptx.sha256,
        operations: [{slide: 0, shape: 0, paragraph: 0, text}]}),
    ];
  }

  verifyReads(prefix, expectedText, writes) {
    for (const kind of Object.keys(this.files)) {
      const result = this.result(prefix + '-' + kind);
      assert.notEqual(result.ok, false, JSON.stringify(result));
      assert.equal(result.sha256, writes[kind].sha256);
      assert.equal(result.sha256, sha256(this.files[kind]));
      if (kind === 'docx') {
        assert.equal(result.paragraphs[0].text, expectedText);
        assert.deepEqual(result.tables, [[['項目', '値'], ['synthetic', '7']]]);
      } else if (kind === 'xlsx') {
        assert.equal(result.cells.find(cell => cell.cell === 'A1').value, expectedText);
        assert.equal(result.cells.find(cell => cell.cell === 'B2').value, 7);
      } else {
        assert.equal(result.slides[0].shapes.find(shape => shape.shape === 0).paragraphs[0], expectedText);
        assert(result.slides[0].shapes.some(shape => shape.paragraphs?.includes('本文 日本語')));
      }
    }
  }

  answer(body) {
    assert.equal(body.model, MODEL);
    assert(Array.isArray(body.messages) && body.messages[0].role === 'system');
    const expectedTools = ['docx_write', 'docx_read', 'docx_edit', 'xlsx_write', 'xlsx_read', 'pptx_write', 'pptx_read', 'pptx_edit'];
    for (const name of expectedTools) assert(body.tools.some(tool => tool.function?.name === name), 'Missing real schema: ' + name);
    for (const message of body.messages.filter(message => message.role === 'tool')) {
      const value = JSON.parse(message.content);
      if (this.results.has(message.tool_call_id)) assert.deepEqual(value, this.results.get(message.tool_call_id));
      this.results.set(message.tool_call_id, value);
    }
    for (const previous of this.previousCalls) this.result(previous.id);
    let calls;
    const initialText = '作成 日本語 & !';
    const editedText = '編集済み 日本語 & !';
    switch (this.stage) {
      case 0:
        assert.equal(this.results.size, 0);
        calls = [
          call('create-docx', 'docx_write', {path: this.files.docx, expected_sha256: 'missing',
            paragraphs: [initialText], tables: [[['項目', '値'], ['synthetic', '7']]]}),
          call('create-xlsx', 'xlsx_write', {path: this.files.xlsx, expected_sha256: 'missing',
            cells: [{sheet: 'Sheet', cell: 'A1', value: initialText}, {sheet: 'Sheet', cell: 'B2', value: 7}]}),
          call('create-pptx', 'pptx_write', {path: this.files.pptx, expected_sha256: 'missing',
            slides: [{title: initialText, body: ['本文 日本語']}]}),
        ];
        break;
      case 1:
        for (const kind of Object.keys(this.files)) this.created[kind] = this.verifyWrite(kind, 'create', 'created');
        calls = this.reads('read-created');
        break;
      case 2:
        this.verifyReads('read-created', initialText, this.created);
        calls = this.edits('edit', this.created, editedText);
        break;
      case 3:
        for (const kind of Object.keys(this.files)) {
          this.edited[kind] = this.verifyWrite(kind, 'edit', 'updated');
          assert.notEqual(this.edited[kind].sha256, this.created[kind].sha256);
        }
        calls = this.reads('read-edited');
        break;
      case 4:
        this.verifyReads('read-edited', editedText, this.edited);
        calls = this.edits('stale', this.created, 'THIS MUST NOT BE WRITTEN');
        break;
      case 5:
        for (const kind of Object.keys(this.files)) {
          assert.equal(this.result('stale-' + kind).ok, false);
          assert.match(this.result('stale-' + kind).error, /expected_sha256/);
          assert.equal(sha256(this.files[kind]), this.edited[kind].sha256);
        }
        calls = this.protectedDirectories.flatMap((directory, index) => [
          call('denied-read-' + index, 'read_text', {path: path.join(directory, 'portable-sentinel.txt')}),
          call('denied-write-' + index, 'write_text', {path: path.join(directory, 'portable-forbidden.txt'),
            text: 'THIS MUST NOT BE WRITTEN', expected_sha256: 'missing'}),
          call('denied-list-' + index, 'list_directory', {path: directory}),
        ]);
        break;
      case 6:
        for (const previous of this.previousCalls) {
          const result = this.result(previous.id);
          assert.equal(result.ok, false, previous.id + ': ' + JSON.stringify(result));
          assert.match(result.error, /denied folder/i, 'Must fail because of runtime deny scope');
        }
        for (const directory of this.protectedDirectories) {
          assert(!fs.existsSync(path.join(directory, 'portable-forbidden.txt')));
          assert.equal(fs.readFileSync(path.join(directory, 'portable-sentinel.txt'), 'utf8'), 'synthetic protected data');
        }
        calls = [];
        break;
      default: throw new Error('Unexpected extra Office model call');
    }
    this.previousCalls = calls;
    this.stage++;
    this.report.providerRequests.push({method: 'POST', path: '/v1/chat/completions', stage: this.stage,
      toolCalls: calls.map(item => ({id: item.id, name: item.function.name}))});
    return completion(this.stage, calls, calls.length ? undefined : FINAL_TEXT);
  }

  async handle(req, res) {
    try {
      assert.equal(req.socket.remoteAddress, '127.0.0.1');
      assert.equal(req.headers.authorization, undefined, 'No real credential may reach fixture');
      if (req.method === 'GET' && req.url === '/v1/models') {
        this.report.providerRequests.push({method: 'GET', path: req.url});
        res.writeHead(200, {'Content-Type': 'application/json'});
        res.end(JSON.stringify({data: [{id: MODEL}]}));
        return;
      }
      assert.equal(req.method, 'POST');
      assert.equal(req.url, '/v1/chat/completions', 'Only local synthetic inference is permitted');
      let raw = '';
      req.setEncoding('utf8');
      for await (const chunk of req) {
        raw += chunk;
        assert(Buffer.byteLength(raw) <= 1024 * 1024, 'Fixture request too large');
      }
      const body = JSON.parse(raw);
      const task = body.messages.find(message => message.role === 'user')?.content;
      if (task === STOP_TASK) {
        assert.equal(body.model, MODEL);
        this.stopRequests++;
        this.pendingStops.add(res);
        this.report.providerRequests.push({method: 'POST', path: req.url, stage: 'held-until-stop'});
        res.on('close', () => {
          this.pendingStops.delete(res);
          if (!res.writableEnded) this.cancelledStops++;
        });
        return;
      }
      assert.equal(task, OFFICE_TASK, 'Unexpected task cannot invoke fixture');
      const response = this.answer(body);
      res.writeHead(200, {'Content-Type': 'application/json'});
      res.end(JSON.stringify(response));
    } catch (error) {
      this.errors.push(error.stack || String(error));
      if (!res.headersSent) res.writeHead(500, {'Content-Type': 'application/json'});
      res.end(JSON.stringify({error: 'Synthetic acceptance assertion failed'}));
    }
  }
}

async function main() {
  const root = path.resolve(__dirname, '..');
  const artifacts = path.join(root, 'runtime', 'verification');
  fs.mkdirSync(artifacts, {recursive: true});
  for (const file of ['portable-workbench.png', 'portable-workbench-failure.png'])
    fs.rmSync(path.join(artifacts, file), {force: true});
  const report = {schemaVersion: 1, fixture: 'SYNTHETIC: local deterministic HTTP provider; no live APIs or user data',
    test: 'actual-frozen-windows-onedir', startedAt: new Date().toISOString(), platform: process.platform,
    commit: process.env.GITHUB_SHA || null, runId: process.env.GITHUB_RUN_ID || null,
    passed: false, checks: [], providerRequests: [], pageErrors: [], externalRequests: [], cspErrors: []};
  const processes = [];
  let provider, occupied, browser, fixture, page, sandbox;
  try {
    assert.equal(process.platform, 'win32', 'Portable acceptance must run on Windows against the real EXE');
    const {chromium} = createRequire(path.join(__dirname, 'browser-tests', 'package.json'))('playwright');
    sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'Workbench 日本語 space & ! '));
    const environment = cleanEnvironment(sandbox);
    const {install, executable, manifest} = await prepareBundle(sandbox, environment, report);
    const workspace = path.join(sandbox, '作業 workspace & !');
    const state = path.join(sandbox, '状態 state & !');
    const internal = path.join(install, '_internal');
    for (const directory of [workspace, state]) fs.mkdirSync(directory);
    for (const directory of [install, internal, state])
      fs.writeFileSync(path.join(directory, 'portable-sentinel.txt'), 'synthetic protected data', 'utf8');
    const version = await runCommand(executable, ['--version'], environment, workspace);
    assert(version.stdout.includes(manifest.version), 'Normal --version matches built manifest');
    report.application = {executable, version: version.stdout.trim(), sha256: sha256(executable), install, internal, state, workspace,
      cwd: workspace, environmentKeys: Object.keys(environment).sort(), childPath: environment.PATH,
      pythonEnvironmentInherited: false, driverDependencies: ['Node', 'Playwright', 'Microsoft Edge']};
    fixture = new OfficeFixture(workspace, [install, internal, state], report);
    provider = http.createServer((req, res) => { void fixture.handle(req, res); });
    await new Promise((resolve, reject) => { provider.once('error', reject); provider.listen(0, '127.0.0.1', resolve); });
    const providerUrl = `http://127.0.0.1:${provider.address().port}/v1`;
    const app = launch(executable, state, environment, workspace);
    processes.push(app);
    const url = await launchUrl(app);
    const origin = new URL(url).origin;
    const port = Number(new URL(url).port);
    const token = new URLSearchParams(new URL(url).hash.slice(1)).get('token');
    report.checks.push('Real relocated MZ EXE starts with system-only PATH, no Python variables, separate Japanese/space/&/! app, state and workspace paths');
    const initial = await request(origin, '/api/state');
    assert.equal(initial.status, 401);
    for (const route of ['/', '/app.js', '/styles.css']) {
      const asset = await request(origin, route);
      assert.equal(asset.status, 200, route);
      assert(asset.raw.length > 100, 'Packaged asset must contain data: ' + route);
      assert.match(asset.headers['content-security-policy'], /default-src 'self'/);
      assert.equal(asset.headers['cache-control'], 'no-store');
    }
    assert.equal((await request(origin, '/api/bootstrap', {method: 'POST', body: {},
      headers: {Origin: origin, 'X-Workbench-Bootstrap': 'invalid-synthetic-token'}})).status, 401);
    assert.equal((await request(origin, '/api/bootstrap', {method: 'POST', body: {},
      headers: {'X-Workbench-Bootstrap': token}})).status, 403);
    assert.equal((await request(origin, '/', {headers: {Host: 'evil.invalid'}})).status, 403);
    assert.equal((await request(origin, '/', {headers: {Origin: 'https://evil.invalid'}})).status, 403);
    assert.equal((await request(origin, '/', {headers: {'Sec-Fetch-Site': 'cross-site'}})).status, 403);
    report.checks.push('Packaged static assets and security headers; no-cookie API denied; invalid bootstrap, Host, Origin and cross-site requests denied');

    // Edge is a test-driver dependency, never a dependency of the EXE process.
    browser = await chromium.launch({headless: true, channel: 'msedge'});
    report.browserVersion = browser.version(); report.browserChannel = 'msedge';
    const context = await browser.newContext({viewport: {width: 1366, height: 900}, locale: 'ja-JP',
      timezoneId: 'UTC', reducedMotion: 'reduce'});
    await context.route('**/*', route => {
      const destination = new URL(route.request().url());
      if (destination.origin === origin) return route.continue();
      report.externalRequests.push(destination.origin + destination.pathname);
      return route.abort('blockedbyclient');
    });
    page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on('pageerror', error => report.pageErrors.push(error.message));
    page.on('console', message => {
      if (/Content Security Policy|violates.*directive/i.test(message.text())) report.cspErrors.push(message.text());
    });
    await page.goto(url);
    await page.getByText('Workbench 接続中', {exact: true}).waitFor({state: 'attached'});
    assert.equal(new URL(page.url()).hash, '');
    const cookie = (await context.cookies(origin)).find(item => item.name === 'workbench_' + port);
    assert(cookie && cookie.httpOnly && cookie.sameSite === 'Strict');
    const authHeaders = {Origin: origin, Cookie: cookie.name + '=' + cookie.value};
    const api = async (route, options = {}) => {
      if (fixture.errors.length) throw new Error(fixture.errors.join('\n'));
      if (app.exited) throw new Error('Packaged server exited: ' + redact(app.stderr));
      const response = await request(origin, route, {...options, headers: {...authHeaders, ...options.headers}});
      assert.equal(response.status, 200, route + ': ' + response.raw);
      return response.json;
    };
    assert.equal((await request(origin, '/api/bootstrap', {method: 'POST', body: {},
      headers: {...authHeaders, 'X-Workbench-Bootstrap': token}})).status, 401);
    assert.equal((await request(origin, '/api/config', {headers: {...authHeaders, Host: 'localhost:' + port}})).status, 403);
    assert.equal((await request(origin, '/api/config', {method: 'PUT', body: {},
      headers: {...authHeaders, Origin: 'https://evil.invalid'}})).status, 403);
    assert.equal((await request(origin, '/api/config', {method: 'PUT', body: {},
      headers: {...authHeaders, 'Content-Type': 'text/plain'}})).status, 415);
    report.checks.push('Real Edge consumes one-use bootstrap, removes fragment and receives HttpOnly SameSite=Strict cookie; replay and authenticated Host/Origin/content-type attacks denied');

    const config = (await api('/api/config')).config;
    const profile = {...config.providers.find(item => item.kind === 'local'), id: 'local', label: 'Synthetic portable acceptance',
      base_url: providerUrl, model: MODEL, api_key_env: '', enabled: true, request_timeout_seconds: 30};
    config.providers = [profile];
    config.paths = {read_roots: [sandbox], write_roots: [sandbox], deny_roots: []};
    config.search.enabled = false; config.search.api_key_env = '';
    Object.assign(config.local, {gpu_guard_enabled: false, max_retries: 0, min_interval_seconds: 0});
    Object.assign(config.limits, {max_workers: 0, max_model_calls: 30, max_tool_calls: 100, max_context_chars: 500000, max_run_seconds: 180});
    await api('/api/config', {method: 'PUT', body: config});
    const persisted = JSON.parse(fs.readFileSync(path.join(state, 'settings.json'), 'utf8'));
    assert.deepEqual(persisted, config);
    const runPayload = {task: OFFICE_TASK, pm_profile: 'local', worker_profiles: [], max_workers: 0};
    const preflight = await api('/api/run-preflight', {method: 'POST', body: runPayload});
    assert.equal(preflight.can_start, true);
    assert.equal(preflight.inference_tested, false); assert.equal(preflight.tools_tested, false);
    const denied = preflight.scope.deny_roots.map(normalized);
    for (const directory of [install, internal, state])
      assert(denied.includes(normalized(directory)), 'Frozen runtime must explicitly deny: ' + directory);
    assert.deepEqual(fixture.report.providerRequests, [], 'Preflight must not perform network inference');
    assert.equal(preflight.destinations[0].endpoint, providerUrl + '/chat/completions');
    const diagnostic = await api('/api/provider-test', {method: 'POST', body: {provider_id: 'local'}});
    assert.equal(diagnostic.ok, true);
    report.checks.push('Persistent packaged config, no-network preflight with real frozen install/_internal/state deny roots, and real models-only provider diagnostic');

    // Start through the packaged UI. No Playwright API response mocks are used.
    await page.reload();
    await page.getByText('Workbench 接続中', {exact: true}).waitFor({state: 'attached'});
    await page.locator('#newRun').click(); await page.locator('#taskInput').fill(OFFICE_TASK);
    await page.locator('#pmProfile').selectOption('local'); await page.locator('#maxWorkers').fill('0');
    const started = page.waitForResponse(response => response.url().endsWith('/api/runs') && response.request().method() === 'POST');
    await page.locator('#startRun').click();
    const startResponse = await started; assert.equal(startResponse.status(), 200);
    const runId = (await startResponse.json()).run.id;
    const completed = await until(async () => {
      const snapshot = await api('/api/state');
      const run = snapshot.runs.find(item => item.id === runId);
      const agent = snapshot.agents.find(item => item.run_id === runId);
      if (agent?.status === 'error') throw new Error('Real packaged engine failed: ' + agent.last_error);
      return run?.status === 'done' ? {snapshot, run, agent} : null;
    }, 'real packaged provider -> engine -> Office round trip', 90000);
    assert.equal(fixture.stage, 7); assert.deepEqual(fixture.errors, []);
    assert.equal(completed.run.model_calls, 7); assert.equal(completed.run.tool_calls, 24);
    assert.equal(completed.agent.status, 'done');
    assert.equal(completed.agent.results.length, 1);
    assert.equal(completed.agent.results[0].source, 'assistant_response');
    assert.equal(completed.agent.results[0].text, FINAL_TEXT);
    assert.equal(completed.agent.output_receipts.length, 6, 'Failed hashes and denied writes cannot create receipts');
    for (const kind of Object.keys(fixture.files)) {
      const receipts = completed.agent.output_receipts.filter(item => normalized(item.path) === normalized(fixture.files[kind]));
      assert.equal(receipts.length, 2);
      assert.deepEqual(receipts.map(item => item.operation), ['created', 'updated']);
      assert.deepEqual(receipts.map(item => item.sha256), [fixture.created[kind].sha256, fixture.edited[kind].sha256]);
      assert.deepEqual(receipts.map(item => item.bytes), [fixture.created[kind].bytes, fixture.edited[kind].bytes]);
      assert.deepEqual(receipts.map(item => item.tool), [kind + '_write', kind === 'xlsx' ? 'xlsx_write' : kind + '_edit']);
    }
    report.office = {created: fixture.created, edited: fixture.edited, receipts: completed.agent.output_receipts,
      results: completed.agent.results, modelCalls: completed.run.model_calls, toolCalls: completed.run.tool_calls};
    report.deniedTools = Object.fromEntries([...fixture.results].filter(([id]) => id.startsWith('denied-')));
    report.checks.push('Real HTTP ProviderClient and Engine create/read/edit/reread three Office packages; exact file hashes, bytes, native content and six successful receipts verified');
    report.checks.push('Stale hashes rejected for DOCX/XLSX/PPTX; read/write/list denied in install folder, _internal and state beneath deliberately broad allowed ancestor; denied writes produce no files or receipts');
    await page.locator('#activeRunStatus').filter({hasText: '完了'}).waitFor();
    await page.locator('#resultsPanel > summary').click();
    await page.waitForFunction(() => document.querySelectorAll('#resultSelection option').length === 7);
    await page.locator('#resultSelection').selectOption(await page.locator('#resultSelection option[value^="result:"]').getAttribute('value'));
    assert.equal(await page.locator('#resultText').textContent(), FINAL_TEXT);
    assert.match(await page.locator('#resultsCount').textContent(), /報告 1 · 保存 6/);
    const receiptOption = await page.locator('#resultSelection option[value^="receipt:"]').first().getAttribute('value');
    await page.locator('#resultSelection').selectOption(receiptOption);
    assert.match(await page.locator('#resultText').textContent(), /[a-f0-9]{64}/);
    assert.match(await page.locator('#resultNotice').textContent(), /保存時点/);
    await page.locator('#resultSelection').selectOption(await page.locator('#resultSelection option[value^="result:"]').getAttribute('value'));
    await page.screenshot({path: path.join(artifacts, 'portable-workbench.png'), fullPage: true, animations: 'disabled'});
    report.screenshot = 'portable-workbench.png';
    report.checks.push('Packaged UI in real Microsoft Edge starts the real run and displays ordinary final result plus six separate saved-file receipts; screenshot captured');

    await page.locator('#newRun').click(); await page.locator('#taskInput').fill(STOP_TASK);
    const stopStarted = page.waitForResponse(response => response.url().endsWith('/api/runs') && response.request().method() === 'POST');
    await page.locator('#startRun').click();
    const stopRunId = (await (await stopStarted).json()).run.id;
    await until(() => fixture.pendingStops.size === 1, 'real provider request in flight');
    assert.equal((await request(origin, '/api/config', {method: 'PUT', body: config, headers: authHeaders})).status, 409);
    await page.locator('#stopRun').click();
    await page.locator('#activeRunStatus').filter({hasText: '停止'}).waitFor();
    const stopped = await api('/api/state');
    assert.equal(stopped.runs.find(item => item.id === stopRunId).status, 'stopped');
    const stoppedAgent = stopped.agents.find(item => item.run_id === stopRunId);
    assert.equal(stoppedAgent.status, 'stopped'); assert.deepEqual(stoppedAgent.output_receipts, []);
    assert.equal(await page.locator('#sendMessage').isDisabled(), true);
    await until(() => fixture.cancelledStops === 1, 'provider connection cancelled by actual stop');
    assert.equal(fixture.stopRequests, 1);
    await api('/api/runs/' + stopRunId + '/stop', {method: 'POST', body: {}});
    assert.equal((await request(origin, '/api/agents/' + stoppedAgent.id + '/message', {
      method: 'POST', body: {text: 'Must be rejected after stop'}, headers: authHeaders})).status, 400);
    await api('/api/config', {method: 'PUT', body: config});
    report.checks.push('Real UI stop cancels a blocked HTTP provider request, settles agent/run, rejects later messages, is idempotent, and unlocks settings');

    const settingsHash = sha256(path.join(state, 'settings.json'));
    report.duplicateDynamic = await duplicateLaunch(executable, state, environment, workspace, 0);
    assert.equal(sha256(path.join(state, 'settings.json')), settingsHash, 'Duplicate launch cannot alter settings');
    report.occupiedApplicationPort = await rejectsOccupiedPort(executable, path.join(sandbox, 'duplicate state 日本語 & !'), environment, workspace, port);
    occupied = http.createServer((_req, res) => res.end('synthetic occupied port'));
    await new Promise((resolve, reject) => { occupied.once('error', reject); occupied.listen(0, '127.0.0.1', resolve); });
    report.occupiedPort = await rejectsOccupiedPort(executable, path.join(sandbox, 'occupied state 日本語 & !'), environment,
      workspace, occupied.address().port);
    const second = launch(executable, path.join(sandbox, 'second state 日本語 & !'), environment, workspace);
    processes.push(second);
    const secondOrigin = new URL(await launchUrl(second)).origin;
    assert.notEqual(secondOrigin, origin, 'Independent --port 0 launches must receive distinct ports');
    assert.equal((await request(secondOrigin, '/api/state', {headers: {...authHeaders, Origin: secondOrigin}})).status, 401);
    await terminate(second);
    report.checks.push('Duplicate same-state port-0 launch exits cleanly without a new token; occupied app/foreign ports fail without creating state; independent port-0 instance gets distinct port and rejects first-instance cookie');

    await browser.close(); browser = null;
    await terminate(app);
    const restarted = launch(executable, state, environment, workspace, port);
    processes.push(restarted);
    const restartUrl = await launchUrl(restarted);
    assert.equal(new URL(restartUrl).origin, origin, 'Terminated process releases its port');
    report.duplicateFixed = await duplicateLaunch(executable, state, environment, workspace, port);
    assert.equal((await request(origin, '/api/state', {headers: authHeaders})).status, 401, 'Old session is invalid after restart');
    const restartToken = new URLSearchParams(new URL(restartUrl).hash.slice(1)).get('token');
    assert.notEqual(restartToken, token);
    const freshBootstrap = await request(origin, '/api/bootstrap', {method: 'POST', body: {},
      headers: {Origin: origin, 'X-Workbench-Bootstrap': restartToken}});
    assert.equal(freshBootstrap.status, 200);
    const freshCookie = freshBootstrap.headers['set-cookie'][0].split(';')[0];
    const freshHeaders = {Origin: origin, Cookie: freshCookie};
    const restored = await request(origin, '/api/config', {headers: freshHeaders});
    assert.equal(restored.status, 200); assert.deepEqual(restored.json.config, config);
    const freshState = await request(origin, '/api/state', {headers: freshHeaders});
    assert.equal(freshState.status, 200); assert.deepEqual(freshState.json.runs, []); assert.deepEqual(freshState.json.agents, []);
    assert(!fs.existsSync(path.join(install, 'settings.json')));
    assert(!fs.existsSync(path.join(internal, 'settings.json')));
    assert(!fs.existsSync(path.join(install, 'state')));
    for (const kind of Object.keys(fixture.files)) assert.equal(sha256(fixture.files[kind]), fixture.edited[kind].sha256);
    await terminate(restarted);
    report.checks.push('Process termination/restart releases port, rotates bootstrap/session, restores external settings, preserves workspace files, and starts without prior in-memory runs; fixed-port duplicate guard verified (not a Ctrl+C test)');
    assert.deepEqual(report.pageErrors, []); assert.deepEqual(report.cspErrors, []);
    assert.deepEqual(report.externalRequests, []); assert.deepEqual(fixture.errors, []);
    report.passed = true;
  } catch (error) {
    report.error = redact(error.stack || error);
    if (page && !page.isClosed()) {
      try { await page.screenshot({path: path.join(artifacts, 'portable-workbench-failure.png'), fullPage: true}); }
      catch { /* Preserve primary failure. */ }
    }
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close().catch(() => {});
    for (const processInfo of processes.reverse()) await terminate(processInfo).catch(error => {
      report.cleanupError = redact(error); report.passed = false; process.exitCode = 1;
    });
    if (fixture) {
      for (const response of fixture.pendingStops) response.destroy();
      report.fixtureErrors = fixture.errors;
    }
    for (const listener of [provider, occupied]) if (listener) {
      listener.closeAllConnections?.();
      await new Promise(resolve => listener.close(resolve));
    }
    report.processes = processes.map(item => ({args: item.args, exitCode: item.child.exitCode,
      signal: item.child.signalCode, stdout: redact(item.stdout), stderr: redact(item.stderr)}));
    report.finishedAt = new Date().toISOString();
    // Keep synthetic files for CI diagnosis. Nothing points to a real workspace.
    report.sandbox = sandbox || null;
    fs.writeFileSync(path.join(artifacts, 'portable-smoke.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({passed: report.passed, checks: report.checks.length,
      report: path.join(artifacts, 'portable-smoke.json'), error: report.error || null}));
  }
}

if (require.main === module) void main();
module.exports = {OfficeFixture, cleanEnvironment, completion, request};
