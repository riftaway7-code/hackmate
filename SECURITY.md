# Security Policy

## Overview

The HackMate project takes the security and integrity of its codebase seriously.
This document outlines our security practices, how to report vulnerabilities, and
what users can expect from the project in terms of responsible disclosure.

---

## Supported Versions

Security fixes are applied to the latest version on the `main` branch only.
We do not backport fixes to older releases. Always ensure you are running the
latest version before reporting an issue.

| Version | Supported |
|---------|-----------|
| Latest (main) | ✅ Yes |
| Any prior release | ❌ No |

---

## Reporting a Vulnerability

If you discover a security vulnerability in HackMate, **please do not open a
public GitHub issue** with sensitive details. Doing so could expose other users
to risk before a fix is available.

Instead, please report it through one of the following channels:

- **GitHub Issues (preferred):** Open an issue labeled `security` and describe
  the general nature of the problem without including exploit details. We will
  follow up with you privately.

- **Direct contact:** If the issue is critical and requires immediate attention,
  mention it in a GitHub issue and we will reach out.

We aim to acknowledge all security reports within **72 hours** and to provide
a fix or mitigation within **14 days** for confirmed vulnerabilities, depending
on severity.

---

## What Counts as a Security Issue

The following are considered security-relevant:

- Code execution vulnerabilities introduced by HackMate itself
- Path traversal or arbitrary file write bugs in the EFI build process
- Dependency confusion or supply chain issues in the updater
- Any issue that could allow a malicious actor to execute code on a user's
  machine by exploiting HackMate's functionality

The following are **not** considered security issues for the purposes of this
policy:

- Bugs that only affect macOS installation success rates
- Hardware detection inaccuracies
- Third-party tools bundled or downloaded by HackMate (OpenCore, SSDTTime, etc.)
  — report those to their respective projects

---

## Responsible Use and Legal Disclaimer

HackMate is an open-source educational tool. It automates the generation of
OpenCore EFI configurations for use on non-Apple hardware. Users are solely
responsible for ensuring their use of this software complies with applicable
laws and any third-party terms of service in their jurisdiction.

The authors of HackMate:

- Do **not** distribute macOS or any Apple intellectual property
- Do **not** endorse, encourage, or facilitate violation of Apple's Software
  License Agreement or any other legal agreement
- Are **not** responsible for any legal consequences arising from the use,
  misuse, distribution, or modification of this software by any third party

Any forks or redistributions of this project are the sole legal and ethical
responsibility of the person or entity that created them. See `LICENSE` for
full terms.

---

## Dependency Security

HackMate downloads files from the following trusted sources at runtime:

| Source | Purpose |
|--------|---------|
| `github.com/acidanthera/OpenCorePkg` | OpenCore bootloader |
| `github.com/corpnewt/SSDTTime` | ACPI table generation |
| `github.com/acidanthera/OpenCorePkg` (macrecovery) | macOS recovery downloader |
| `raw.githubusercontent.com/riftaway7-code/hackmate` | HackMate auto-updater |
| `Apple CDN` | macOS recovery image |

All downloads are performed over HTTPS. We do not verify checksums for
third-party tools at this time — this is a known limitation and a planned
improvement.

**Opt-in hardware log submission** (`src/hwdb_submit.py`) uploads to a single
Cloudflare Worker (`hackmate-hwdb-relay.riftaway7.workers.dev`) under one
personal account — there's no fallback if that account or Worker goes down.
This has no user-facing impact: submission is entirely best-effort, requires
explicit consent, and every failure (relay down, network error, anything) is
caught and silently ignored — it never blocks or errors a build. The relay
URL can be overridden via the `HACKMATE_HWDB_RELAY_URL` environment
variable (set it empty to disable submission outright) for forks or
self-hosted deployments.

---

## Auto-Updater Security

HackMate includes an auto-updater that downloads Python source files from
the official GitHub repository on launch. This updater:

- Only downloads from `raw.githubusercontent.com/riftaway7-code/hackmate`
- Requires explicit user confirmation before applying any update
- Replaces `.py` files in-place and restarts the process

If you are concerned about the auto-updater, you can disable it by deleting
or not running `updater.py`. HackMate will still function without it.

---

## Contact

For non-security bugs and feature requests, please open a regular GitHub issue.
For security concerns, open an issue labeled `security` and we will follow up.
