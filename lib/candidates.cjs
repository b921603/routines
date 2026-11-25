'use strict';
/* candidate database maintenance: v2 metrics + scoring + weekly merge.
 * db = state/candidates.json keyed by itunes_id; grows across sweeps. */
const fs = require('fs');
const path = require('path');
const https = require('https');

const MAJOR = ['iHeart', 'Wondery', 'Spotify Studios', 'The New York Times', 'NPR', 'BBC',
  'Global', 'Goalhanger', 'Dear Media', 'audiochuck', 'The Daily Wire', 'MeidasTouch',
  'Comedy Central', 'The Athletic', 'Barstool', 'WWE', 'Campside', 'Sony', 'Warner',
  'NBC', 'Fox', 'Vox', 'Crooked'];
const LEARN_HI = ['interview', 'history', 'science', 'documentary', 'story', 'deep dive',
  'explained', 'analysis', 'economics', 'war', 'empire', 'ww2', 'philosophy',
  'culture', 'business', 'how ', 'why ', 'journalism'];
const LEARN_LO = ['sh**', 'banter', 'gossip', 'react', 'meme'];
// 雋永性（v2.1，11-25 用戶策展核心）：5 年後仍值得聽的內容基因
const PEREN_HI = ['consciousness', 'meaning', 'philosophy', 'mind', 'cosmos', 'universe',
  'brain', 'ancient', 'history of', 'human nature', 'wisdom', 'ethics', 'mortality',
  'death', 'love', 'memory', 'sleep', 'science of', 'why we', 'how to live',
  'mystery', 'truth', 'art of', 'soul', 'time'];
const PEREN_LO = ['this week', 'election', 'latest', 'today', 'breaking', 'episode \d+',
  'match', 'season \d+', 'update', 'reaction', 'recap', 'weekly news', 'daily brief',
  'trump', 'ballot', 'poll'];

// perennial score 0-15：類型基因＋標題/描述語義＋長訪談加成
function perenScore(c) {
  const g = String(c.genre || '').toLowerCase();
  const hiG = { 'science': 13, 'philosophy': 13, 'history': 12, 'documentary': 12,
    'arts': 10, 'society': 9, 'culture': 9, 'education': 9, 'religion': 9,
    'psychology': 11, 'health': 7, 'business': 6, 'technology': 6, 'design': 8,
    'self': 7, 'fiction': 5, 'comedy': 3, 'news': 3, 'politics': 3, 'sports': 2,
    'crime': 4, 'music': 6, 'tv': 3, 'film': 4 };
  let base = 5;
  for (const k of Object.keys(hiG)) if (g.includes(k)) { base = hiG[k]; break; }
  const txt = (String(c.name || '') + ' ' + String(c.description || '') + ' ' +
    ((c.rss && c.rss.sample_titles) || []).join(' ')).toLowerCase();
  const hi = PEREN_HI.filter((k) => txt.includes(k)).length;
  const lo = PEREN_LO.filter((k) => txt.includes(k)).length;
  const med = (c.rss && c.rss.median_min) || 0;
  const longForm = med >= 45 ? 1 : 0;         // 長訪談＝深度對話基因
  return Math.max(0, Math.min(15, base + hi - lo * 2 + longForm));
}

function get(url, timeout = 30000) {
  return new Promise((resolve) => {
    const req = https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' }, timeout }, (res) => {
      let buf = '';
      res.on('data', (c) => { buf += c; });
      res.on('end', () => resolve(buf));
    });
    req.on('timeout', () => req.destroy());
    req.on('error', () => resolve(''));
  });
}

function pubClass(artist) {
  const a = String(artist || '');
  if (MAJOR.some((k) => a.toLowerCase().includes(k.toLowerCase()))) return 'major';
  if (/Network|Studios|Digital|Entertainment|Media Group/.test(a)) return 'mid';
  return 'independent';
}

