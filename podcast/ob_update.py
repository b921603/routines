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
import os, re, io, json, time, html, subprocess, sys
from email.utils import parsedate_to_datetime
import requests

BASE = "https://my.eudic.net"
FEED = "https://feeds.simplecast.com/AuAxH_Bf"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
SEG = 3600                      # 平台單篇音訊上限（秒）
CH_NAME = "On Being"            # 平台 IsBannedWords 拒全名（iter-3 實錘）→ 短名（節目通用名）
CH_NAME_CANDS = ["On Being", "On Being 慢訪談", "On Being Podcast", "On Being with Krista Tippett"]
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
PARTS = os.path.join(TRAIL, "ob_parts.jsonl")
OBCHS = os.path.join(TRAIL, "ob_channels.json")   # 頻道登記簿（dedup 跨 repo 讀取）
BINDS = os.path.join(TRAIL, "ob_binds.json")      # 已綁分組的 cid 集合
CH_CAP = int(os.environ.get("OB_CHANNEL_CAPACITY", "100"))


def parts_marked():
    """已建立分片 resume 錨點 {(guid, part)}——kill-safe（tfs parts_ledger_mark 繼承）。"""
    out = set()
    try:
        with open(PARTS, encoding="utf-8") as f:
            for line in f:
                try:
                    j = json.loads(line)
                    out.add((j["guid"], j["part"]))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return out


def parts_mark(guid, part, title, cid, mid):
    """單分片建立即記（mid 入帳＝dedup 正主錨點；隨增量 commit 落 git 跨 run 存活）。"""
    with open(PARTS, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%F %T"), "guid": guid, "part": part,
                            "title": title[:80], "cid": cid, "mid": mid},
                           ensure_ascii=False) + "\n")


def _git_progress():
    """增量 commit：每集進度即落 git（tfs git-as-queue 的 ob 版本——kill 後任何 runner 都看得到）。"""
    try:
        subprocess.run(["git", "add", "trail/done_ob.json", "trail/ob_parts.jsonl"],
                       check=False, capture_output=True, timeout=30)
        if subprocess.run(["git", "diff", "--cached", "--quiet"],
                          capture_output=True).returncode != 0:
            subprocess.run(["git", "commit", "-q", "-m",
                            f"ob progress: {time.strftime('%H:%M:%S')}"], check=False,
                           capture_output=True, timeout=60)
            r = subprocess.run(["git", "pull", "--rebase", "-q"], capture_output=True, timeout=90)
            if r.returncode == 0:
                subprocess.run(["git", "push", "-q", "origin", "main"],
                               capture_output=True, timeout=90)
            else:
                subprocess.run(["git", "rebase", "--abort"], capture_output=True, timeout=30)
                log("  progress commit: rebase conflict — 本地保留（trail step 末再 push）")
    except Exception as ex:
        log(f"  progress commit err: {str(ex)[:60]}")


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


def retry_backoff(fn, pauses=(20, 45, 90, 180, 300)):
    """上傳退避重試：Eudic『保存異常，請重試』為伺服器端暫時性 500——長間隔退避（11-25 ob 首航教訓）。"""
    for k, p in enumerate(pauses):
        try:
            return fn()
        except Exception as ex:
            log(f"  backoff{k}: {str(ex)[:90]} → 等待 {p}s")
            time.sleep(p)
    raise RuntimeError("backoff exhausted")


def ntfy(title, body, prio=3):
    n = os.environ.get("NTFY_URL", "")
    if not n:
        return
    try:
        SES.post(n, data=body.encode(), timeout=30,
                 headers={"Title": title, "Priority": str(prio), "Tags": "podcast"})
    except Exception as ex:
        log(f"ntfy err: {str(ex)[:60]}")


class AuthError(Exception):
    """Cookie 失效（302/401 或被導向登入頁）——tfs 繼承審計缺口 A（11-26）。
    若無此防護：cookie 中途死→have_titles 回空→全部誤判未搬運→大規模重複上傳。"""


GAP = 2.4                         # 全局請求最小間隔（tfs 繼承審計缺口 B：WAF 節流）
_last_req = [0.0]
_RELOGIN = [0]                    # mid-run relogin 次數（上限 1/run）


