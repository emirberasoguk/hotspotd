# Contributing to hotspotd

The most valuable contribution is not code. It is **a radio hotspotd gets
wrong.**

## Report a radio

hotspotd's whole claim is that it can tell you why an access point will not
start. When it fails to, that is the bug. To report one:

```sh
sudo hotspotd doctor --json > doctor.json
sudo iw list > iw-list.txt
sudo iw reg get > iw-reg.txt
```

Open an issue with those three files, your distribution and kernel version,
and what actually happened. `iw list` output becomes a fixture in
`tests/fixtures/`, and the diagnosis for your chipset becomes a test case -
which is how hotspotd avoids regressions on hardware the author does not own.

## Working on the code

There is nothing to install and nothing to build:

```sh
make test      # the suite
make check     # the suite, plus a byte-compile of every module
```

The suite is plain functions with plain asserts and a small runner, so it
works on a bare system. `pytest tests/` works too if you prefer it.

Some ground rules the code follows:

- **No runtime dependencies.** hotspotd has to work on a machine whose
  network is down, which is exactly when `pip` cannot fetch anything. Only
  the Python standard library, and only Python 3.9 or newer.
- **Diagnosis is a pure function.** `doctor.diagnose()` takes collected facts
  and returns findings without touching the system. That separation is what
  lets the suite test radios nobody here owns.
- **Every system change is recorded before it is made.** If `up` changes
  something, it goes in `hotspotd/state.py` so `down` can undo precisely that.
  Nothing is undone on the basis of a default value.
- **Never leave the machine different.** Enabling masquerading that was
  already on and then switching it off at teardown would break someone else's
  connection sharing. Query first, record what you changed, restore only that.
- **No tracebacks reach the user.** A failure the user can act on is one
  sentence saying what went wrong, and where possible what to do about it.

## Pull requests

Explain the failure your change fixes and how you reproduced it. If it
touches parsing or diagnosis, add a test with the real output that motivated
it. Run `make check` before opening the PR.

By contributing you agree that your work is released under the MIT licence in
[LICENSE](LICENSE).
