#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jobs/diag_display.py — 「未顯示」偵查（11-27 用戶截圖：ting/index 多集顯示 未顯示）。

唯讀。①抓 ting/index 管理清單→逐列定位 顯示狀態（未顯示/正常）＋標題→
與帳本（how＝heal/backfill）對照；②各挑一集 未顯示/正常 → 抓編輯頁全部表單欄位
→ diff 找出「顯示」開關欄位名與值 → 為修復提供契約。
"""
import os, re, sys, json, html
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "podcast"))
import ob_update as OB

def log(m):
    print(f"[disp] {m}", flush=True)


def index_rows():
    """ting/index 管理頁 → [(title, state)]。防禦式解析：以 顯示狀態字串為錨。"""
    r = OB.req("GET", f"{OB.BASE}/ting/index", timeout=45)
    txt = r.text or ""
    rows = []
    for m in re.finditer(r"(未顯示|正常)", txt):
        ctx = txt[max(0, m.start() - 1200):m.start()]
        tm = None
        for tm in re.finditer(r'title="([^"]{8,})"', ctx):
            pass
        title = html.unescape(tm.group(1)) if tm else "?"
        rows.append((title.strip(), m.group(1)))
    return rows, len(txt)


def edit_fields(cid, mid):
    """編輯頁全部表單欄位（input/select/textarea name→value）。"""
    r = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid}&itemType=0",
               timeout=45)
    t = r.text or ""
    fields = {}
    for m in re.finditer(r'<(input|select|textarea)[^>]*>', t):
        tag = m.group(0)
        nm = re.search(r'name="([^"]+)"', tag)
        if not nm:
            continue
        val = re.search(r'value="([^"]*)"', tag)
        checked = 'checked' in tag
        fields[nm.group(1)] = ("CHECKED" if checked else
                               (html.unescape(val.group(1)) if val else ""))
    return fields


def main():
    log("=== 未顯示偵查（唯讀）===")
    OB.login()
    cid = OB.channel_id()
    rows, page_bytes = index_rows()
    log(f"ting/index 頁面 {page_bytes}B，狀態列 {len(rows)} 條")
    led = OB.rj(OB.LEDGER, {}) or {}
    hidden = [t for t, s in rows if s == "未顯示"]
    normal = [t for t, s in rows if s == "正常"]
    log(f"未顯示 {len(hidden)}｜正常 {len(normal)}")
    for t, s in rows[:24]:
        how = next((v.get("how") for k, v in led.items()
                    if OB.norm(v.get("title", "")) and t.lower().startswith(v.get("title", "")[:24].lower())), "?")
        log(f"  [{s}] ({how}) {t[:58]}")
    # 挑樣本：各一集 抓編輯頁 diff
    media = FM_list(cid) if False else None
    def find_mid(title):
        for pg in range(3):
            r = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}",
                       timeout=45)
            for x in re.split(r'<div class="dragBox">', r.text or "")[1:]:
                tm = re.search(r'rl-title"[^>]*title="([^"]*)"', x)
                mid = re.search(r'media_id"[^>]*data="([^"]+)"', x)
                if tm and mid and html.unescape(tm.group(1)).strip() == title.strip():
                    return mid.group(1)
        return None
    for tag, pool in (("未顯示", hidden), ("正常", normal)):
        if not pool:
            continue
        title = pool[0]
        mid = find_mid(title)
        log(f"── 樣本[{tag}] {title[:50]} mid={mid}")
        if not mid:
            log("  mid 未找到——跳過")
            continue
        f = edit_fields(cid, mid)
        log(f"  欄位 {len(f)} 個：")
        for k in sorted(f):
            v = str(f[k])
            if len(v) > 60:
                v = v[:60] + "…"
            log(f"    {k} = {v!r}")
    log("=== 偵查完畢 ===")


if __name__ == "__main__":
    main()
