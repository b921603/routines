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
    # 優先猜測：管理清單＝GetPrivateMedias dragBox 本體（dragList.js 共用渲染）
    r = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page=0&channelId={cid}",
               timeout=45)
    if "未顯示" in (r.text or ""):
        log("★ GetPrivateMedias dragBox 內含狀態字！")
        boxes = re.split(r'<div class="dragBox">', r.text or "")[1:]
        log(f"dragBox {len(boxes)} 個；首盒全文：")
        log(boxes[0][:1600])
        rows = parse_rows(r.text)
        hidden = [t for t, s in rows if s == "未顯示"]
        normal = [t for t, s in rows if s == "正常"]
        log(f"列 {len(rows)}：未顯示 {len(hidden)}｜正常 {len(normal)}")
        led = OB.rj(OB.LEDGER, {}) or {}

        def how_of(t):
            for v in led.values():
                tt = v.get("title", "")
                if tt and t.lower().startswith(tt.lower()[:20]):
                    return v.get("how")
            return "?"

        for t, s in rows[:20]:
            log(f"  [{s}] ({how_of(t)}) {t[:56]}")

        def find_mid(title):
            for x in boxes:
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
            log(f"── 樣本[{tag}] mid={mid} {title[:50]}")
            if not mid:
                continue
            f = edit_fields(cid, mid)
            for k in sorted(f):
                log(f"    {k} = {f[k]!r}")
        log("=== 偵查完畢 ===")
        return
    log("dragBox 無狀態字——退回端點探險")
    method, path, body = probe_endpoints()
    if not body:
        log("!! 常見端點都沒中——下一步：抓殼引用的 JS 檔找真正的 XHR 路徑")
        for u in sorted(clues):
            if u.endswith(".js"):
                url = u if u.startswith("http") else f"{OB.BASE}{u}"
                try:
                    j = OB.retry(lambda: OB.requests.get(url, headers=OB.UA, timeout=60))
                    js = j.text or ""
                    if "未顯示" in js:
                        i = js.index("未顯示")
                        log(f"  ★ JS 含狀態字：{url[:80]}")
                        log(f"    上下文: …{js[max(0,i-300):i+200]}…")
                except Exception as ex:
                    log(f"  js fetch err {str(ex)[:50]}")
        return
    rows = parse_rows(body)
    hidden = [t for t, s in rows if s == "未顯示"]
    normal = [t for t, s in rows if s == "正常"]
    log(f"端點 {method} {path}｜列 {len(rows)}：未顯示 {len(hidden)}｜正常 {len(normal)}")
    led = OB.rj(OB.LEDGER, {}) or {}

    def how_of(t):
        for v in led.values():
            tt = v.get("title", "")
            if tt and t.lower().startswith(tt.lower()[:20]):
                return v.get("how")
        return "?"

    for t, s in rows[:20]:
        log(f"  [{s}] ({how_of(t)}) {t[:56]}")

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
        log(f"── 樣本[{tag}] mid={mid} {title[:50]}")
        if not mid:
            continue
        f = edit_fields(cid, mid)
        for k in sorted(f):
            log(f"    {k} = {f[k]!r}")
    log("=== 偵查完畢 ===")


if __name__ == "__main__":
    main()
