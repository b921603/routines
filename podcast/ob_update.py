#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""podcast/ob_update.py — On Being with Krista Tippett 引擎（2026-11-25 開坑，用戶令）。

管線：ensure_channel（冪等建頻道）→ RSS catalog（986 集全量可補完）→
guid 帳本（kill-safe）→ 下載 → 32k mono → >60min 分段 → 上傳 → 發文
（AI 字幕：>60min 集平台拒→自動 false）→ pit-status/1 → 輕審計 → ntfy。
模式：daily（預設，4 天窗最新優先）／backfill（PODCAST_BACKFILL=1，oldest-first drain）。
可補完性：simplecast feed 全量（986/986 enclosure）——無 feed-window 邊界。
簡介紀律：無「RSS 同步」類尾綴；官方逐字稿 feed 未提供（transcript_tag=false）不宣稱。
憑證：PODCAST_COOKIE（免登入）／SVC_USER+SVC_PASS／GH_TOKEN（槽位）／NTFY_URL。
"""
import os, re, io, json, time, html, subprocess
from email.utils import parsedate_to_datetime
import requests

BASE = "https://my.eudic.net"
FEED = "https://feeds.simplecast.com/AuAxH_Bf"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
SEG = 3600                      # 平台單篇音訊上限（秒）
CH_NAME = "On Being with Krista Tippett"
CH_DESC = ("Krista Tippett 的慢訪談：詩人、科學家、神學家在這裡談意識、愛、時間與失落。"
           "Michael Pollan 探問意識之謎、Robin Wall Kimmerer 帶來苔蘚的智慧——"
           "每一場對話都像在時間之外進行。英語清晰溫潤，適合精聽與跟讀。")
MAX_PER_RUN = int(os.environ.get("OB_MAX_PER_RUN", "2"))
DAYS_WINDOW = 4
BACKFILL = os.environ.get("OB_BACKFILL", "") == "1"
BACKFILL_MAX = int(os.environ.get("OB_BACKFILL_MAX", "24"))
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIL = os.path.join(_REPO, "trail")
LEDGER = os.path.join(TRAIL, "done_ob.json")
PIT = os.path.join(TRAIL, "ob-pit.json")
CHFILE = os.path.join(TRAIL, "ob_channel.json")
AUD = os.path.join(_REPO, "state", "ob_audio")

SES = requests.Session()


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


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def retry(fn, tries=6, pause=8):
    for k in range(tries):
        try:
            return fn()
        except Exception as ex:
            log(f"  retry{k}: {str(ex)[:90]}")
            time.sleep(pause)
    raise RuntimeError("retry exhausted")


def ntfy(title, body, prio=3):
    n = os.environ.get("NTFY_URL", "")
    if not n:
        return
    try:
        SES.post(n, data=body.encode(), timeout=30,
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
    if os.name == "nt":
        return "ffmpeg"                    # windows runner 自帶
    tgt = os.path.join(os.environ.get("TMPDIR", "/tmp"), "ob_ffmpeg", "ffmpeg")
    if os.path.isfile(tgt):
        return tgt
    import tarfile, tempfile, urllib.request
    try:
        urls = [("https://johnvansickle.com/ffmpeg/releases/"
                 "ffmpeg-release-amd64-static.tar.xz", "/ffmpeg"),
                ("https://github.com/BtbN/FFmpeg-Builds/releases/download/"
                 "latest/ffmpeg-master-latest-linux64-gpl.tar.xz", "/bin/ffmpeg")]
        d = os.path.dirname(tgt)
        os.makedirs(d, exist_ok=True)
        last = None
        for url, suf in urls:
            try:
                log(f"ffmpeg missing — fetching {url.split('/')[2]} …")
                t0 = os.path.join(d, f"ff-{os.getpid()}.tar.xz")
                urllib.request.urlretrieve(url, t0)
                with tarfile.open(t0) as tf:
                    for m in tf.getmembers():
                        if m.name.endswith(suf):
                            with open(tgt + ".part", "wb") as f:
                                f.write(tf.extractfile(m).read())
                            break
                    else:
                        raise RuntimeError("binary not in tarball")
                os.chmod(tgt + ".part", 0o755)
                os.replace(tgt + ".part", tgt)
                try:
                    os.remove(t0)
                except Exception:
                    pass
                return tgt
            except Exception as ex:
                last = ex
                log(f"  source failed: {str(ex)[:70]}")
        raise last
    except Exception as e:
        log(f"ffmpeg bootstrap failed: {e}")
        return None


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


def channel_id(force=False):
    """CID 解析：secret OB_CID → trail/ob_channel.json → ensure（冪等自建）。"""
    cid = os.environ.get("OB_CID", "")
    if cid and not force:
        return cid
    saved = rj(CHFILE, {}) or {}
    if saved.get("cid") and not force:
        return saved["cid"]
    r = req("GET", f"{BASE}/ting/GetPrivateChannels", timeout=45)
    for c in (r.json().get("channelList", {}).get("UploadedChannels") or []):
        if html.unescape(c.get("Name") or "") == CH_NAME:
            cid = c["Id"]
            log(f"channel found: {cid}")
            wj(CHFILE, {"cid": cid, "name": CH_NAME, "at": time.strftime("%F %T")})
            return cid
    # create（IsBannedWords precheck → CreatePrivateChannel；thumb 空可）
    rr = req("POST", f"{BASE}/ting/IsBannedWords",
             data={"name": CH_NAME, "channelId": ""}, timeout=30)
    if rr.json().get("success") is False:
        raise RuntimeError(f"channel name rejected: {CH_NAME}")
    r = req("POST", f"{BASE}/ting/CreatePrivateChannel",
            data={"name": CH_NAME, "thumb": "", "channelType": "",
                  "description": CH_DESC}, timeout=45)
    if r.status_code != 200:
        raise RuntimeError(f"create channel failed: {r.status_code} {(r.text or '')[:80]}")
    # 回讀取得 Id
    r2 = req("GET", f"{BASE}/ting/GetPrivateChannels", timeout=45)
    for c in (r2.json().get("channelList", {}).get("UploadedChannels") or []):
        if html.unescape(c.get("Name") or "") == CH_NAME:
            cid = c["Id"]
            log(f"channel created: {cid}")
            wj(CHFILE, {"cid": cid, "name": CH_NAME, "at": time.strftime("%F %T")})
            return cid
    raise RuntimeError("channel created but not found in listing")


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
                        buf = io.BytesIO()
                        im.save(buf, "JPEG")
                        return buf.getvalue()
                    return img
                except Exception:
                    return img
    return None


def upload_thumb(img):
    r = req("POST", f"{BASE}/ting/uploadprivatemedia",
            files={"file": ("cover.jpg", img, "image/jpeg")}, timeout=120)
    m = re.search(r'["{]?(?:fid|fileId|id)["\s:=]+([0-9a-f\-]{36})', r.text or "")
    if not m:
        raise RuntimeError(f"thumb upload failed: {(r.text or '')[:80]}")
    return m.group(1)


def upload_media(path):
    with open(path, "rb") as f:
        r = req("POST", f"{BASE}/ting/uploadprivatemedia",
                files={"file": (os.path.basename(path), f, "audio/mpeg")}, timeout=3300)
    m = re.search(r'["{]?(?:fid|fileId|id)["\s:=]+([0-9a-f\-]{36})', r.text or "")
    if not m:
        raise RuntimeError(f"media upload failed: {(r.text or '')[:80]}")
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


def strip_html(s):
    return re.sub(r"<[^>]+>", " ", s or "").strip()


SLOT_BUSY = ("处理程序", "资源处理")
try:
    import eudic_slots
except Exception:
    eudic_slots = None


def post(cid, title, thumb_fid, media_fid, desc, ai_sub=True):
    data = {"id": "", "title": title, "channelId": cid, "thumb": thumb_fid or "",
            "media": media_fid or "", "voice": "", "textAudioMode": "standard",
            "podcastVoices": "", "podcastSpeakers": "", "lrc": "",
            "needProcessLrc": "true", "needKeepformat": "false",
            "reformatParagraph": "true", "splitLongSentence": "true",
            "needMachineTranslation": "false", "allowMachineTranslation": "false",
            "needAISubtitle": "true" if ai_sub else "false",
            "description": (desc or "")[:3000],
            "mediatype": "0", "intros": "", "istiming": "false", "timing": "",
            "html": "", "insertImage": "false", "mdChapterId": ""}
    for k in range(10):
        try:
            r = req("POST", f"{BASE}/ting/uploadprivatemedia", data=data, timeout=120)
            if r.status_code == 200 and '"success":true' in (r.text or "").replace(" ", ""):
                return True
            txt = r.text or ""
            if any(b in txt for b in SLOT_BUSY):
                log(f"  slot busy — wait 90s（{k + 1}/10）")
                time.sleep(90)
                continue
            log(f"  post try{k}: {r.status_code} {txt[:80]}")
            time.sleep(8)
        except Exception as ex:
            log(f"  post try{k} err: {str(ex)[:80]}")
            time.sleep(8)
    return False


def audit(cid):
    nb = nc = 0
    try:
        r = req("GET", f"{BASE}/ting/GetPrivateMedias?sortby=0&page=0&channelId={cid}",
                timeout=45)
        boxes = re.split(r'<div class="dragBox">', r.text or "")[1:]
        nb = len(boxes)
        nc = sum(1 for x in boxes if "no-cover" in x or "default.png" in x)
    except Exception as ex:
        log(f"audit err: {str(ex)[:60]}")
    return nb, nc


def emit_pit(ledger, catalog, dead):
    """pit-status/1：family=ob。simplecast 全量 feed——無視窗邊界。"""
    avail = len(catalog)
    done_n = sum(1 for e in catalog if e["guid"] in ledger)
    pubs = [e["date"] for e in catalog]
    done_pubs = [e["date"] for e in catalog if e["guid"] in ledger]
    lag = round((max(pubs) - max(done_pubs)).total_seconds() / 86400, 1) \
        if pubs and done_pubs else None
    pit = {"protocol": "pit-status/1", "family": "ob",
           "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "mode": "backlog", "source": "engine",
           "official_total": avail + dead, "official_available": avail,
           "completed_eps": done_n, "true_missing": avail - done_n,
           "completion": round(done_n / avail, 3) if avail else None,
           "status": "complete" if avail - done_n == 0 else "in_progress",
           "dead_links": dead,
           "feed_window": {"from": min(pubs).strftime("%F") if pubs else "?",
                           "to": max(pubs).strftime("%F") if pubs else "?",
                           "note": "simplecast 全量 feed——可補完性無邊界"},
           "follow_lag_days": lag,
           "notes": "completion = ledger guids / catalog; parts inflate article counts"}
    wj(PIT, pit)
    log(f"pit: {done_n}/{avail} completion={pit['completion']} dead={dead}")
    return pit


def main():
    login()
    cid = channel_id()
    cover = channel_cover_bytes(cid)
    items = rss_items()
    catalog = [e for e in items if e["url"]]
    dead = len(items) - len(catalog)
    ledger = rj(LEDGER, {}) or {}
    have = have_titles(cid)
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
        pool.sort(key=lambda e: e["date"])            # oldest-first drain
        cap = BACKFILL_MAX
        log(f"BACKFILL mode: pool {len(pool)} ｜ cap {cap}/run")
    else:
        pool = [e for e in catalog if e["guid"] and e["guid"] not in ledger
                and (time.time() - e["date"].timestamp()) < DAYS_WINDOW * 86400]
        pool.sort(key=lambda e: e["date"], reverse=True)
        cap = MAX_PER_RUN
    todo = pool[:cap]
    log(f"new episodes: {len(todo)}")
    if not todo:
        nb, nc = audit(cid)
        remain = len([e for e in catalog if e["guid"] not in ledger])
        ntfy("On Being sync: up to date",
             f"{'全集進度：剩 ' + str(remain) + ' 集（backfill 下輪續）' if BACKFILL else 'RSS 無新集'}。"
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
                        sid = eudic_slots.claim("ob", mid, os.environ["GH_TOKEN"],
                                                wait_min=8, ttl=300, log=log)
                    except Exception:
                        sid = None
                okp = True
                try:
                    # >60min 集（分段 n>1）平台拒 AI 字幕→自動 false
                    okp = post(cid, ptitle, fid, mid, strip_html(e["desc"]),
                               ai_sub=(n == 1))
                except Exception:
                    okp = False
                finally:
                    if sid and not okp:
                        try:
                            eudic_slots.release("ob", sid, os.environ.get("GH_TOKEN"), log=log)
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
    nb, nc = audit(cid)
    body = (f"同步 {synced}/{len(todo)} 集（{'全集 backfill' if BACKFILL else '日更'}）：\n" +
            "\n".join(f"• {e['date'].strftime('%m-%d')} {e['title'][:60]}" for e in todo) +
            f"\n頻道首頁 {nb} 篇｜缺封面 {nc}"
            f"\n全集進度 {pit['completed_eps']}/{pit['official_available']}"
            f"（剩 {pit['true_missing']}）")
    if failed:
        body += "\n失敗（下輪續傳）：" + "、".join(failed)
        ntfy(f"On Being sync: PARTIAL {synced}/{len(todo)}", body, 4)
    else:
        ntfy(f"On Being sync: OK {synced} ep", body, 3)
    log("done")


if __name__ == "__main__":
    main()