def req(method, url, *, data=None, timeout=60, tries=6, headers=None, files=None,
        auth_check=True):
    """Rate-gated（GAP 全局節流）＋auth 偵測（302/401／登入頁→AuthError，不重試直接上拋）。"""
    kw = {}
    if headers:
        kw["headers"] = headers
    if files:
        kw["files"] = files
    for k in range(tries):
        wait = _last_req[0] + GAP - time.time()
        if wait > 0:
            time.sleep(wait + 0.15)
        _last_req[0] = time.time()
        try:
            r = SES.request(method, url, data=data, timeout=timeout, **kw)
            if auth_check and r.status_code in (302, 401):
                raise AuthError(f"HTTP {r.status_code} — cookie expired?")
            if (auth_check and r.status_code == 200
                    and "EudicWebSession" in (r.text or "")[:4000]
                    and "uploadprivatemedia" not in url):
                raise AuthError("redirected to login — cookie expired?")
            if r.status_code in (429, 502, 503):
                raise IOError(f"HTTP {r.status_code}")
            return r
        except AuthError:
            raise
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
        img = re.search(r'<itunes:image[^>]*href="([^"]+)"', blk) or \
            re.search(r"<image>.*?<url>([^<]+)</url>", blk, re.S)
        g = re.search(r"<guid[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</guid>", blk, re.S)
        de = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", blk, re.S)
        if not (t and d):
            continue
        items.append({"title": html.unescape(t.group(1)).strip(),
                      "date": parsedate_to_datetime(d.group(1)),
                      "url": html.unescape(enc.group(1)) if enc else "",
                      "guid": html.unescape(g.group(1)).strip() if g
                              else (html.unescape(enc.group(1)) if enc else ""),
                      "desc": html.unescape(de.group(1)).strip() if de else "",
                      "img": html.unescape(img.group(1)).strip() if img else ""})
    return items


def norm(s):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (s or "").lower())


def _banned_check(name):
    """IsBannedWords 語義（iter-5 實錘）：裸 bool——True=違禁／False=通過；
    兼容 dict 型 {success:false}=違禁（tfs_engine 老碼路徑）。"""
    rr = req("POST", f"{BASE}/ting/IsBannedWords",
             data={"name": name, "channelId": ""}, timeout=30)
    try:
        res = rr.json()
        if isinstance(res, bool):
            return res                       # False=通過（iter-5 四候選全誤判的根因）
        if isinstance(res, dict):
            return res.get("success") is False
    except Exception:
        pass
    return False                             # 解析失敗≠違禁——照常嘗試


def channel_id(force=False):
    """CID 解析：secret OB_CID → trail/ob_channel.json → ensure（冪等自建）。
    頻道名多候選（iter-3：全名被 IsBannedWords 拒→依序試至過審）。"""
    cid = os.environ.get("OB_CID", "")
    if cid and not force:
        return cid
    saved = rj(CHFILE, {}) or {}
    if saved.get("cid") and not force:
        return saved["cid"]
    names = [saved.get("name")] if saved.get("name") else []
    names += [n for n in CH_NAME_CANDS if n not in names]
    r = req("GET", f"{BASE}/ting/GetPrivateChannels", timeout=45)
    have = {html.unescape(c.get("Name") or ""): c["Id"]
            for c in (r.json().get("channelList", {}).get("UploadedChannels") or [])}
    for nm in names:                          # 已存在的候選名優先（冪等）
        if nm in have:
            log(f"channel found: {nm} → {have[nm]}")
            wj(CHFILE, {"cid": have[nm], "name": nm, "at": time.strftime("%F %T")})
            return have[nm]
    for nm in names:                          # 逐候選過審→create
        if _banned_check(nm):
            log(f"  banned skip: {nm}")
            continue
        r = req("POST", f"{BASE}/ting/CreatePrivateChannel",
                data={"name": nm, "thumb": "", "channelType": "",
                      "description": CH_DESC}, timeout=45)
        if r.status_code == 200 and '"success":true' in (r.text or "").replace(" ", ""):
            log(f"channel created: {nm}")
            have = {html.unescape(c.get("Name") or ""): c["Id"]
                    for c in (req("GET", f"{BASE}/ting/GetPrivateChannels", timeout=45)
                              .json().get("channelList", {}).get("UploadedChannels") or [])}
            if nm in have:
                wj(CHFILE, {"cid": have[nm], "name": nm, "at": time.strftime("%F %T")})
                return have[nm]
        log(f"  create fail: {r.status_code} {(r.text or '')[:60]}")
        time.sleep(3)
    raise RuntimeError(f"all channel-name candidates rejected/banned: {names}")


