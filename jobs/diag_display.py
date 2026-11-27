#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jobs/diag_display.py v3 — 「未顯示」偵查。ting/index 是 JS 殼→
①挖殼線索（script/端點字串）②形狀探險試管理清單端點③找到含狀態的端點後
解析列＋挑未顯示/正常各一集抓編輯頁欄位 diff。唯讀。"""
import os, re, sys, html
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "podcast"))
import ob_update as OB


def log(m):
    print(f"[disp] {m}", flush=True)


def shell_clues():
    r = OB.req("GET", f"{OB.BASE}/ting/index", timeout=45)
    txt = r.text or ""
    clues = set()
    for m in re.finditer(r'(?:src|href)=["\']([^"\']+)["\']', txt):
        u = m.group(1)
        if ".js" in u:
            clues.add(u)
    for m in re.finditer(r'["\']([^"\']*(?:ting|Media|media|List|list|upload)[^"\']*)["\']', txt):
        u = m.group(1)
        if "/" in u and len(u) < 90 and not u.startswith("#"):
            clues.add(u)
    return clues, txt


def probe_endpoints():
    cands = [
        ("GET", "/ting/GetUploadList"), ("GET", "/ting/getmedialist"),
        ("GET", "/ting/GetPrivateMedias?page=0"), ("POST", "/ting/GetMyUpload"),
        ("GET", "/ting/myupload"), ("GET", "/ting/index/list"),
        ("POST", "/ting/GetMediaList"), ("GET", "/Ting/GetUploadedList"),
    ]
    for method, path in cands:
        try:
            r = OB.req(method, f"{OB.BASE}{path}",
                       data="" if method == "POST" else None, timeout=30)
            body = r.text or ""
            mark = ("未顯示" in body) or ("正常" in body)
            log(f"  probe {method} {path}: {r.status_code} len={len(body)} 狀態字={mark}")
            if mark:
                return method, path, body
        except Exception as ex:
            log(f"  probe {method} {path}: err {str(ex)[:60]}")
    return None, None, None


def parse_rows(body):
    rows = []
    for m in re.finditer(r"(未顯示|正常)", body):
        ctx = body[max(0, m.start() - 1500):m.start()]
        tm = None
        for tm in re.finditer(r'title="([^"]{8,})"', ctx):
            pass
        t2 = re.findall(r'>([^<>]{12,})<', ctx)
        title = html.unescape(tm.group(1)) if tm else (t2[-1].strip() if t2 else "?")
        rows.append((title.strip(), m.group(1)))
    return rows


def edit_fields(cid, mid):
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
        fields[nm.group(1)] = ("CHECKED" if "checked" in tag else
                               (html.unescape(val.group(1))[:80] if val else ""))
    return fields


def main():
    log("=== 未顯示偵查 v3（唯讀）===")
    OB.login()
    cid = OB.channel_id()
    clues, shell = shell_clues()
    log(f"殼 {len(shell)}B｜線索 {len(clues)} 條：")
    for c in sorted(clues)[:20]:
        log(f"    {c[:88]}")
    # ── 主偵查：頻道清單 vs 審核假說 ──
    boxes = []
    for pg in range(2):
        r = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}",
                   timeout=45)
        boxes += re.split(r'<div class="dragBox">', r.text or "")[1:]
    log(f"頻道清單 dragBox 共 {len(boxes)} 盒")
    suspects = ["Surviving the Religion of Mao", "Gay", "[Unedited]",
                "Cloning", "Laurie Zoloth"]
    log("── 截圖中『未顯示』樣本是否在頻道清單？──")
    for s_ in suspects:
        hit = next((x for x in boxes if s_.lower() in html.unescape(
            (re.search(r'rl-title"[^>]*title="([^"]*)"', x) or re.match(r"$^","")).group(1)).lower()
            if re.search(r'rl-title"', x)), None)
        if hit is not None and s_ == "[Unedited]":
            tm = re.search(r'rl-title"[^>]*title="([^"]*)"', hit)
            log(f"  {s_!r}: 有（{html.unescape(tm.group(1))[:44] if tm else '?'})")
        elif hit is not None:
            tm = re.search(r'rl-title"[^>]*title="([^"]*)"', hit)
            log(f"  {s_!r}: 有（{html.unescape(tm.group(1))[:44] if tm else '?'}）")
        else:
            log(f"  {s_!r}: ✗ 不在頻道清單")
    log("── 首盒完整標記（找 hidden/audit/isShow 痕跡）──")
    if boxes:
        b0 = boxes[0]
        b0s = re.sub(r"\s+", " ", b0)
        for kw in ("hide", "audit", "isShow", "isshow", "display", "未顯示", "正常", "no-cover"):
            if kw.lower() in b0s.lower():
                i = b0s.lower().index(kw.lower())
                log(f"  {kw!r} @ …{b0s[max(0,i-120):i+160]}…")
        log(f"  首盒 400B: {b0s[:400]}")
    # 截圖比對：用 led 統計上傳時間窗
    log("── JS 轉義字串與 ajax url ──")
    for u in sorted(clues):
        if not u.endswith(".js"):
            continue
        url = u if u.startswith("http") else f"{OB.BASE}{u}"
        try:
            j = OB.retry(lambda: OB.requests.get(url, headers=OB.UA, timeout=60))
            js = j.text or ""
            for esc in ("\\u672a\\u663e\\u793a", "未顯示", "GetPrivateMedias", "GetMediaList"):
                if esc.lower() in js.lower():
                    i = js.lower().index(esc.lower())
                    log(f"  ★ {u[:40]} 含 {esc!r} @ …{js[max(0,i-200):i+240]}…")
                    break
        except Exception as ex:
            log(f"  js err {str(ex)[:50]}")
    # 編輯頁樣本：找一個 Mao 標題（若在清單）
    def fields_of(pred, tag):
        x = next((x for x in boxes if pred(x.lower())), None)
        if not x:
            log(f"  （{tag} 樣本不在清單）")
            return {}
        tm = re.search(r'rl-title"[^>]*title="([^"]*)"', x)
        mid = re.search(r'media_id"[^>]*data="([^"]+)"', x)
        if not (tm and mid):
            return {}
        log(f"  [{tag}] {html.unescape(tm.group(1))[:52]}")
        return edit_fields(cid, mid.group(1))

    fh = fields_of(lambda x: "mao" in x, "未顯示")
    fn = fields_of(lambda x: "spirit of defiance" in x, "正常")
    keys = sorted(set(fh) | set(fn))
    log("── 編輯頁欄位 diff（未顯示 vs 正常）──")
    for k in keys:
        a, b = fh.get(k, "<缺>"), fn.get(k, "<缺>")
        if a != b:
            log(f"    {k}: 未顯示={a!r} | 正常={b!r}")
    # JS 轉義字串
    try:
        j = OB.retry(lambda: OB.requests.get(f"{OB.BASE}/js/common.min.js",
                                             headers=OB.UA, timeout=60))
        js = j.text or ""
        log(f"common.min.js {len(js)}B")
        for esc in ("\\u672a\\u663e\\u793a", "\\u6b63\\u5e38",
                    "GetPrivateMedias", "studyList"):
            for m in re.finditer(re.escape(esc), js, re.I):
                i = m.start()
                log(f"  ★ {esc!r} @ …{js[max(0, i-260):i+260]}…")
                break
    except Exception as ex:
        log(f"  common.min.js err: {str(ex)[:60]}")
    log("=== 偵查完畢 ===")
    return


if __name__ == "__main__":
    main()
