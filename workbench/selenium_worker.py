"""Fixed Selenium worker. Browser processes run as the ordinary Windows user.

Only the structured operations below are accepted; there is no model supplied
Python, JavaScript, browser option, driver command, or existing-profile attach.
This is an automation interface, NOT a filesystem or network sandbox.
"""
from __future__ import annotations

import json
import os
import re
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


def _page_options(options, job, workspace):
    """Browser search: an ordinary (not headless) window with the application's own lasting profile.

    The profile keeps cookies between searches, which is what lets a search
    engine recognise a browser that a person already verified. It is never the
    human's own profile. The window is kept off the visible screen unless a
    person has to act in it.
    """
    options.binary_location = job['browser_executable']
    profile = _text(job['profile_dir'], 'profile folder', 4096)
    for value in ('--disable-extensions', '--no-first-run', '--no-default-browser-check',
                  '--disable-component-update', '--disable-sync', '--remote-debugging-pipe',
                  '--disk-cache-size=52428800', '--window-size=1180,860', f'--user-data-dir={profile}'):
        options.add_argument(value)
    options.add_argument('--window-position=60,40' if job['visible'] is True else '--window-position=-2400,-2400')
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


def _fetch_options(options, job, workspace):
    """One try of a refused address: an ordinary window on the screen, a fresh profile that is deleted afterwards.

    Nothing here hides that the browser is driven by a program: no changed
    User-Agent, no removed automation marks, no headless mode. A PDF is saved
    into this job's private folder instead of being shown in the viewer.
    """
    options.binary_location = job['browser_executable']
    for value in ('--disable-extensions', '--no-first-run', '--no-default-browser-check',
                  '--disable-component-update', '--disable-sync', '--remote-debugging-pipe',
                  '--window-size=1180,860', '--window-position=60,40', f'--user-data-dir={workspace / "profile"}'):
        options.add_argument(value)
    proxy = validate_proxy(job.get('proxy_url', ''))
    options.add_argument(f'--proxy-server={proxy}' if proxy else '--no-proxy-server')
    options.add_experimental_option('prefs', {
        'credentials_enable_service': False,
        'profile.password_manager_enabled': False,
        'autofill.profile_enabled': False,
        'autofill.credit_card_enabled': False,
        'download.default_directory': str(workspace / 'downloads'),
        'download.prompt_for_download': False,
        'plugins.always_open_pdf_externally': True,
        'profile.default_content_setting_values.automatic_downloads': 2,
    })
    return options


_PARTIAL = ('.crdownload', '.tmp', '.partial')
_STATUS = ("const e = performance.getEntriesByType('navigation')[0];"
           "return [e && typeof e.responseStatus === 'number' ? e.responseStatus : 0, String(document.contentType || ''),"
           " String(document.readyState || '')];")


# A PDF that the window shows in its viewer instead of saving it (the "always download PDFs" preference
# does not take in every browser version): the same document is read through the page's own fetch, which
# uses the window's session and its cache, as "Save" in the viewer does. Nothing is requested that the
# window has not already been given.
# The links of the page that may lead to a PDF: read from the page, never clicked.
_PDF_LINKS = ("const rows = [];"
              "for (const e of Array.from(document.querySelectorAll('a[href], a[data-href], a[data-url]')).slice(0, 3000)) {"
              "  let h = '';"
              "  for (const v of [e.getAttribute('data-href'), e.getAttribute('data-url'), e.getAttribute('href')]) {"
              "    if (v && (!h || /pdf/i.test(v))) { try { h = new URL(v, document.baseURI).href; } catch (x) {} if (/pdf/i.test(v)) break; }"
              "  }"
              "  if (h) rows.push([h, String(e.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 160)]);"
              "}"
              "return rows.slice(0, 3000);")
_FULL_REPORT = re.compile(r'full[\s-]*(?:report|text|document|publication)|complete report|entire report|'
                          r'報告書全体|全文|本文|報告書全文', re.I)


# Where the job is, for the record of a failure: "start browser", "open address", ...
_STEP = ['prepare']


def _step(name):
    _STEP[0] = name


