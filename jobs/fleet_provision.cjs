/**
 * fleet provision — 歐路帳號艦隊自動註冊（用戶核准 2026-11-23）
 * 流程（全部實證）：mail.tm 建信箱（無點 local part）→ dict.eudic.net SendEmailCode
 *   → mail.tm 收 6 位碼 → POST Register → 302=成功 → 寫入加密保險庫 fleet.enc + 公開影子 fleet.json
 * 安全：密碼只入 AES-256-GCM 密文（FLEET_KEY）；日誌永不出現帳密。每 run 上限 3 帳。
 */
const crypto = require('crypto');
const fs = require('fs');
const https = require('https');

const KEY = process.env.FLEET_KEY || '';
const COUNT = Math.min(parseInt(process.env.FLEET_COUNT || '1', 10) || 1, 3);
const DICT = 'https://dict.eudic.net';
const MAIL = 'https://api.mail.tm';
if (!KEY) { console.log('FLEET_KEY missing'); process.exit(1); }

function req(url, { method = 'GET', headers = {}, body = null, timeout = 40000 } = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const h = Object.assign({ 'User-Agent': 'Mozilla/5.0', 'Accept': '*/*' }, headers);
    const data = body ? Buffer.from(body) : null;
    if (data) { h['Content-Length'] = data.length; }
    const r = https.request({ hostname: u.hostname, path: u.pathname + u.search, method, headers: h, timeout }, (res) => {
      let buf = '';
      res.on('data', (c) => (buf += c));
      res.on('end', () => resolve({ code: res.statusCode, loc: res.headers.location, setCookie: res.headers['set-cookie'] || [], text: buf }));
    });
    r.on('timeout', () => r.destroy(new Error('timeout')));
    r.on('error', reject);
    if (data) r.write(data);
    r.end();
  });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jarPush = (jar, setCookie) => { for (const c of setCookie) jar.add(c.split(';')[0]); };

function encLine(key, obj) {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', key, iv);
  const ct = Buffer.concat([c.update(JSON.stringify(obj), 'utf8'), c.final()]);
  return JSON.stringify({ v: 1, iv: iv.toString('base64'), ct: ct.toString('base64'), tag: c.getAuthTag().toString('base64') });
}

async function main() {
  const key = crypto.scryptSync(KEY, 'eudic-fleet-v1', 32, { N: 16384, r: 8, p: 1 });
  const encPath = 'state/fleet.enc';
  const shadowPath = 'state/fleet.json';
  const enc = fs.existsSync(encPath) ? fs.readFileSync(encPath, 'utf8').trim().split('\n').filter(Boolean) : [];
  const shadow = fs.existsSync(shadowPath) ? JSON.parse(fs.readFileSync(shadowPath, 'utf8')) : { fleet: [] };

  // 活躍 mail.tm 網域
  const d = await req(MAIL + '/domains');
  const doms = JSON.parse(d.text || '{}');
  const arr = Array.isArray(doms) ? doms : (doms['hydra:member'] || []);
  const domain = (arr.find((x) => x.isActive) || {}).domain;
  if (!domain) { console.log('no active mail domain'); process.exit(1); }

  let made = 0;
  for (let n = 0; n < COUNT; n++) {
    const hex = crypto.randomBytes(2).toString('hex');
    const nick = 'tingfleet' + hex;
    const email = nick + '@' + domain;            // 無點 local part（mail.tm 正規化安全）
    const mpw = crypto.randomBytes(12).toString('base64').replace(/[^A-Za-z0-9]/g, 'x').slice(0, 16);
    const epw = crypto.randomBytes(12).toString('base64').replace(/[^A-Za-z0-9]/g, 'x').slice(0, 16);
    console.log(`=== provisioning ${nick} ===`);

    // 1) mail.tm 帳號
    let r = await req(MAIL + '/accounts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ address: email, password: mpw }) });
    if (r.code !== 201) { console.log('mail create fail', r.code, r.text.slice(0, 120)); continue; }
    r = await req(MAIL + '/token', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ address: email, password: mpw }) });
    const mtok = (JSON.parse(r.text || '{}').token) || '';
    if (!mtok) { console.log('mail token fail', r.code); continue; }

    // 2) dict session + 發碼
    const jar = new Set();
    r = await req(DICT + '/Account/Register', {});
    jarPush(jar, r.setCookie);
    r = await req(DICT + '/Account/SendEmailCode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'Referer': DICT + '/Account/Register', 'X-Requested-With': 'XMLHttpRequest', 'Cookie': [...jar].join('; ') },
      body: 'email=' + encodeURIComponent(email),
    });
    const sendOk = (JSON.parse(r.text || '{}').success) === true;
    if (!sendOk) { console.log('send code fail', r.code, r.text.slice(0, 120)); continue; }

    // 3) 收碼（最多 3 分鐘）
    let code = null;
    for (let i = 0; i < 15 && !code; i++) {
      await sleep(12000);
      const b = await req(MAIL + '/messages?page=1', { headers: { 'Authorization': 'Bearer ' + mtok } });
      const box = JSON.parse(b.text || '{}');
      const msgs = Array.isArray(box) ? box : (box['hydra:member'] || []);
      for (const m of msgs) {
        const f = await req(MAIL + '/messages/' + m.id, { headers: { 'Authorization': 'Bearer ' + mtok } });
        const full = JSON.parse(f.text || '{}');
        const txt = full.text || (Array.isArray(full.html) ? full.html[0] : (full.html || ''));
        const mm = txt.match(/验证码是\s*(\d{4,8})/);
        if (mm && m.from && /eudic/i.test(m.from.address || '')) { code = mm[1]; break; }
      }
    }
    if (!code) { console.log('code not received'); continue; }

    // 4) 註冊（302=成功）
    r = await req(DICT + '/Account/Register?returnUrl=&recmdBy=&style=', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'Referer': DICT + '/Account/Register', 'Cookie': [...jar].join('; ') },
      body: `Email=${encodeURIComponent(email)}&Password=${encodeURIComponent(epw)}&ConfirmPassword=${encodeURIComponent(epw)}&NickName=${encodeURIComponent(nick)}&EmailCheckCode=${code}&returnUrl=&recmdBy=&style=`,
    });
    if (r.code !== 302) { console.log('register fail', r.code, r.text.replace(/<[^>]+>/g, ' ').slice(0, 200)); continue; }

    // 5) 保險庫（密文）＋影子（無憑證）
    enc.push(encLine(key, { account: nick, email, email_pw: mpw, eudic_pw: epw, role: '', channels: '', created: new Date().toISOString().slice(0, 10), status: 'active' }));
    shadow.fleet.push({ account: nick, email, role: '', channels: [], created: new Date().toISOString().slice(0, 10), status: 'active' });
    made++;
    console.log(`provisioned: ${nick} ok`);
    await sleep(4000);
  }

  fs.writeFileSync(encPath, enc.join('\n') + '\n');
  fs.writeFileSync(shadowPath, JSON.stringify(shadow, null, 1) + '\n');
  console.log(`done: ${made}/${COUNT} provisioned`);
}
main().catch((e) => { console.log('fatal', e.message); process.exit(1); });
