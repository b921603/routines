'use strict';
/* ting_ops.cjs — 每日英语听力/每日西语听力 App API 自動化（11-28 用戶指定）。
 * 地基：lib/eudic.cjs（login+lockShape）＋ lib/native/core-linux.node（Linux AppImage
 * 26.11.1 抽出的 eudic_core ELF；ubuntu runner 可載，win32 core 保留給 Windows）。
 * 模式：
 *   export  — 訂閱收藏夾（subscribecollections）＋分類樹（channelgroup）→ trail/ting_export.json
 *   checkin — a/b 兩產品逐個：GET 簽到狀態→未簽且 TING_CHECKIN_POST=1 才 POST；回應全記錄
 *             （伺服器是否核實 15 分鐘聽力＝POST 回應直接給答案）
 * 端點（desktop JS 逆向實證）：/api/v2/auth/authorize、/api/v3/user/checkin、
 *   /api/v5/ting/subscribecollections、/api/v5/ting/channelgroup/
 */
const fs = require('fs');
const path = require('path');
const X = require('../lib/eudic.cjs');
const { load } = require('../lib/bridge.cjs');

const CORE_LINUX = path.join(__dirname, '..', 'lib', 'native', 'core-linux.node');
const OUT = path.join(__dirname, '..', 'trail', 'ting_export.json');
const PORTALS = ['https://api.frdic.com', 'https://api.esdict.cn'];
const MODE = process.env.TING_MODE || 'checkin';
const PRODUCTS = (process.env.TING_PRODUCTS || 'a,b').split(',');   // a=ting_en b=ting_es
const POST_OK = process.env.TING_CHECKIN_POST === '1';

// linux core 注入所有 unit（identity 在 UA tag，core 僅簽名器）
function useLinuxCore(u) {
  if (!u.api) u.api = load('core-linux.node');
  return u;
}

async function withPortal(u, cred, shape, fn) {
  let lastErr = null;
  for (const portal of PORTALS) {
    try {
      const r = await fn(portal);
      if (r && r.code === 401 && portal === PORTALS[0]) { lastErr = r; continue; }
      return r;
    } catch (e) { lastErr = { code: 0, text: String(e).slice(0, 120) }; }
  }
  return lastErr;
}

