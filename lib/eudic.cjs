'use strict';
/* shared glue: vendored win32 core, request helpers, session flow.
 * all jobs import from here — policy changes land in ../policies and propagate. */
const https = require('https');
const path = require('path');
const fs = require('fs');
const { load } = require('./bridge.cjs');

const B = (s) => Buffer.from(s, 'base64').toString('utf8');

const E = {
  portal: B('aHR0cHM6Ly9hcGkuZnJkaWMuY29t'),
  entry: B('L2FwaS92Mi9hdXRoL2F1dGhvcml6ZQ=='),
  profile: B('L2FwaS92Mi9hdXRoL1VzZXJJbmZv'),
  visit: B('L2FwaS92My91c2VyL2NoZWNraW4='),
  hunt: B('L2FwaS92NC90aW5nL3NlYXJjaA=='),
  kAuth: B('QXV0aG9yaXphdGlvbg=='),
  kTz: B('RXVkaWNUaW1lem9uZQ=='),
  kUa: B('RXVkaWNVc2VyQWdlbnQ='),
  kUser: B('dXNlcm5hbWU='),
  kHash: B('cGFzc2hhc2g='),
  kZone: B('dGltZXpvbmU='),
  kWord: B('a2V5d29yZA=='),
  stamp: B('MjYuMTEuMQ=='),
  zone: '8',
};

