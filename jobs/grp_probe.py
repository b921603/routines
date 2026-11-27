#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""grp_probe — 分組內「頻道順序」機制探查（唯讀）：JS 端點面＋GetChannelGroups 形狀。"""
import re, sys
sys.path.insert(0, "podcast")
import ob_update as OB

def log(m): print(f"[gp] {m}", flush=True)

OB.login()
body = OB.req("GET", "https://my.eudic.net/js/common.min.js", timeout=60).text or ""
log("═══ JS 內 Group/頻道排序相關端點 ═══")
for m in re.finditer(r"url:\s*['\"]([^'\"]*[Gg]roup[^'\"]*)['\"]", body):
    log(f"  端點: {m.group(1)}")
for kw in ("OrderChannel", "SortChannel", "ChannelOrder", "dragChannel", "channelSort"):
    for m in list(re.finditer(re.escape(kw), body))[:2]:
        seg = re.sub(r"\s+", " ", body[max(0, m.start()-100):m.end()+250])
        log(f"  [{kw}] …{seg[:300]}…")
log("═══ GetChannelGroups / GetPrivateChannels 回應形狀 ═══")
for api in ("GetChannelGroups", "GetPrivateChannels", "GetGroupChannels"):
    try:
        r = OB.req("GET", f"{OB.BASE}/ting/{api}", timeout=45)
        t = (r.text or "")[:600]
        log(f"── {api}: HTTP {r.status_code} ──")
        log(f"  {re.sub(r'[ ]+', ' ', t)[:500]}")
    except Exception as ex:
        log(f"  {api} err: {str(ex)[:60]}")
