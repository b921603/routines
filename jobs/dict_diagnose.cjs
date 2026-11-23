'use strict';
/* dict_diagnose.cjs — 歐路詞典(c)/西語助手(d) 桌面版打卡機制診斷（POC）。
 * 假說：Eusoft 家族共用 /api/v2/auth/authorize＋/api/v3/user/checkin，
 * 簽章演算法一致（tag 僅存於 EudicUserAgent）；passhash 可能 per-app。
 * 只讀模式預設（GET）；DICT_POST=1 才 POST。 */
const X = require('../lib/eudic.cjs');
const { load } = require('../lib/bridge.cjs');

const PORTAL = 'https://api.frdic.com';
const STAMP = process.env.DICT_STAMP || '26.8.0';
const DEV = process.env.SHAPE_DEV || '9f2c1a67-40d8-4e55-a1b3-8c6f22d90e14_mac_00:00:00:00:00:00';
const EIC = process.env.DICT_EIC || 'eIcO';

const APPS = {
  c: { tag: 'eusoft_eudic_en_mac', core: 'core-a.node', name: 'EudicDict' },
  d: { tag: 'eusoft_eudic_es_mac', core: 'core-b.node', name: 'EsHelper' },
};

function https(method, rel, body, headers, timeout = 40000) {
  return new Promise((resolve, reject) => {
    const payload = body ? Buffer.from(JSON.stringify(body)) : null;
    const u = new URL(PORTAL + rel);
    const h = Object.assign({}, headers);
    if (payload) { h['Content-Type'] = 'application/json'; h['Content-Length'] = payload.length; }
    else h['Content-Length'] = 0;
    const req = require('https').request({
      hostname: u.hostname, path: u.pathname + u.search, method, headers: h, timeout,
    }, (res) => {
      let buf = '';
      res.on('data', (c) => (buf += c));
      res.on('end', () => resolve({ code: res.statusCode, text: buf }));
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

function ua(tag) { return `/${tag}/${STAMP}/${DEV}/${EIC}//`; }

function hdrs(tag, api, rel, cred, shape) {
  return {
    Authorization: api.g(rel, cred.user || '', !!shape.vip, cred.token || '',
      shape.first, shape.launch, shape.camp || ''),
    EudicTimezone: '8',
    EudicUserAgent: ua(tag),
  };
}

(async () => {
  const USER = process.env.SVC_USER, PASS = process.env.SVC_PASS;
  const doPost = process.env.DICT_POST === '1';
  for (const id of Object.keys(APPS)) {
    const app = APPS[id];
    const api = load(app.core);
    const shape = {
      vip: (process.env.SHAPE_VIP || 'true') === 'true',
      first: Number(process.env.SHAPE_FIRST || 1600000000000),
      launch: Number(process.env.SHAPE_LAUNCH || 1),
      camp: process.env.SHAPE_CAMP || '',
    };
    console.log(`=== ${id} ${app.name} (${app.tag}) ===`);
    let r = null;
    try {
      r = await https('POST', '/api/v2/auth/authorize',
        { username: USER, passhash: String(api.pwd(PASS)) },
        hdrs(app.tag, api, '/api/v2/auth/authorize', {}, shape));
    } catch (e) { console.log('login err:', String(e).slice(0, 90)); continue; }
    const j = X.jparse(r.text);
    const d = (j && j.data) || {};
    const tok = (j && j.token) || d.token || '';
    const uid = (j && j.userid) || d.userid || '';
    console.log(`login: ${r.code} token=${tok ? 'ok' : '-'} uid=${uid ? 'ok' : '-'}`);
    if (!tok) { console.log('resp:', r.text.slice(0, 220)); continue; }
    const cred = { user: uid, token: tok };
    const pf = await https('GET', '/api/v2/auth/UserInfo', null,
      hdrs(app.tag, api, '/api/v2/auth/UserInfo', cred, shape));
    console.log('profile:', pf.code, pf.text.slice(0, 100).replace(/\s+/g, ' '));
    const probe = '/api/v3/user/checkin?timezone=8';
    const g = await https('GET', probe, null, hdrs(app.tag, api, probe, cred, shape));
    console.log('GET checkin:', g.code, g.text.slice(0, 300).replace(/\s+/g, ' '));
    if (doPost) {
      const p = await https('POST', '/api/v3/user/checkin', { timezone: '8' },
        hdrs(app.tag, api, '/api/v3/user/checkin', cred, shape));
      console.log('POST checkin:', p.code, p.text.slice(0, 340).replace(/\s+/g, ' '));
    }
    await new Promise((res) => setTimeout(res, 2500));
  }
  console.log('dict diagnose done');
})();