def have_titles(cid):
    out = set()
    for pg in range(50):      # 3 頁上限會讓 dup 防線對舊集失效（tfs 繼承審計缺口 E）
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
    """UploadTingFile?type=thumb → fileId（tfs_engine 兩步式流程）。
    11-25 深夜根因修復：舊版把 multipart 直砸 uploadprivatemedia（媒體建立表單端點）
    ＝錯誤端點——500 保存异常實為 API 誤用（同窗 tff-rotate 經 UploadTingFile 上傳成功×5）。"""
    for i in range(6):
        busy = False
        try:
            r = req("POST", f"{BASE}/ting/UploadTingFile?type=thumb",
                    files={"file": ("cover.jpg", img, "image/jpeg")}, timeout=180)
            j = r.json()
            if j.get("success") and (j.get("fileId") or j.get("result")):
                return j.get("fileId") or j.get("result").split("/")[-1]
            busy = "处理程序" in (r.text or "") or "还在处理" in (r.text or "")
            log(f"  thumb try{i}: {(r.text or '')[:90]}")
        except AuthError:
            raise
        except Exception as ex:
            log(f"  thumb try{i} err: {str(ex)[:70]}")
        time.sleep(45 if busy else min(3 + 3 * i, 18))
    return None


_THUMB = {"fid": ""}


def thumb_fid(img):
    """頻道封面每 run 只上傳一次（tfs 72h-cache 的 per-run 版）——逐集重傳＝浪費＋孤兒 thumb 檔。"""
    if not img:
        return ""
    if not _THUMB["fid"]:
        _THUMB["fid"] = upload_thumb(img) or ""
    return _THUMB["fid"]


def upload_media(path):
    """UploadTingFile?type=media → fileId。GitHub runner→歐路上行 ~23KB/s（tfs 實測）：
    12.8MB≈9-10min/次 → 長 socket timeout＋少量 tries（OB_MEDIA_TIMEOUT 預設 900s×2）。"""
    payload = open(path, "rb").read()
    timeout = int(os.environ.get("OB_MEDIA_TIMEOUT", "900"))
    for i in range(2):
        busy = False
        try:
            r = req("POST", f"{BASE}/ting/UploadTingFile?type=media",
                    files={"file": (os.path.basename(path), payload, "audio/mpeg")},
                    timeout=timeout)
            j = r.json()
            if j.get("success") and (j.get("fileId") or j.get("result")):
                return j.get("fileId") or j.get("result").split("/")[-1]
            busy = "处理程序" in (r.text or "") or "还在处理" in (r.text or "")
            log(f"  upload try{i}: {(r.text or '')[:90]}")
        except AuthError:
            raise
        except Exception as ex:
            log(f"  upload try{i} err: {str(ex)[:70]}")
        time.sleep(45 if busy else min(3 + 3 * i, 18))
    return None


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


SLOT_BUSY = ("处理程序", "资源处理", "资源进程")
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
            flat = (r.text or "").replace(" ", "")
            # 11-26 根因修復（殭屍 run 45727889185 驗屍）：uploadprivatemedia 成功回
            # {"code":200,"message":"保存成功","data":null}——舊判定抄 DeletePriveteMedia
            # 的 "success":true 形狀→永不認成功→每集連傳 5 份＋判失敗不入帳本。
            # 對齊 tfs_engine（895 集實證）的 code:200 判定；busy 訊息補 资源进程。
            if r.status_code == 200 and ('"code":200' in flat or '"success":true' in flat):
                return True
            txt = r.text or ""
            if any(b in txt for b in SLOT_BUSY):
                log(f"  slot busy — wait 90s（{k + 1}/10）")
                time.sleep(90)
                continue
            log(f"  post try{k}: {r.status_code} {txt[:80]}")
            time.sleep(8)
        except AuthError:
            raise
        except Exception as ex:
            log(f"  post try{k} err: {str(ex)[:80]}")
            time.sleep(8)
    return False


