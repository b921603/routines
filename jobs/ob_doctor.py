#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jobs/ob_doctor.py — On Being 封面體檢（2026-11-27 用戶回報「分組/頻道/episode 封面
依然沒處理好」）。三層診斷＋DOCTOR_FIX=1 修復：

  頻道層   Thumb 實值形狀（empty/default/url/fid）＋修復模式強制重設（RSS art→fid→Update）
  分組層   四策展分組 Thumb 形狀；修復模式＝thumb 單獨強制 fid 重設（set_group_desc 的
           「desc 已新即跳過」會漏掉 thumb 壞掉的情況——本件補洞）
  各集層   每註冊頻道 audit 缺封面數＋裸圖樣本；修復模式＝patch_zombie_thumbs（泛化版
           補任何裸圖）

唯讀預設；修復需明確 DOCTOR_FIX=1（ob-doctor.yml 的 fix input）。報告落
trail/ob-doctor.json（workflow 收尾 commit）＋ntfy。
"""
import os, sys, time, json
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "podcast"))   # ob_update／ob_face_maint
sys.path.insert(0, _HERE)
import ob_update as OB
import ob_face_maint as FM

FIX = os.environ.get("DOCTOR_FIX") == "1"
CURATED = {"9007fbda": "TFF", "de9abbba": "HTF", "87c5aed8": "BWK"}


def shape(t):
    t = (t or "").strip()
    if not t:
        return "empty"
    if "default" in t:
        return "default"
    if t.startswith("http"):
        return "url"
    return "fid"


def log(m):
    print(f"[doctor] {m}", flush=True)


def get_chs():
    return OB.req("GET", f"{OB.BASE}/ting/GetPrivateChannels", timeout=45) \
        .json().get("channelList", {}).get("UploadedChannels", [])


def get_grps():
    return OB.req("POST", f"{OB.BASE}/ting/GetPrivateGroups?withDefault=false",
                  data="", timeout=40).json() \
        .get("channelList", {}).get("UploadedChannels", [])


def art_fid():
    art = OB.feed_channel_art()
    return OB.upload_thumb(art) if art else None


def force_channel_cover(ch):
    """頻道封面強制重設（與 ensure_channel_cover 同形狀，但無 skip 檢查）。"""
    fid = art_fid()
    if not fid:
        log("  channel fix: feed art 不可得——跳過（下輪再試）")
        return False
    r = OB.req("POST", f"{OB.BASE}/ting/UpdatePrivateChannel",
               data={"id": ch["Id"], "name": ch.get("Name") or "",
                     "thumb": fid, "channelType": ch.get("ChannelType") or "",
                     "description": ch.get("Description") or ""}, timeout=60)
    ok = r.status_code == 200 and '"success":false' not in (r.text or "")
    after = next((c for c in get_chs() if c.get("Id") == ch["Id"]), {})
    log(f"  channel fix: {r.status_code} {(r.text or '')[:50]} | thumb after={shape(after.get('Thumb'))}")
    return ok


def force_group_thumb(grp):
    """分組 thumb 單獨重設（desc 原樣保留；三段教訓：只有 fid 形狀合法）。"""
    fid = art_fid()
    if not fid:
        log("  group fix: art fid 不可得——跳過")
        return False
    gid, name = grp["Id"], grp.get("Name") or ""
    ctype = grp.get("ChannelType") or "2"
    desc = grp.get("Description") or ""
    for shape_key in ("id", "channelId"):
        data = {shape_key: gid, "name": name, "channelType": ctype,
                "description": desc, "thumb": fid}
        r = OB.req("POST", f"{OB.BASE}/ting/UpdatePrivateChannel?itemtype=7",
                   data=data, timeout=60)
        after = next((c for c in get_grps() if c.get("Id") == gid), {})
        ok = r.status_code == 200 and '"success":false' not in (r.text or "") \
            and shape(after.get("Thumb")) not in ("empty", "default")
        log(f"  group fix[{name[:20]}] ({shape_key}): {r.status_code} "
            f"{(r.text or '')[:44]} | thumb after={shape(after.get('Thumb'))}")
        if ok:
            return True
    return False


def main():
    log(f"=== OB 封面體檢（fix={FIX}）===")
    OB.login()
    rep = {"at": time.strftime("%F %T"), "fix": FIX,
           "channels": [], "groups": [], "episodes": []}

    cid_now = OB.channel_id()
    reg = [r.get("cid") for r in (OB.rj(OB.OBCHS, []) or []) if r.get("cid")]
    cids = list(dict.fromkeys(([cid_now] if cid_now else []) + reg))

    # ── 頻道層 ──
    chs = get_chs()
    log("── 頻道層 ──")
    ob_chs = []
    for cid in cids:
        ch = next((c for c in chs if c.get("Id") == cid), None)
        if not ch:
            log(f"  {cid[:8]} 不在頻道清單！")
            rep["channels"].append({"cid": cid, "missing": True})
            continue
        s = shape(ch.get("Thumb"))
        log(f"  CH {(ch.get('Name') or '')[:40]!r} {cid[:8]} thumb={s} head={(ch.get('Thumb') or '')[:52]!r}")
        rep["channels"].append({"cid": cid, "name": ch.get("Name"),
                                "thumb": s, "head": (ch.get("Thumb") or "")[:52]})
        ob_chs.append(ch)
        if FIX:
            force_channel_cover(ch)

    # ── 分組層 ──
    grps = get_grps()
    log("── 分組層 ──")
    for g in grps:
        gid = g.get("Id") or ""
        tag = CURATED.get(gid[:8])
        is_ob = tag is None and (("being" in (g.get("Name") or "").lower())
                                 or (gid[:8] not in CURATED
                                     and len([x for x in grps
                                              if (x.get("Id") or "")[:8] not in CURATED]) == 1))
        if not (tag or is_ob):
            continue
        s = shape(g.get("Thumb"))
        log(f"  GP {g.get('Name')!r} [{tag or 'OB'}] thumb={s} "
            f"desc_len={len(g.get('Description') or '')}")
        rep["groups"].append({"name": g.get("Name"), "tag": tag or "OB",
                              "thumb": s, "desc_len": len(g.get("Description") or "")})
        if FIX and (s in ("empty", "default", "url") or (tag or "OB") == "OB"):
            force_group_thumb(g)

    # ── 各集層 ──
    log("── 各集層 ──")
    for cid in cids:
        nb, nc = OB.audit(cid)
        log(f"  {cid[:8]} 首頁 {nb} 篇｜缺封面 {nc}")
        rep["episodes"].append({"cid": cid, "page0": nb, "bare": nc})
        if FIX and nc:
            FM.patch_zombie_thumbs(cid)

    # ── 判定 ──
    bad_ch = [c for c in rep["channels"] if c.get("thumb") in ("empty", "default")]
    bad_gp = [g for g in rep["groups"] if g.get("thumb") in ("empty", "default")]
    bare = sum(e.get("bare", 0) for e in rep["episodes"])
    verdict = "HEALTHY" if not (bad_ch or bad_gp or bare) else "NEEDS-FIX"
    rep["verdict"] = verdict
    log(f"=== 判定: {verdict}（頻道病 {len(bad_ch)}｜分組病 {len(bad_gp)}｜裸圖 {bare}）===")
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "trail", "ob-doctor.json")
    json.dump(rep, open(out, "w"), ensure_ascii=False, indent=1)
    OB.ntfy(f"OB 封面體檢: {verdict}{'（已修復）' if FIX else ''}",
            f"頻道病 {len(bad_ch)}｜分組病 {len(bad_gp)}｜裸圖 {bare}"
            f"{'——修復模式已執行，詳 Actions log' if FIX else '——DOCTOR_FIX=1 可修復'}",
            3 if verdict == "HEALTHY" else 4)


if __name__ == "__main__":
    main()
