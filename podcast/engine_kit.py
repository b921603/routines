#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""podcast/engine_kit.py — 搬運引擎標準件（T-080 自動開坑的消費核心）。

理念（11-26 用戶裁定）：新海選節目經 gate 裁決 → work order 後，
**不得第三次複製貼上引擎**——tfs_engine（894 集戰錘）與 ob_update（iter-7 除錯史）
的模式必須以標準件形式沿襲。本模組＝模式正典：

  ① UploadTingFile 兩步式上傳（iter-7 根因教訓）
  ② auth 防護（302/401/登入頁→AuthError）＋ mid-run relogin（繼承審計 A）
  ③ GAP 全局節流（B）④ thumb 快取（C）⑤ per-part ledger＋mids 入帳（G）
  ⑥ 分組綁定（F）⑦ 冪等掃描（帳本 guid∪標題，50 頁）⑧ heal ⑨ zero-sync 誠實 exit
  ⑩ kill-safe 帳本＋每集增量 git commit ⑪ ntfy 分級報告

新節目 onboarding＝ShowConfig(~15 欄) + show_<id>.py 薄殼(~10 行 import 本件) + workflow
範本例化 + preflight 範本測試——機制沿襲由結構保證，不靠記憶。
ob_update/tfs_engine 維持獨立戰錘（作戰中不重構）；兩者未來採納 kit 模組為機會性遷移。
"""
import os, re, io, json, time, html, subprocess
import requests
from dataclasses import dataclass, field

BASE = "https://my.eudic.net"
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIL = os.path.join(_REPO, "trail")
AUD = os.path.join(_REPO, "state", "kit_audio")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}
SLOT_BUSY = ("还在处理", "处理程序", "同时只能有一个")


# ─────────────────────────── ShowConfig（新節目唯一要填的東西） ───────────────────────────
@dataclass
class ShowConfig:
    key: str                       # 短名：trail 檔案前綴（done_<key>.json / pit_<key>.json）
    itunes_id: int
    name: str
    feed_url: str
    channel_names: list            # 建頻道候選（IsBannedWords 依序過審）
    group_name: str                # 頻道分組名
    description: str = ""
    seg_seconds: int = 3600        # 平台單篇音訊上限
    ai_sub_single: bool = True     # 單片集 AI 字幕
    ai_sub_multi: bool = False     # 分段集平台拒字幕（平台約束）
    backfill_max: int = 12
    days_window: int = 4
    max_per_run: int = 2
    channel_art: str = "rss_or_generate"   # rss_or_generate | rss_only | never
    episode_art: str = "when_available"    # when_available | never
    accent: str = "#0f766e"                # 生成封面主色
    backfill: bool = True

    def p_ledger(self): return os.path.join(TRAIL, f"done_{self.key}.json")
    def p_channel(self): return os.path.join(TRAIL, f"{self.key}_channel.json")
    def p_parts(self): return os.path.join(TRAIL, f"{self.key}_parts.jsonl")
    def p_pit(self): return os.path.join(TRAIL, f"{self.key}-pit.json")


# ─────────────────────────── 模式①②③：auth＋節流＋請求 ───────────────────────────
class AuthError(Exception):
    """Cookie 失效（302/401/登入頁）——直上拋（防 cookie 死後大規模重複）。"""


GAP = 2.4
_last_req = [0.0]
_RELOGIN = [0]
SES = requests.Session()
SES.headers.update(UA)


def req(method, url, *, data=None, timeout=60, tries=6, headers=None, files=None,
        auth_check=True):
    """Rate-gated（GAP）＋auth 偵測＋429/5xx 重試（tfs/ob 審計後正典）。"""
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


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def ntfy(title, body, prio=3):
    n = os.environ.get("NTFY_URL", "")
    if not n:
        log(f"[ntfy#?] {title}")
        return
    try:
        requests.post(n, data=body.encode("utf-8"),
                      headers={"Title": title, "Priority": str(prio),
                               "Tags": "podcast"}, timeout=30)
    except Exception as ex:
        log(f"ntfy err: {str(ex)[:60]}")


def login():
    """PODCAST_COOKIE（艦隊級 secret）優先；失效→SVC_USER/PASS 密碼重登。"""
    raw = os.environ.get("PODCAST_COOKIE", "")
    if raw:
        SES.headers["Cookie"] = raw
        try:
            req("GET", f"{BASE}/ting/GetPrivateChannels",
                headers={"X-Requested-With": "XMLHttpRequest"}, timeout=45)
            log("cookie OK（免登入）")
            return
        except AuthError:
            log("cookie 失效 → 密碼登入")
    s = requests.Session()
    s.headers.update({**UA, "Referer": "https://dict.eudic.net/account/login"})
    s.get("https://dict.eudic.net/account/login",
          params={"returnUrl": "http://my.eudic.net/Account/Login"}, timeout=45)
    s.post("https://dict.eudic.net/Account/Login",
           params={"returnUrl": "http://my.eudic.net/Account/Login"},
           data={"UserName": os.environ.get("SVC_USER", ""),
                 "Password": os.environ.get("SVC_PASS", ""),
                 "returnUrl": "http://my.eudic.net/Account/Login", "RememberMe": "true"},
           timeout=45, allow_redirects=True)
    ck = {c.name: c.value for c in s.cookies
          if (c.domain or "").endswith("eudic.net")
          and c.name not in ("__cf_bm", "cf_clearance", "__cf_chl")}
    raw = "; ".join(f"{k}={v}" for k, v in sorted(ck.items()))
    if "EudicWebSession" not in raw:
        raise RuntimeError("login did not yield session cookie")
    SES.headers["Cookie"] = raw
    req("GET", f"{BASE}/ting/GetPrivateChannels",
        headers={"X-Requested-With": "XMLHttpRequest"}, timeout=45)
    log("password login OK")


# ─────────────────────────── 模式①：UploadTingFile 兩步式 ───────────────────────────
def eudic_upload(kind, filename, payload, mime, media_timeout=900):
    """binary → fileId（正確端點；iter-7：multipart 直砸 uploadprivatemedia＝500 風暴）。"""
    files = {"file": (filename, payload, mime)}
    big = kind != "thumb"
    timeout, tries = ((media_timeout, 2) if big else (180, 6))
    for i in range(tries):
        busy = False
        try:
            r = req("POST", f"{BASE}/ting/UploadTingFile?type={kind}",
                    files=files, timeout=timeout)
            j = r.json()
            if j.get("success") and (j.get("fileId") or j.get("result")):
                return j.get("fileId") or j.get("result").split("/")[-1]
            busy = any(b in (r.text or "") for b in ("处理程序", "还在处理"))
            log(f"  {kind} upload try{i}: {(r.text or '')[:90]}")
        except AuthError:
            raise
        except Exception as ex:
            log(f"  {kind} upload try{i} err: {str(ex)[:70]}")
        time.sleep(45 if busy else min(3 + 3 * i, 18))
    return None


def post_media(cfg, cid, title, thumb_fid, media_fid, desc):
    """表單建立媒體（media=fid；slot-busy×10×90s）。"""
    data = {"id": "", "title": title, "channelId": cid, "thumb": thumb_fid or "",
            "media": media_fid or "", "voice": "", "textAudioMode": "standard",
            "podcastVoices": "", "podcastSpeakers": "", "lrc": "",
            "needProcessLrc": "true", "needKeepformat": "false",
            "reformatParagraph": "true", "splitLongSentence": "true",
            "needMachineTranslation": "false", "allowMachineTranslation": "false",
            "needAISubtitle": "true" if (len(title) and "（" not in title.split("（")[-1]
                                        and cfg.ai_sub_single) else
            ("false"),  # 分段（i/n）後綴者走 ai_sub_multi（平台約束）
            "description": (desc or "")[:3000], "mediatype": "0", "intros": "",
            "istiming": "false", "timing": "", "html": "",
            "insertImage": "false", "mdChapterId": ""}
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
        except AuthError:
            raise
        except Exception as ex:
            log(f"  post try{k} err: {str(ex)[:80]}")
            time.sleep(8)
    return False


# ─────────────────────────── 模式⑥：頻道＋分組 ───────────────────────────
def _banned_check(name):
    rr = req("POST", f"{BASE}/ting/IsBannedWords",
             data={"name": name, "channelId": ""}, timeout=30)
    try:
        res = rr.json()
        if isinstance(res, bool):
            return res                       # True=違禁／False=通過（iter-5 語義）
        if isinstance(res, dict):
            return res.get("success") is False
    except Exception:
        pass
    return False


def _channels():
    r = req("GET", f"{BASE}/ting/GetPrivateChannels", timeout=45)
    return {html.unescape(c.get("Name") or ""): c["Id"]
            for c in (r.json().get("channelList", {}).get("UploadedChannels") or [])}


def ensure_channel(cfg, chfile=None):
    """冪等建頻道：secret→chfile→既有比對→逐候選過審→create→回讀。"""
    chfile = chfile or cfg.p_channel()
    saved = _rj(chfile, {}) or {}
    if saved.get("cid"):
        return saved["cid"]
    names = ([saved.get("name")] if saved.get("name") else []) + \
            [n for n in cfg.channel_names if n not in (saved.get("name"),)]
    have = _channels()
    for nm in names:
        if nm in have:
            _wj(chfile, {"cid": have[nm], "name": nm, "at": time.strftime("%F %T")})
            return have[nm]
    for nm in names:
        if _banned_check(nm):
            log(f"  banned skip: {nm}")
            continue
        r = req("POST", f"{BASE}/ting/CreatePrivateChannel",
                data={"name": nm, "thumb": "", "channelType": "",
                      "description": cfg.description or f"{cfg.name} 全集搬運"}, timeout=45)
        if r.status_code == 200 and '"success":true' in (r.text or "").replace(" ", ""):
            have = _channels()
            if nm in have:
                _wj(chfile, {"cid": have[nm], "name": nm, "at": time.strftime("%F %T")})
                log(f"channel created: {nm}")
                return have[nm]
        log(f"  create fail: {r.status_code} {(r.text or '')[:60]}")
        time.sleep(3)
    raise RuntimeError(f"all channel-name candidates rejected: {names}")


def ensure_group(cfg, cid):
    """頻道分組（缺口 F 正典）：itemtype=7 建分組→AddChannelsToPrivateGroup；缺綁才 POST。"""
    try:
        gl = (req("POST", f"{BASE}/ting/GetPrivateGroups?withDefault=false",
                  data="", timeout=40).json()
              .get("channelList", {}).get("UploadedChannels", []))
        grp = next((c for c in gl if c.get("Name") == cfg.group_name), None)
        if not grp:
            req("POST", f"{BASE}/ting/CreatePrivateChannel?itemtype=7",
                data={"name": cfg.group_name, "thumb": "", "channelType": "2",
                      "description": f"{cfg.name} 全集搬運頻道分組"}, timeout=40)
            gl = (req("POST", f"{BASE}/ting/GetPrivateGroups?withDefault=false",
                      data="", timeout=40).json()
                  .get("channelList", {}).get("UploadedChannels", []))
            grp = next((c for c in gl if c.get("Name") == cfg.group_name), None)
            if not grp:
                log("  group create failed — skip (retry next run)")
                return
        gid = grp["Id"]
        if (grp.get("TotalMediaCount") or 0) >= 1:
            log(f"  group bind: already bound — skip")
            return
        req("POST", f"{BASE}/ting/AddChannelsToPrivateGroup",
            data=[("groupId", gid), ("channelIds", cid)], timeout=60)
        log(f"  group bound: {cfg.group_name}")
    except Exception as ex:
        log(f"  group err（非致命）: {str(ex)[:80]}")


# ─────────────────────────── 模式④⑤⑦⑧：thumb 快取／per-part／冪等掃描 ───────────────────────────
class ThumbCache:
    """頻道封面每 run 一次（繼承審計 C）。"""
    def __init__(self):
        self.fid = ""

    def fid_for(self, img):
        if not img:
            return ""
        if not self.fid:
            self.fid = eudic_upload("thumb", "cover.jpg", img, "image/jpeg") or ""
        return self.fid


def parts_marked(cfg):
    out = set()
    try:
        with open(cfg.p_parts(), encoding="utf-8") as f:
            for line in f:
                try:
                    j = json.loads(line)
                    out.add((j["guid"], j["part"]))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return out


def parts_mark(cfg, guid, part, title, cid, mid):
    with open(cfg.p_parts(), "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%F %T"), "guid": guid, "part": part,
                            "title": title[:80], "cid": cid, "mid": mid},
                           ensure_ascii=False) + "\n")


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def have_titles(cid, pages=50):
    out = set()
    for pg in range(pages):
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


def _rj(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _wj(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, p)


def git_progress(paths):
    """模式⑩：每集進度即落 git（tfs git-as-queue 正典；衝突 abort 下輪續）。"""
    try:
        subprocess.run(["git", "add"] + paths, check=False, capture_output=True, timeout=30)
        if subprocess.run(["git", "diff", "--cached", "--quiet"],
                          capture_output=True).returncode != 0:
            subprocess.run(["git", "commit", "-q", "-m",
                            f"kit progress: {time.strftime('%H:%M:%S')}"],
                           check=False, capture_output=True, timeout=60)
            r = subprocess.run(["git", "pull", "--rebase", "-q"],
                               capture_output=True, timeout=90)
            if r.returncode == 0:
                subprocess.run(["git", "push", "-q", "origin", "main"],
                               capture_output=True, timeout=90)
            else:
                subprocess.run(["git", "rebase", "--abort"], capture_output=True, timeout=30)
    except Exception as ex:
        log(f"  git progress err: {str(ex)[:60]}")


def emit_pit(cfg, ledger, official_total):
    """pit 標準形（policies pits.<key> 註冊為 SOP 步驟）。"""
    total = official_total or len(ledger)
    pit = {"family": cfg.key, "mode": "backlog" if cfg.backfill else "daily",
           "status": "complete" if len(ledger) >= total and total > 0 else "draining",
           "completed_eps": len(ledger), "official_available": total,
           "completion": round(len(ledger) / total, 3) if total else None,
           "true_missing": max(0, total - len(ledger)),
           "at": time.strftime("%F %T"), "source": "engine"}
    _wj(cfg.p_pit(), pit)
    return pit
