#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vip_probe — ①drain-era 新上傳集的 lrc 現況（VIP 是否仍在）②Zoloth edit 頁
AI radio 的 disabled/vip 鎖形狀③Volf 現況。"""
import os, re, sys, html
sys.path.insert(0, "podcast")
import ob_update as OB
import ob_face_maint as FM

def log(m): print(f"[vip] {m}", flush=True)

OB.login()
cid = OB.channel_id()

# 清單前 12 條（= 最新上傳，drain-era）
boxes = []
for pg in range(2):
    rr = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}", timeout=45)
    boxes += re.split(r'<div class="dragBox">', rr.text or "")[1:]
log(f"listing {len(boxes)}（前 12 條 = 最新）")
for b in boxes[:12]:
    tm = re.search(r'rl-title"[^>]*title="([^"]*)"', b)
    mid = re.search(r'media_id"[^>]*data="([^"]+)"', b)
    if not (tm and mid):
        continue
    title = html.unescape(tm.group(1))
    ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid.group(1)}&itemType=0", timeout=45).text or ""
    info = FM.parse_edit_page(ep)
    lrc = "✓" if (info.get("lrc") or "").strip() else "✗空"
    log(f"  lrc={lrc}｜{title[:52]}")
# Zoloth edit 頁的 AI radio 形狀
MID = "4bbac3f3-6467-47f9-9011-468186ebb173"
ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={MID}&itemType=0", timeout=45).text or ""
for pat in (r'<input[^>]*allowAISubtitle[^>]*>', r'class="[^"]*subAI[^"]*"[^>]*>',
            r'class="vipText[^"]*"[^>]*>'):
    for m in list(re.finditer(pat, ep))[:2]:
        log(f"AI radio/鎖: {re.sub(r'\\s+', ' ', m.group(0))[:200]}")
dis = re.search(r'allowAISubtitle"[^>]*disabled', ep)
log(f"AI radio disabled: {'是——VIP 閘門鎖' if dis else '否（可選）'}")
