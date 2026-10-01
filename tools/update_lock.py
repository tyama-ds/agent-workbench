"""Record this clean development venv's distributions and PyPI release hashes.

Run explicitly after reviewing dependency updates. This is never run at app startup.
"""
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import distributions
import json
from pathlib import Path
from urllib.request import Request, urlopen


def entry(distribution):
    name, version = distribution.metadata['Name'], distribution.version
    request = Request(f'https://pypi.org/pypi/{name}/{version}/json', headers={'User-Agent': 'AgentWorkbench-Lock/0.1'})
    with urlopen(request, timeout=30) as response:
        release = json.load(response)
    hashes = sorted({item['digests']['sha256'] for item in release['urls'] if not item.get('yanked')})
    if not hashes:
        raise RuntimeError(f'No non-yanked hashes for {name}=={version}')
    return f'{name}=={version} \\\n' + ' \\\n'.join(f'    --hash=sha256:{digest}' for digest in hashes)


if __name__ == '__main__':
    installed = sorted((item for item in distributions() if item.metadata['Name'].lower() not in {'pip', 'agent-workbench'}),
                       key=lambda item: item.metadata['Name'].lower())
    with ThreadPoolExecutor(max_workers=6) as pool:
        lines = list(pool.map(entry, installed))
    destination = Path(__file__).resolve().parents[1] / 'requirements.lock'
    destination.write_text('# Runtime and validation dependencies, pinned with PyPI SHA-256 release hashes.\n'
                           '# Install: python -m pip install --require-hashes -r requirements.lock\n\n'
                           + '\n\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Locked {len(installed)} distributions with release hashes.')