def main_pdf_link(rows, page_url):
    """The one link of a read page that is its full report on the page's own site, or ''.

    A link counts when its address names a PDF. It is taken when its words say "full report" (or the like),
    or its file is named text.pdf / full*.pdf, or when it is the only PDF link of the site on the page.
    Several candidates and no such sign: none is taken, and the choice stays with whoever reads the page.
    """
    from urllib.parse import urlsplit, urldefrag
    host, found = urlsplit(page_url).hostname, {}
    for row in rows if isinstance(rows, list) else []:
        if not (isinstance(row, (list, tuple)) and len(row) == 2 and all(isinstance(item, str) for item in row)):
            continue
        try:
            address = validate_url(urldefrag(row[0])[0])
        except ValueError:
            continue
        parts = urlsplit(address)
        if parts.hostname != host or 'pdf' not in (parts.path + '?' + parts.query).lower() or len(address) > 2000:
            continue
        found.setdefault(address, row[1])
    for address, words in found.items():
        name = urlsplit(address).path.rsplit('/', 1)[-1].lower()
        if _FULL_REPORT.search(words) or name == 'text.pdf' or name.startswith('full'):
            return address
    return next(iter(found)) if len(found) == 1 else ''


_SHOWN_FETCH = ("const done = arguments[arguments.length - 1];"
                "fetch(window.location.href, {credentials: 'include', cache: 'force-cache'})"
                ".then(r => { if (!r.ok) throw new Error('status ' + r.status); return r.arrayBuffer(); })"
                ".then(b => { window.__awbPdf = new Uint8Array(b); done(window.__awbPdf.length); })"
                ".catch(e => done('error: ' + String(e).slice(0, 200)));")
_SHOWN_CHUNK = ("const a = window.__awbPdf.subarray(arguments[0], arguments[1]); let s = '';"
                "for (let i = 0; i < a.length; i += 32768) s += String.fromCharCode.apply(null, a.subarray(i, i + 32768));"
                "return btoa(s);")
_SHOWN_STEP = 512 * 1024


def _save_shown_pdf(driver, downloads, largest):
    """Write the PDF that the window is showing into the download folder. -> (file name or '', size, reason)."""
    import base64
    driver.set_script_timeout(120)
    try:
        size = driver.execute_async_script(_SHOWN_FETCH)
        if type(size) is not int or size <= 0:
            return '', 0, str(size)[:200] if isinstance(size, str) else 'the page gave no data'
        if size > largest:
            return '', size, 'too_large'
        target = downloads / 'shown.pdf'
        with open(target, 'wb') as stream:
            for start in range(0, size, _SHOWN_STEP):
                stream.write(base64.b64decode(driver.execute_script(_SHOWN_CHUNK, start, min(size, start + _SHOWN_STEP))))
        if target.stat().st_size != size:
            target.unlink()
            return '', 0, 'the data read from the page was incomplete'
        return target.name, size, ''
    except Exception as exc:
        return '', 0, type(exc).__name__
    finally:
        driver.set_script_timeout(5)


