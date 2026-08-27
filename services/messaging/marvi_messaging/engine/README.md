# Marvi Messaging Engine

This directory is Marvi OS's bundled messaging implementation. It is loaded
only through `marvi_messaging.main`, packaged with a private Python runtime and
its locked dependencies, and does not perform source acquisition at runtime.

See `docs/UPSTREAM.md` for provenance and the pinned extraction boundary.
