'use strict';
/* sweep — weekly candidate scan.
 * pulls a public podcast chart, scores entries per ../policies, then asks the
 * signed catalog how much of each candidate is already mirrored here.
 * writes state/discovery-<week>.json and pushes a short summary. */
const fs = require('fs');
const path = require('path');
const X = require('../lib/eudic.cjs');
const DB = require('../lib/candidates.cjs');

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

async function lookupJSON(id, mk) {
  return fetchJSON(`https://itunes.apple.com/lookup?id=${id}&country=${mk}&entity=podcast`);
}

// enrich one candidate via itunes lookup (feed url, episode count, freshness)
async function enrich(c) {
  if (!c.itunes_id) return;
  try {
    const j = await lookupJSON(c.itunes_id, c.market || 'us');
    const r = (j && j.results && j.results[0]) || {};
    c.feed_url = r.feedUrl || '';
    c.track_count = r.trackCount || 0;
    c.release_date = r.releaseDate || '';
    c.genre = r.primaryGenreName || '';
    c.view_url = r.trackViewUrl || '';
  } catch (_) { /* stays blank */ }
}

// quick rss transferability check for the top fresh candidates
async function feedCheck(c) {
  if (!c.feed_url) return;
  try {
    const u = new URL(c.feed_url);
    const txt = await new Promise((resolve) => {
      const req = require('https').get(u, { headers: { 'User-Agent': 'Mozilla/5.0' }, timeout: 30000 }, (res) => {
        let buf = '';
        res.on('data', (x) => { buf += x; });
        res.on('end', () => resolve(buf));
      });
      req.on('timeout', () => req.destroy());
      req.on('error', () => resolve(''));
    });
    const items = (txt.match(/<item>/g) || []).length;
    const enc = (txt.match(/<enclosure[^>]+url=/g) || []).length;
    c.feed_check = { ok: items > 0, items, enclosures: enc };
  } catch (_) { /* stays blank */ }
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
        itunes_id: (r.id && r.id.attributes && r.id.attributes['im:id']) || '',
        genres: [(r.category && r.category.attributes && r.category.attributes.label) || '',
                 (r['im:genre'] && r['im:genre'].label) || ''].filter(Boolean),
        score: score(r, i, items.length), market: mk });
    });
    await X.sleep(WAF);
  }
  // dedupe by name + attach itunes ids from the chart entries
  const seen = new Set();
  const list = cands.filter((c) => { const k = norm(c.name); if (seen.has(k)) return false; seen.add(k); return true; });
  list.sort((a, b) => b.score - a.score);
  console.log(`candidates: ${list.length}`);

  // 2. session for the signed catalog probe
  const s = await X.login(user, pass, 'a');
  let shape = null;
  if (s) shape = await X.lockShape(s.u, s.cred);
  if (!shape) console.log('coverage probe unavailable this round (logged as unknown)');

  // 3. coverage probe per candidate (+ itunes enrichment after probing)
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

  // 4. enrich metadata + candidate-db merge (v2 metrics, scoring, history)
  for (const c of results) await enrich(c);
  const freshAll = results.filter((r) => r.present === false).sort((a, b) => b.score - a.score);
  for (const c of freshAll.slice(0, 8)) await feedCheck(c);
  // chart ranks for the db (both markets)
  const rank = {};
  for (const mk of D.markets || ['us']) {
    const j = await fetchJSON(`https://itunes.apple.com/${mk}/rss/toppodcasts/limit=${D.candidates || 40}/json`);
    ((j && j.feed && j.feed.entry) || []).forEach((e, i) => {
      const iid = e.id && e.id.attributes && e.id.attributes['im:id'];
      if (iid) (rank[iid] = rank[iid] || {})[mk] = i + 1;
    });
    await X.sleep(WAF);
  }
  const week = DB.wk();
  try {
    const db = await DB.mergeDB(results, rank, week);
    console.log(`db merged: ${Object.keys(db.items).length} items`);
  } catch (e) { console.log('db merge error:', String(e).slice(0, 120)); }

  // 5. report
  const wk = isojwk(new Date());
  const dir = path.join(__dirname, '..', 'state');
  fs.mkdirSync(dir, { recursive: true });
  const out = { week: wk, pv: P.policy_version, at: new Date().toISOString(), candidates: results };
  fs.writeFileSync(path.join(dir, `discovery-${wk}.json`), JSON.stringify(out));

  // 6. summary push: top takeover candidates; body carries the report link so
  //    it's tappable everywhere (click header is a bonus for the whole bubble)
  const fresh = freshAll.slice(0, 5)
    .map((r) => `${r.score.toFixed(0)} ${r.name.slice(0, 26)}`);
  const link = process.env.NTFY_CLICK || '';
  const msg = (fresh.length
    ? `sweep ${wk} pv${P.policy_version}: ${results.filter((r) => r.present === false).length} fresh | top: ${fresh.join(' · ')}`
    : `sweep ${wk} pv${P.policy_version}: no new candidates`) +
    (link ? `\nreport: ${link}` : '');
  console.log(msg);
  await X.notify(msg, link || '');
}

main().catch((e) => { console.log('fatal:', String(e).slice(0, 200)); process.exit(1); });
