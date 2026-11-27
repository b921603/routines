#!/usr/bin/env python3
import os, re, sys
sys.path.insert(0, "podcast")
import ob_update as OB
import ob_face_maint as FM

def log(m): print(f"[zp] {m}", flush=True)

OB.login()
cid = OB.channel_id()
MID = "4bbac3f3-6467-47f9-9011-468186ebb173"   # Zoloth（rv2 取得）
ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={MID}&itemType=0", timeout=45)
log(f"edit page HTTP {ep.status_code} len={len(ep.text or '')}")
info = FM.parse_edit_page(ep.text or "")
log(f"title={(info.get('title') or '')[:56]!r}")
log(f"lrc: {'✓ 已生成（'+str(len(info.get('lrc') or ''))+'B）' if (info.get('lrc') or '').strip() else '✗ 空'}")
sam = re.search(r'name="subtitle_upload_method"[^>]*value="([^"]*)"', ep.text or "")
log(f"subtitle_upload_method={sam.group(1) if sam else '?'}")
bm = None
for pg in range(6):
    rr = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}", timeout=45)
    for b in re.split(r'<div class="dragBox">', rr.text or "")[1:]:
        if MID in b:
            bm = re.search(r'<span class="badge[^"]*">([^<]*)</span>', re.sub(r"\s+", " ", b))
            break
    if bm: break
log(f"清單 badge: {bm.group(1) if bm else '（清單中無此媒體）'}")
