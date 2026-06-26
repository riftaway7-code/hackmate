# Contributing to HackMate

Thanks for wanting to help! HackMate is a community-driven project and contributions are welcome.
Read this before opening a PR so your work doesn't get stuck in review.

---

## Before You Start

- Check [open issues](https://github.com/riftaway7-code/hackmate/issues) to see if someone is already working on what you want to fix
- For big changes (new features, restructuring), open an issue first to discuss the approach
- For bug fixes, you can go straight to a PR

---

## How to Contribute

1. **Fork** the repo and clone your fork
2. Make your changes in `src/`
3. Test locally (see below)
4. Open a PR against `main`

---

## Testing Your Changes

HackMate doesn't have an automated test suite yet, so manual testing is required.

**Minimum testing for any PR:**

- Run HackMate on your machine and complete a full scan (`sudo .venv/bin/python3 src/hackmate.py`)
- Confirm the hardware detection screen shows correct results for your system
- If your change touches USB formatting, kext selection, config generation, or SSDT generation — run a Full Build and check the output

**For hardware detection changes:**

- Test on the OS your change targets (Linux / Windows / macOS)
- Include the hardware detection output in your PR description so reviewers can verify

**For config.plist / kext changes:**

- If possible, boot the generated USB and confirm macOS loads (or at least gets further than before)
- If you can't test a boot, say so in the PR — we'll flag it for community testing

---

## PR Guidelines

**Title:** Short and descriptive. Use a prefix:
- `fix:` for bug fixes
- `feat:` for new features
- `docs:` for documentation changes

**Description:** Include:
- What the problem was
- What you changed and why
- What you tested and on what hardware/OS
- Any known limitations or things that need follow-up

**Keep PRs focused.** One fix or feature per PR. Don't combine unrelated changes — it makes review much harder.

**Don't reformat unrelated code.** If your change is a bug fix in `hardware.py`, don't also clean up whitespace in `config_gen.py`. Noisy diffs make it hard to see what actually changed.

---

## Code Style

- Python 3.10+
- No external dependencies beyond `textual` (which is in `setup.py`)
- Keep platform checks using `IS_WINDOWS`, `IS_MACOS`, `IS_LINUX` from `compat.py`
- Hardware detection goes in `hardware.py`, EFI generation in `config_gen.py`, kext selection in `kexts.py`
- If you add a new kext, add it to `kexts.py` with the correct `exe_name` if the binary name differs from the kext name

---

## Reporting Bugs

Open an issue and fill out the template. The most useful things to include:

- Your OS and machine model
- The hardware detection output (screenshot or paste)
- What you expected vs what happened
- Any error messages or logs

---

## Questions

Open an issue labeled `question` and we'll help you out.
