PREFIX ?= /usr/local
LIBDIR := $(PREFIX)/lib/hotspotd
BINDIR := $(PREFIX)/bin

.PHONY: test install uninstall
test:
	python3 tests/run.py

install:
	install -d $(LIBDIR)/hotspotd
	install -m 644 hotspotd/*.py $(LIBDIR)/hotspotd/
	install -d $(BINDIR)
	printf '#!/bin/sh\nexec python3 -c "import sys; sys.path.insert(0,\x27$(LIBDIR)\x27); from hotspotd.cli import main; sys.exit(main())" "$$@"\n' > $(BINDIR)/hotspotd
	chmod 755 $(BINDIR)/hotspotd

uninstall:
	rm -rf $(LIBDIR) $(BINDIR)/hotspotd
