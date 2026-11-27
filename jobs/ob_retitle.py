#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jobs/ob_retitle.py — 4 集「未顯示」標題改寫（2026-11-27 用戶明示核准「由你進行」）。

病根＝標題敏感詞（Mao／Gay／Cloning）觸發平台審核→「處理完成但未顯示」。
處置＝**只改 title**（同義委婉語，語義不變）；音檔/字幕/簡介一律不動；
lrc 必帶編輯頁現值（face-maint 教訓：空值會清字幕）；thumb 不帶欄位——
若因此被清，face-maint 泛化裸圖自癒（本件結尾也會即場補）。
逐集驗證：re-fetch 編輯頁 title==新值 才算過。
"""
import os, re, sys, html, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "podcast"))
import ob_update as OB
import ob_face_maint as FM

RULES = [
    (re.compile(r"the Religion of Mao", re.I), "a Turbulent Era"),
    (re.compile(r"\bGay\b"), "Same-Sex"),
    (re.compile(r"\bCloning", re.I), "Genetic Duplication"),
]
TARGET_KEYS = ("mao", "mollenkott", "zoloth")     # 4 集（Mao 兩集）


def log(m):
    print(f"[retitle] {m}", flush=True)


def new_title(t):
    nt = t
    for rx, rep in RULES:
        nt = rx.sub(rep, nt)
    return nt


def listing(cid):
    out = []
    for pg in range(2):
        r = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias"
                         f"?sortby=0&page={pg}&channelId={cid}", timeout=45)
        for x in re.split(r'<div class="dragBox">', r.text or "")[1:]:
            tm = re.search(r'rl-title"[^>]*title="([^"]*)"', x)
            mid = re.search(r'media_id"[^>]*data="([^"]+)"', x)
            if tm and mid:
                out.append((html.unescape(tm.group(1)), mid.group(1)))
    return out


def patch(cid, mid, nt, info):
    """face-maint 實證 payload（media 省略＝沿用原音檔）－thumb 欄位不帶。"""
    payload = {"id": mid, "title": nt, "channelId": cid,
               "lrc": info.get("lrc") or "",
               "needProcessLrc": "false", "needKeepformat": "false",
               "reformatParagraph": "false", "splitLongSentence": "true",
               "needMachineTranslation": "false", "allowMachineTranslation": "false",
               "needAISubtitle": "false",
               "description": info.get("desc") or "",
               "mediatype": "0", "intros": info.get("intros_html") or "",
               "istiming": "false", "timing": "", "html": "",
               "insertImage": "true", "mdChapterId": ""}
    for k in range(6):
        try:
            r = OB.req("POST", f"{OB.BASE}/ting/uploadprivatemedia",
                       data=payload, timeout=120)
            flat = (r.text or "").replace(" ", "")
            if r.status_code == 200 and '"code":200' in flat:
                return True, (r.text or "")[:60]
            if any(b in (r.text or "") for b in OB.SLOT_BUSY):
                log(f"  busy——wait 90s（{k+1}/6）")
                time.sleep(90)
                continue
            log(f"  try{k}: {r.status_code} {(r.text or '')[:70]}")
            time.sleep(8)
        except OB.AuthError:
            raise
        except Exception as ex:
            log(f"  try{k} err: {str(ex)[:70]}")
            time.sleep(8)
    return False, "exhausted"


def main():
    log("=== 未顯示 4 集標題改寫（用戶 11-27 核准）===")
    OB.login()
    cid = OB.channel_id()
    rows = listing(cid)
    log(f"頻道清單 {len(rows)} 條")
    targets = [(t, m) for t, m in rows
               if any(k in t.lower() for k in TARGET_KEYS)]
    log(f"目標 {len(targets)} 集")
    done, failed, thumb_lost = 0, [], []
    for t, mid in targets:
        nt = new_title(t)
        if nt == t:
            log(f"  ⚠ 規則未命中，跳過: {t[:60]}")
            failed.append(t[:40])
            continue
        log(f"  ▸ {t[:64]}")
        log(f"    → {nt[:64]}")
        ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}"
                           f"&mediaid={mid}&itemType=0", timeout=45).text or ""
        info = FM.parse_edit_page(ep)
        ok, msg = patch(cid, mid, nt, info)
        if not ok:
            log(f"    ✗ patch 失敗: {msg}")
            failed.append(t[:40])
            continue
        # 驗證：re-fetch 編輯頁
        ep2 = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}"
                            f"&mediaid={mid}&itemType=0", timeout=45).text or ""
        info2 = FM.parse_edit_page(ep2)
        got = (info2.get("title") or "").strip()
        if got == nt.strip():
            done += 1
            lrc_ok = bool((info2.get("lrc") or "").strip())
            th = info2.get("thumb_data_src") or ""
            th_bad = (not th) or ("default" in th)
            log(f"    ✓ 已改寫＋驗證｜字幕現值 {'在' if lrc_ok else '⚠空'}｜"
                f"縮圖 {'⚠被清' if th_bad else '在'}")
            if th_bad:
                thumb_lost.append(mid)
        else:
            log(f"    ✗ 驗證失敗：現值={got[:50]!r}")
            failed.append(t[:40])
        time.sleep(3)
    if thumb_lost:
        log(f"── {len(thumb_lost)} 集縮圖被清→即場裸圖自癒 ──")
        try:
            FM.patch_zombie_thumbs(cid)
        except Exception as ex:
            log(f"  自癒 err（下輪 face-maint 再補）: {str(ex)[:60]}")
    log(f"=== 完成：{done}/{len(targets)} 改寫｜失敗 {len(failed)} ===")
    OB.ntfy("OB 未顯示 4 集：標題改寫完成" if not failed else
            "OB 標題改寫：部分失敗",
            f"{done}/{len(targets)} 已改寫＋驗證（音檔/字幕/簡介未動）。"
            f"\n平台重審為異步——請稍後在 ting/index 刷新查看是否轉「正常」。"
            + (f"\n失敗: {failed}" if failed else ""), 3 if not failed else 4)


if __name__ == "__main__":
    main()
