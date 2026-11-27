#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ob_resub — Zoloth 重觸發 AI 字幕（lrc 空＝未顯示黏滯假說的對症治療）。
Volf 時長偵查（斷判「時長原因」）。字幕已存在者絕不重觸發（face-maint 教訓）。"""
import os, re, sys, html, time
sys.path.insert(0, "podcast")
import ob_update as OB
import ob_face_maint as FM

def log(m): print(f"[resub] {m}", flush=True)

OB.login()
cid = OB.channel_id()

# ── Volf 時長 ──
try:
    r = OB.retry(lambda: OB.requests.get(OB.FEED, headers=OB.UA, timeout=90))
    items = re.findall(r"<item>.*?</item>", r.text or "", re.S)
    for it in items:
        t = re.search(r"<title>(?:<!\[CDATA\[)?([^<\]]+)", it)
        if t and "Volf" in t.group(1):
            d = re.search(r"<itunes:duration>([^<]+)</itunes:duration>", it)
            log(f"Volf: feed title={t.group(1)[:50]!r} duration={d.group(1) if d else '?'}")
            break
    ds = []
    for it in items[:12]:
        d = re.search(r"<itunes:duration>([^<]+)</itunes:duration>", it)
        t = re.search(r"<title>(?:<!\[CDATA\[)?([^<\]]+)", it)
        if d: ds.append(f"{t.group(1)[:26]}={d.group(1)}")
    log(f"近期集時長對照: {ds[:6]}")
except Exception as ex:
    log(f"feed err {str(ex)[:60]}")

# ── Zoloth 重觸發 ──
boxes = []
for pg in range(10):
    rr = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}", timeout=45)
    boxes += re.split(r'<div class="dragBox">', rr.text or "")[1:]
x = next((b for b in boxes if "genetic duplication" in html.unescape(
    (re.search(r'rl-title"[^>]*title="([^"]*)"', b) or re.match(r"$^","")).group(1)).lower()
    if re.search(r'rl-title"', b)), None)
if x is None:
    log("Zoloth 不在清單——exit"); sys.exit(1)
mid = re.search(r'media_id"[^>]*data="([^"]+)"', x).group(1)
ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid}&itemType=0", timeout=45).text or ""
info = FM.parse_edit_page(ep)
if (info.get("lrc") or "").strip():
    log("✓ Zoloth 已有字幕——旗標應自行解除，不重觸發"); sys.exit(0)
log("Zoloth lrc 空——重觸發 AI 字幕（needAISubtitle=true）")
sam = re.search(r'name="subtitle_upload_method"[^>]*value="([^"]*)"', ep)
method = (sam.group(1) if sam else "ai")
log(f"subtitle_upload_method={method!r}")
payload = {"id": mid, "title": info.get("title") or "", "channelId": cid,
           "lrc": "", "needProcessLrc": "false", "needKeepformat": "false",
           "reformatParagraph": "false", "splitLongSentence": "true",
           "needMachineTranslation": "false", "allowMachineTranslation": "false",
           "needAISubtitle": "true", "subtitle_upload_method": method,
           "textAudioMode": (re.search(r'name="text_audio_mode"[^>]*value="([^"]*)"', ep) or
                             re.match(r"$^","")) and (re.search(r'name="text_audio_mode"[^>]*value="([^"]*)"', ep).group(1) if re.search(r'name="text_audio_mode"[^>]*value="([^"]*)"', ep) else "podcast_ai"),
           "description": info.get("desc") or "",
           "mediatype": "0", "intros": info.get("intros_html") or "",
           "istiming": "false", "timing": "", "html": "",
           "insertImage": "true", "mdChapterId": ""}
for k in range(6):
    try:
        r2 = OB.req("POST", f"{OB.BASE}/ting/uploadprivatemedia", data=payload, timeout=120)
        flat = (r2.text or "").replace(" ", "")
        log(f"  try{k}: {r2.status_code} {(r2.text or '')[:70]}")
        if r2.status_code == 200 and ('"code":200' in flat or '"success":true' in flat):
            log("  ✓ 已送出（AI 字幕異步生成中）")
            break
        if any(b in (r2.text or "") for b in OB.SLOT_BUSY):
            log("  busy——wait 90s"); time.sleep(90); continue
        time.sleep(8)
    except OB.AuthError:
        raise
    except Exception as ex:
        log(f"  try{k} err: {str(ex)[:70]}"); time.sleep(8)
# 3 分鐘後查 lrc 是否落地（異步）
time.sleep(180)
ep2 = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid}&itemType=0", timeout=45).text or ""
i2 = FM.parse_edit_page(ep2)
log(f"3min 後 lrc: {'✓ 已生成' if (i2.get('lrc') or '').strip() else '尚未（異步——稍後驗）'}")