def run_fetch_job(job, workspace, *, driver_factory=None, clock=time.monotonic, sleep=time.sleep):
    """Load one address once in a visible window and report what came: a saved file, a page, or neither.

    Nothing is clicked, typed or solved. The window is closed whatever happens. A PDF that the window shows
    in its viewer is read through the page's own fetch (its session and cache) and saved like a download.
    With ``via`` the page that links to the address is loaded first, in the same window.
    With ``person_seconds`` a person has agreed to pass the site's check in this window: while the page is
    such a check (one of ``check_words`` in its title or its short text), the window stays open and is
    looked at again, until the page or a download arrives, the window is closed, or that time is over.
    With ``follow`` a page that links to its full report on its own site (see main_pdf_link) is followed by
    that file, in the same window; what came of it is in ``linked`` ({kind, url, status, file, bytes}, or {}).
    Returns {kind: download|page|closed|timeout|too_large, url, status, content_type, title, html, truncated,
    file, bytes, check, linked}.
    """
    url = validate_url(job['url'])
    wait, maximum, largest = job['wait_seconds'], job['max_page_chars'], job['max_download_bytes']
    person, words = job.get('person_seconds', 0), job.get('check_words', [])
    if type(person) is not int or not 0 <= person <= 600:
        raise ValueError('Invalid wait for a person')
    if not isinstance(words, list) or len(words) > 60 or not all(isinstance(word, str) and 0 < len(word) <= 80 for word in words):
        raise ValueError('Invalid check words')
    words = [word.casefold() for word in words]
    via = validate_url(job['via']) if job.get('via') else ''

    def is_check(title, text):
        title, text = title.casefold(), text[:6000].casefold()
        return any(word in title for word in words) or (len(text) < 6000 and any(word in text for word in words))
    if type(wait) is not int or not 5 <= wait <= 300:
        raise ValueError('Invalid fetch wait')
    if type(maximum) is not int or not 10000 <= maximum <= 4000000:
        raise ValueError('Invalid page size limit')
    if type(largest) is not int or not 1024 <= largest <= 1024 * 1024 * 1024:
        raise ValueError('Invalid download size limit')
    downloads = workspace / 'downloads'
    downloads.mkdir(exist_ok=True)
    result = {'kind': 'timeout', 'url': url, 'status': 0, 'content_type': '', 'title': '', 'html': '',
              'truncated': False, 'file': '', 'bytes': 0, 'check': False, 'linked': {}}
    _step('start browser')
    driver = (driver_factory or create_driver)(job, workspace)
    try:
        _step('set up window')
        driver.set_page_load_timeout(45)
        driver.set_script_timeout(5)
        driver.implicitly_wait(0)
        try:
            driver.execute_cdp_cmd('Browser.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': str(downloads)})
        except Exception:
            pass  # the profile's download folder is set as well; a browser without this command still saves there
        _step('open address')
        if via:
            # The page that links to the file, which a window read before: it is loaded first, and the file is
            # then asked for in the same window, with the session that page set up. Nothing is clicked.
            try:
                driver.get(via)
            except Exception:
                pass
            settled = clock() + 15
            while clock() < settled:
                try:
                    if driver.execute_script(_STATUS)[2] == 'complete':
                        break
                except Exception:
                    break
                sleep(.5)
            for item in downloads.iterdir():  # only what the address itself brings counts as its download
                if item.is_file():
                    item.unlink()
        def watch(result, started, deadline):
            """Look at the window until a download, a page, a closed window or the deadline; fill ``result``."""
            last = None
            while True:
                files = sorted(item for item in downloads.iterdir() if item.is_file())
                sizes = [(item.name, item.stat().st_size) for item in files]
                if any(size > largest for _, size in sizes):
                    result.update(kind='too_large', bytes=max(size for _, size in sizes))
                    break
                whole = [row for row in sizes if not row[0].lower().endswith(_PARTIAL)]
                if whole and len(whole) == len(sizes) and sizes == last:
                    # Present and unchanged since the last look: the download is finished.
                    result.update(kind='download', file=whole[0][0], bytes=whole[0][1])
                    break
                last = sizes
                try:
                    status, content_type, ready = driver.execute_script(_STATUS)
                    current = str(driver.current_url)
                except Exception:
                    if not sizes:
                        result['kind'] = 'closed'  # the person closed the window
                        break
                    status, content_type, ready, current = 0, '', '', ''
                if (not sizes and ready == 'complete' and current.startswith(('http://', 'https://'))
                        and clock() - started >= 2):
                    # A page stands in the window and no download began.
                    try:
                        check = is_check(str(driver.title), str(driver.page_source))
                    except Exception:
                        check = False
                    if check and person and clock() < deadline:
                        sleep(1)  # the person is passing the check; look again
                        continue
                    result.update(kind='page', status=status if type(status) is int and 0 <= status <= 599 else 0,
                                  content_type=str(content_type)[:80], check=check)
                    break
                if clock() >= deadline:
                    break
                sleep(.5)
            if result['kind'] == 'page' and result['content_type'].lower().startswith('application/pdf') and not result['check']:
                name, size, reason = _save_shown_pdf(driver, downloads, largest)
                if name:
                    result.update(kind='download', file=name, bytes=size)
                elif reason == 'too_large':
                    result.update(kind='too_large', bytes=size)
                else:
                    result['title'] = ('The PDF was shown but could not be read from the page: ' + reason)[:300]

        started = clock()
        try:
            driver.get(url)
        except Exception:
            pass  # an address that starts a download does not "load"; what arrived is looked at below
        _step('wait for the address')
        watch(result, started, started + max(wait, person))
        if result['kind'] == 'page':
            _step('read the page')
            try:
                html = str(driver.page_source).replace('\0', '').encode('utf-8', 'replace').decode('utf-8')
            except Exception as exc:
                # The window shows something that cannot be read as a page (it stopped answering, or closed).
                html = ''
                result['title'] = result['title'] or f'The page could not be read from the window ({type(exc).__name__})'
            try:
                result['url'] = validate_url(driver.current_url)
            except Exception:
                pass
            try:
                title = str(driver.title)
            except Exception:
                title = ''
            result.update(title=result['title'] or title.replace('\0', '').encode('utf-8', 'replace').decode('utf-8')[:500],
                          html=html[:maximum], truncated=len(html) > maximum)
            _step('follow the report link')
            if (job.get('follow') is True and not result['check'] and result['status'] in (0, 200)
                    and not result['content_type'].lower().startswith('application/pdf')):
                # The page is read. Where it links to its full report on its own site, that file is asked for
                # next in this same window and session, as a person reading the page would; nothing is clicked.
                try:
                    link = main_pdf_link(driver.execute_script(_PDF_LINKS), result['url'])
                except Exception:
                    link = ''
                if link:
                    linked = {'kind': 'timeout', 'url': link, 'status': 0, 'content_type': '', 'title': '', 'file': '',
                              'bytes': 0, 'check': False}
                    began = clock()
                    try:
                        driver.get(link)
                    except Exception:
                        pass
                    watch(linked, began, began + wait)
                    result['linked'] = {key: linked[key] for key in ('kind', 'url', 'status', 'file', 'bytes')}
        return result
    finally:
        try:
            driver.quit()
        except Exception:
            pass  # the parent Job stops every descendant either way


