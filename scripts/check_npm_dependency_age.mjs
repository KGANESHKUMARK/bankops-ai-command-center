#!/usr/bin/env node
/**
 * Supply-chain hygiene check for npm lockfiles: flag packages published < N days ago.
 *
 * Usage:
 *   node scripts/check_npm_dependency_age.mjs frontend/package-lock.json tests/e2e/package-lock.json [--days 7]
 *   node scripts/check_npm_dependency_age.mjs --suggest react vite@8 typescript@5.9 [--days 7]
 *
 * Check mode reads every registry package in the lockfile(s) and looks up its publish time in the public
 * npm registry. Exit code 1 if any package is younger than the threshold or its publish time is unknown.
 * Suggest mode prints the newest stable version (optionally within a major/minor prefix) old enough to use.
 */
import { readFileSync } from "node:fs";

const argv = process.argv.slice(2);
let days = 7;
let suggest = false;
const inputs = [];
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === "--days") days = Number(argv[++i]);
  else if (argv[i] === "--suggest") suggest = true;
  else inputs.push(argv[i]);
}
if (!inputs.length || !Number.isFinite(days)) {
  console.error("usage: check_npm_dependency_age.mjs <package-lock.json...> | --suggest <pkg[@prefix]...> [--days N]");
  process.exit(2);
}

const REGISTRY = (process.env.NPM_REGISTRY || "https://registry.npmjs.org").replace(/\/$/, "");
const now = Date.now();
const cutoff = now - days * 86_400_000;
const cache = new Map();

function packument(name) {
  if (!cache.has(name)) {
    const path = name.startsWith("@") ? "@" + encodeURIComponent(name.slice(1)) : encodeURIComponent(name);
    cache.set(name, (async () => {
      for (let attempt = 0; ; attempt++) {
        try {
          const res = await fetch(`${REGISTRY}/${path}`, { headers: { accept: "application/json" } });
          if (res.status === 404) return null;
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return await res.json();
        } catch (err) {
          if (attempt >= 2) throw err;
          await new Promise((r) => setTimeout(r, 750 * (attempt + 1)));
        }
      }
    })());
  }
  return cache.get(name);
}

async function pool(items, size, fn) {
  const out = new Array(items.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(size, items.length) }, async () => {
    while (next < items.length) {
      const idx = next++;
      out[idx] = await fn(items[idx]);
    }
  }));
  return out;
}

const parse = (v) => {
  const m = /^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$/.exec(v);
  return m ? { major: +m[1], minor: +m[2], patch: +m[3], pre: m[4] ?? null } : null;
};
const cmp = (a, b) => a.major - b.major || a.minor - b.minor || a.patch - b.patch;
const day = (ms) => new Date(ms).toISOString().slice(0, 10);

if (suggest) {
  await pool(inputs, 8, async (spec) => {
    const at = spec.lastIndexOf("@");
    const name = at > 0 ? spec.slice(0, at) : spec;
    const prefix = at > 0 ? spec.slice(at + 1) : "";
    const doc = await packument(name);
    if (!doc) return console.log(`${spec.padEnd(34)} NOT FOUND`);
    const candidates = Object.keys(doc.versions || {})
      .map((v) => ({ v, p: parse(v), t: Date.parse(doc.time?.[v] ?? "") }))
      .filter((c) => c.p && !c.p.pre && Number.isFinite(c.t) && c.t <= cutoff && !doc.versions[c.v].deprecated)
      .filter((c) => !prefix || c.v === prefix || c.v.startsWith(prefix + "."))
      .sort((a, b) => cmp(b.p, a.p));
    const best = candidates[0];
    const latest = doc["dist-tags"]?.latest;
    console.log(`${spec.padEnd(34)} ${best ? `${best.v.padEnd(12)} (published ${day(best.t)})` : "NONE OLD ENOUGH".padEnd(37)}`
      + `  latest=${latest} (${doc.time?.[latest] ? day(Date.parse(doc.time[latest])) : "?"})`);
  });
  process.exit(0);
}

const wanted = new Map();
for (const file of inputs) {
  const lock = JSON.parse(readFileSync(file, "utf8"));
  for (const [key, entry] of Object.entries(lock.packages || {})) {
    if (!key || entry.link || !entry.version || !entry.resolved?.startsWith("http")) continue;
    const name = entry.name || key.slice(key.lastIndexOf("node_modules/") + "node_modules/".length);
    wanted.set(`${name}@${entry.version}`, { name, version: entry.version });
  }
}
const items = [...wanted.values()];
const results = await pool(items, 16, async ({ name, version }) => {
  try {
    const doc = await packument(name);
    const t = Date.parse(doc?.time?.[version] ?? "");
    return { name, version, t: Number.isFinite(t) ? t : null };
  } catch {
    return { name, version, t: null };
  }
});
const unknown = results.filter((r) => r.t === null);
const tooNew = results.filter((r) => r.t !== null && r.t > cutoff);
for (const r of unknown) console.log(`UNKNOWN  ${r.name}@${r.version}`);
for (const r of tooNew) {
  console.log(`TOO NEW  ${r.name}@${r.version} (published ${day(r.t)}, ${Math.floor((now - r.t) / 86_400_000)}d ago)`);
}
console.log(`Checked ${results.length} npm packages; ${tooNew.length} younger than ${days} days, ${unknown.length} unknown.`);
process.exit(tooNew.length || unknown.length ? 1 : 0);