OB_GROUP = os.environ.get("OB_GROUP_NAME", "On Being")


def ensure_ob_group(cid):
    """tfs ensure_group 繼承（繼承審計缺口 F，11-26 用戶點名）：ob 頻道綁進分組。
    Eudic 分組＝ChannelType-2 頻道實體（CreatePrivateChannel?itemtype=7 →
    AddChannelsToPrivateGroup{groupId,channelIds}）。只在缺綁時 POST（重綁會重排）。"""
    try:
        gl = (req("POST", f"{BASE}/ting/GetPrivateGroups?withDefault=false",
                  data="", timeout=40).json()
              .get("channelList", {}).get("UploadedChannels", []))
        grp = next((c for c in gl if c.get("Name") == OB_GROUP), None)
        if not grp:
            # 11-26 用戶已自行改名分組——名稱找不到時，僅剩的一個非 TFF/HTF/Bulwark
            # 分組視為 OB 分組（ob_face_maint 偵查同款啟發法）。
            unk = [c for c in gl
                   if not any((c.get("Id") or "").startswith(p)
                              for p in ("9007fbda", "de9abbba", "87c5aed8"))]
            if len(unk) == 1:
                grp = unk[0]
                log(f"  group by-elimination: {grp.get('Name')!r}")
        if not grp:
            r = req("POST", f"{BASE}/ting/CreatePrivateChannel?itemtype=7",
                    data={"name": OB_GROUP, "thumb": "", "channelType": "2",
                          "description": "On Being with Krista Tippett 全集搬運分組"}, timeout=40)
            log(f"  group create: {r.status_code} {(r.text or '')[:60]}")
            gl = (req("POST", f"{BASE}/ting/GetPrivateGroups?withDefault=false",
                      data="", timeout=40).json()
                  .get("channelList", {}).get("UploadedChannels", []))
            grp = next((c for c in gl if c.get("Name") == OB_GROUP), None)
            if not grp:
                log("  group create failed — skip (retry next run)")
                return
        gid = grp["Id"]
        binds = set(rj(BINDS, []) or [])
        if cid in binds:
            log("  group bind: 已綁（binds 記錄）— skip")
            return
        r = req("POST", f"{BASE}/ting/AddChannelsToPrivateGroup",
                data=[("groupId", gid), ("channelIds", cid)], timeout=60)
        log(f"  group bind: {r.status_code} {(r.text or '')[:60]}")
        if r.status_code == 200:
            binds.add(cid)
            wj(BINDS, sorted(binds))
    except Exception as ex:
        log(f"  group err（非致命）: {str(ex)[:80]}")


def feed_channel_art():
    """RSS 頻道級插畫（<channel> 的 itunes:image）→ bytes|None。"""
    try:
        r = retry(lambda: requests.get(FEED, headers=UA, timeout=90))
        head = (r.text or "")[:60000]
        m = re.search(r"<itunes:image[^>]*href=\"([^\"]+)\"", head) or \
            re.search(r"<image>.*?<url>([^<]+)</url>", head, re.S)
        if not m:
            return None
        img = requests.get(m.group(1), headers=UA, timeout=60)
        return img.content if img.status_code == 200 and len(img.content) > 5000 else None
    except Exception as ex:
        log(f"feed art err: {str(ex)[:60]}")
        return None


def ensure_channel_cover(cid, name):
    """頻道級封面（11-26 用戶問責：ob 從未設過——create 時 thumb 空，各集 fallback 也拿不到）。
    缺封面→RSS 頻道插畫→UploadTingFile→UpdatePrivateChannel（thumb 不可空——正是本呼叫在補）。"""
    try:
        r = req("GET", f"{BASE}/ting/GetPrivateChannels", timeout=45)
        ch = next((c for c in (r.json().get("channelList", {}).get("UploadedChannels") or [])
                   if c.get("Id") == cid), None)
        if not ch:
            return
        cur = ch.get("Thumb") or ""
        if cur and "default.png" not in cur:
            log("channel cover: 已有（跳過）")
            return
        art = feed_channel_art()
        if not art:
            log("channel cover: RSS 無頻道插畫——維持預設")
            return
        fid = upload_thumb(art)
        if not fid:
            log("channel cover: 上傳失敗（下輪再試）")
            return
        r2 = req("POST", f"{BASE}/ting/UpdatePrivateChannel",
                 data={"id": cid, "name": name or ch.get("Name", ""), "thumb": fid,
                       "channelType": ch.get("ChannelType") or "",
                       "description": html.unescape(ch.get("Description") or "")},
                 timeout=60)
        log(f"channel cover: UpdatePrivateChannel {r2.status_code} {(r2.text or '')[:50]}")
    except Exception as ex:
        log(f"channel cover err（非致命）: {str(ex)[:80]}")


