#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sort_probe — 獵 ting/index「默認排序/拖曳排序」下拉選單的後端端點與 payload 形狀（唯讀）。"""
import re, sys
sys.path.insert(0, "podcast")
import ob_update as OB

def log(m): print(f"[sortp] {m}", flush=True)

OB.login()
cid = OB.channel_id()
pages = {
    "index": f"{OB.BASE}/ting/index",
    "index+cid": f"{OB.BASE}/ting/index?channelid={cid}",
    "list": f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page=0&channelId={cid}",
}
scripts = set()
for tag, u in pages.items():
    t = OB.req("GET", u, timeout=45).text or ""
    log(f"═══ {tag} {len(t)}B ═══")
    for kw in ("拖曳排序", "默认排序", "从新到旧", "从旧到新"):
        for m in list(re.finditer(re.escape(kw), t))[:1]:
            ctx = re.sub(r"\s+", " ", t[max(0, m.start()-200):m.start()+250])
            log(f"  {kw!r}: …{ctx}…")
    for s in re.findall(r'<script[^>]*src="([^"]+)"', t):
        scripts.add(s if s.startswith("http") else OB.BASE + s)
log(f"JS 共 {len(scripts)} 個")
for u in sorted(scripts):
    try:
        body = OB.req("GET", u, timeout=45).text or ""
    except Exception:
        continue
    hits = []
    for kw in ("拖曳", "默认排序", "从新到旧", "从旧到新", "SortMedia", "sortMedia",
               "MediaSort", "mediaSort", "SortPrivate", "sortPrivate", "mediaIds",
               "sortby", "SortType", "sortType"):
        for m in list(re.finditer(re.escape(kw), body))[:2]:
            ctx = re.sub(r"\s+", " ", body[max(0, m.start()-260):m.start()+320])
            hits.append(f"  [{kw}] …{ctx}…")
    if hits:
        log(f"── {u[-52:]} ──")
        for h in hits[:8]:
            log(h)
