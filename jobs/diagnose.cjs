'use strict';
/* one-off diagnosis: log masked response shapes to align field mapping. */
const X = require('../lib/eudic.cjs');

function mask(s) {
  return String(s).replace(/[A-Za-z0-9+/=._-]{24,}/g, (m) =>
    m.length > 24 ? m.slice(0, 6) + '***' + m.slice(-4) : m);
}

async function main() {
  const user = process.env.SVC_USER || '';
  const pass = process.env.SVC_PASS || '';
  const u = X.unit('a');
  const shape = X.shapes()[0];

  console.log('== login ==');
  const body = { [X.E.kUser]: user, [X.E.kHash]: String(u.api.pwd(pass)) };
  console.log('keys:', Object.keys(body).join(','), '| hash.len:', String(body[X.E.kHash]).length);

  const r = await X.call('POST', X.E.entry, body, X.hdrs(u, X.E.entry, {}, shape));
  console.log('login http:', r.code);
  console.log('login body:', mask(r.text).slice(0, 700));

  const j = X.jparse(r.text);
  console.log('all field names:', [...new Set(flattenKeys(j))].join(','));

  if (j) {
    const tok = X.digKey(j, 'token') || X.digKey(j, 'Token');
    const uid = X.digKey(j, 'userid') || X.digKey(j, 'userId') || X.digKey(j, 'uid');
    if (tok && uid) {
      const cred = { user: String(uid), token: String(tok) };
      console.log('== profile with extracted cred ==');
      const p = await X.call('GET', X.E.profile, null, X.hdrs(u, X.E.profile, cred, shape));
      console.log('profile http:', p.code, 'body:', mask(p.text).slice(0, 300));
      for (let i = 0; i < X.shapes().length; i++) {
        const sh = X.shapes()[i];
        const rel = X.E.visit + '?' + X.E.kZone + '=' + X.E.zone;
        const pr = await X.call('GET', rel, null, X.hdrs(u, rel, cred, sh));
        console.log(`checkin probe ${i + 1} vip=${sh.vip} first=${sh.first} launch=${sh.launch} -> ${pr.code}`, mask(pr.text).slice(0, 160));
        if (pr.code === 200) { console.log('SHAPE OK at', i + 1); break; }
        await X.sleep(600);
      }
      console.log('== hunt ==');
      const h = await X.hunt(u, cred, shape, 'Daily');
      console.log('hunt http:', h.code, 'type:', Array.isArray(h.data) ? 'array' : typeof h.data);
      console.log('hunt body:', mask(JSON.stringify(h.data) || '').slice(0, 800));
    }
  }
}

function flattenKeys(o, pre = '') {
  const out = [];
  if (!o || typeof o !== 'object') return out;
  for (const k of Object.keys(o)) {
    out.push(pre + k);
    out.push(...flattenKeys(o[k], pre + k + '.'));
  }
  return out;
}

main().catch((e) => { console.log('fatal:', String(e).slice(0, 300)); process.exit(1); });
