#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sort_probe4 — 全 JS 枚舉 /ting/ API 面＋getSortChannels/dragSave 儲存函數本體。"""
import re, sys
sys.path.insert(0, "podcast")
import ob_update as OB

def log(m): print(f"[sp4] {m}", flush=True)

OB.login()
cid = OB.channel_id()
idx = OB.req("GET", f"{OB.BASE}/ting/index?channelid={cid}", timeout=45).text or ""
scripts = set()
for s in re.findall(r'<script[^>]*src="([^"]+)"', idx):
    scripts.add(s if s.startswith("http") else OB.BASE + s)
log(f"JS {len(scripts)} 個")
apis = {}
for u in sorted(scripts):
    try:
        body = OB.req("GET", u, timeout=60).text or ""
    except Exception as ex:
        log(f"  fetch err {u[-40:]}: {str(ex)[:50]}"); continue
    log(f"  {u[-52:]} {len(body)}B")
    for m in re.finditer(r"url:\s*['\"/]((?:ting|Ting)/[A-Za-z]+|/[A-Za-z]+/[A-Za-z]+)['\"/]", body):
        apis.setdefault(m.group(1), u[-30:])
    for kw in ("getSortChannels", "dragStart", "dragSave"):
        for m in list(re.finditer(re.escape(kw), body))[:4]:
            seg = re.sub(r"\s+", " ", body[max(0, m.start()-120):m.end()+500])
            log(f"═══ {u[-30:]} :: {kw} ═══")
            log(f"  …{seg[:600]}…")
log("═══ 全 JS 的 /ting/ API 面 ═══")
for a, src in sorted(apis.items()):
    log(f"  {a}   ({src})")
