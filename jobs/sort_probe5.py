#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sort_probe5 — OrderPriveteMedia/BatchAiSubtitle 呼叫上下文（payload 形狀）。"""
import re, sys
sys.path.insert(0, "podcast")
import ob_update as OB

def log(m): print(f"[sp5] {m}", flush=True)

OB.login()
body = OB.req("GET", "https://my.eudic.net/js/common.min.js", timeout=60).text or ""
for fn in ("OrderPriveteMedia", "BatchAiSubtitle", "SetMaintainTopMedia"):
    for m in list(re.finditer(re.escape(fn), body))[:2]:
        seg = re.sub(r"\s+", " ", body[max(0, m.start()-700):m.end()+400])
        log(f"═══ {fn} ═══")
        log(f"  …{seg}…")
