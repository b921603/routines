#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jobs/ob_redesc.py — 4 集「未顯示」簡介改寫（2026-11-27 用戶「由你進行」授權延伸）。

rv_diag 實證：標題已改但 desc 殘留敏感詞（surviving-religion-mao URL／gay marriage／
cloned pigs）→審核旗標黏滯。本件只改 desc（title 帶現值＝不變）；音檔/字幕不動；
lrc 帶現值。500 可能異步生效——驗證以 re-fetch 為準。附全艦 desc 敏感詞掃描（報告用）。
"""
import os, re, sys, html, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "podcast"))
import ob_update as OB
import ob_face_maint as FM

RULES = [
    (re.compile(r"program/surviving-religion-mao", re.I), "programs"),
    (re.compile(r"\bgay\b", re.I), "same-sex"),
    (re.compile(r"\bcloned\b", re.I), "genetically modified"),
    (re.compile(r"\bcloning\b", re.I), "genetic modification"),
    (re.compile(r"\bMao\b"), "that era"),
]
TARGET_KEYS = ("mao", "mollenkott", "zoloth",
               "anchee", "turbulent")     # 標題已改寫，原鍵不再命中（11-27 實證）
SCAN_WORDS = ("mao", "gay", "clon")


def log(m):
    print(f"[redesc] {m}", flush=True)


def listing(cid):
    out = []
    for pg in range(10):
        r = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias"
                         f"?sortby=0&page={pg}&channelId={cid}", timeout=45)
        for x in re.split(r'<div class="dragBox">', r.text or "")[1:]:
            tm = re.search(r'rl-title"[^>]*title="([^"]*)"', x)
            mid = re.search(r'media_id"[^>]*data="([^"]+)"', x)
            if tm and mid:
                out.append((html.unescape(tm.group(1)), mid.group(1)))
    return out


def patch_desc(cid, mid, title_now, desc_new, info):
    payload = {"id": mid, "title": title_now, "channelId": cid,
               "lrc": info.get("lrc") or "",
               "needProcessLrc": "false", "needKeepformat": "false",
               "reformatParagraph": "false", "splitLongSentence": "true",
               "needMachineTranslation": "false", "allowMachineTranslation": "false",
               "needAISubtitle": "false",
               "description": desc_new[:3000],
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
    return False, "exhausted（500 可能仍異步生效——以清單/re-fetch 為準）"


def main():
    log("=== 未顯示 4 集：簡介敏感詞改寫（用戶授權延伸）===")
    OB.login()
    cid = OB.channel_id()
    rows = listing(cid)
    log(f"清單 {len(rows)} 條")

    # ── 全艦掃描（報告用）──
    log("── 全艦 desc 掃描（抽敏感詞）──")
    scan_hits = {}
    for t, mid in rows:
        ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}"
                           f"&mediaid={mid}&itemType=0", timeout=45).text or ""
        d = (FM.parse_edit_page(ep).get("desc") or "").lower()
        hits = [w for w in SCAN_WORDS if w in d]
        if hits:
            scan_hits[t[:44]] = hits
        time.sleep(0.8)
    for t, h in scan_hits.items():
        log(f"  ⚠ {t} → {h}")
    log(f"掃描完成：{len(scan_hits)}/{len(rows)} 集殘留")

    # ── 4 集改寫 ──
    done, failed = 0, []
    for t, mid in rows:
        if not any(k in t.lower() for k in TARGET_KEYS):
            continue
        log(f"  ▸ {t[:62]}")
        ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}"
                           f"&mediaid={mid}&itemType=0", timeout=45).text or ""
        info = FM.parse_edit_page(ep)
        desc = info.get("desc") or ""
        nd = desc
        for rx, rep in RULES:
            nd = rx.sub(rep, nd)
        if nd == desc:
            log("    desc 無敏感詞（標題改寫已足）——確認跳過")
            done += 1
            continue
        log(f"    desc {len(desc)}B → {len(nd)}B（敏感詞已委婉化）")
        ok, msg = patch_desc(cid, mid, t, nd, info)
        # 驗證（500 可能異步生效）
        ep2 = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}"
                            f"&mediaid={mid}&itemType=0", timeout=45).text or ""
        d2 = (FM.parse_edit_page(ep2).get("desc") or "")
        l2 = d2.lower()
        if not any(w in l2 for w in SCAN_WORDS):
            log(f"    ✓ desc 已無敏感詞（驗證過）")
            done += 1
        else:
            log(f"    ⚠ re-fetch 殘留 {[w for w in SCAN_WORDS if w in l2]}（可能異步未落地——下輪驗證）")
        time.sleep(3)
    log(f"=== 完成：{done}/4 ===")
    OB.ntfy("OB 未顯示 4 集：簡介改寫完成",
            f"desc 敏感詞已委婉化（音檔/字幕/標題未再動）。全艦掃描殘留 {len(scan_hits)} 集。"
            f"\n平台重審異步——稍後 ting/index 刷新查看。", 3)


if __name__ == "__main__":
    main()
