# sfile — super file: detailed file header decoding
CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra -std=c11
PREFIX  ?= /usr/local

SRC     = src/sfile.c
BIN     = sfile
GEN     = tools/gen_formats.py
TABLE   = src/formats.h src/formats.json

all: $(BIN)

$(BIN): $(SRC) src/formats.h
	$(CC) $(CFLAGS) -o $@ $(SRC)

# Regenerate the format table from the collected reference code.
# (Requires tools/all_formats.cpp; overrides live in tools/overrides.json.)
table: $(GEN) tools/all_formats.cpp
	python3 $(GEN) tools/all_formats.cpp src/formats.json src/formats.h

test: $(BIN)
	./tests/run_tests.sh

install: $(BIN)
	mkdir -p $(PREFIX)/bin
	cp $(BIN) $(PREFIX)/bin/
	chmod 755 $(PREFIX)/bin/$(BIN)

clean:
	rm -f $(BIN) *.o

.PHONY: all table test install clean
