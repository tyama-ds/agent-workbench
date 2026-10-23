"""Fixed Selenium worker. Browser processes run as the ordinary Windows user.

Only the structured operations below are accepted; there is no model supplied
Python, JavaScript, browser option, driver command, or existing-profile attach.
This is an automation interface, NOT a filesystem or network sandbox.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

_MAX_URL = 8192
_PNG = b'\x89PNG\r\n\x1a\n'
_DETACHED_PROCESS = 0x00000008  # Win32 constant; worker always runs on Windows.
_FILL = """
const e = arguments[0], value = arguments[1];
const tag = e.tagName.toLowerCase();
const allowed = ['text', 'search', 'email', 'url', 'tel', 'password', 'number'];
if (!(tag === 'textarea' || (tag === 'input' && allowed.includes(e.type))) ||
    e.disabled || e.readOnly || e.matches(':disabled')) {
  throw new Error('Only editable text inputs and textareas may be filled');
}
// The native value setter never selects or uploads a file. Unlike send_keys,
// a change to type=file cannot turn this operation into a host-file upload.
const proto = tag === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
Object.getOwnPropertyDescriptor(proto, 'value').set.call(e, value);
e.dispatchEvent(new Event('input', {bubbles: true}));
e.dispatchEvent(new Event('change', {bubbles: true}));
"""
_READ = "return Array.from(String(arguments[0].innerText || arguments[0].textContent || '').slice(0, arguments[1] * 2)).slice(0, arguments[1]).join('');"
_BODY = "return document.body ? Array.from(String(document.body.innerText || '').slice(0, arguments[0] * 2)).slice(0, arguments[0]).join('') : '';"
_ELEMENTS = """
const result = [], limit = arguments[0];
let truncated = false, visited = 0;
const clip = (s, n) => Array.from(String(s || '').slice(0, n * 2)).slice(0, n).join('');
function textWithoutValues(node) {
  const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
  let value = '', count = 0, text;
  while ((text = walker.nextNode()) && count++ < 2000 && Array.from(value).length < 240) {
    if (!text.parentElement.closest('input,textarea,select,option,script,style')) {
      value += clip(text.data, 240 - Array.from(value).length);
    }
  }
  return clip(value.replace(/\\s+/g, ' ').trim(), 120);
}
function selectorFor(e) {
  if (e.id) {
    const selector = '#' + CSS.escape(e.id);
    if (document.querySelectorAll(selector).length === 1) return selector;
  }
  const path = [];
  let current = e;
  while (current && current !== document.body && path.length < 64) {
    let index = 1, previous = current.previousElementSibling;
    while (previous) {
      if (previous.localName === current.localName) ++index;
      previous = previous.previousElementSibling;
    }
    path.unshift(current.localName + ':nth-of-type(' + index + ')');
    current = current.parentElement;
  }
  return current === document.body ? ['body', ...path].join(' > ') : '';
}
for (const e of document.querySelectorAll('button,a,input,select,textarea')) {
  if (++visited > 2000) { truncated = true; break; }
  const style = getComputedStyle(e);
  if (e.namespaceURI !== 'http://www.w3.org/1999/xhtml' || e.getRootNode() !== document || !e.getClientRects().length ||
      style.visibility === 'hidden' || style.visibility === 'collapse' || style.display === 'none' ||
      (e.localName === 'input' && e.type === 'hidden')) continue;
  if (result.length === limit) { truncated = true; break; }
  const selector = selectorFor(e);
  if (!selector || selector.length > 2048) { truncated = true; continue; }
  const tag = e.localName;
  let label = e.getAttribute('aria-label');
  if (!label && e.labels && e.labels.length) label = textWithoutValues(e.labels[0]);
  if (!label && (tag === 'a' || tag === 'button')) label = textWithoutValues(e);
  if (!label) label = e.getAttribute('placeholder') || e.getAttribute('name') || '';
  const item = {selector, tag, label: clip(String(label).replace(/\\s+/g, ' ').trim(), 120)};
  if (tag === 'a' && e.href) {
    try {
      const href = new URL(e.href);
      if (['http:', 'https:'].includes(href.protocol) && !href.username && !href.password && href.href.length <= 8192) {
        item.href = href.href;
      }
    } catch (_) {}
  }
  result.push(item);
}
return {elements: result, truncated};
"""


def _validate_elements(value):
    if not isinstance(value, list) or len(value) > 40:
        raise ValueError('Invalid Selenium elements list')
    result = []
    for item in value:
        if (not isinstance(item, dict) or not {'selector', 'tag', 'label'} <= set(item)
                or set(item) - {'selector', 'tag', 'label', 'href'}):
            raise ValueError('Invalid Selenium element fields')
        tag = item['tag']
        if not isinstance(tag, str) or tag not in {'button', 'a', 'input', 'select', 'textarea'}:
            raise ValueError('Invalid Selenium element tag')
        entry = {'selector': _text(item['selector'], 'element selector', 2048), 'tag': tag,
                 'label': _text(item['label'], 'element label', 120, empty=True)}
        if 'href' in item:
            entry['href'] = validate_url(item['href'])
        result.append(entry)
    return result


def _text(value, label, maximum, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value) or '\0' in value:
        raise ValueError(f'{label} must be a string of at most {maximum} characters')
    value.encode('utf-8')
    return value


def validate_url(value):
    value = _text(value, 'URL', _MAX_URL)
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or '\\' in value:
        raise ValueError('URL cannot contain whitespace, controls, or backslashes')
    try:
        parts = urlsplit(value)
        if (parts.scheme.lower() not in {'http', 'https'} or not parts.hostname
                or parts.username is not None or parts.password is not None or '%' in parts.hostname):
            raise ValueError('Only HTTP(S) URLs without embedded credentials are supported')
        parts.port
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Only valid HTTP(S) URLs without embedded credentials are supported') from exc
    return value


def validate_proxy(value):
    if value == '':
        return ''
    value = validate_url(value)
    parts = urlsplit(value)
    if parts.path not in {'', '/'} or parts.query or parts.fragment:
        raise ValueError('Selenium proxy must contain only an HTTP(S) server and optional port')
    return value.rstrip('/')


def validate_actions(actions):
    if actions is None:
        return []
    if not isinstance(actions, list) or len(actions) > 20:
        raise ValueError('Selenium actions must contain at most 20 operations')
    result = []
    for item in actions:
        if not isinstance(item, dict):
            raise ValueError('Each Selenium action must be an object')
        action = item.get('action')
        if not isinstance(action, str) or action not in {'click', 'fill', 'read', 'wait'}:
            raise ValueError('Unsupported Selenium action')
        required = {'action', 'selector', 'text'} if action == 'fill' else {'action', 'selector'}
        if set(item) != required:
            raise ValueError('Selenium action has unsupported or missing fields')
        selector = _text(item['selector'], 'CSS selector', 2048)
        entry = {'action': action, 'selector': selector}
        if action == 'fill':
            entry['text'] = _text(item['text'], 'fill text', 8000, empty=True)
        result.append(entry)
    return result


def _options(options, job, workspace):
    options.binary_location = job['browser_executable']
    for value in ('--headless=new', '--disable-extensions', '--no-first-run',
                  '--no-default-browser-check', '--disable-background-networking',
                  '--disable-component-update', '--disable-sync', '--remote-debugging-pipe',
                  '--window-size=1280,800', f'--user-data-dir={workspace / "profile"}'):
        options.add_argument(value)
    proxy = validate_proxy(job.get('proxy_url', ''))
    options.add_argument(f'--proxy-server={proxy}' if proxy else '--no-proxy-server')
    options.add_experimental_option('prefs', {
        'credentials_enable_service': False,
        'profile.password_manager_enabled': False,
        'autofill.profile_enabled': False,
        'autofill.credit_card_enabled': False,
        'download_restrictions': 3,
        'profile.default_content_setting_values.automatic_downloads': 2,
    })
    return options


def create_driver(job, workspace):
    # Imports are deliberately delayed until main has installed the explicitly
    # selected library folders. Supplying Service and binary avoids Manager.
    from selenium import webdriver
    if job['browser'] == 'edge':
        from selenium.webdriver.edge.service import Service
        options, factory = webdriver.EdgeOptions(), webdriver.Edge
    elif job['browser'] == 'chrome':
        from selenium.webdriver.chrome.service import Service
        options, factory = webdriver.ChromeOptions(), webdriver.Chrome
    else:
        raise ValueError('Selenium browser must be edge or chrome')
    # Do not create a console host that could exit before the parent Job runner
    # captures its process handle. Pipes still carry the service's standard I/O.
    service = Service(executable_path=job['driver_executable'],
                      service_args=['--allowed-ips=127.0.0.1'], log_output=subprocess.DEVNULL,
                      popen_kw={'creation_flags': _DETACHED_PROCESS})
    return factory(service=service, options=_options(options, job, workspace))


def _visible(driver, selector, deadline):
    from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
    until = min(deadline, time.monotonic() + 5)
    while True:
        try:
            element = driver.find_element('css selector', selector)
            if element.is_displayed():
                return element
        except (NoSuchElementException, StaleElementReferenceException):
            pass
        remaining = until - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Selenium element did not become visible within the wait limit')
        time.sleep(min(.1, remaining))


def run_job(job, workspace, *, driver_factory=None):
    url, actions = validate_url(job['url']), validate_actions(job.get('actions'))
    maximum = job['max_output_chars']
    if type(maximum) is not int or not 1000 <= maximum <= 100000:
        raise ValueError('Invalid Selenium output limit')
    timeout = job['timeout_seconds']
    if type(timeout) is not int or not 10 <= timeout <= 300:
        raise ValueError('Invalid Selenium timeout')
    deadline = time.monotonic() + timeout
    driver = (driver_factory or create_driver)(job, workspace)
    try:
        driver.set_page_load_timeout(min(timeout, 30))
        driver.set_script_timeout(min(timeout, 5))
        driver.implicitly_wait(0)
        # Browser-wide denial covers new tabs too. Failure is fatal: no page is
        # loaded if this Chromium feature is unavailable on the selected pair.
        driver.execute_cdp_cmd('Browser.setDownloadBehavior', {'behavior': 'deny'})
        driver.get(url)
        validate_url(driver.current_url)
        results, read_budget, truncated = [], maximum, False
        for index, item in enumerate(actions):
            if time.monotonic() >= deadline:
                raise TimeoutError('Selenium operation deadline exceeded')
            validate_url(driver.current_url)
            element = _visible(driver, item['selector'], deadline)
            record = {'index': index, 'action': item['action']}
            if item['action'] == 'click':
                # A native file picker is not part of this tool's interface.
                if element.tag_name.lower() == 'input' and element.get_attribute('type').lower() == 'file':
                    raise ValueError('File input interactions are not supported')
                href = element.get_attribute('href')
                if href:
                    validate_url(href)
                element.click()
            elif item['action'] == 'fill':
                driver.execute_script(_FILL, element, item['text'])
            elif item['action'] == 'read':
                content = driver.execute_script(_READ, element, read_budget + 1)
                content = _text(content, 'element text', maximum + 1, empty=True)
                truncated |= len(content) > read_budget
                record['text'] = content[:read_budget]
                read_budget -= len(record['text'])
            validate_url(driver.current_url)
            results.append(record)
        final_url = validate_url(driver.current_url)
        title = str(driver.title)
        discovered = driver.execute_script(_ELEMENTS, 40)
        if (not isinstance(discovered, dict) or set(discovered) != {'elements', 'truncated'}
                or type(discovered['truncated']) is not bool):
            raise ValueError('Invalid Selenium element discovery result')
        elements = _validate_elements(discovered['elements'])
        truncated |= discovered['truncated']
        body = driver.execute_script(_BODY, maximum + 1)
        body = _text(body, 'page text', maximum + 1, empty=True)
        # One budget for URL, title, reads, discovered elements, and page text.
        remaining = maximum
        def take(value):
            nonlocal remaining, truncated
            truncated |= len(value) > remaining
            text = value[:remaining]
            remaining -= len(text)
            return text
        output = {'url': take(final_url), 'title': take(title), 'actions': results, 'elements': []}
        for record in results:
            if 'text' in record:
                record['text'] = take(record['text'])
        # Reserve at least half the initial budget for page/explicit read text.
        # Selectors must remain complete; a shortened selector is not actionable.
        discovery_left = min(remaining, maximum // 2)
        for item in elements:
            base = len(item['selector']) + len(item['tag'])
            if base > discovery_left:
                truncated = True
                continue
            entry = {'selector': take(item['selector']), 'tag': take(item['tag'])}
            discovery_left -= base
            label = item['label'][:discovery_left]
            truncated |= len(label) < len(item['label'])
            entry['label'] = take(label)
            discovery_left -= len(label)
            if 'href' in item:
                if len(item['href']) <= discovery_left:
                    entry['href'] = take(item['href'])
                    discovery_left -= len(item['href'])
                else:
                    truncated = True
            output['elements'].append(entry)
        output['text'] = take(body)
        output['truncated'] = truncated
        if job.get('screenshot_requested'):
            data = driver.get_screenshot_as_png()
            if not isinstance(data, bytes) or not data.startswith(_PNG) or len(data) > job['max_screenshot_bytes']:
                raise ValueError('Screenshot is not a PNG or exceeds the file limit')
            (workspace / 'screenshot.png').write_bytes(data)
        return output
    finally:
        # Even when quit fails or hangs, the parent Job runner stops and waits
        # for every descendant before any file is published or storage removed.
        driver.quit()


def main():
    if len(sys.argv) != 2:
        raise ValueError('Expected the private job file')
    job_path = Path(sys.argv[1])
    if job_path.stat().st_size > 1024 * 1024:
        raise ValueError('Selenium job file is too large')
    job = json.loads(job_path.read_text(encoding='utf-8'))
    workspace = job_path.parent
    os.chdir(workspace)
    os.environ.update(SE_OFFLINE='true', SE_AVOID_STATS='true', MSEDGEDRIVER_TELEMETRY_OPTOUT='1',
                      NO_PROXY='localhost,127.0.0.1,::1', TEMP=str(workspace), TMP=str(workspace))
    libraries = job['library_paths']
    if not isinstance(libraries, list) or len(libraries) > 32 or not all(isinstance(x, str) for x in libraries):
        raise ValueError('Invalid Selenium library folders')
    sys.path.extend(libraries)
    result = run_job(job, workspace)
    (workspace / 'result.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Selenium {type(exc).__name__}: {str(exc)[:2000]}', file=sys.stderr)
        raise SystemExit(1)
