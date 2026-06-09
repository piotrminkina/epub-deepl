# Base image: generic Debian (NOT mcr.microsoft.com/devcontainers/base — that
# pre-bakes a vscode user at UID 1000, which we explicitly avoid per project
# policy). User creation is delegated to the common-utils devcontainer feature
# (see devcontainer.json), which provisions the `devcontainer` user with
# UID/GID matched to the host at container creation time.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=0

# ---------------------------------------------------------------------------
# Layer 1 — OS toolchain, Python runtime, build deps for lxml.
# Debian 12 (bookworm) ships Python 3.11 in apt — matches the PRD TC-1 floor.
# ---------------------------------------------------------------------------
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 \
      python3-venv \
      python3-dev \
      python3-pip \
      libxml2-dev \
      libxslt1-dev \
      zlib1g-dev \
      build-essential \
      pkg-config \
      default-jre-headless \
      unzip \
      zip \
      diffutils \
      git \
      curl \
      ca-certificates \
      sudo \
      less \
      vim-tiny \
      locales \
      tzdata \
 && sed -i 's/^# *\(en_US.UTF-8\)/\1/' /etc/locale.gen \
 && locale-gen \
 && rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

# Convenience symlinks so `python` and `pip` work without the 3 suffix.
RUN ln -sf /usr/bin/python3 /usr/local/bin/python \
 && ln -sf /usr/bin/pip3    /usr/local/bin/pip

# ---------------------------------------------------------------------------
# Layer 2 — epubcheck for manual EPUB validation (SM-4 from the PRD).
# Installed system-wide so any user can invoke it via `epubcheck <file.epub>`.
# Version + SHA256 pinned together — bump both whenever upgrading.
# Verification protects against supply-chain compromise: GitHub releases are
# HTTPS-authenticated, but the asset bytes are not signed by W3C, so we hash-
# pin to detect any future swap. The hash was computed from the official
# release at https://github.com/w3c/epubcheck/releases/tag/v5.1.0.
# ---------------------------------------------------------------------------
ARG EPUBCHECK_VERSION=5.1.0
ARG EPUBCHECK_SHA256=74a59af8602bf59b1d04266a450d9cdcb5986e36d825adc403cde0d95e88c9e8
RUN curl -fsSL \
      "https://github.com/w3c/epubcheck/releases/download/v${EPUBCHECK_VERSION}/epubcheck-${EPUBCHECK_VERSION}.zip" \
      -o /tmp/epubcheck.zip \
 && printf '%s  /tmp/epubcheck.zip\n' "${EPUBCHECK_SHA256}" | sha256sum -c - \
 && unzip -q /tmp/epubcheck.zip -d /opt \
 && ln -sfn "/opt/epubcheck-${EPUBCHECK_VERSION}" /opt/epubcheck \
 && rm /tmp/epubcheck.zip \
 && printf '#!/bin/sh\nexec java -jar /opt/epubcheck/epubcheck.jar "$@"\n' \
      > /usr/local/bin/epubcheck \
 && chmod +x /usr/local/bin/epubcheck

# Default shell for any future RUN instructions appended by features.
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]
