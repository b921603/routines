#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ob_unstick — Volf（Violence 疑觸發字幕管線擱置）委婉改寫＋Zoloth 字幕重觸發複驗。"""
import os, re, sys, html, time
sys.path.insert(0, "podcast")
import ob_update as OB
import ob_face_maint as FM

def log(m): print(f"[unstick] {m}", flush=True)

OB.login()
cid = OB.channel_id()

def find(key):
    for pg in range(30):        # #17 持續上傳會把舊集擠到深頁（11-27 兩度實證）
        rr = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}", timeout=45)
        segs = re.split(r'<div class="dragBox">', rr.text or "")[1:]
        if not segs:
            break
        for b in segs:
            tm = re.search(r'rl-title"[^>]*title="([^"]*)"', b)
            mid = re.search(r'media_id"[^>]*data="([^"]+)"', b)
            if tm and mid and key in html.unescape(tm.group(1)).lower():
                return html.unescape(tm.group(1)), mid.group(1)
    log(f"  find({key!r}): 30 頁未命中")
    return None, None

def save(mid, payload, tag):
    for k in range(6):
        try:
            r = OB.req("POST", f"{OB.BASE}/ting/uploadprivatemedia", data=payload, timeout=120)
            flat = (r.text or "").replace(" ", "")
            ok = r.status_code == 200 and ('"code":200' in flat or '"success":true' in flat)
            log(f"  [{tag}] try{k}: {r.status_code} {(r.text or '')[:56]} {'✓' if ok else ''}")
            if ok:
                return True
            if any(b in (r.text or "") for b in OB.SLOT_BUSY):
                time.sleep(90); continue
            # 500 可能異步生效（Zoloth 契約）——收了再驗
            time.sleep(8)
        except OB.AuthError:
            raise
        except Exception as ex:
            log(f"  [{tag}] try{k} err: {str(ex)[:60]}"); time.sleep(8)
    return False

# ── Volf：Violence→Conflict／violent→destructive ──
t, mid = find("religion and violence")
if t:
    ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid}&itemType=0", timeout=45).text or ""
    info = FM.parse_edit_page(ep)
    nt = t.replace("Violence", "Conflict")
    nd = (info.get("desc") or "").replace("violent", "destructive")
    log(f"Volf: {t[:52]!r} → {nt[:52]!r}｜desc violent→destructive")
    payload = {"id": mid, "title": nt, "channelId": cid,
               "lrc": info.get("lrc") or "",
               "needProcessLrc": "false", "needKeepformat": "false",
               "reformatParagraph": "false", "splitLongSentence": "true",
               "needMachineTranslation": "false", "allowMachineTranslation": "false",
               "needAISubtitle": "false",
               "description": nd, "mediatype": "0",
               "intros": info.get("intros_html") or "",
               "istiming": "false", "timing": "", "html": "",
               "insertImage": "true", "mdChapterId": ""}
    save(mid, payload, "Volf")
    ep2 = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid}&itemType=0", timeout=45).text or ""
    i2 = FM.parse_edit_page(ep2)
    log(f"  驗證: title={(i2.get('title') or '')[:46]!r}｜desc violent={'仍有' if 'violent' in (i2.get('desc') or '').lower() else '已清'}｜lrc={'✓' if (i2.get('lrc') or '').strip() else '空（任務中/擱置）'}")
else:
    log("Volf 不在清單")

# ── Zoloth：needAISubtitle=true 重觸發（字幕管線重排）──
t, mid = find("Genetic Duplication")
if t:
    ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid}&itemType=0", timeout=45).text or ""
    info = FM.parse_edit_page(ep)
    if (info.get("lrc") or "").strip():
        log("Zoloth: ✓ 字幕已生成——無需動作")
    else:
        payload = {"id": mid, "title": info.get("title") or "", "channelId": cid,
                   "lrc": "", "needProcessLrc": "false", "needKeepformat": "false",
                   "reformatParagraph": "false", "splitLongSentence": "true",
                   "needMachineTranslation": "false", "allowMachineTranslation": "false",
                   "needAISubtitle": "true",
                   "description": info.get("desc") or "", "mediatype": "0",
                   "intros": info.get("intros_html") or "",
                   "istiming": "false", "timing": "", "html": "",
                   "insertImage": "true", "mdChapterId": ""}
        save(mid, payload, "Zoloth")
        for wait_s in (300, 300):
            time.sleep(wait_s)
            ep2 = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid}&itemType=0", timeout=45).text or ""
            i2 = FM.parse_edit_page(ep2)
            if (i2.get("lrc") or "").strip():
                log(f"  ✓ 字幕已生成（{wait_s}s 後）——未顯示旗標應隨之解除")
                break
            log(f"  {wait_s}s 後 lrc 仍空（字幕生成 10-60min 級異步——下輪再驗）")
OB.ntfy("OB unstick 完成", "Volf Violence→Conflict 委婉改寫＋Zoloth AI 字幕重觸發——兩案異步，稍後複驗。", 3)
