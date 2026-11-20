'use strict';
/* routines — daily marks (win32 runner; x86 node).
 * retries until the day is done, then later sweeps exit quietly. */
const fs = require('fs');
const path = require('path');
const X = require('../lib/eudic.cjs');

const P = X.readPolicies();
const ROUNDS = Number(process.env.HKG_ROUNDS || P.pacing.rounds || 4);
const PAUSE = Number(process.env.HKG_PAUSE || P.pacing.round_pause_s || 90);
const UNIT_RETRIES = Number(process.env.HKG_UNIT_RETRIES || P.pacing.unit_retry || 3);

function todayKey() {
  return new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 10);
}
function statePath() { return path.join(__dirname, '..', 'logs', 'state.json'); }
function readState() {
  try { return JSON.parse(fs.readFileSync(statePath(), 'utf8')); } catch (_) { return {}; }
}
function writeState(st) {
  try {
    fs.mkdirSync(path.dirname(statePath()), { recursive: true });
    fs.writeFileSync(statePath(), JSON.stringify(st));
  } catch (_) { /* silent */ }
}

async function markUnit(id, cred, shape) {
  const u = X.unit(id);
  let code = 0;
  for (let k = 0; k < UNIT_RETRIES; k++) {
    try {
      const r = await X.call('POST', X.E.visit, { [X.E.kZone]: Number(X.E.zone) },
        X.hdrs(u, X.E.visit, cred, shape));
      code = r.code;
      if (code === 200 || code === 409) {
        const j = X.jparse(r.text);
        const day = j && j.data && j.data.checkin_date;
        if (day) console.log(`${id} marked ${day}`);
        return code;
      }
      console.log(`${id} try${k + 1} -> ${code}`);
    } catch (e) { console.log(`${id} try${k + 1} error:`, String(e).slice(0, 100)); }
    await X.sleep(5000 * (k + 1));
  }
  return code;
}

async function fullAttempt(user, pass) {
  const s = await X.login(user, pass, 'a');
  if (!s) return { ok: false, codes: {} };
  const shape = await X.lockShape(s.u, s.cred);
  if (!shape) return { ok: false, codes: {} };
  console.log('shape locked');
  const codes = {};
  let allOk = true;
  for (const id of ['a', 'b']) {
    const code = await markUnit(id, s.cred, shape);
    codes[id] = code;
    const ok = code === 200 || code === 409;
    console.log(`${id}: ${ok ? 'done' : 'skip'} (${code})`);
    if (!ok) allOk = false;
    await X.sleep(700);
  }
  return { ok: allOk, codes };
}

async function run() {
  const user = process.env.SVC_USER || '';
  const pass = process.env.SVC_PASS || '';
  const day = todayKey();

  const st = readState();
  if (st.day === day && st.ok) { console.log('already ok today'); process.exit(0); return; }
  if (!user || !pass) { console.log('missing credentials'); process.exit(1); return; }

  let last = { ok: false, codes: {} };
  for (let r = 1; r <= ROUNDS; r++) {
    console.log(`— round ${r}/${ROUNDS} —`);
    try { last = await fullAttempt(user, pass); }
    catch (e) { console.log('round error:', String(e).slice(0, 160)); }
    if (last.ok) break;
    if (r < ROUNDS) await X.sleep(PAUSE * 1000);
  }

  writeState({ day, ok: last.ok, codes: last.codes || {}, pv: P.policy_version, at: new Date().toISOString() });
  if (last.ok) {
    const c = last.codes;
    await X.notify(`ok ${c.a || 0}/${c.b || 0} pv${P.policy_version}`);
    process.exit(0);
  } else {
    const cc = last.codes || {};
    await X.notify(`FAIL ${cc.a || 0}/${cc.b || 0} — sweeps continue`);
    process.exit(1);
  }
}

run().catch((e) => { console.log('fatal:', String(e).slice(0, 200)); process.exit(1); });
