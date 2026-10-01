"""Read PyPI's known-vulnerability records for the exact locked releases.

No credentials are read or sent. This is a point-in-time known-advisory check,
not a proof that a dependency is free of vulnerabilities.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen


def check(item):
    name, version = item
    request = Request(f'https://pypi.org/pypi/{name}/{version}/json', headers={'User-Agent': 'AgentWorkbench-Audit/0.1'})
    with urlopen(request, timeout=30) as response:
        release = json.load(response)
    active = [v for v in release.get('vulnerabilities', []) if not v.get('withdrawn')]
    return {'name': name, 'version': version, 'advisories': [
        {'id': v.get('id'), 'aliases': v.get('aliases', []), 'fixed_in': v.get('fixed_in', []), 'link': v.get('link')}
        for v in active]}


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    packages = re.findall(r'^([A-Za-z0-9_.-]+)==([^\s]+)', (root / 'requirements.lock').read_text(encoding='utf-8'), re.M)
    with ThreadPoolExecutor(max_workers=6) as pool:
        findings = list(pool.map(check, packages))
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'source': 'PyPI release vulnerability records', 'packages': findings}
    destination = root / 'runtime' / 'verification' / 'dependency-audit.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    affected = [item for item in findings if item['advisories']]
    print(json.dumps({'packages_checked': len(findings), 'affected': affected}))
    raise SystemExit(1 if affected else 0)
