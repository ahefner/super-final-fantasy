#!/bin/sh
#  Build the SNES port.  Run from this directory.
set -e
cd "$(dirname "$0")"
mkdir -p out gen

python3 tools/genpal.py
python3 tools/convert.py

CA65="ca65 --cpu 65816 --feature force_range $CA65EXTRA"

# The generated banks live in gen/, which also carries the 'bin' symlink the
# original .incbin paths need; ca65 resolves those against the current
# directory, so assemble from in there.
( cd gen && for b in 01 09 0B 0C 0D 0E 0F; do
    $CA65 -I ../src bank_$b.asm -o ../out/bank_$b.o
  done )

( cd src && $CA65 hal.asm    -o ../out/hal.o
           $CA65 header.asm -o ../out/header.o )

ld65 -C snes.cfg -o /dev/null \
    out/hal.o out/header.o \
    out/bank_01.o out/bank_09.o out/bank_0B.o out/bank_0C.o \
    out/bank_0D.o out/bank_0E.o out/bank_0F.o

python3 tools/mkrom.py
