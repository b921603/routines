#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rv_diag2 — Volf 卡處理＋Zoloth 黏滯旗標深挖（唯讀）。
①Volf：feed 時長＋dragBox badge 現況 vs 後發集 ②Zoloth vs 已清集 vs 從未病集：
dragBox 全文 diff＋edit 頁定时显示(timing)欄位＋desc 全文寬譜掃描。"""
import os, re, sys, html
sys.path.insert(0, "podcast")
import ob_update as OB
import ob_face_maint as FM

def log(m): print(f"[rv2] {m}", flush=True)

OB.login()
cid = OB.channel_id()

# feed 時長（Volf）
try:
    r = OB.retry(lambda: OB.requests.get(OB.FEED, headers=OB.UA, timeout=90))
    m = re.search(r"<item>(?:(?!</item>).)*?2005-08-04(?:(?!</item>).)*?"
                  r"<itunes:duration>([^<]+)</itunes:duration>", r.text or "", re.S)
    log(f"Volf feed duration: {m.group(1) if m else '?'}")
except Exception as ex:
    log(f"feed err {str(ex)[:50]}")

boxes = []
for pg in range(10):
    rr = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}", timeout=45)
    boxes += re.split(r'<div class="dragBox">', rr.text or "")[1:]
log(f"listing {len(boxes)}")

PICKS = [
    ("Volf", "religion and violence"),
    ("Zoloth(黏滯)", "genetic duplication"),
    ("Mollenkott(已清?)", "same-sex marriage"),
    ("Pearl(對照)", "spirit of defiance"),
]
fulls = {}
for tag, key in PICKS:
    x = next((b for b in boxes if key in html.unescape(
        (re.search(r'rl-title"[^>]*title="([^"]*)"', b) or re.match(r"$^","")).group(1)).lower()
        if re.search(r'rl-title"', b)), None)
    if x is None:
        log(f"── {tag}: 不在清單"); continue
    tm = re.search(r'rl-title"[^>]*title="([^"]*)"', x)
    mid = re.search(r'media_id"[^>]*data="([^"]+)"', x)
    log(f"── [{tag}] {html.unescape(tm.group(1))[:52]}")
    flat = re.sub(r"\s+", " ", x)
    bm = re.search(r'<span class="badge[^"]*">([^<]*)</span>', flat)
    log(f"    badge: {bm.group(1) if bm else '(無)'}")
    log(f"    box 700B: {flat[:700]}")
    fulls[tag] = flat
    ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid.group(1)}&itemType=0", timeout=45).text or ""
    info = FM.parse_edit_page(ep)
    log(f"    edit: title={(info.get('title') or '')[:44]!r} lrc={'在' if (info.get('lrc') or '').strip() else '空'}")
    for kw in ('istiming', '"timing"'):
        mm = re.search(kw + r'[^>]{0,200}', ep)
        if mm: log(f"    {kw}: …{re.sub(chr(92)+'s+',' ',mm.group(0))[:160]}…")
    jt = re.search(r'(hide-jingting|show-jingting)[^>]*style="([^"]*)"', ep)
    log(f"    定时显示區塊: {jt.group(1) if jt else '?'} style={jt.group(2) if jt else '?'}")
    tmv = re.search(r'name="timing"[^>]*value="([^"]*)"', ep)
    log(f"    timing value: {tmv.group(1) if tmv else '(無)'}")
    d = info.get("desc") or ""
    log(f"    desc {len(d)}B 全文: {d[:520]}")
    wide = ("violence","violent","kill","war","terror","sex","embryo","stem","abortion","mao","gay","clon","武器","暴力")
    hits = [w for w in wide if w in d.lower()]
    log(f"    desc 寬譜: {hits or '無'}")
