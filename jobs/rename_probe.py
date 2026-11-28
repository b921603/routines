#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rename_probe — UpdatePrivateChannel 失敗鑑識（唯讀＋一次對照寫入）。"""
import re, sys
sys.path.insert(0, "podcast")
import ob_update as OB

def log(m): print(f"[rp] {m}", flush=True)

OB.login()
cid = OB.channel_id()
NEW = "On Being with Krista Tippett 001-100"
# ①敏感詞檢查
for nm in (NEW, "On Being with Krista Tippett 1-100", "On Being with Krista Tippett"):
    r = OB.req("POST", f"{OB.BASE}/ting/IsBannedWords", data={"words": nm}, timeout=45)
    log(f"IsBannedWords({nm[-10:]!r}): HTTP {r.status_code} {(r.text or '')[:100]}")
# ②min.js 的 UpdatePrivateChannel 呼叫上下文
js = OB.req("GET", "https://my.eudic.net/js/common.min.js", timeout=60).text or ""
for m in list(re.finditer(r"UpdatePrivateChannel", js))[:2]:
    seg = re.sub(r"\s+", " ", js[m.start():m.start()+1100])
    log(f"JS ctx FULL: …{seg}…")
# ③對照組：同名＋新 fid（排除名稱因素）
chans = OB.req("GET", f"{OB.BASE}/ting/GetPrivateChannels", timeout=45).json()
cur = next(c for c in chans["channelList"]["UploadedChannels"] if c["Id"] == cid)
img = OB.channel_cover_bytes(cid)
fid = OB.upload_thumb(img)
import html as H
r = OB.req("POST", f"{OB.BASE}/ting/UpdatePrivateChannel",
           data={"channelId": cid, "name": cur.get("Name"),
                 "thumb": fid,
                 "description": H.unescape(cur.get("Description") or "")}, timeout=60)
log(f"對照組(channelId): HTTP {r.status_code} {(r.text or '')[:120]}")
