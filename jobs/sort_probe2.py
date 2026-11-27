#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sort_probe2 — 挖 reSortByChannel/dragSave 函數體＋完整 sortUl 選項＋sort 端點。"""
import re, sys
sys.path.insert(0, "podcast")
import ob_update as OB

def log(m): print(f"[sp2] {m}", flush=True)

OB.login()
cid = OB.channel_id()
idx = OB.req("GET", f"{OB.BASE}/ting/index?channelid={cid}", timeout=45).text or ""
# ①完整 sortChannelby 選項列
blk = re.search(r'<span class="sortUl">(.*?)</span>\s*</span>\s*</span>', idx, re.S)
if blk:
    log("═══ sortUl 全選項 ═══")
    for m in re.finditer(r'<input name="(\w+)"[^>]*value="(\d+)"[^>]*onchange="(\w+)\(([^)]*)\)"[^>]*>([^<]*)', blk.group(1)):
        log(f"  {m.group(1)} value={m.group(2)} fn={m.group(3)}({m.group(4)}) {m.group(5).strip()!r}")
# ②全 JS 挖函數
scripts = set()
for s in re.findall(r'<script[^>]*src="([^"]+)"', idx):
    scripts.add(s if s.startswith("http") else OB.BASE + s)
log(f"JS {len(scripts)} 個")
for u in sorted(scripts):
    try:
        body = OB.req("GET", u, timeout=45).text or ""
    except Exception:
        continue
    for fn in ("reSortByChannel", "dragSave", "reSortBy"):
        for m in list(re.finditer(fn, body))[:3]:
            seg = body[m.start():m.start()+700]
            seg = seg.replace("\r", " ").replace("\n", " ")
            log(f"── {u[-44:]} :: {fn} ──")
            log(f"  {re.sub(r'[ ]+', ' ', seg)[:660]}")
    for m in list(re.finditer(r'["\'](/(?:ting|Ting)/[A-Za-z]*[Ss]ort[A-Za-z]*)["\']', body))[:4]:
        log(f"  SORT 端點: {m.group(1)} (ctx: {re.sub(r'[ ]+',' ',body[max(0,m.start()-120):m.end()+160])[:240]})")
