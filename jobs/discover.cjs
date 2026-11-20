'use strict';
/* sweep — weekly candidate scan.
 * pulls a public podcast chart, scores entries per ../policies, then asks the
 * signed catalog how much of each candidate is already mirrored here.
 * writes state/discovery-<week>.json and pushes a short summary. */
const fs = require('fs');
const path = require('path');
const X = require('../lib/eudic.cjs');

const P = X.readPolicies();
const D = (P.discovery || {});
const WAF = P.pacing && P.pacing.waf_ms || 350;

function isojwk(d) {
  const dt = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const day = dt.getUTCDay() || 7;
  dt.setUTCDate(dt.getUTCDate() + 4 - day);
  const start = new Date(Date.UTC(dt.getUTCFullYear(), 0, 1));
  const wk = Math.ceil(((dt - start) / 864e5 + 1) / 7);
  return `${dt.getUTCFullYear()}-W${String(wk).padStart(2, '0')}`;
}

function norm(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

async function fetchJSON(url) {
  return new Promise((resolve) => {
    const get = (u, hops) => {
      const req = require('https').get(u, { headers: { 'User-Agent': 'Mozilla/5.0' }, timeout: 30000 }, (res) => {
        if (res.statusCode >= 301 && res.statusCode <= 302 && res.headers.location && hops < 3) {
          res.resume();
          return get(res.headers.location, hops + 1);
        }
        let buf = '';
        res.on('data', (c) => { buf += c; });
        res.on('end', () => {
          try { resolve(JSON.parse(buf)); } catch (_) { resolve(null); }
        });
      });
      req.on('timeout', () => req.destroy());
      req.on('error', () => resolve(null));
    };
    get(url, 0);
  });
}

function score(entry, rank, total) {
  // rank weight (higher rank = hotter), genre bonus, longevity proxy via chart presence
  const rankScore = Math.round(((total - rank) / total) * 6);
  const genres = (entry.genres || []).map(norm);
  const bonus = (D.genre_bonus || []).filter((g) => genres.includes(norm(g))).length;
  return Math.min(10, rankScore + bonus * 1.5);
}

async function main() {
  const user = process.env.SVC_USER || '';
  const pass = process.env.SVC_PASS || '';
  if (!user || !pass) { console.log('missing credentials'); process.exit(1); return; }

  // 1. chart candidates (itunes classic rss — stable, no key)
  const cands = [];
  for (const mk of D.markets || ['us']) {
    const j = await fetchJSON(`https://itunes.apple.com/${mk}/rss/toppodcasts/limit=${D.candidates || 40}/json`);
    const items = (j && j.feed && j.feed.entry) || [];
    items.forEach((r, i) => {
      const name = r['im:name'] && r['im:name'].label;
      if (!name) return;
      cands.push({ name, artist: (r['im:artist'] && r['im:artist'].label) || '',
        url: (r.id && r.id.label) || '',
        genres: [(r.category && r.category.attributes && r.category.attributes.label) || '',
                 (r['im:genre'] && r['im:genre'].label) || ''].filter(Boolean),
        score: score(r, i, items.length), market: mk });
    });
    await X.sleep(WAF);
  }
  // dedupe by name
  const seen = new Set();
  const list = cands.filter((c) => { const k = norm(c.name); if (seen.has(k)) return false; seen.add(k); return true; });
  list.sort((a, b) => b.score - a.score);
  console.log(`candidates: ${list.length}`);

  // 2. session for the signed catalog probe
  const s = await X.login(user, pass, 'a');
  let shape = null;
  if (s) shape = await X.lockShape(s.u, s.cred);
  if (!shape) console.log('coverage probe unavailable this round (logged as unknown)');

  // 3. coverage probe per candidate
  const results = [];
  for (const c of list) {
    let present = null;
    let hits = 0;
    if (shape) {
      try {
        const r = await X.hunt(s.u, s.cred, shape, c.name.slice(0, 40));
        if (r.code === 200) {
          const key = norm(c.name);
          hits = r.flat.filter((x) => {
            const t = norm(x.title || x.name);
            return t && (t.includes(key) || key.includes(t));
          }).length;
          present = hits > 0;
        }
      } catch (_) { /* stays unknown */ }
    }
    results.push(Object.assign({}, c, { present, hits }));
    console.log(`${c.score.toFixed(1)} ${c.name.slice(0, 34)} present=${present} hits=${hits}`);
    await X.sleep(WAF);
  }

  // 4. report
  const wk = isojwk(new Date());
  const dir = path.join(__dirname, '..', 'state');
  fs.mkdirSync(dir, { recursive: true });
  const out = { week: wk, pv: P.policy_version, at: new Date().toISOString(), candidates: results };
  fs.writeFileSync(path.join(dir, `discovery-${wk}.json`), JSON.stringify(out));

  // 5. short summary: top unknowns = best takeover candidates
  const fresh = results.filter((r) => r.present === false).slice(0, 5)
    .map((r) => `${r.score.toFixed(1)} ${r.name.slice(0, 28)}`);
  const msg = fresh.length ? `sweep ${wk} pv${P.policy_version}: ${fresh.join(' | ')}` : `sweep ${wk} pv${P.policy_version}: no new candidates`;
  console.log(msg);
  await X.notify(msg);
}

main().catch((e) => { console.log('fatal:', String(e).slice(0, 200)); process.exit(1); });
