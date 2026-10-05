# Explicit Windows ONEDIR console build. Invoked only by build_portable.py.
import json
import os
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

if sys.platform != "win32":
    raise RuntimeError("The portable spec must be built on Windows")
context = json.loads(Path(os.environ["WORKBENCH_BUILD_CONTEXT"]).read_text(encoding="utf-8"))
root = Path(context["root"])
datas = [(str(root / "static"), "static"), (str(root / "docs" / "interface.json"), "docs")]
for package in ("docx", "pptx"):
    # Includes the default.docx and default.pptx templates used by exports.
    datas += collect_data_files(package)
for distribution in context["runtime_distributions"] + ["agent-workbench"]:
    datas += copy_metadata(distribution)

a = Analysis(
    [str(root / "scripts" / "portable_workbench.py")],
    pathex=[str(root)], binaries=[], datas=datas,
    hiddenimports=["aiohttp", "docx", "openpyxl", "pptx"],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["pytest", "_pytest", "pip", "setuptools", "tkinter"],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="AgentWorkbench", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True, disable_windowed_traceback=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    version=context["version_resource"], contents_directory="_internal",
)
collect = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AgentWorkbench")