def run_page_job(job, workspace, *, driver_factory=None):
    """Open one page and return its HTML once ``ready_selector`` matches or the wait ends.

    With ``visible`` the window is shown and the wait is long: a person may be
    passing a verification. Nothing is clicked or typed by this function.
    """
    url = validate_url(job['url'])
    ready = _text(job['ready_selector'], 'ready selector', 300)
    visible, wait, maximum = job['visible'], job['wait_seconds'], job['max_page_chars']
    if type(visible) is not bool or type(wait) is not int or not 1 <= wait <= 600:
        raise ValueError('Invalid page wait')
    if type(maximum) is not int or not 10000 <= maximum <= 4000000:
        raise ValueError('Invalid page size limit')
    driver = (driver_factory or create_driver)(job, workspace)
    try:
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(5)
        driver.implicitly_wait(0)
        driver.execute_cdp_cmd('Browser.setDownloadBehavior', {'behavior': 'deny'})
        if not visible:
            try:
                driver.minimize_window()
            except Exception:
                pass  # the off-screen position already keeps it out of the way
        driver.get(url)
        deadline, found, closed = time.monotonic() + wait, False, False
        while True:
            try:
                found = bool(driver.find_elements('css selector', ready))
            except Exception:
                closed = True  # the person closed the window
                break
            if found or time.monotonic() >= deadline:
                break
            time.sleep(.5 if visible else .2)
        if closed:
            return {'url': url, 'title': '', 'html': '', 'ready': False, 'closed': True, 'truncated': False}
        # Page text is data for the host's parser: drop what JSON or UTF-8 cannot carry.
        html = str(driver.page_source).replace('\0', '').encode('utf-8', 'replace').decode('utf-8')
        try:
            final = validate_url(driver.current_url)
        except ValueError:
            final = url
        title = str(driver.title).replace('\0', '').encode('utf-8', 'replace').decode('utf-8')[:500]
        return {'url': final, 'title': title, 'html': html[:maximum], 'ready': found,
                'closed': False, 'truncated': len(html) > maximum}
    finally:
        try:
            driver.quit()
        except Exception:
            pass  # the parent Job stops every descendant either way


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
    arguments = ['--allowed-ips=127.0.0.1']
    if job.get('mode') == 'fetch':
        # The driver's own log, in this job's private folder: kept by the application only when the try fails.
        arguments.append(f'--log-path={workspace / "driver.log"}')
    service = Service(executable_path=job['driver_executable'],
                      service_args=arguments, log_output=subprocess.DEVNULL,
                      popen_kw={'creation_flags': _DETACHED_PROCESS})
    build = {'page': _page_options, 'fetch': _fetch_options}.get(job.get('mode'), _options)
    return factory(service=service, options=build(options, job, workspace))


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
    run = {'page': run_page_job, 'fetch': run_fetch_job}.get(job.get('mode'), run_job)
    result = run(job, workspace)
    (workspace / 'result.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')


def failure_record(exc, step):
    """What went wrong, for a person: the kind of error, where the job was, the message and the trace."""
    import traceback
    message = str(exc).replace('\0', '')
    first = next((line.strip() for line in message.splitlines() if line.strip() and line.strip() != 'Message:'), '')
    return {'type': type(exc).__name__, 'step': step, 'summary': first.removeprefix('Message:').strip()[:300],
            'message': message[:4000],
            'traceback': ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-8000:]}


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        record = failure_record(exc, _STEP[0])
        try:
            # Beside the job file, in the private folder: the application keeps it when the job failed.
            (Path(sys.argv[1]).parent / 'error.json').write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass
        # One line that says it all comes first: the kind of error, the step, the first words of the message.
        print(f'Selenium {record["type"]} at step "{record["step"]}": {record["summary"]}', file=sys.stderr)
        print(str(exc)[:2000], file=sys.stderr)
        raise SystemExit(1)