function learnScore(c) {
  const g = String(c.genre || '').toLowerCase();
  const hiG = ['education', 'science', 'history', 'business', 'technology', 'documentary', 'society', 'culture']
    .some((k) => g.includes(k));      // v2.1: news/politics 移出學習基因（時事≠雋永）
  const titles = ((c.rss && c.rss.sample_titles) || []).join(' ').toLowerCase();
  const hiT = LEARN_HI.filter((k) => titles.includes(k)).length;
  const loT = LEARN_LO.filter((k) => titles.includes(k)).length;
  const name = String(c.name || '').toLowerCase();
  let base = hiG ? 9 : 5;
  if (['history', 'war', 'empire', 'business', 'science', 'philosophy'].some((k) => name.includes(k))) base += 3;
  return Math.max(0, Math.min(15, base + hiT - loT * 2));
}

function scoreV2(c, rank) {
  const r = c.rss || {};
  const rk = rank[c.itunes_id] || {};
  const best = Math.min(...Object.values(rk), 41);
  const heat = Math.round((20 - (best - 1) * 17 / 39) * 10) / 10;
  const ew = r.eps_week || 0;
  let stale = false;
  if (r.latest) stale = (Date.now() - new Date(r.latest + 'T00:00:00Z').getTime()) > 60 * 864e5;
  const cadence = stale ? 0 : (ew >= 4 ? 15 : ew >= 2 ? 12 : ew >= 1 ? 10 : ew >= 0.5 ? 7 : ew > 0 ? 4 : 2);
  const n = r.items || 0;
  const depth = n >= 500 ? 10 : n >= 200 ? 8 : n >= 100 ? 6 : n >= 30 ? 4 : n > 0 ? 2 : 0;
  const med = r.median_min || 0;
  const fit = (med >= 10 && med <= 40) ? 15 : med > 40 && med <= 70 ? 12 : med > 70 && med <= 90 ? 8 : med > 0 && med < 10 ? 6 : med > 90 ? 5 : 4;
  const learning = learnScore(c);
  const perennial = perenScore(c);
  const encRate = n ? (r.enclosures || 0) / n : 0;
  const transfer = (r.transcript_tag ? 6 : 0) + (n && encRate > 0.9 ? 4 : n && encRate > 0.5 ? 2 : 0);
  const pc = pubClass(c.artist);
  const legal = pc === 'independent' ? 10 : pc === 'mid' ? 6 : 3;
  const rt = c.rating;
  const audience = rt >= 4.5 ? 5 : rt >= 4.3 ? 4 : rt >= 4.0 ? 3 : rt >= 3.5 ? 2 : rt > 0 ? 1 : 2.5;
  const total = Math.round((heat + cadence + depth + fit + learning + perennial + transfer + legal + audience) * 10) / 10;
  return { total, heat, cadence, depth, fit, learning, perennial, transfer, legal, audience, pub_class: pc, chart_rank: rk };
}

