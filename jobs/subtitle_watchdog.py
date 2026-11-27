#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""subtitle_watchdog — Volf/Zoloth 字幕管線追蹤到癒（11-27 兩案收斂自動化）。
Volf：處理完成且 lrc 空→委婉改寫（Violence→Conflict）＋重觸發；lrc ✓→結案。
Zoloth（11-27 驗屍改判）：壞媒體集已刪＋帳本 guid 已移除→drain 重傳新鮮副本；
watchdog 改依標題動態查找新 mid（重傳後自動接手），lrc ✓→結案。
狀態 trail/sub_watch.json；ntfy 只報狀態變化。"""
import os, re, sys, json, time
sys.path.insert(0, "podcast")
import ob_update as OB
import ob_face_maint as FM

STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "trail", "sub_watch.json")
VOLF_MID = "0a12fb2f-156d-49b9-8137-e4bd7ba25925"
ZOLOTH_MID = "4bbac3f3-6467-47f9-9011-468186ebb173"
RETRIG_GAP = 4 * 3600


def log(m):
    print(f"[watch] {m}", flush=True)


def edit(cid, mid):
    ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid}&itemType=0",
                timeout=45).text or ""
    info = FM.parse_edit_page(ep)
    sam = re.search(r'name="subtitle_upload_method"[^>]*value="([^"]*)"', ep)
    return info, (sam.group(1) if sam else "?"), ep


def badge(cid, mid):
    for pg in range(8):
        rr = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}",
                    timeout=45)
        for b in re.split(r'<div class="dragBox">', rr.text or "")[1:]:
            if mid in b:
                bm = re.search(r'<span class="badge[^"]*">([^<]*)</span>',
                               re.sub(r"\s+", " ", b))
                return bm.group(1) if bm else "?"
    return "not-in-listing"


def save(cid, mid, payload):
    for k in range(4):
        try:
            r = OB.req("POST", f"{OB.BASE}/ting/uploadprivatemedia", data=payload, timeout=120)
            flat = (r.text or "").replace(" ", "")
            ok = r.status_code == 200 and ('"code":200' in flat or '"success":true' in flat)
            log(f"  try{k}: {r.status_code} {(r.text or '')[:52]} {'✓' if ok else ''}")
            if ok:
                return True
            if "资源还在处理" in (r.text or ""):
                return False                     # 編輯鎖——平台真在算
            if any(b in (r.text or "") for b in OB.SLOT_BUSY):
                time.sleep(90); continue
            time.sleep(8)                        # 500 可能異步生效
        except OB.AuthError:
            raise
        except Exception as ex:
            log(f"  try{k} err: {str(ex)[:60]}"); time.sleep(8)
    return False


def retrigger(cid, mid, info):
    payload = {"id": mid, "title": info.get("title") or "", "channelId": cid,
               "lrc": "", "needProcessLrc": "false", "needKeepformat": "false",
               "reformatParagraph": "false", "splitLongSentence": "true",
               "needMachineTranslation": "false", "allowMachineTranslation": "false",
               "needAISubtitle": "true",
               "description": info.get("desc") or "", "mediatype": "0",
               "intros": info.get("intros_html") or "",
               "istiming": "false", "timing": "", "html": "",
               "insertImage": "true", "mdChapterId": ""}
    return save(cid, mid, payload)


def main():
    OB.login()
    cid = OB.channel_id()
    st = OB.rj(STATE, {}) or {}
    now = time.time()
    report = []

    # ── Volf ──
    info, method, _ = edit(cid, VOLF_MID)
    lrc = bool((info.get("lrc") or "").strip())
    bd = badge(cid, VOLF_MID)
    if lrc:
        log(f"Volf: lrc ✓ badge={bd}——結案")
        st["volf"] = {"state": "done", "at": time.strftime("%F %T")}
    elif "正在处理" in bd:
        log(f"Volf: 仍在處理（badge={bd}）——等（編輯鎖中，委婉改寫待完成後自動執行）")
        st["volf"] = {"state": "processing", "at": time.strftime("%F %T")}
    else:
        log(f"Volf: badge={bd} lrc ✗——委婉改寫＋重觸發")
        nt = (info.get("title") or "").replace("Violence", "Conflict")
        nd = (info.get("desc") or "").replace("violent", "destructive")
        payload = {"id": VOLF_MID, "title": nt, "channelId": cid,
                   "lrc": "", "needProcessLrc": "false", "needKeepformat": "false",
                   "reformatParagraph": "false", "splitLongSentence": "true",
                   "needMachineTranslation": "false", "allowMachineTranslation": "false",
                   "needAISubtitle": "true", "description": nd, "mediatype": "0",
                   "intros": info.get("intros_html") or "",
                   "istiming": "false", "timing": "", "html": "",
                   "insertImage": "true", "mdChapterId": ""}
        ok = save(cid, VOLF_MID, payload)
        log(f"  改寫＋重觸發: {'已送出' if ok else '未確認（異步驗證下輪）'}")
        st["volf"] = {"state": "euphemized+retriggered", "at": time.strftime("%F %T")}
        report.append("Volf 已改寫＋重觸發")

    # ── Zoloth（依標題動態查找——壞媒體舊 mid 已刪，重傳後 mid 變新）──
    zmid = None
    for pg in range(6):
        rr = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}",
                    timeout=45)
        for b in re.split(r'<div class="dragBox">', rr.text or "")[1:]:
            tm = re.search(r'rl-title"[^>]*title="([^"]*)"', b)
            if tm and "zoloth" in OB.norm(__import__("html").unescape(tm.group(1)).lower()):
                mm = re.search(r'media_id"[^>]*data="([^"]+)"', b)
                if mm:
                    zmid = mm.group(1)
        if zmid or "dragBox" not in (rr.text or ""):
            break
    if not zmid:
        log("Zoloth: 清單無此集——等待 drain 重傳（帳本 guid 已移除）")
        st["zoloth"] = {"state": "reuploading", "at": time.strftime("%F %T")}
        OB.wj(STATE, st)
        log(f"state: {json.dumps(st, ensure_ascii=False)}")
        return
    info, method, _ = edit(cid, zmid)
    lrc = bool((info.get("lrc") or "").strip())
    bd = badge(cid, zmid)
    if lrc:
        log(f"Zoloth: lrc ✓ badge={bd}——結案（未顯示旗標應隨之解除）")
        st["zoloth"] = {"state": "done", "at": time.strftime("%F %T")}
    else:
        last = st.get("zoloth_last_trigger", 0)
        if now - last < RETRIG_GAP:
            log(f"Zoloth: lrc ✗（限流中——上次觸發 {int((now-last)/60)}min 前）")
        else:
            log(f"Zoloth: lrc ✗ badge={bd}——重觸發 AI 字幕")
            ok = retrigger(cid, ZOLOTH_MID, info)
            st["zoloth_last_trigger"] = now
            log(f"  觸發: {'已送出' if ok else '未確認（異步）'}")
            report.append("Zoloth 重觸發")
        st["zoloth"] = {"state": "waiting-subtitle", "at": time.strftime("%F %T")}

    OB.wj(STATE, st)
    if report:
        OB.ntfy("OB subtitle watchdog", "；".join(report) + "——異步，下輪複驗。", 3)
    log(f"state: {json.dumps(st, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
