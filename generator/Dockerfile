# Flagprint sandbox for per-team generate.py scripts ("Script" delivery).
# Runs offline and locked down; this image only adds the tools generators commonly need:
#   C/C++ (gcc, g++, 32-bit via gcc-multilib), Rust (rustc), nasm, musl for static builds,
#   binutils (strip, objcopy), patchelf, upx, zip, and Python libraries Pillow and PyCryptodome.
# Build:  docker build -t flagprint/generator:latest CTFd/plugins/flagprint/generator
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential gcc-multilib g++-multilib binutils patchelf nasm musl-tools \
      rustc upx-ucl zip unzip file xxd \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir pillow pycryptodome

# Writable home for compilers that keep caches there
ENV HOME=/tmp
WORKDIR /work