// parse one podcast rss feed into compact metrics
async function rssMetrics(feedUrl) {
  if (!feedUrl) return null;
  const txt = await get(String(feedUrl).replace(/^http:\/\//, 'https://'));  // iTunes 常回 http feed——https 升級（11-25 W48：ERR_INVALID_PROTOCOL 炸整批 merge）
  if (!txt) return null;
  const dates = [];
  const re = /<pubDate>([^<]+)<\/pubDate>/g;
  let m, guard = 0;
  while ((m = re.exec(txt)) && guard++ < 60) {
    const t = Date.parse(m[1]);
    if (!isNaN(t)) dates.push(t);
  }
  const durs = [];
  const rd = /<itunes:duration>([^<]+)<\/itunes:duration>/g;
  guard = 0;
  while ((m = rd.exec(txt)) && guard++ < 200) {
    const p = String(m[1]).trim().split(':').map(Number);
    if (p.every((x) => !isNaN(x))) durs.push(p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p.length === 2 ? p[0] * 60 + p[1] : p[0]);
  }
  durs.sort((a, b) => a - b);
  const epsWeek = dates.length >= 5 ? Math.round(((dates.length - 1) / ((Math.max(...dates) - Math.min(...dates)) / 604800e3 || 1)) * 10) / 10 : 0;
  const med = durs.length ? durs[Math.floor(durs.length / 2)] : 0;
  return {
    items: (txt.match(/<item>/g) || []).length,
    enclosures: (txt.match(/<enclosure[^>]+url=/g) || []).length,
    eps_week: epsWeek,
    median_min: Math.round((med / 60) * 10) / 10,
    latest: dates.length ? new Date(Math.max(...dates)).toISOString().slice(0, 10) : '',
    language: (txt.match(/<language>([^<]+)<\/language>/) || [])[1] || '',
    transcript_tag: txt.includes('<podcast:transcript'),
    sample_titles: (txt.match(/<title>(?:<!\[CDATA\[)?([^<\]]+)/g) || [])
      .slice(1, 9).map((s) => s.replace(/<title>(?:<!\[CDATA\[)?/, '').trim().slice(0, 80)),
  };
}

// web-page rating (JSON-LD); empty when the show has too few ratings
async function webRating(viewUrl) {
  const x = await get(viewUrl || '');
  if (!x) return {};
  const m = x.match(/"ratingValue"\s*:\s*([0-9.]+)/);
  const mc = x.match(/"ratingCount"\s*:\s*"?(\d+)"?/);
  if (m && mc) return { rating: parseFloat(m[1]), rating_count: parseInt(mc[1], 10) };
  return {};
}

const dbPath = () => path.join(__dirname, '..', 'state', 'candidates.json');

function loadDB() {
  try { return JSON.parse(fs.readFileSync(dbPath(), 'utf8')); }
  catch (_) { return { version: 1, updated: '', score_schema: 'v2', items: {} }; }
}

function saveDB(db) {
  db.updated = new Date().toISOString();
  fs.mkdirSync(path.dirname(dbPath()), { recursive: true });
  fs.writeFileSync(dbPath(), JSON.stringify(db));
}

function wk() {
  const d = new Date();
  const dt = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const day = dt.getUTCDay() || 7;
  dt.setUTCDate(dt.getUTCDate() + 4 - day);
  const start = new Date(Date.UTC(dt.getUTCFullYear(), 0, 1));
  return `${dt.getUTCFullYear()}-W${String(Math.ceil((((dt - start) / 864e5 + 1) / 7))).padStart(2, '0')}`;
}

// merge this week's candidates into the db (enrich + score + persist)
async function mergeDB(results, rank, week) {
  const db = loadDB();
  let merged = 0, skipped = 0;
  for (const c of results) {
    try {
    const r = await rssMetrics(c.feed_url);
    if (r) c.rss = r;
    const wr = await webRating(c.view_url);
    Object.assign(c, wr);
    c.score_v2 = scoreV2(c, rank);
    const key = c.itunes_id || 'name:' + c.name;
    const ex = db.items[key];
    if (ex) {
      ex.chart_rank = { ...(ex.chart_rank || {}), ...c.score_v2.chart_rank };
      ex.coverage[week] = { present: c.present, hits: c.hits };
      ex.rss = c.rss; ex.rating = c.rating; ex.rating_count = c.rating_count;
      ex.track_count = c.track_count; ex.score = { v1: c.score, v2: c.score_v2 };
      ex.publisher_class = c.score_v2.pub_class;
      ex.last_seen = week; ex.feed_url = c.feed_url; ex.view_url = c.view_url;
      ex.genre = c.genre;
    } else {
      db.items[key] = {
        name: c.name, artist: c.artist, genre: c.genre,
        feed_url: c.feed_url, view_url: c.view_url,
        markets: Object.keys(c.score_v2.chart_rank),
        chart_rank: c.score_v2.chart_rank,
        track_count: c.track_count, rss: c.rss,
        rating: c.rating, rating_count: c.rating_count,
        coverage: { [week]: { present: c.present, hits: c.hits } },
        publisher_class: c.score_v2.pub_class,
        score: { v1: c.score, v2: c.score_v2 },
        status: 'candidate', first_seen: week, last_seen: week, notes: '',
      };
    }
    merged++;
    } catch (e) { skipped++; }
  }
  saveDB(db);
  console.log(`db merge: ${merged} merged, ${skipped} skipped (per-candidate isolation)`);
  return db;
}

module.exports = { scoreV2, rssMetrics, webRating, pubClass, loadDB, saveDB, mergeDB, wk };
