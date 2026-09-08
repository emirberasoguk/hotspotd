# hotspotd - no build step, no dependencies; this only copies files into place.

PREFIX      ?= /usr/local
DESTDIR     ?=
LIBDIR      := $(PREFIX)/lib/hotspotd
BINDIR      := $(PREFIX)/bin
MANDIR      := $(PREFIX)/share/man/man8
SYSTEMDDIR  ?= /usr/lib/systemd/system
BASHCOMPDIR ?= /usr/share/bash-completion/completions
ZSHCOMPDIR  ?= /usr/share/zsh/site-functions

PYTHON ?= python3

.PHONY: all test check install uninstall clean

all:
	@echo "nothing to build - run 'make test' or 'sudo make install'"

test:
	$(PYTHON) tests/run.py

# what CI runs: the suite, plus a byte-compile of every module so a syntax
# error can never reach a release.
check: test
	$(PYTHON) -m compileall -q hotspotd tests
	$(PYTHON) -c "import sys; sys.path.insert(0, '.'); from hotspotd import cli; cli.build_parser()"

install:
	install -d $(DESTDIR)$(LIBDIR)/hotspotd
	install -m 644 hotspotd/*.py $(DESTDIR)$(LIBDIR)/hotspotd/
	install -d $(DESTDIR)$(BINDIR)
	{ \
	  echo '#!/bin/sh'; \
	  echo 'exec env PYTHONPATH=$(LIBDIR) $(PYTHON) -m hotspotd "$$@"'; \
	} > $(DESTDIR)$(BINDIR)/hotspotd
	chmod 755 $(DESTDIR)$(BINDIR)/hotspotd
	install -d $(DESTDIR)$(MANDIR)
	install -m 644 man/hotspotd.8 $(DESTDIR)$(MANDIR)/
	install -d $(DESTDIR)$(SYSTEMDDIR)
	sed 's|@BINDIR@|$(BINDIR)|g' contrib/hotspotd.service \
		> $(DESTDIR)$(SYSTEMDDIR)/hotspotd.service
	chmod 644 $(DESTDIR)$(SYSTEMDDIR)/hotspotd.service
	install -d $(DESTDIR)$(BASHCOMPDIR)
	install -m 644 contrib/hotspotd.bash $(DESTDIR)$(BASHCOMPDIR)/hotspotd
	install -d $(DESTDIR)$(ZSHCOMPDIR)
	install -m 644 contrib/_hotspotd $(DESTDIR)$(ZSHCOMPDIR)/_hotspotd
	@echo
	@echo "installed. next: sudo hotspotd doctor"

uninstall:
	rm -rf $(DESTDIR)$(LIBDIR)
	rm -f $(DESTDIR)$(BINDIR)/hotspotd
	rm -f $(DESTDIR)$(MANDIR)/hotspotd.8
	rm -f $(DESTDIR)$(SYSTEMDDIR)/hotspotd.service
	rm -f $(DESTDIR)$(BASHCOMPDIR)/hotspotd
	rm -f $(DESTDIR)$(ZSHCOMPDIR)/_hotspotd
	@echo "removed. /etc/hotspotd and /run/hotspotd are left alone"

clean:
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
