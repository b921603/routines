#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ev_probe — Evangelical 7 連鑑識（dups 還是 parts？）＋Volf/Zoloth 現況。"""
import os, re, sys, json, html
sys.path.insert(0, "podcast")
import ob_update as OB
import ob_face_maint as FM

def log(m): print(f"[ev] {m}", flush=True)

OB.login()
cid = OB.channel_id()
boxes = []
for pg in range(3):
    rr = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}", timeout=45)
    boxes += re.split(r'<div class="dragBox">', rr.text or "")[1:]
log(f"listing {len(boxes)}")
evs = []
for b in boxes:
    tm = re.search(r'rl-title"[^>]*title="([^"]*)"', b)
    mid = re.search(r'media_id"[^>]*data="([^"]+)"', b)
    if tm and mid and "evangelic" in html.unescape(tm.group(1)).lower():
        bm = re.search(r'<span class="badge[^"]*">([^<]*)</span>', re.sub(r"\s+", " ", b))
        evs.append((html.unescape(tm.group(1)), mid.group(1), bm.group(1) if bm else "?"))
log(f"Evangelical 條目 {len(evs)}：")
for t, m, bd in evs:
    log(f"  [{bd}] {t!r}")
    log(f"      mid={m}")
# ledger 該 guid
led = OB.rj(OB.LEDGER, {}) or {}
for g, v in led.items():
    if "evangelic" in v.get("title", "").lower():
        log(f"帳本: guid={g[:20]}… title={v.get('title','')[:48]!r} how={v.get('how')} mids={len(v.get('mids', []))} 個")
# Volf / Zoloth 現況
for tag, key in (("Volf", "religion and violen"), ("Zoloth", "genetic duplication")):
    b = next((b for b in boxes if key in html.unescape(
        (re.search(r'rl-title"[^>]*title="([^"]*)"', b) or re.match(r"$^","")).group(1)).lower()
        if re.search(r'rl-title"', b)), None)
    if b is None:
        log(f"{tag}: 不在清單"); continue
    tm = re.search(r'rl-title"[^>]*title="([^"]*)"', b)
    mid = re.search(r'media_id"[^>]*data="([^"]+)"', b)
    bm = re.search(r'<span class="badge[^"]*">([^<]*)</span>', re.sub(r"\s+", " ", b))
    ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid.group(1)}&itemType=0", timeout=45).text or ""
    info = FM.parse_edit_page(ep)
    log(f"{tag}: badge={bm.group(1) if bm else '?'} lrc={'✓' if (info.get('lrc') or '').strip() else '✗空'} title={(info.get('title') or '')[:40]!r}")
