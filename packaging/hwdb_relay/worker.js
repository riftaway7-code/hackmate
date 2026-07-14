/**
 * Relay for opt-in hardware log submissions from HackMate to
 * github.com/riftaway7-code/hackmate-hwdb.
 *
 * The GitHub token lives only here, as a Cloudflare secret (HWDB_TOKEN),
 * scoped to "Issues: write" on this one repo only — never in the
 * distributed HackMate app. If this endpoint is abused, the blast radius
 * is spam issues on one repo, not arbitrary pushes.
 *
 * Submissions land as GitHub issues, not direct file commits — every log
 * gets a human look before it becomes a permanent file in the repo. This
 * also matches what the repo's README already documents as an accepted
 * submission path ("paste your log in a hackmate issue").
 */

const REPO = "riftaway7-code/hackmate-hwdb";
const MAX_CONTENT_BYTES = 8192; // a real log is a few hundred bytes; generous cap against abuse

const FEATURE_FOLDERS = new Set([
  "full-build-logs",
  "already-formatted-logs",
  "repair-efi-logs",
  "no-usb-logs",
  "dual-boot-logs",
  "efi-health-check-logs",
]);

const GEN_FOLDERS = new Set([
  "intel-gen2", "intel-gen3", "intel-gen4", "intel-gen5", "intel-gen6",
  "intel-gen7", "intel-gen8", "intel-gen9", "intel-gen10", "intel-gen11",
  "intel-gen12", "intel-gen13", "intel-gen14", "intel-gen15",
  "amd-zen", "amd-zen-plus", "amd-zen2", "amd-zen3", "amd-zen3-plus",
  "amd-zen4", "amd-zen5",
]);

function safeFilename(name) {
  const cleaned = String(name || "").toLowerCase().replace(/[^a-z0-9._-]/g, "-");
  const trimmed = cleaned.slice(0, 80) || "device";
  return trimmed.endsWith(".log") ? trimmed : `${trimmed}.log`;
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("method not allowed", { status: 405 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response("bad json", { status: 400 });
    }

    const { feature_folder, gen_folder, filename, content } = body || {};

    if (!FEATURE_FOLDERS.has(feature_folder)) {
      return new Response("unknown feature_folder", { status: 400 });
    }
    if (!GEN_FOLDERS.has(gen_folder)) {
      return new Response("unknown gen_folder", { status: 400 });
    }
    if (typeof content !== "string" || content.length === 0) {
      return new Response("empty content", { status: 400 });
    }
    if (new TextEncoder().encode(content).length > MAX_CONTENT_BYTES) {
      return new Response("content too large", { status: 413 });
    }

    const path = `${feature_folder}/${gen_folder}/${safeFilename(filename)}`;
    const title = `[auto] ${path}`;
    const issueBody = "```\n" + content + "\n```\n\n" +
      `suggested path: \`${path}\`\n\n` +
      "auto-submitted via the opt-in hackmate hardware log feature.";

    const ghResp = await fetch(`https://api.github.com/repos/${REPO}/issues`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.HWDB_TOKEN}`,
        "Accept": "application/vnd.github+json",
        "User-Agent": "hackmate-hwdb-relay",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        title,
        body: issueBody,
        labels: ["auto-submitted"],
      }),
    });

    if (!ghResp.ok) {
      return new Response("upstream error", { status: 502 });
    }

    return new Response("ok", { status: 200 });
  },
};