def _ch_base_name():
    """頻道命名基底＝現在的頻道名剝掉既有「001-100」區段後綴（用戶改名後跟隨）。"""
    saved = rj(CHFILE, {}) or {}
    nm = saved.get("name") or "On Being"
    return re.sub(r"\s*\d{3}-\d{3}\s*$", "", nm).strip() or nm


def maybe_rotate(cid, ledger):
    """頻道容量輪轉（11-26 用戶裁定：比照 TFF 每 100 集開新頻，之後隨更新續開）。
    n_done=帳本數（heal＋backfill 全計）→ 目標頻道序 = n_done // CH_CAP；
    當前序落後才補建（冪等；一次建到目標序）。新頻自動：封面＋分組＋登記簿。"""
    try:
        n_done = len(ledger)
        idx_tgt = n_done // CH_CAP
        reg = rj(OBCHS, []) or []
        idx_cur = next((i for i, r in enumerate(reg) if r.get("cid") == cid), None)
        if idx_cur is None:                       # 首頻未登記 → 補登記
            reg = [{"cid": cid, "name": (rj(CHFILE, {}) or {}).get("name") or "On Being",
                    "lo": 1, "hi": CH_CAP, "at": time.strftime("%F %T")}]
            wj(OBCHS, reg)
            idx_cur = 0
        if idx_tgt <= idx_cur:
            return cid
        for idx in range(idx_cur + 1, idx_tgt + 1):
            lo, hi = idx * CH_CAP + 1, (idx + 1) * CH_CAP
            nm = f"{_ch_base_name()} {lo:03d}-{hi:03d}"
            if _banned_check(nm):
                nm = f"{_ch_base_name()}-{lo:03d}-{hi:03d}"      # 過審變體
            r = req("POST", f"{BASE}/ting/CreatePrivateChannel",
                    data={"name": nm, "thumb": "", "channelType": "",
                          "description": CH_DESC}, timeout=45)
            if not (r.status_code == 200
                    and '"success":true' in (r.text or "").replace(" ", "")):
                log(f"rotate: create fail {r.status_code} {(r.text or '')[:60]}")
                return cid
            have = {html.unescape(c.get("Name") or ""): c["Id"]
                    for c in (req("GET", f"{BASE}/ting/GetPrivateChannels", timeout=45)
                              .json().get("channelList", {})
                              .get("UploadedChannels") or [])}
            if nm not in have:
                log(f"rotate: created but not listed: {nm}")
                return cid
            ncid = have[nm]
            log(f"rotate: 頻道 #{idx + 1} 建立 {nm} → {ncid}")
            ensure_channel_cover(ncid, nm)
            ensure_ob_group(ncid)
            reg.append({"cid": ncid, "name": nm, "lo": lo, "hi": hi,
                        "at": time.strftime("%F %T")})
            wj(OBCHS, reg)
            wj(CHFILE, {"cid": ncid, "name": nm, "at": time.strftime("%F %T")})
            cid = ncid
            ntfy("On Being 開新頻", f"{nm}（第 {lo}-{hi} 集）已建立＋封面＋分組。", 2)
        return cid
    except Exception as ex:
        log(f"rotate err（非致命）: {str(ex)[:80]}")
        return cid


