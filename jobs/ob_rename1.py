#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ob_rename1 — 第一頻改「On Being with Krista Tippett 001-100」（用戶核准，
與輪轉命名視覺一致）。UpdatePrivateChannel 全欄位保留僅改 Name；覆蓋自動驗證。"""
import json, re, sys
sys.path.insert(0, "podcast")
import ob_update as OB

NEW = "On Being with Krista Tippett 001-100"

def log(m): print(f"[rn] {m}", flush=True)

OB.login()
chans = OB.req("GET", f"{OB.BASE}/ting/GetPrivateChannels", timeout=45).json()
lst = (chans.get("channelList", {}).get("UploadedChannels") or [])
cur = next((c for c in lst if c.get("Id") == OB.channel_id()), None)
if not cur:
    log("✗ 找不到現役頻道"); sys.exit(1)
log(f"現名: {cur.get('Name')!r}  thumb={cur.get('Thumb')!r}")
if cur.get("Name") == NEW:
    log("已是目標名——僅同步登記簿")
else:
    r = OB.req("POST", f"{OB.BASE}/ting/UpdatePrivateChannel",
               data={"id": cur["Id"], "name": NEW,
                     "thumb": cur.get("Thumb") or "",
                     "channelType": cur.get("ChannelType") or "",
                     "description": cur.get("Description") or ""}, timeout=60)
    ok = '"success":true' in (r.text or "").replace(" ", "")
    log(f"UpdatePrivateChannel: HTTP {r.status_code} {ok}")
    if not ok:
        sys.exit(1)
chans2 = OB.req("GET", f"{OB.BASE}/ting/GetPrivateChannels", timeout=45).json()
c2 = next((c for c in chans2["channelList"]["UploadedChannels"] if c["Id"] == cur["Id"]), {})
log(f"驗證名: {c2.get('Name')!r}")
log(f"驗證 thumb: {c2.get('Thumb')!r}")
if c2.get("Name") != NEW:
    sys.exit(1)
reg = OB.rj(OB.OBCHS, []) or []
for x in reg:
    if x.get("cid") == cur["Id"]:
        x["name"] = NEW
OB.wj(OB.OBCHS, reg)
OB.wj(OB.CHFILE, {"cid": cur["Id"], "name": NEW, "at": OB.time.strftime("%F %T")})
log("登記簿＋CHFILE 同步 ✓")