// call() 固定 portal——這裡複刻一份支援 portal 切換
const https = require('https');
function callPortal(portal, method, rel, body, headers, timeout = 40000) {
  return new Promise((resolve, reject) => {
    const payload = body ? Buffer.from(JSON.stringify(body)) : null;
    const u = new URL(portal + rel);
    const h = Object.assign({}, headers);
    if (payload) { h['Content-Type'] = 'application/json'; h['Content-Length'] = payload.length; }
    else h['Content-Length'] = 0;
    const req = https.request({ hostname: u.hostname, path: u.pathname + u.search,
      method, headers: h, timeout }, (res) => {
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

function rel(portal, path) { return path; }

async function loginPortal(portal, user, pass, id) {
  const u = useLinuxCore(X.UNITS[id]);
  for (let i = 0; i < 3; i++) {
    let r = null;
    try {
      r = await callPortal(portal, 'POST', X.E.entry,
        { username: user, passhash: String(u.api.pwd(pass)) },
        X.hdrs(u, X.E.entry, {}, X.shapes()[0]));
    } catch (e) { r = null; }
    const j = X.jparse(r && r.text);
    const d = (j && j.data) || {};
    const tok = (j && j.token) || d.token || (d.user && d.user.token) || '';
    const uid = (j && j.userid) || d.userid || (d.user && d.user.userid) || '';
    if (r && r.code === 200 && tok) return { u, cred: { user: uid, token: tok } };
    console.log(`[${id}@${new URL(portal).host}] login ${r ? r.code + ' ' + (r.text || '').slice(0, 80) : 'err'}`);
    if (r && r.code === 200 && !tok) break;      // 200 但無 token＝形狀異常，換 portal
    await X.sleep(2500);
  }
  return null;
}

async function opExport(sess, portal, tag) {
  const { u, cred } = sess;
  const shape = await X.lockShape(u, cred);
  if (!shape) { console.log(`[${tag}] lockShape 全滅——簽名形狀待對齊`); return null; }
  const H = (rel) => X.hdrs(u, rel, cred, shape);
  const out = {};
  const subs = await callPortal(portal, 'GET', '/api/v5/ting/subscribecollections', null,
    H('/api/v5/ting/subscribecollections'));
  console.log(`[${tag}] subscribecollections: ${subs.code} ${subs.text.slice(0, 300)}`);
  const sj = X.jparse(subs.text) || {};
  const cols = sj.collections || [];
  // 整理成乾淨樹：收藏夾 → 頻道
  const tree = cols.map((c) => ({
    collection: c.name || c.title || '',
    collection_id: c.id || c.collection_id || '',
    channel_count: (c.channels || []).length,
    channels: (c.channels || []).map((ch) => ({
      name: ch.name || ch.title || '',
      id: ch.id || ch.uuid || '',
      subscribed: ch.subscribed,
      article_count: ch.article_count !== undefined ? ch.article_count : (ch.count !== undefined ? ch.count : undefined),
      category: ch.category_name || ch.category || undefined,
    })),
  }));
  out.subscription_tree = tree;
  // 每收藏夾試 channelgroup/{id}（分類樹端點，best-effort）
  out.channelgroups = {};
  for (const c of cols) {
    const cid = c.id || c.collection_id;
    if (!cid) continue;
    await X.sleep(350);
    const r = await callPortal(portal, 'GET', `/api/v5/ting/channelgroup/${cid}`, null, H(`/api/v5/ting/channelgroup/${cid}`));
    console.log(`[${tag}] channelgroup/${cid.slice(0, 8)} → ${r.code} ${r.text.slice(0, 200)}`);
    out.channelgroups[cid] = r.code === 200 ? X.jparse(r.text) : { http: r.code };
  }
  const n = tree.reduce((a, t) => a + t.channel_count, 0);
  console.log(`[${tag}] 匯出完成：${tree.length} 收藏夾 / ${n} 頻道`);
  return out;
}

// 精聽學習計畫獎勵偵察：todayplan→bookId/dayIndex→簽到狀態→分享資訊→（閘門）分享回報
async function opReward(sess, portal, tag) {
  const { u, cred } = sess;
  const shape = await X.lockShape(u, cred);
  if (!shape) { console.log(`[${tag}] lockShape 全滅`); return null; }
  const g = async (rel) => {
    const r = await callPortal(portal, 'GET', rel, null, X.hdrs(u, rel, cred, shape));
    console.log(`[${tag}] GET ${rel.slice(0, 70)} → ${r.code} ${r.text.slice(0, 500)}`);
    return r;
  };
  const out = {};
  const tp = await g('/api/v5/ting/todayplan');
  out.todayplan = X.jparse(tp.text);
  const ej = await g('/api/v5/ting/eicojingtinghomepage');
  out.jt_home = X.jparse(ej.text);
  const pd = await g('/api/v5/jingting/purchased');
  out.purchased = X.jparse(pd.text);
  // 從 todayplan/jt_home 挖 bookId/dayIndex
  const blob = JSON.stringify(out);
  const bookIds = [...new Set([...blob.matchAll(/"(?:book_?[Ii]d|uuid)"\s*:\s*"([0-9a-f-]{36})"/g)].map(m => m[1]))];
  const dayIdx = [...new Set([...blob.matchAll(/"(?:day_?[Ii]ndex|period_?[Ii]ndex|current_?day)"\s*:\s*"?([0-9]+)"?/g)].map(m => m[1])))];
  out.detected = { bookIds, dayIdx };
  console.log(`[${tag}] detected bookIds=${JSON.stringify(bookIds)} dayIdx=${JSON.stringify(dayIdx)}`);
  if (bookIds[0]) {
    const bid = bookIds[0], di = dayIdx[0] || '1';
    const ck = await g(`/api/v5/ting/GetJingTingCheckIn?bookId=${bid}&dayIndex=${di}`);
    out.checkin_detail = X.jparse(ck.text);
    const si = await g(`/api/v5/ting/jingtingshareinfo?bookId=${bid}&dayIndex=${di}`);
    out.shareinfo = X.jparse(si.text);
    if (process.env.TING_SHARE_POST === '1') {
      await X.sleep(800);
      const rel = `/api/v5/ting/UpdateJingTingShareStatus?bookId=${bid}&dayIndex=${di}`;
      const p = await callPortal(portal, 'POST', rel, null, X.hdrs(u, rel, cred, shape));
      console.log(`[${tag}] UpdateJingTingShareStatus → ${p.code} ${p.text.slice(0, 400)}`);
      out.share_post = { code: p.code, body: X.jparse(p.text) };
    } else {
      out.share_post = 'skipped (TING_SHARE_POST 未開)';
    }
  }
  return out;
}

async function opCheckin(sess, portal, tag) {
  const { u, cred } = sess;
  const shape = await X.lockShape(u, cred);
  if (!shape) { console.log(`[${tag}] lockShape 全滅`); return null; }
  const probe = '/api/v3/user/checkin?timezone=8';
  const st = await callPortal(portal, 'GET', probe, null, X.hdrs(u, probe, cred, shape));
  console.log(`[${tag}] checkin GET ${st.code}: ${st.text.slice(0, 500)}`);
  const res = { get_code: st.code, get_body: X.jparse(st.text) };
  if (st.code !== 200) return res;
  const data = res.get_body && res.get_body.data;
  // data 可能是 false（未簽）或 {checkin_date...} 物件
  const checked = !(data === false || data === 'false' || data === null);
  res.checked_in_today = checked;
  if (!checked && POST_OK) {
    await X.sleep(800);
    const p = await callPortal(portal, 'POST', '/api/v3/user/checkin',
      { timezone: 8 }, X.hdrs(u, '/api/v3/user/checkin', cred, shape));
    console.log(`[${tag}] checkin POST ${p.code}: ${p.text.slice(0, 600)}`);
    res.post_code = p.code;
    res.post_body = X.jparse(p.text);
    res.post_raw = p.text.slice(0, 600);
  } else if (!checked) {
    res.post_skipped = 'TING_CHECKIN_POST 未開';
  }
  return res;
}

async function main() {
  const user = process.env.SVC_USER || '';
  const pass = process.env.SVC_PASS || '';
  if (!user || !pass) { console.log('no creds'); process.exit(1); }
  const results = {};
  for (const id of PRODUCTS) {
    const tag = `unit-${id}`;
    let sess = null, portalUsed = null;
    for (const portal of PORTALS) {
      sess = await loginPortal(portal, user, pass, id);
      if (sess) { portalUsed = portal; break; }
    }
    if (!sess) { results[id] = { error: 'login failed on all portals' }; continue; }
    console.log(`[${tag}] login OK via ${new URL(portalUsed).host} userid=${sess.cred.user}`);
    results[id] = MODE === 'export'
      ? await opExport(sess, portalUsed, tag)
      : MODE === 'reward'
        ? await opReward(sess, portalUsed, tag)
        : await opCheckin(sess, portalUsed, tag);
  }
  fs.writeFileSync(path.join(__dirname, '..', 'trail', `ting_${MODE}.json`),
    JSON.stringify({ at: new Date().toISOString(), mode: MODE, results }, null, 1));
  if (MODE === 'export') {
    fs.writeFileSync(OUT, JSON.stringify(results, null, 1));
  }
  const brief = Object.entries(results).map(([k, v]) => {
    if (!v) return `${k}:null`;
    if (v.error) return `${k}:登入失敗`;
    if (MODE === 'checkin') return `${k}:GET${v.get_code}${v.checked_in_today === undefined ? '' : v.checked_in_today ? '已簽' : '未簽'}${v.post_code ? '→POST' + v.post_code : ''}`;
    return `${k}:訂閱${v.subscriptions_raw ? '✓' : '✗'}分類${v.channelgroup_raw ? '✓' : '✗'}`;
  }).join('｜');
  console.log('SUMMARY ' + brief);
  await X.notify(`Ting ${MODE}: ${brief}`, '');
}

main().catch((e) => { console.error('FATAL', e); process.exit(1); });