_EPART = {}                                # per-ep 插畫快取（URL→fid；多分片共用一次上傳）
def ep_thumb_fid(e, fallback_img):
    """各集封面（11-26 用戶要求）：per-item RSS 插畫→上傳（URL 快取）；無→沿用頻道封面。"""
    u = e.get("img") or ""
    if u:
        if u in _EPART:
            return _EPART[u]
        try:
            img = requests.get(u, headers=UA, timeout=60).content
        except Exception:
            img = b""
        if len(img) > 5000:
            f = upload_thumb(img)
            _EPART[u] = f or ""
            if f:
                return _EPART[u]
    return thumb_fid(fallback_img)


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
    ensure_ob_group(cid)
    ensure_channel_cover(cid, (rj(CHFILE, {}) or {}).get("name", ""))
    cover = channel_cover_bytes(cid)
    items = rss_items()
    catalog = [e for e in items if e["url"]]
    dead = len(items) - len(catalog)
    ledger = rj(LEDGER, {}) or {}
    have = set()                             # 跨頻道並集（輪轉後 dedup-skip 仍有效）
    for _r in [x for x in (rj(OBCHS, []) or []) if x.get("cid")] + [{"cid": cid}]:
        try:
            have |= have_titles(_r["cid"])
        except Exception:
            pass
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
    _pre = cid
    cid = maybe_rotate(cid, ledger)          # 容量輪轉（滿 100 開新頻；11-26 用戶裁定）
    if cid != _pre:
        cover = channel_cover_bytes(cid)     # fallback 用 logo——重抓（同 feed logo，保險）
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
    marked = parts_marked()
    for e in todo:
        key = e["date"].strftime("%Y%m%d")
        full = f'{e["date"].strftime("%F")} {e["title"]}'
        log(f"▶ {full[:64]}")
        try:
            parts = prep_audio(e["url"], key)
            ok_all = True
            ep_mids = []
            for pf, i, n in parts:
                ptitle = full if n == 1 else f"{full}（{i}/{n}）"
                if norm(ptitle) in have or (e["guid"], i) in marked:
                    continue
                fid = ep_thumb_fid(e, cover)
                media_fid = upload_media(pf)
                if not media_fid:            # 上傳耗盡→本集失敗下輪續傳（TFF 同款；免雙層重試拖爆輪預算）
                    raise RuntimeError("media upload failed (UploadTingFile exhausted)")
                sid = None
                if eudic_slots and os.environ.get("GH_TOKEN"):
                    try:
                        sid = eudic_slots.claim("ob", media_fid, os.environ["GH_TOKEN"],
                                                wait_min=8, ttl=300, log=log)
                    except Exception:
                        sid = None
                okp = True
                try:
                    # >60min 集（分段 n>1）平台拒 AI 字幕→自動 false
                    okp = post(cid, ptitle, fid, media_fid, strip_html(e["desc"]),
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
                if e["guid"]:
                    parts_mark(e["guid"], i, full, cid, media_fid)
                    marked.add((e["guid"], i))
                ep_mids.append(media_fid)
                time.sleep(3)
            if ok_all:
                synced += 1
                if e["guid"]:
                    ledger[e["guid"]] = {"title": full, "pub": e["date"].strftime("%F"),
                                         "at": time.strftime("%F %T"),
                                         "how": "backfill" if BACKFILL else "daily",
                                         "mids": ep_mids}   # dedup 正主錨點
                    wj(LEDGER, ledger)        # kill-safe：每集成功即落帳
                    if BACKFILL:
                        _git_progress()       # per-ep 進度落 git（跨 run 存活）
                    cid = maybe_rotate(cid, ledger)   # 滿額即開新頻（下集進新頻）
            else:
                failed.append(full[:50])
        except Exception as ex:
            log(f"  ✗ {str(ex)[:110]}")
            if isinstance(ex, AuthError) and not _RELOGIN[0]:
                _RELOGIN[0] = 1       # tfs auto_relogin 繼承：首次 AuthError→密碼重登，後續集正常
                try:
                    login()
                    log("  ↻ mid-run relogin OK——後續集正常；本集下輪續傳")
                except Exception as le:
                    log(f"  relogin err: {str(le)[:60]}")
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
    if synced == 0 and todo:
        ntfy(f"On Being sync: TOTAL FAIL 0/{len(todo)}",
             body + "\n全數失敗——疑似平台端故障（保存異常類）。GA 標記 failure；下輪排程自動續傳。", 4)
        log("done (exit 1: zero-sync total failure)")
        sys.exit(1)                       # 全敗＝GA failure——success conclusion 不得掩蓋零產出（11-25 教訓）
    ntfy(f"On Being sync: {'PARTIAL' if failed else 'OK'} {synced}/{len(todo)}", body, 4 if failed else 3)
    log("done")


if __name__ == "__main__":
    main()
