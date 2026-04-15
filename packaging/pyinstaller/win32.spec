# packaging/pyinstaller/win32.spec
# Generic PyInstaller spec for Windows
# Entry point: python -m <module>

import os

module_name = os.environ.get("PYINSTALLER_MODULE", "project")
binary_name = os.environ.get("PYINSTALLER_NAME", module_name)
project_root = os.path.abspath(os.environ.get("PYINSTALLER_PROJECT_ROOT", os.getcwd()))
module_entrypoint = os.path.join(project_root, "src", *module_name.split("."), "__main__.py")
exe_icon_path = os.path.join(project_root, "icons", "icon.ico")
runtime_icon_path = os.path.join(project_root, "icons", "icon_16.png")

if not os.path.exists(module_entrypoint):
    raise SystemExit(f"Module entrypoint not found: {module_entrypoint}")
if not os.path.exists(exe_icon_path):
    raise SystemExit(f"EXE icon not found: {exe_icon_path}")
if not os.path.exists(runtime_icon_path):
    raise SystemExit(f"Runtime icon not found: {runtime_icon_path}")

a = Analysis(
    [module_entrypoint],
    pathex=[project_root, os.path.join(project_root, "src")],
    hiddenimports=[module_name],
    binaries=[],
    datas=[(runtime_icon_path, "icons")],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name=binary_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=exe_icon_path,
)
