#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""podcast/patrol.py — P4.0 影子巡邏（READ-ONLY）。

全艦審計：TFF 9＋HTF 2＋Bulwark 1 頻道＋3 分組。真相源＝平台本身。
零寫入原則：本版不做任何修復（P4.1 白名單尚未實裝；PATROL_WRITE=1
僅印出提醒，不會打開任何寫入路徑）。

每頻道一次 pagination 全掃（sortby=0 至空頁，≤16 頁）同時產出：
可靠計數＋全量封面缺漏＋標題集（Bulwark L3 RSS 對帳復用）。
分組走 GetPrivateGroups（成員數/描述/封面皆可靠）。
漂移偵測＝與上輪快照比對（篇數回落、分組掉成員）。
狀態累積 state/patrol-state.json（保留 30 輪）。
"""
import os, re, json, time, html
import requests

from bulwark_update import login, req, ntfy, norm, SES, BASE, log

STATE_PATH = os.environ.get("PATROL_STATE", "state/patrol-state.json")
BUL_CID = os.environ.get("PODCAST_CID", "")
SHIP_PREFIXES = ("The Tim Ferriss Show #", "How To Fail")
GROUPS = ("Tim Ferriss Show", "How To Fail With Elizabeth Day", "The Bulwark Daily")
MAX_PAGES = int(os.environ.get("PATROL_MAX_PAGES", "16"))
BANNED = re.compile(r"(RSS|同步|AI ?字幕|AI ?逐字稿|逐字稿|搬运|搬運|"
                    r"uploadprivatemedia|needAISubtitle|官方同步)")

# ── P4.2 Lite 艦隊心跳：公開 GitHub API 唯讀，零 token、零寫入 ──
FLEET = {   # repo → [(workflow 名, 靜默閾值小時)]
    "tf-engine": [("tff-sync", 36), ("tff-rotate", 36), ("tff-keepalive", 36)],
    "htf-engine": [("htf-sync", 36), ("htf-rotate", 36), ("htf-keepalive", 36)],
    "routines": [("housekeeping", 36), ("sweep", 9 * 24),
                 ("podcast-sync", 36), ("patrol", 36)],
}
GH = "https://api.github.com"
GH_H = {"User-Agent": "patrol", "Accept": "application/vnd.github+json"}


def _ago_h(iso):
    from datetime import datetime, timezone as _tz
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_tz.utc)
    return (time.time() - dt.timestamp()) / 3600


def fleet_heartbeat():
    segs, amber = [], []
    for repo, wfs in FLEET.items():
        parts = []
        try:
            wfl = requests.get(f"{GH}/repos/b921603/{repo}/actions/workflows",
                               headers=GH_H, timeout=30).json().get("workflows", [])
            ids = {w["name"]: w["id"] for w in wfl}
        except Exception:
            segs.append(f"{repo}: ?")
            continue
        for wf, thr in wfs:
            tag = wf.split("-", 1)[-1]          # tff-sync → sync
            wid = ids.get(wf) or ids.get(wf.replace("-", " ").title())
            if not wid:
                parts.append(f"{tag}:?")
                continue
            try:
                rr = requests.get(
                    f"{GH}/repos/b921603/{repo}/actions/workflows/{wid}/runs?per_page=3",
                    headers=GH_H, timeout=30).json().get("workflow_runs", [])
                if not rr:
                    parts.append(f"{tag}:—")
                    continue
                r0 = rr[0]
                h = _ago_h(r0["created_at"])
                c = r0.get("conclusion")
                if r0["status"] != "completed":
                    parts.append(f"{tag}⏳({h:.0f}h)")
                elif c not in ("success", "skipped"):
                    done3 = [x.get("conclusion") for x in rr
                             if x.get("status") == "completed"]
                    consec = 0
                    for cc in done3:
                        if cc in ("success", "skipped"):
                            break
                        consec += 1
                    parts.append(f"{tag}✗{str(c)[:5]}({'x' + str(consec) if consec > 1 else ''}{h:.0f}h)")
                    amber.append(f"艦隊 {repo}/{wf}: conclusion={c}"
                                 + (f"（連續 {consec} 次失敗——需人工查看 log）" if consec >= 2 else ""))
                elif h > thr:
                    parts.append(f"{tag}✗靜默({h:.0f}h)")
                    amber.append(f"艦隊 {repo}/{wf}: 靜默 {h:.0f}h（閾值 {thr}h）")
                else:
                    parts.append(f"{tag}✓({h:.0f}h)")
            except Exception:
                parts.append(f"{tag}:?")
        segs.append(repo.replace("-engine", "") + " " + " ".join(parts))
    return "｜".join(segs), amber


def channel_scan(cid):
    """→ (計數, 缺封面[(mid,title)], 標題 norm 集)。至空頁為止。"""
    count, nocover, titles = 0, [], set()
    for pg in range(MAX_PAGES):
        r = req("GET", f"{BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}",
                timeout=45)
        boxes = re.split(r'<div class="dragBox">', r.text or "")[1:]
        if not boxes:
            break
        for x in boxes:
            count += 1
            z = re.search(r'class="img-zlg"[^>]*src="([^"]*)"', x)
            m = re.search(r'rl-title"[^>]*title="([^"]*)"', x)
            mid = re.search(r'media_id"[^>]*data="([^"]+)"', x)
            if z and "media_default.png" in z.group(1):
                nocover.append((mid.group(1) if mid else "?",
                                html.unescape(m.group(1))[:40] if m else "?"))
            if m:
                titles.add(norm(html.unescape(m.group(1))))
        time.sleep(0.5)
    return count, nocover, titles


def ships_and_groups():
    r = req("GET", f"{BASE}/ting/GetPrivateChannels", timeout=45)
    ships = {}
    for c in r.json()["channelList"]["UploadedChannels"]:
        n = html.unescape(c.get("Name") or "")
        if n.startswith(SHIP_PREFIXES) or (BUL_CID and c.get("Id") == BUL_CID):
            ships[n] = c
    g = req("POST", f"{BASE}/ting/GetPrivateGroups?withDefault=false", data="", timeout=40)
    groups = {}
    for c in g.json()["channelList"]["UploadedChannels"]:
        n = html.unescape(c.get("Name") or "")
        if n in GROUPS:
            groups[n] = c
    return ships, groups


def bulwark_l3(titles):
    """RSS 4 天窗 vs 頻道標題集（復用 channel_scan 結果，零額外分頁）。"""
    r = requests.get("https://audioboom.com/channels/5114286.rss",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
    from email.utils import parsedate_to_datetime
    expect = []
    for blk in re.findall(r"<item>(.*?)</item>", r.text or "", re.S):
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", blk, re.S)
        d = re.search(r"<pubDate>([^<]+)</pubDate>", blk)
        if not (t and d):
            continue
        dt = parsedate_to_datetime(d.group(1))
        if time.time() - dt.timestamp() < 4 * 86400:
            expect.append((dt.strftime("%F"), html.unescape(t.group(1)).strip()))
    missing = []
    for d, t in expect:
        key = norm(f"{d} {t}")
        if not any(h.startswith(key) for h in titles):
            missing.append(f"{d} {t[:44]}")
    return expect, missing


PIT_REPORTS = {   # pit-status/1 協議：引擎回報 → patrol 讀取
    "tff": "https://raw.githubusercontent.com/b921603/tf-engine/main/trail/pit-status.json",
    "htf": "https://raw.githubusercontent.com/b921603/htf-engine/main/trail/pit-status.json",
}


def pits_report(rep):
    """坑位完成度：優先讀引擎 pit-status/1 回報；無回報→本地估算＋備註。"""
    pol = {}
    try:
        pol = json.load(open("policies/policies.json")).get("pipeline", {})
    except Exception:
        pass
    out = []
    for p in pol.get("pits", []):
        cnt = sum(v["count"] for k, v in rep["channels"].items()
                  if k.startswith(p["prefix"]))
        pit = {"family": p["family"], "mode": p["mode"], "platform": cnt}
        src = PIT_REPORTS.get(p["family"])
        if src:
            try:
                r = requests.get(src, timeout=30)
                if r.status_code == 200:
                    rr = r.json()
                    if rr.get("protocol") == "pit-status/1":
                        pit.update({"source": "engine",
                                    "completion": rr.get("completion"),
                                    "status": rr.get("status"),
                                    "official_total": rr.get("official_total"),
                                    "official_available": rr.get("official_available"),
                                    "completed_eps": rr.get("completed_eps"),
                                    "true_missing": rr.get("true_missing"),
                                    "reported_at": rr.get("updated_at"),
                                    "follow_lag_days": rr.get("follow_lag_days")})
                    else:
                        pit["source"] = "protocol-mismatch"
                else:
                    pit["source"] = "report-pending"
            except Exception:
                pit["source"] = "report-unreachable"
        else:
            pit["source"] = "rolling-local"
        if "completion" not in pit and p["mode"] == "backlog":
            # 本地估算（僅備援）：篇數含分段膨脹，僅供參考
            pit["completion_est"] = None
        out.append(pit)
    rep["pits"] = out


def main():
    if os.environ.get("PATROL_WRITE") == "1":
        log("PATROL_WRITE=1 → P4.1 白名單修復尚未實裝；本版仍為只讀影子巡邏")
    login()
    ships, groups = ships_and_groups()
    rep = {"at": time.strftime("%F %T"), "channels": {}, "groups": {},
           "drifts": [], "verdict": "GREEN"}
    st = {}
    if os.path.exists(STATE_PATH):
        try:
            st = json.load(open(STATE_PATH))
        except Exception:
            st = {}
    runs = st.get("runs") or []
    prev = runs[0] if runs else {}
    prev_ch = prev.get("channels", {}) if isinstance(prev, dict) else {}
    prev_gr = prev.get("groups", {}) if isinstance(prev, dict) else {}

    red, amber = [], []
    bul_titles = None
    for n, c in sorted(ships.items()):
        desc = html.unescape(c.get("Description") or "")
        thumb = c.get("Thumb") or ""
        count, nocover, titles = channel_scan(c["Id"])
        if n.startswith("The Bulwark Daily"):
            bul_titles = titles
        entry = {"count": count,
                 "cover_ok": bool(thumb) and "default.png" not in thumb,
                 "desc_ok": bool(desc.strip()) and not BANNED.search(desc),
                 "ep_nocover": [t for _, t in nocover[:10]]}
        p = prev_ch.get(n) or {}
        if count < (p.get("count") or 0):
            d = f"{n}: 篇數 {p.get('count')}→{count}（回落）"
            rep["drifts"].append(d); amber.append(d)
        if not entry["cover_ok"]:
            amber.append(f"{n}: 頻道封面缺失")
        if not entry["desc_ok"]:
            amber.append(f"{n}: 簡介缺失或含禁語")
        if nocover:
            amber.append(f"{n}: {len(nocover)} 篇缺封面（例：{nocover[0][1]}）")
        if count == 0 and (p.get("count") or 0) > 0:
            red.append(f"{n}: 頻道被清空（{p.get('count')}→0）")
        # count==0 且無前例 → 基線記錄不報警（頻道結構屬各引擎財產；巡邏只盯「變化」）
        rep["channels"][n] = entry
    if BUL_CID and BUL_CID not in {c["Id"] for c in ships.values()}:
        red.append("Bulwark 頻道消失")
    for n in GROUPS:
        g = groups.get(n)
        if not g:
            red.append(f"分組缺失: {n}")
            continue
        members = g.get("TotalMediaCount") or 0
        gdesc = html.unescape(g.get("Description") or "")
        gthumb = g.get("Thumb") or g.get("ThumbUrl") or ""
        entry = {"members": members,
                 "desc_ok": bool(gdesc.strip()) and not BANNED.search(gdesc),
                 "cover_ok": bool(gthumb) and "default.png" not in gthumb}
        p = prev_gr.get(n) or {}
        if members < (p.get("members") or 0):
            d = f"分組 {n}: 成員 {p.get('members')}→{members}（掉出）"
            rep["drifts"].append(d); amber.append(d)
        if not entry["desc_ok"]:
            amber.append(f"分組 {n}: 簡介缺失或含禁語")
        if not entry["cover_ok"]:
            amber.append(f"分組 {n}: 封面缺失")
        rep["groups"][n] = entry
    if bul_titles is not None:
        expect, missing = bulwark_l3(bul_titles)
        rep["bulwark_rss"] = {"expected_4d": len(expect), "missing": missing}
        for m in missing:
            amber.append(f"Bulwark RSS 缺: {m}")
    fb, famber = fleet_heartbeat()
    rep["fleet"] = fb
    amber += famber
    pits_report(rep)

    # 上傳槽位統御視圖（帳號級 5 槽位；TTL 過期自動清除）
    try:
        sp = os.path.join(os.path.dirname(STATE_PATH) or ".", "upload_slots.json")
        sv = json.load(open(sp)) if os.path.exists(sp) else {"slots": []}
        now = time.time()
        live = [x for x in sv.get("slots", []) if x.get("exp", 0) > now]
        stale = len(sv.get("slots", [])) - len(live)
        rep["slots"] = {"live": len(live), "stale_swept": stale, "cap": 5,
                        "owners": sorted({x.get("owner") for x in live})}
        if len(live) >= 5:
            rep.setdefault("notes", []).append("upload slots 5/5 full — 跨源統御中（等待 TTL 釋放）")
    except Exception:
        rep["slots"] = {"live": None, "err": "read fail"}

    rep["verdict"] = "RED" if red else ("AMBER" if amber else "GREEN")

    runs.insert(0, {k: rep[k] for k in ("at", "verdict", "channels", "groups",
                                        "drifts", "fleet", "pits", "slots")})
    st["runs"] = runs[:30]
    os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
    json.dump(st, open(STATE_PATH, "w"), ensure_ascii=False, indent=1)

    print(json.dumps(rep, ensure_ascii=False, indent=1))
    lines = [f"verdict={rep['verdict']}｜頻道 {len(rep['channels'])}｜分組 {len(rep['groups'])}"]
    lines += [f"⚠ {d}" for d in (red + amber)[:6]]
    if rep["drifts"]:
        lines.append("漂移：" + "；".join(rep["drifts"][:3]))
    lines.append(f"艦隊：{rep['fleet']}")
    ntfy(f"patrol: {rep['verdict']}", "\n".join(lines) or "全艦正常",
         4 if rep["verdict"] != "GREEN" else 1)
    log("patrol done")


if __name__ == "__main__":
    main()
