"""Exercise the Windows installer without network access or a real pip install."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


SETUP = Path(__file__).resolve().parents[1] / "scripts" / "Setup-Windows.ps1"
POWERSHELL = shutil.which("powershell.exe") if os.name == "nt" else None
pytestmark = pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell 5.1 is required")


@pytest.fixture
def run_setup(tmp_path):
    project = tmp_path / "project with spaces"
    scripts = project / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_bytes(b"non-executable test placeholder")
    (project / "requirements.lock").write_text("# fixture: no dependencies\n", encoding="utf-8")
    (project / "pyproject.toml").write_text('[project]\nname = "installer-fixture"\n', encoding="utf-8")
    certificate = project / "company certificate.pem"
    certificate.write_text("-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n", encoding="ascii")
    log = tmp_path / "argv.log"
    environment_log = tmp_path / "environment.log"
    child_environment = dict(os.environ)
    child_environment.update(
        WORKBENCH_SETUP_TEST_LOG=str(log),
        WORKBENCH_SETUP_TEST_ENV=str(environment_log),
        HTTPS_PROXY="http://inherited-proxy.example:3128",
        PIP_PROXY="http://inherited-pip-proxy.example:8080",
        WORKBENCH_SETUP_TEST_FAIL_PIP="0",
    )
    wrapper = tmp_path / "invoke.ps1"
    wrapper.write_text(
        "param([string]$FixturePath)\n"
        "$ErrorActionPreference = 'Stop'\n"
        "$fixture = Get-Content -LiteralPath $FixturePath -Raw | ConvertFrom-Json\n"
        "$parameters = @{}\n"
        "$fixture.arguments.PSObject.Properties | ForEach-Object { $parameters[$_.Name] = $_.Value }\n"
        "$python = Join-Path $parameters.ProjectRoot '.venv\\Scripts\\python.exe'\n"
        "Set-Item -LiteralPath ('Function:\\' + $python) -Value {\n"
        "  ConvertTo-Json -InputObject @($args) -Compress | Add-Content -LiteralPath $env:WORKBENCH_SETUP_TEST_LOG -Encoding UTF8\n"
        "  @{HTTPS_PROXY=$env:HTTPS_PROXY; PIP_PROXY=$env:PIP_PROXY} | ConvertTo-Json -Compress | Set-Content -LiteralPath $env:WORKBENCH_SETUP_TEST_ENV -Encoding UTF8\n"
        "  $global:LASTEXITCODE = 0\n"
        "  if ($env:WORKBENCH_SETUP_TEST_FAIL_PIP -eq '1' -and $args.Count -ge 2 -and $args[0] -eq '-m' -and $args[1] -eq 'pip') { $global:LASTEXITCODE = 42 }\n"
        "}\n"
        "& $fixture.setup @parameters\n",
        encoding="utf-8",
    )

    def invoke(*arguments, fail_pip=False):
        assert len(arguments) % 2 == 0
        options = {"ProjectRoot": str(project)}
        options.update({str(arguments[i]).lstrip("-"): str(arguments[i + 1])
                        for i in range(0, len(arguments), 2)})
        fixture = tmp_path / "fixture.json"
        fixture.write_text(json.dumps({"setup": str(SETUP), "arguments": options}), encoding="utf-8")
        environment = dict(child_environment, WORKBENCH_SETUP_TEST_FAIL_PIP="1" if fail_pip else "0")
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(wrapper), "-FixturePath", str(fixture)],
            capture_output=True, text=True, timeout=30, env=environment,
        )
        calls = [
            json.loads(line)
            for line in log.read_text(encoding="utf-8-sig").splitlines()
        ] if log.exists() else []
        return result, calls

    invoke.project = project
    invoke.certificate = certificate
    invoke.environment_log = environment_log
    return invoke


def pip_calls(calls):
    return [arguments for arguments in calls if arguments[:2] == ["-m", "pip"]]


def assert_option(arguments, name, expected):
    assert arguments.count(name) == 1, arguments
    assert arguments[arguments.index(name) + 1] == str(expected), arguments


def test_default_setup_preserves_existing_proxy_and_pip_safety(run_setup):
    result, calls = run_setup()
    assert result.returncode == 0, result.stdout + result.stderr
    install = pip_calls(calls)
    assert len(install) == 2
    for arguments in install:
        assert "--proxy" not in arguments and "--cert" not in arguments
        assert_option(arguments, "--timeout", 60)
        assert_option(arguments, "--retries", 3)
        assert "--disable-pip-version-check" in arguments
        assert "--trusted-host" not in arguments
    assert "--require-hashes" in install[0]
    assert_option(install[0], "-r", run_setup.project / "requirements.lock")
    assert "--no-deps" in install[1] and "--no-build-isolation" in install[1]
    assert json.loads(run_setup.environment_log.read_text(encoding="utf-8-sig")) == {
        "HTTPS_PROXY": "http://inherited-proxy.example:3128",
        "PIP_PROXY": "http://inherited-pip-proxy.example:8080",
    }


@pytest.mark.parametrize("proxy", ["http://proxy.example:8080", "https://proxy.example:8443"])
def test_explicit_proxy_certificate_and_limits_reach_both_pip_stages(run_setup, proxy):
    result, calls = run_setup(
        "-ProxyUrl", proxy, "-CertificatePath", run_setup.certificate,
        "-TimeoutSeconds", "135", "-Retries", "7",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    install = pip_calls(calls)
    assert len(install) == 2
    for arguments in install:
        assert_option(arguments, "--proxy", proxy)
        assert_option(arguments, "--cert", run_setup.certificate.resolve())
        assert_option(arguments, "--timeout", 135)
        assert_option(arguments, "--retries", 7)
    assert json.loads(run_setup.environment_log.read_text(encoding="utf-8-sig")) == {
        "HTTPS_PROXY": "http://inherited-proxy.example:3128",
        "PIP_PROXY": "http://inherited-pip-proxy.example:8080",
    }


def test_failed_download_stops_before_editable_install_and_preserves_environment(run_setup):
    environment = run_setup.project / ".venv"
    executable = environment / "Scripts" / "python.exe"
    original = executable.read_bytes()
    result, calls = run_setup(fail_pip=True)
    assert result.returncode != 0
    assert len(pip_calls(calls)) == 1
    assert "ConnectTimeout" in result.stderr
    assert executable.read_bytes() == original


@pytest.mark.parametrize("proxy", [
    "proxy.example:8080", "socks5://proxy.example:1080",
    "http://user:password@proxy.example:8080", "http://proxy.example/path",
    "http://proxy.example?token=secret", "http://proxy.example#secret",
])
def test_invalid_proxy_fails_before_any_python_or_pip_execution(run_setup, proxy):
    result, calls = run_setup("-ProxyUrl", proxy)
    assert result.returncode != 0
    assert calls == []


@pytest.mark.parametrize("certificate", ["missing.pem", "."])
def test_missing_or_directory_certificate_fails_before_execution(run_setup, certificate):
    result, calls = run_setup("-CertificatePath", run_setup.project / certificate)
    assert result.returncode != 0
    assert calls == []


@pytest.mark.parametrize("name,value", [
    ("-TimeoutSeconds", "4"), ("-TimeoutSeconds", "601"),
    ("-Retries", "-1"), ("-Retries", "11"),
])
def test_limits_rejected_before_execution(run_setup, name, value):
    result, calls = run_setup(name, value)
    assert result.returncode != 0
    assert calls == []


def test_ps51_parser_accepts_installer(tmp_path):
    parser = tmp_path / "parse.ps1"
    parser.write_text(
        "param([string]$Source)\n"
        "$tokens = $null; $errors = $null\n"
        "[System.Management.Automation.Language.Parser]::ParseFile($Source, [ref]$tokens, [ref]$errors) | Out-Null\n"
        "if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }\n"
        "@{major=$PSVersionTable.PSVersion.Major; minor=$PSVersionTable.PSVersion.Minor} | ConvertTo-Json -Compress\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(parser), "-Source", str(SETUP)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"major": 5, "minor": 1}
