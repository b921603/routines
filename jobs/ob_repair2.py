#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ob_repair2 — 從清單頁 JS 獵 DeletePriveteMedia 呼叫形狀→多形狀刪除→驗證。"""
import json, re, sys, time
sys.path.insert(0, "podcast")
import ob_update as OB

def log(m): print(f"[r2] {m}", flush=True)

TARGETS = ["4bbac3f3-6467-47f9-9011-468186ebb173",
           "717a3ade-8bae-4f00-86fc-797789ec0a17"]

OB.login()
cid = OB.channel_id()
# ①清單頁 → JS 檔 → DeletePriveteMedia 呼叫上下文
listing = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page=0&channelId={cid}", timeout=45).text or ""
js = sorted(set(re.findall(r'src="([^"]*\.js[^"]*)"', listing)))
log(f"JS 檔 {len(js)} 個")
for u in js:
    if "min.js" not in u and "upload" not in u and "ting" not in u:
        continue
    try:
        body = OB.req("GET", u if u.startswith("http") else (OB.BASE + u), timeout=45).text or ""
    except Exception:
        continue
    for m in list(re.finditer(r"DeletePriveteMedia", body))[:2]:
        ctx = re.sub(r"\s+", " ", body[max(0, m.start()-300):m.start()+300])
        log(f"── {u[-40:]}: …{ctx}…")
# ②多形狀刪除嘗試
def try_del(mid, data, hdrs=None, tag=""):
    r = OB.req("POST", f"{OB.BASE}/ting/DeletePriveteMedia", data=data, headers=hdrs, timeout=60)
    ok = ('"success":true' in (r.text or "")) or ('"code":200' in (r.text or "").replace(" ", ""))
    log(f"  [{tag}] HTTP {r.status_code} {(r.text or '')[:90]} {'✓' if ok else ''}")
    return ok
for mid in TARGETS:
    done = False
    done |= try_del(mid, {"mediaIds[]": mid}, tag="form[]")
    if not done: done |= try_del(mid, {"mediaIds": mid}, tag="form-scalar")
    if not done: done |= try_del(mid, {"mediaIds": json.dumps([mid])}, tag="form-jsonstr")
    if not done: done |= try_del(mid, json.dumps({"mediaIds": [mid]}),
                                 {"Content-Type": "application/json"}, tag="json")
    time.sleep(3)
# ③驗證
gone = set()
for pg in range(24):
    rr = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}", timeout=45)
    txt = rr.text or ""
    for mid in TARGETS:
        if mid in txt:
            gone.add(mid)
    if "dragBox" not in txt:
        break
for mid in TARGETS:
    log(f"verify {mid[:8]}: {'✗ 仍在' if mid in gone else '✓ 已刪'}")
if gone:
    sys.exit(1)
log("repair done")
