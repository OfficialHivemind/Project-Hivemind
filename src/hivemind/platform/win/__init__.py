"""The Windows side of the platform seam (RL6 phase 3, docs/pending/windows-port.md).

Imported only through platform/current when sys.platform == "win32"; every
module here also imports on Linux (DLLs and Windows-only libraries are loaded
lazily) so the unit tests run there with them mocked.
"""