const UNITS = {
  a: { id: 'a', core: 'core-a.node', tag: B('ZXVzb2Z0X3RpbmdfZW5fZGVza3RvcA==') },
  b: { id: 'b', core: 'core-b.node', tag: B('ZXVzb2Z0X3RpbmdfZXNfZGVza3RvcA==') },
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const MOCK = !!process.env.HKG_MOCK;

function unit(id) {
  const u = UNITS[id];
  if (MOCK) {
    u.api = {
      pwd: (s) => 'mock' + Buffer.from(String(s)).toString('hex').slice(0, 12),
      g: (p, uid, vip, tok, f, l, c) =>
        'mock:' + [p, uid, vip, tok, f, l, c].join('|').slice(0, 40),
    };
  } else if (!u.api) {
    u.api = load(u.core);
  }
  return u;
}

function ua(u) {
  const dev = process.env.SHAPE_DEV || '9f2c1a67-40d8-4e55-a1b3-8c6f22d90e14_mac_00:00:00:00:00:00';
  return `/${u.tag}/${E.stamp}/${dev}/eico//`;
}

function sign(u, rel, cred, shape) {
  return u.api.g(rel, cred.user || '', !!shape.vip, cred.token || '',
    shape.first, shape.launch, shape.camp || '');
}

function hdrs(u, rel, cred, shape) {
  return {
    [E.kAuth]: sign(u, rel, cred, shape),
    [E.kTz]: E.zone,
    [E.kUa]: ua(u),
  };
}

function call(method, rel, body, headers, timeout = 40000) {
  if (MOCK) return mockCall(method, rel, body);
  return new Promise((resolve, reject) => {
    const payload = body ? Buffer.from(JSON.stringify(body)) : null;
    const u = new URL(E.portal + rel);
    const h = Object.assign({}, headers);
    if (payload) {
      h['Content-Type'] = 'application/json';
      h['Content-Length'] = payload.length;
    } else {
      h['Content-Length'] = 0;
    }
    const req = https.request({
      hostname: u.hostname,
      path: u.pathname + u.search,
      method,
      headers: h,
      timeout,
    }, (res) => {
      let buf = '';
      res.on('data', (c) => { buf += c; });
      res.on('end', () => resolve({ code: res.statusCode, text: buf }));
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

let mockSignedIn = false;
function mockCall(method, rel, body) {
  return sleep(40).then(() => {
    if (rel === E.entry) {
      if (!body || !body[E.kUser] || !body[E.kHash]) return { code: 401, text: '{}' };
      mockSignedIn = true;
      return { code: 200, text: JSON.stringify({ status: 200, data: { token: 'T0K', userid: 'U1' } }) };
    }
    if (rel === E.profile) {
      return { code: mockSignedIn ? 200 : 401, text: JSON.stringify({ status: 200, data: { ting: { istingvip: true } } }) };
    }
    if (rel.startsWith(E.visit)) {
      if (!mockSignedIn) return { code: 401, text: '{}' };
      if (process.env.HKG_MOCK_FAIL) return { code: 500, text: '{"status":500}' };
      if (method === 'POST') return { code: 200, text: JSON.stringify({ status: 200, data: { checkin_date: '2026-11-20' } }) };
      return { code: 200, text: JSON.stringify({ status: 200, data: false }) };
    }
    if (rel.startsWith(E.hunt)) {
      if (!mockSignedIn) return { code: 401, text: '{}' };
      return { code: 200, text: JSON.stringify({ status: 200, data: [] }) };
    }
    return { code: 404, text: '{}' };
  });
}

function jparse(t) { try { return JSON.parse(t); } catch (_) { return null; } }

function digKey(obj, key) {
  if (!obj || typeof obj !== 'object') return null;
  if (Object.prototype.hasOwnProperty.call(obj, key)) return obj[key];
  for (const k of Object.keys(obj)) {
    const hit = digKey(obj[k], key);
    if (hit !== null) return hit;
  }
  return null;
}

// ledger knobs: a precise shape can be injected via env (SHAPE_*), else try common ones
const baseShapes = [
  { vip: true, first: 1600000000000, launch: 1, camp: '' },
  { vip: false, first: 1600000000000, launch: 1, camp: '' },
  { vip: true, first: 1600000000000, launch: 42, camp: '' },
  { vip: true, first: 0, launch: 1, camp: '' },
  { vip: false, first: 0, launch: 1, camp: '' },
  { vip: true, first: 1577836800000, launch: 1, camp: '' },
  { vip: false, first: 1600000000000, launch: 42, camp: '' },
  { vip: true, first: 1600000000000, launch: 1, camp: 'eudic' },
];
function shapes() {
  const out = [];
  if (process.env.SHAPE_FIRST || process.env.SHAPE_LAUNCH || process.env.SHAPE_CAMP) {
    out.push({
      vip: (process.env.SHAPE_VIP || 'true') === 'true',
      first: Number(process.env.SHAPE_FIRST || 1600000000000),
      launch: Number(process.env.SHAPE_LAUNCH || 1),
      camp: process.env.SHAPE_CAMP || '',
    });
  }
  out.push(...baseShapes);
  return out;
}

async function login(user, pass, id = 'a', tries = 3) {
  const u = unit(id);
  for (let i = 0; i < tries; i++) {
    let r = null;
    try {
      r = await call('POST', E.entry, { [E.kUser]: user, [E.kHash]: String(u.api.pwd(pass)) },
        hdrs(u, E.entry, {}, shapes()[0]));
    } catch (e) { r = null; }
    const j = r && jparse(r.text);
    // login response is flat: {token, userid, expirein, profile...}
    const d = (j && j.data) || {};
    const tok = (j && j.token) || d.token || (d.user && d.user.token) || '';
    const uid = (j && j.userid) || d.userid || d.uid || (d.user && d.user.userid) || '';
    if (r && r.code === 200 && tok) return { u, cred: { user: uid, token: tok } };
    console.log(`login ${r ? r.code : 'err'}`);
    await sleep(3000);
  }
  return null;
}

// probe a working ledger shape (first unit); caches on the unit for the run
async function lockShape(u, cred) {
  if (u.shape) return u.shape;
  for (let i = 0; i < shapes().length; i++) {
    let c = shapes()[i];
    let refined = c;
    try {
      const pf = await call('GET', E.profile, null, hdrs(u, E.profile, cred, c));
      const pv = pf.code === 200 ? digKey(jparse(pf.text), 'istingvip') : null;
      if (typeof pv === 'boolean') refined = Object.assign({}, c, { vip: pv });
    } catch (_) { /* keep */ }
    const probe = E.visit + '?' + E.kZone + '=' + E.zone;
    try {
      const pr = await call('GET', probe, null, hdrs(u, probe, cred, refined));
      console.log(`probe ${i + 1}/${shapes().length} -> ${pr.code}`);
      if (pr.code === 200) { u.shape = refined; return refined; }
    } catch (e) { console.log('probe error:', String(e).slice(0, 100)); }
    await sleep(600);
  }
  return null;
}

async function hunt(u, cred, shape, keyword) {
  const rel = E.hunt + '?' + E.kWord + '=' + encodeURIComponent(keyword) +
    '&type=homepage&showtype=1&page=0&pageSize=20&classification=0';
  const r = await call('GET', rel, null, hdrs(u, rel, cred, shape));
  const j = jparse(r.text);
  // response is grouped: {items: [{name: "频道", total_count, items: [...]}, ...]}
  const groups = (j && j.items) || [];
  const flat = [];
  for (const g of groups) {
    for (const x of (g && g.items) || []) flat.push(x);
  }
  return { code: r.code, flat, groups: groups.length };
}

async function notify(text, click) {
  const url = process.env.NTFY_URL || '';
  if (!url) return;
  try {
    const h = {};
    if (click) h['X-Click'] = click;
    await fetch(url, { method: 'POST', body: text, headers: h });
  } catch (_) { /* silent */ }
}

function readPolicies() {
  try {
    return JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'policies', 'policies.json'), 'utf8'));
  } catch (_) { return { policy_version: 0, pacing: {} }; }
}

module.exports = { E, UNITS, sleep, MOCK, unit, ua, sign, hdrs, call, jparse, digKey,
  shapes, login, lockShape, hunt, notify, readPolicies, B };
