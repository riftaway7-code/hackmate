# Deploying the hwdb relay

This is a small Cloudflare Worker that stands between HackMate and GitHub, so
the app never carries a token with write access. It only ever creates GitHub
*issues* (not direct commits) on `hackmate-hwdb` — logs get a quick human
look before becoming real files in the repo, same as the manual submission
path already documented in that repo's README.

## 1. Create a scoped GitHub token

github.com → Settings → Developer settings → **Fine-grained tokens** → Generate new token.

- Repository access: **Only select repositories** → `hackmate-hwdb`
- Permissions: **Issues: Read and write**. Nothing else — no Contents, no
  Metadata beyond the default, no access to any other repo including
  `hackmate` itself.
- Expiration: set a real expiry and calendar-remind yourself to rotate it,
  rather than "no expiration."

Copy the token once — GitHub won't show it again.

## 2. Deploy the worker

Requires a (free tier is fine) Cloudflare account.

```
cd packaging/hwdb_relay
npm install -g wrangler   # if you don't have it
wrangler login
wrangler secret put HWDB_TOKEN     # paste the token from step 1 when prompted
wrangler deploy
```

`wrangler deploy` prints the worker's URL, something like
`https://hackmate-hwdb-relay.<your-subdomain>.workers.dev`.

## 3. Point the app at it

Put that URL in `src/hwdb_submit.py`:

```python
RELAY_URL = "https://hackmate-hwdb-relay.<your-subdomain>.workers.dev"
```

Until `RELAY_URL` is set, `submit_log()` is a silent no-op — nothing is
sent, opted-in or not.

## Notes

- The worker validates `feature_folder` and `gen_folder` against a fixed
  allowlist and caps content size, so it can't be used to write arbitrary
  paths or dump huge payloads.
- It has no rate limiting built in yet. If abuse becomes a problem, add a
  Cloudflare rate limiting rule on the route, or a Turnstile check — not
  needed for launch, worth revisiting if submission volume looks off.
- Rotate `HWDB_TOKEN` periodically; it's the only credential this whole
  feature depends on.
