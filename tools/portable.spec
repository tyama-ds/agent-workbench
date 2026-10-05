# Retired entrypoint: do not build or distribute a Python-bundled application.
# Keep this explicit failure so old direct PyInstaller commands cannot build it.
raise SystemExit(
    "Python bundling is disabled. Use an organization-approved, separately installed "
    "Python with Setup.cmd and Launch.cmd."
)
