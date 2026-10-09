from pathlib import Path
import tomllib

from workbench import __version__


def test_package_and_runtime_versions_match():
    metadata = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text(encoding='utf-8'))
    assert metadata['project']['version'] == __version__
