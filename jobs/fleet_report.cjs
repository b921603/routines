/**
 * fleet report — 解密保險庫 → 掩碼總表（帳密永不明文進日誌）
 */
const crypto = require('crypto');
const fs = require('fs');

const KEY = process.env.FLEET_KEY || '';
if (!KEY) { console.log('FLEET_KEY missing'); process.exit(1); }
const key = crypto.scryptSync(KEY, 'eudic-fleet-v1', 32, { N: 16384, r: 8, p: 1 });
const encPath = 'state/fleet.enc';
if (!fs.existsSync(encPath)) { console.log('fleet.enc not found'); process.exit(0); }

const rows = fs.readFileSync(encPath, 'utf8').trim().split('\n').filter(Boolean).map((line) => {
  const rec = JSON.parse(line);
  const d = crypto.createDecipheriv('aes-256-gcm', key, Buffer.from(rec.iv, 'base64'));
  d.setAuthTag(Buffer.from(rec.tag, 'base64'));
  return JSON.parse(Buffer.concat([d.update(Buffer.from(rec.ct, 'base64')), d.final()]).toString('utf8'));
});

console.log('fleet roster (masked):');
for (const r of rows) {
  console.log(`  ${r.account} | ${r.email} | pw:${'*'.repeat((r.eudic_pw || '').length)} | role=${r.role || '-'} | ch=${(r.channels || '') || '-'} | ${r.created} | ${r.status}`);
}
console.log(`total: ${rows.length}`);
const shadow = JSON.parse(fs.readFileSync('state/fleet.json', 'utf8'));
console.log('shadow fleet.json entries:', shadow.fleet.length);
