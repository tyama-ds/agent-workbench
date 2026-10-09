"""Historical ONEDIR entrypoint; Python-bundled builds are retired and disabled."""
import sys

for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='replace')

# Dispatch before importing the server, acquiring its mutex, or starting threads.
# This is a fixed native-utility bridge, never a model tool or arbitrary command.
if len(sys.argv) > 1 and sys.argv[1] == '--internal-windows-utility':
    from workbench.windows_runtime import helper_main
    raise SystemExit(helper_main(sys.argv[2:]))

from scripts.start_workbench import main

if __name__ == '__main__':
    raise SystemExit(main())
