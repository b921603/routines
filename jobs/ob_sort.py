#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ob_sort — 頻道「拖曳排序」＝依集數日期（用戶 11-27 指定，GA 自動化）。
端點 /ting/OrderPriveteMedia（min.js 實證）：POST form {mediaIds[]: 有序 mids, channelId}
→ success:true。jQuery 的 {mediaIds: [...]} 序列化即 mediaIds[]=，requests 同形。
排序鍵＝標題開頭的 ISO 日期（"2003-10-30 Laurie Zoloth — …"），升冪＝播出順序
（舊→新）；OB_SORT_DESC=1 反轉；無日期前綴排最後。全 OB 輪轉頻道逐一處理。
trail/ob_sort.json 落盤（workflow bot commit）。drain 每班收尾自動重排——
上傳順序是「上傳時間序」，不自排的話公開頻道永遠新上傳在前（＝播出順序倒反）。"""
import os, re, sys
sys.path.insert(0, "podcast")
import ob_update as OB
import ob_face_maint as FM

DESC = os.environ.get("OB_SORT_DESC", "") == "1"

def log(m):
    print(f"[sort] {m}", flush=True)


def date_key(title):
    m = re.match(r"(\d{4}-\d{2}-\d{2})", title or "")
    return (m.group(1) if m else "9999-99-99", title or "")


def sort_channel(cid, name=""):
    eps = FM.list_media(cid)
    if not eps:
        log(f"{name or cid[:8]}: 0 集——跳過")
        return None
    ordered = sorted(eps, key=lambda t: date_key(t[0]), reverse=DESC)
    mids = [mid for _, mid in ordered]
    r = OB.req("POST", f"{OB.BASE}/ting/OrderPriveteMedia",
               data={"mediaIds[]": mids, "channelId": cid}, timeout=120)
    ok = '"success":true' in (r.text or "")
    log(f"{name or cid[:8]}: {len(mids)} 集 POST → HTTP {r.status_code} "
        f"{'✓ success' if ok else (r.text or '')[:90]}")
    log(f"  首集: {ordered[0][0][:56]!r}")
    log(f"  末集: {ordered[-1][0][:56]!r}")
    return {"cid": cid, "name": name, "n": len(mids), "ok": ok,
            "first": ordered[0][0], "last": ordered[-1][0]}


def main():
    OB.login()
    chs = []
    for x in (OB.rj(OB.OBCHS, []) or []):
        if x.get("cid"):
            chs.append((x["cid"], x.get("name") or ""))
    cur = OB.channel_id()
    if not any(c == cur for c, _ in chs):
        chs.append((cur, ""))
    log(f"頻道 {len(chs)} 個（desc={DESC}）")
    results = []
    for cid, name in chs:
        try:
            r = sort_channel(cid, name)
            if r:
                results.append(r)
        except Exception as ex:
            log(f"{cid[:8]} sort err: {str(ex)[:90]}")
    if not results:
        log("無頻道可排——結束")
        return
    ok = all(r["ok"] for r in results)
    OB.wj(os.path.join(OB.TRAIL, "ob_sort.json"),
          {"at": OB.time.strftime("%F %T"), "desc": DESC, "channels": results})
    OB.ntfy(f"OB 頻道排序（依日期）{'✓' if ok else '✗'}",
            "；".join(f"{r.get('name') or r['cid'][:8]} {r['n']} 集" for r in results)
            + "——拖曳排序已寫入，聽眾端為播出順序。", 3 if ok else 4)
    if not ok:
        log("done (exit 1: sort failed)")
        sys.exit(1)
    log("done")


if __name__ == "__main__":
    main()
