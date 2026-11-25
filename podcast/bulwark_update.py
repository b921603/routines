#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""podcast/bulwark_update.py — Bulwark 同步＋全集 backfill runner 端（v2）。

管線：RSS diff → 下載 → 32k mono 轉碼 → >60min 分段 → 上傳 → 發文
（官方封面＋描述＋平台 AI 字幕）→ 輕審計 → ntfy。
v2（11-25 用戶裁示：Bulwark 升級全集型）：
  - guid 帳本 trail/done_bulwark.json（kill-safe：每集成功即寫）
  - 日更模式（預設）：4 天窗、最新優先、MAX_PER_RUN=2
  - 全集模式（PODCAST_BACKFILL=1）：最舊優先 drain、PODCAST_BACKFILL_MAX=12/run
  - heal：頻道已有但帳本缺（種子集）→ 補帳
  - pit-status/1 回報 trail/bulwark-pit.json（patrol→gate 消費）
可補完性邊界：audioboom feed 截斷 500 集——全集=feed 視窗全集，窗外不可得。
憑證：全部走環境變數（GitHub Secrets）——SVC_USER/SVC_PASS/PODCAST_CID/NTFY_URL。
"""
import os, re, io, json, time, html, subprocess
from email.utils import parsedate_to_datetime
import requests

BASE = "https://my.eudic.net"
FEED = "https://audioboom.com/channels/5114286.rss"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
SEG = 3600                      # 平台單篇音訊上限（秒）
MAX_PER_RUN = int(os.environ.get("PODCAST_MAX_PER_RUN", "2"))
DAYS_WINDOW = 4                 # 只同步 N 天內的新集（補跑安全窗）
CID = os.environ.get("PODCAST_CID", "")
BACKFILL = os.environ.get("PODCAST_BACKFILL", "") == "1"
BACKFILL_MAX = int(os.environ.get("PODCAST_BACKFILL_MAX", "12"))
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIL = os.path.join(_REPO, "trail")
LEDGER = os.path.join(TRAIL, "done_bulwark.json")
PIT = os.path.join(TRAIL, "bulwark-pit.json")


def rj(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def wj(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, p)
NTFY = os.environ.get("NTFY_URL", "")
AUD = "/tmp/podcast_media"
SES = requests.Session(); SES.headers.update(UA)
FF = os.environ.get("FF_PATH", "")


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def retry(fn, tries=6, pause=8):
    last = None
    for k in range(tries):
        try:
            return fn()
        except Exception as ex:
            last = ex
            log(f"  retry{k}: {str(ex)[:90]}")
            time.sleep(pause + pause * k)
    raise last


def ntfy(title, body, prio=3):
    if not NTFY:
        return
    try:
        SES.post(NTFY, data=body.encode(), timeout=30,
                 headers={"Title": title, "Priority": str(prio), "Tags": "podcast"})
    except Exception as ex:
        log(f"ntfy err: {str(ex)[:60]}")


def req(method, url, *, data=None, timeout=60, tries=6, headers=None, files=None):
    kw = {}
    if headers:
        kw["headers"] = headers
    if files:
        kw["files"] = files
    for k in range(tries):
        try:
            r = SES.request(method, url, data=data, timeout=timeout, **kw)
            if r.status_code in (429, 502, 503):
                raise IOError(f"HTTP {r.status_code}")
            return r
        except Exception as ex:
            log(f"  http retry{k}: {str(ex)[:80]}")
            time.sleep(6 + 6 * k)
    raise RuntimeError(f"http exhausted: {url[:80]}")


def login():
    global RAW_COOKIE
    raw = os.environ.get("PODCAST_COOKIE", "")
    if raw:
        SES.headers["Cookie"] = raw
        try:
            req("GET", f"{BASE}/ting/GetPrivateChannels",
                headers={"X-Requested-With": "XMLHttpRequest"}, timeout=45)
            log("cookie OK（免登入）")
            return
        except Exception:
            log("cookie 失效 → 密碼登入")
    s = requests.Session()
    s.headers.update({**UA, "Referer": "https://dict.eudic.net/account/login"})
    s.get("https://dict.eudic.net/account/login",
          params={"returnUrl": "http://my.eudic.net/Account/Login"}, timeout=45)
    s.post("https://dict.eudic.net/Account/Login",
           params={"returnUrl": "http://my.eudic.net/Account/Login"},
           data={"UserName": os.environ["SVC_USER"], "Password": os.environ["SVC_PASS"],
                 "returnUrl": "http://my.eudic.net/Account/Login", "RememberMe": "true"},
           timeout=45, allow_redirects=True)
    ck = {c.name: c.value for c in s.cookies
          if (c.domain or "").endswith("eudic.net") and c.name not in
          ("__cf_bm", "cf_clearance", "__cf_chl")}
    raw = "; ".join(f"{k}={v}" for k, v in sorted(ck.items()))
    if "EudicWebSession" not in raw:
        raise RuntimeError("login did not yield session cookie")
    SES.headers["Cookie"] = raw
    r = req("GET", f"{BASE}/ting/GetPrivateChannels",
            headers={"X-Requested-With": "XMLHttpRequest"}, timeout=45)
    if "UploadedChannels" not in (r.text or ""):
        raise RuntimeError("cookie verify failed")
    log("login OK")


def ff_boot():
    """Runner 可能沒有 ffmpeg — 靜態版 bootstrap（快取於 /tmp）。"""
    global FF
    if FF:
        return FF
    tgt = "/tmp/pod_ffmpeg/ffmpeg"
    if os.path.isfile(tgt):
        FF = tgt
        return tgt
    import tarfile, urllib.request
    url = ("https://johnvansickle.com/ffmpeg/releases/"
           "ffmpeg-release-amd64-static.tar.xz")
    t0 = tgt + ".tar.xz"
    os.makedirs(os.path.dirname(tgt), exist_ok=True)
    urllib.request.urlretrieve(url, t0)
    with tarfile.open(t0) as tf:
        for m in tf.getmembers():
            if m.name.endswith("/ffmpeg"):
                open(tgt + ".part", "wb").write(tf.extractfile(m).read())
                break
    os.chmod(tgt + ".part", 0o755)
    os.replace(tgt + ".part", tgt)
    FF = tgt
    log(f"ffmpeg ready: {tgt}")
    return tgt


def rss_items():
    r = retry(lambda: requests.get(FEED, headers=UA, timeout=90))
    txt = r.text or ""
    items = []
    for blk in re.findall(r"<item>(.*?)</item>", txt, re.S):
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", blk, re.S)
        d = re.search(r"<pubDate>([^<]+)</pubDate>", blk)
        enc = re.search(r'<enclosure[^>]*url="([^"]+)"', blk)
        g = re.search(r"<guid[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</guid>", blk, re.S)
        de = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", blk, re.S)
        if not (t and d):
            continue
        items.append({"title": html.unescape(t.group(1)).strip(),
                      "date": parsedate_to_datetime(d.group(1)),
                      "url": html.unescape(enc.group(1)) if enc else "",
                      "guid": html.unescape(g.group(1)).strip() if g
                              else (html.unescape(enc.group(1)) if enc else ""),
                      "desc": html.unescape(de.group(1)).strip() if de else ""})
    return items


def norm(s):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (s or "").lower())


def have_titles(cid):
    out = set()
    for pg in range(3):
        r = req("GET", f"{BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}",
                timeout=45)
        got = 0
        for x in re.split(r'<div class="dragBox">', r.text or "")[1:]:
            tm = re.search(r'rl-title"[^>]*title="([^"]*)"', x)
            if tm:
                out.add(norm(html.unescape(tm.group(1))))
                got += 1
        if not got:
            break
    return out


def channel_cover_bytes(cid):
    r = req("GET", f"{BASE}/ting/GetPrivateChannels", timeout=45)
    for c in (r.json().get("channelList", {}).get("UploadedChannels") or []):
        if c.get("Id") == cid:
            u = c.get("Thumb") or ""
            if u and "default.png" not in u:
                img = requests.get(u, headers=UA, timeout=60).content
                try:
                    from PIL import Image
                    im = Image.open(io.BytesIO(img)).convert("RGB")
                    if max(im.size) > 1280:
                        im.thumbnail((1280, 1280), Image.LANCZOS)
                    o = io.BytesIO(); im.save(o, "JPEG", quality=88, optimize=True)
                    return o.getvalue()
                except Exception:
                    return img if len(img) < 2_000_000 else None
    return None


def upload_thumb(img):
    r = req("POST", f"{BASE}/ting/UploadTingFile?type=thumb",
            files={"file": ("keep.jpg", img, "image/jpeg")}, timeout=120)
    m = re.search(r'"fileId"\s*:\s*"([^"]+)"', r.text or "")
    return m.group(1) if m else ""


def upload_media(path):
    size = os.path.getsize(path)
    log(f"  ↑ upload {os.path.basename(path)} {size/1e6:.1f}MB …")
    with open(path, "rb") as f:
        r = retry(lambda: SES.post(f"{BASE}/ting/UploadTingFile?type=media",
                   files={"file": (os.path.basename(path), f, "audio/mpeg")},
                   timeout=int(os.environ.get("PODCAST_UPLOAD_TIMEOUT", "3300"))), tries=2, pause=30)
    m = re.search(r'"fileId"\s*:\s*"([^"]+)"', r.text or "")
    if not m:
        raise RuntimeError(f"media upload failed: {(r.text or '')[:80]}")
    log(f"  ↑ fileId={m.group(1)[:36]}")
    return m.group(1)


def prep_audio(url, key):
    os.makedirs(AUD, exist_ok=True)
    raw = os.path.join(AUD, key + ".mp3")
    if not (os.path.exists(raw) and os.path.getsize(raw) > 1_000_000):
        log(f"  ↓ download {key}")
        subprocess.run(["curl", "-sL", "--retry", "3", url, "-H",
                        "User-Agent: Mozilla/5.0", "-o", raw, "--max-time", "1200"],
                       check=True)
    ff = ff_boot()
    dst = os.path.join(AUD, key + "_32.mp3")
    if not (os.path.exists(dst) and os.path.getsize(dst) > 500_000):
        subprocess.run([ff, "-y", "-i", raw, "-ac", "1", "-b:a", "32k",
                        "-ar", "44100", dst], check=True, capture_output=True)
        log(f"  ⚙ 32k {os.path.getsize(raw)/1e6:.0f}→{os.path.getsize(dst)/1e6:.0f}MB")
    d = subprocess.run([ff, "-i", dst], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+)", d)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) if m else 0
    if dur <= SEG:
        return [(dst, 1, 1)]
    base = dst.replace(".mp3", "")
    subprocess.run([ff, "-y", "-i", dst, "-f", "segment", "-segment_time", str(SEG),
                    "-c", "copy", base + "_p%02d.mp3"], check=True, capture_output=True)
    parts, i = [], 0
    while os.path.exists(f"{base}_p{i:02d}.mp3"):
        parts.append((f"{base}_p{i:02d}.mp3", i + 1, 0))
        i += 1
    n = len(parts)
    log(f"  ✂ {dur//60}min → {n} parts")
    return [(p, j + 1, n) for j, (p, _, _) in enumerate(parts)]


# 平台 5-槽位提示（用戶實錄 T-029）：同帳同時處理進程 ≤5，滿時 create 被拒
# → 槽位感知退避（比一般錯誤更有耐心：槽位清空常需數分鐘）
SLOT_BUSY = ("处理程序", "资源处理")
try:
    import eudic_slots
except Exception:
    eudic_slots = None


def post(cid, title, thumb_fid, media_fid, desc):
    data = {"id": "", "title": title, "channelId": cid, "thumb": thumb_fid or "",
            "media": media_fid or "", "voice": "", "textAudioMode": "standard",
            "podcastVoices": "", "podcastSpeakers": "", "lrc": "",
            "needProcessLrc": "true", "needKeepformat": "false",
            "reformatParagraph": "true", "splitLongSentence": "true",
            "needMachineTranslation": "false", "allowMachineTranslation": "false",
            "needAISubtitle": "true", "description": (desc or "")[:3000],
            "mediatype": "0", "intros": "", "istiming": "false", "timing": "",
            "html": "", "insertImage": "false", "mdChapterId": ""}
    tries, slot_seen = 6, False
    for k in range(10):
        try:
            r = req("POST", f"{BASE}/ting/uploadprivatemedia", data=data, timeout=120)
            if r.status_code == 200 and '"code":200' in (r.text or "").replace(" ", ""):
                return True
            txt = (r.text or "")
            if any(w in txt for w in SLOT_BUSY):
                slot_seen = True                    # 5 槽位滿：長退避等槽位
                log(f"  post try{k}: slot busy (5-process limit)")
            else:
                log(f"  post try{k}: {r.status_code} {txt[:80]}")
        except Exception as ex:
            log(f"  post try{k} err: {str(ex)[:80]}")
        time.sleep((90 + 45 * k) if slot_seen else (12 + 12 * k))
    return False


def audit(cid):
    r = req("GET", f"{BASE}/ting/GetPrivateMedias?sortby=0&page=0&channelId={cid}", timeout=45)
    boxes = re.split(r'<div class="dragBox">', r.text or "")[1:]
    nocover = sum(1 for x in boxes
                  if re.search(r'class="img-zlg"[^>]*src="[^"]*media_default\.png', x))
    return len(boxes), nocover


def strip_html(s):
    return re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ").strip()


def emit_pit(ledger, catalog, dead):
    """pit-status/1：family=bulwark（11-25 起全集型）。補完定義＝可補完性制約
    （dead link 不計債；feed 視窗外不可得，記 boundary）。"""
    avail = len(catalog)
    done_n = sum(1 for e in catalog if e["guid"] in ledger)
    pubs = [e["date"] for e in catalog]
    done_pubs = [e["date"] for e in catalog if e["guid"] in ledger]
    lag = round((max(pubs) - max(done_pubs)).total_seconds() / 86400, 1) \
        if pubs and done_pubs else None
    win = (min(pubs).strftime("%F"), max(pubs).strftime("%F")) if pubs else ("?", "?")
    pit = {"protocol": "pit-status/1", "family": "bulwark",
           "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "mode": "backlog", "source": "engine",
           "official_total": avail + dead, "official_available": avail,
           "completed_eps": done_n, "true_missing": avail - done_n,
           "completion": round(done_n / avail, 3) if avail else None,
           "status": "complete" if avail - done_n == 0 else "in_progress",
           "dead_links": dead,
           "feed_window": {"from": win[0], "to": win[1],
                           "note": "audioboom feed 截斷 500 集——窗外不可得（可補完性邊界）"},
           "follow_lag_days": lag,
           "notes": "completion = ledger guids within feed window / catalog; parts inflate article counts"}
    wj(PIT, pit)
    log(f"pit: {done_n}/{avail} completion={pit['completion']} dead={dead}")
    return pit


def main():
    if not CID:
        print("PODCAST_CID missing — skip"); return
    login()
    cover = channel_cover_bytes(CID)
    items = rss_items()
    catalog = [e for e in items if e["url"]]
    dead = len(items) - len(catalog)
    ledger = rj(LEDGER, {}) or {}
    have = have_titles(CID)
    # heal：頻道已有（種子/舊份）但帳本缺 → 補帳（前綴比對，與舊冪等機制接軌）
    healed = 0
    for e in catalog:
        key = norm(f'{e["date"].strftime("%F")} {e["title"]}')
        if e["guid"] and e["guid"] not in ledger \
                and any(h.startswith(key) for h in have):
            ledger[e["guid"]] = {"title": f'{e["date"].strftime("%F")} {e["title"]}',
                                 "pub": e["date"].strftime("%F"),
                                 "at": time.strftime("%F %T"), "how": "heal"}
            healed += 1
    if healed:
        wj(LEDGER, ledger)
        log(f"heal: +{healed} ledger entries (頻道既有)")
    emit_pit(ledger, catalog, dead)
    if BACKFILL:
        pool = [e for e in catalog if e["guid"] and e["guid"] not in ledger]
        pool.sort(key=lambda e: e["date"])            # 全集模式：oldest-first drain
        cap = BACKFILL_MAX
        log(f"BACKFILL mode: pool {len(pool)} ｜ cap {cap}/run")
    else:
        pool = [e for e in catalog if e["guid"] and e["guid"] not in ledger
                and (time.time() - e["date"].timestamp()) < DAYS_WINDOW * 86400]
        pool.sort(key=lambda e: e["date"], reverse=True)   # 日更模式：最新優先
        cap = MAX_PER_RUN
    todo = pool[:cap]
    log(f"new episodes: {len(todo)}")
    if not todo:
        nb, nc = audit(CID)
        remain = len([e for e in catalog if e["guid"] not in ledger])
        ntfy("podcast sync: up to date",
             f"{'全集進度：剩 ' + str(remain) + ' 集（backfill 下輪續）' if BACKFILL else 'RSS 無新集（4 天窗）'}。"
             f"\n頻道首頁 {nb} 篇、缺封面 {nc}。", 1)
        return
    synced, failed = 0, []
    for e in todo:
        key = e["date"].strftime("%Y%m%d")
        full = f'{e["date"].strftime("%F")} {e["title"]}'
        log(f"▶ {full[:64]}")
        try:
            parts = prep_audio(e["url"], key)
            ok_all = True
            for pf, i, n in parts:
                ptitle = full if n == 1 else f"{full}（{i}/{n}）"
                if norm(ptitle) in have:
                    continue
                fid = upload_thumb(cover) if cover else ""
                mid = upload_media(pf)
                sid = None
                if eudic_slots and os.environ.get("GH_TOKEN"):
                    try:
                        sid = eudic_slots.claim("bulwark", mid, os.environ["GH_TOKEN"],
                                                wait_min=8, ttl=300, log=log)
                    except Exception:
                        sid = None
                okp = True
                try:
                    okp = post(CID, ptitle, fid, mid, strip_html(e["desc"]))
                except Exception:
                    okp = False
                finally:
                    if sid and not okp:
                        try:
                            eudic_slots.release("bulwark", sid, os.environ.get("GH_TOKEN"), log=log)
                        except Exception:
                            pass
                if not okp:
                    ok_all = False
                    break
                have.add(norm(ptitle))
                time.sleep(3)
            if ok_all:
                synced += 1
                if e["guid"]:
                    ledger[e["guid"]] = {"title": full, "pub": e["date"].strftime("%F"),
                                         "at": time.strftime("%F %T"),
                                         "how": "backfill" if BACKFILL else "daily"}
                    wj(LEDGER, ledger)        # kill-safe：每集成功即落帳
            else:
                failed.append(full[:50])
        except Exception as ex:
            log(f"  ✗ {str(ex)[:110]}")
            failed.append(full[:50])
    pit = emit_pit(ledger, catalog, dead)
    nb, nc = audit(CID)
    body = (f"同步 {synced}/{len(todo)} 集（{'全集 backfill' if BACKFILL else '日更'}）：\n" +
            "\n".join(f"• {e['date'].strftime('%m-%d')} {e['title'][:60]}" for e in todo) +
            f"\n頻道首頁 {nb} 篇｜缺封面 {nc}"
            f"\n全集進度 {pit['completed_eps']}/{pit['official_available']}"
            f"（剩 {pit['true_missing']}）")
    if failed:
        body += "\n失敗（下輪續傳）：" + "、".join(failed)
        ntfy(f"podcast sync: PARTIAL {synced}/{len(todo)}", body, 4)
    else:
        ntfy(f"podcast sync: OK {synced} ep", body, 3)
    log("done")


if __name__ == "__main__":
    main()
