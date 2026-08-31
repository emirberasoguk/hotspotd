#!/usr/bin/env python3
"""Zero-dependency test runner.

hotspotd deliberately has no runtime or test dependencies, so the suite is
plain functions with plain asserts.  `pytest tests/` works too if you have
it; this runner exists so `make test` works on a bare system.
"""
import importlib.util
import pathlib
import sys
import traceback

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent))


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    passed = failed = 0
    for path in sorted(HERE.glob("test_*.py")):
        module = load(path)
        for name in sorted(n for n in dir(module) if n.startswith("test_")):
            fn = getattr(module, name)
            if not callable(fn):
                continue
            try:
                fn()
            except Exception:
                failed += 1
                print(f"FAIL {path.name}::{name}")
                traceback.print_exc()
            else:
                passed += 1
                print(f"ok   {path.name}::{name}")
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
