# HackMate Community

Reddit-style board for HackMate: categories, posts, comments, upvotes, GitHub login.
React + Vite frontend, Supabase (Postgres + Auth) backend, no server to run — deploys
as static files into `../docs/community/`, served by the same GitHub Pages site as
the main landing page (`docs/index.html`).

## One-time setup (do this once, in the browser)

**1. Create a Supabase project**
- https://supabase.com → New project (free tier is enough).
- Once created: Project Settings → API → copy the `Project URL` and the `anon public` key.

**2. Run the schema**
- Supabase dashboard → SQL Editor → paste the contents of `schema.sql` in this folder → Run.
- This creates the tables, the seed categories (General/Help/Bugs/Showcase), and the
  row-level-security policies that make posting/voting require login.

**3. Create a GitHub OAuth app** (so "sign in with GitHub" works)
- https://github.com/settings/developers → New OAuth App.
- Homepage URL: `https://riftaway7-code.github.io/hackmate/community/`
- Authorization callback URL: use the one Supabase shows you at
  Authentication → Providers → GitHub (looks like `https://<project>.supabase.co/auth/v1/callback`).
- Copy the generated Client ID and Client Secret into Supabase's GitHub provider settings, then enable it.

**4. Local dev env**
```
cd community
cp .env.example .env
# fill in VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY from step 1
npm install
npm run dev
```

**5. Repo secrets for auto-deploy**
- GitHub repo → Settings → Secrets and variables → Actions → New repository secret:
  - `SUPABASE_URL`
  - `SUPABASE_ANON_KEY`
- `.github/workflows/deploy-community.yml` builds `community/` and commits the output
  into `docs/community/` on every push to `main` that touches `community/**` — same
  pattern as `update-stats.yml` already uses for `docs/stats.json`.

## Why it's built this way

- **GitHub Pages is static-only.** It can't run a backend, so a real backend
  (Supabase: Postgres + Auth + row-level security) sits behind a static frontend.
  The anon key is safe to ship in the built JS — it's meant to be public; RLS
  policies in `schema.sql` are what actually enforce "must be logged in to post/vote."
- **HashRouter, not BrowserRouter.** Pages has no server-side rewrite rule, so a
  real path like `/community/p/<id>` would 404 on refresh. Hash routes
  (`/community/#/p/<id>`) always resolve to `index.html`.
- **Builds into `../docs/community`** so it ships through the exact same Pages
  deploy as the rest of the site (Pages is configured to serve `docs/` on `main`).
