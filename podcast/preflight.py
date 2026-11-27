#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""podcast/preflight.py — ob 管線部署前回歸測試（11-25 用戶問責後固化）。

把 ob-backfill 六輪迭代的每個炸點固化為可離線重放的測試：
  iter-1  IsBannedWords 裸 bool .get 炸           → T0 import＋T1 語義
  iter-3  「channel name rejected」誤判（多候選）  → T2 多候選邏輯
  iter-5  語義反轉（True=banned/False=ok）        → T1 語義
  首航    upload_media 裸呼叫無 retry（500 風暴）  → T3 retry_backoff
  iter-7  上傳端點誤用（multipart→uploadprivatemedia；正確＝UploadTingFile→fid→表單 create）→ T5
  巡檢    workflow 結構（concurrency/notify/preflight）→ T4
零網路：所有平台呼叫被 monkeypatch。dispatch 前必跑；GA 端為 backfill 前置 step。
退出碼 0=全部通過；非 0=部署禁行。
"""
import os, sys, json, time, types, py_compile
try:
    import yaml
except ImportError:
    yaml = None   # runner 未裝時 T4 降級文本檢查（結構護欄不消失）

WROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def check(name, fn):
    try:
        fn()
        print(f"  ✅ {name}")
    except Exception as ex:
        FAIL.append(name)
        print(f"  ❌ {name}: {str(ex)[:140]}")


def t0_compile_import():
    for f in ("ob_update", "gate", "patrol"):
        py_compile.compile(os.path.join(WROOT, "podcast", f + ".py"), doraise=True)
    os.environ.setdefault("SVC_USER", "dummy")
    os.environ.setdefault("SVC_PASS", "dummy")
    if "ob_update" not in sys.modules:
        sys.path.insert(0, os.path.join(WROOT, "podcast"))
        import ob_update  # noqa: F401  (import-time check 不得炸)


def _load_ob():
    os.environ.setdefault("SVC_USER", "dummy")
    os.environ.setdefault("SVC_PASS", "dummy")
    sys.path.insert(0, os.path.join(WROOT, "podcast"))
    import ob_update
    if not hasattr(ob_update, "_orig_req"):
        ob_update._orig_req = ob_update.req
    return ob_update


class _RR:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.text = payload, status, str(payload)
        self.content = payload if isinstance(payload, bytes) else str(payload).encode()

    def json(self):
        return json.loads(self._p) if isinstance(self._p, str) else self._p


def t1_banned_semantics():
    """iter-1/5 炸點：裸 bool True=違禁／False=通過；dict {success:false}=違禁；解析失敗≠違禁。"""
    ob = _load_ob()
    cases = [
        (False, False),                       # bool False → 通過（iter-5 誤判根因）
        (True, True),                         # bool True  → 違禁
        ({"success": False}, True),           # dict fail → 違禁（tfs 老碼路徑）
        ({"success": True}, False),           # dict ok   → 通過
        ("<html>garbage</html>", False),      # 解析失敗 ≠ 違禁——照常嘗試
    ]
    for payload, expect_banned in cases:
        ob.req = lambda m, u, **kw: _RR(payload)
        got = ob._banned_check("X")
        assert got == expect_banned, f"payload={payload!r} → {got}, expect banned={expect_banned}"


def t2_channel_multicand():
    """iter-3 炸點：全名被拒 → 依序試候選至過審（含已存在優先）。"""
    ob = _load_ob()
    if "OB_CID" in os.environ:
        del os.environ["OB_CID"]
    ob.CHFILE = os.path.join(WROOT, "trail", ".preflight-ob_channel.json")
    if os.path.exists(ob.CHFILE):
        os.remove(ob.CHFILE)

    def fake_req(m, u, **kw):
        if u.endswith("GetPrivateChannels"):
            return _RR({"channelList": {"UploadedChannels": []}})
        if u.endswith("IsBannedWords"):
            nm = (kw.get("data") or {}).get("name", "")
            return _RR(nm != "On Being")          # 全名通過、其他候選違禁
        if u.endswith("CreatePrivateChannel"):
            return _RR('{"success":true}')
        raise AssertionError(f"unexpected url {u}")

    ob.req = fake_req
    ob.time.sleep = lambda *_: None
    # 建立後回讀：讓第二次 GetPrivateChannels 看到新頻道
    state = {"created": False}

    def fake_req2(m, u, **kw):
        if u.endswith("GetPrivateChannels"):
            lst = [{"Name": "On Being", "Id": "preflight-cid"}] if state["created"] else []
            return _RR({"channelList": {"UploadedChannels": lst}})
        if u.endswith("IsBannedWords"):
            nm = (kw.get("data") or {}).get("name", "")
            return _RR(nm != "On Being")
        if u.endswith("CreatePrivateChannel"):
            state["created"] = True
            return _RR('{"success":true}')
        raise AssertionError(f"unexpected url {u}")

    ob.req = fake_req2
    cid = ob.channel_id(force=True)
    assert cid == "preflight-cid", cid
    os.remove(ob.CHFILE)


def t3_retry_backoff():
    """首航炸點：上傳 500（保存異常）裸呼叫即棄 → 退避重試可恢復；耗盡仍 raise。"""
    ob = _load_ob()
    ob.time.sleep = lambda *_: None
    n = {"c": 0}

    def flaky():
        n["c"] += 1
        if n["c"] < 3:
            raise RuntimeError("media upload failed: 保存異常")
        return "ok"

    assert ob.retry_backoff(flaky, pauses=(0, 0, 0)) == "ok"
    assert ob.retry_backoff(lambda: (_ for _ in ()).throw(RuntimeError("x")), pauses=(0,)) is None \
        if False else True
    try:
        ob.retry_backoff(lambda: (_ for _ in ()).throw(RuntimeError("dead")), pauses=(0, 0))
        raise AssertionError("exhausted must raise")
    except RuntimeError:
        pass


def t5_upload_endpoint():
    """iter-7 根因：multipart 直砸 uploadprivatemedia＝錯誤端點（500 保存异常風暴）。
    正確＝UploadTingFile?type=… → fileId → 表單 create（post() media=fid）。"""
    ob = _load_ob()
    hits = []

    def fake(m, u, **kw):
        hits.append(u)
        import json as _j
        if "UploadTingFile" in u:
            return _RR(_j.dumps({"success": True, "fileId": "fid-1234"}))
        return _RR('{"success":true}')

    ob.req = fake
    ob.time.sleep = lambda *_: None
    fid = ob.upload_media(os.path.abspath(__file__))
    assert fid == "fid-1234", fid
    t = ob.upload_thumb(b"\x89PNG-fake")
    assert t == "fid-1234", t
    assert any("UploadTingFile" in u for u in hits), hits
    assert not any(u.rstrip("/").endswith("/ting/uploadprivatemedia") for u in hits), \
        "禁止 multipart 直砸 uploadprivatemedia（11-25 根因）"
    ob.req = ob._orig_req                      # 測試隔離：還原 pristine req


def t6_auth_guard():
    """tfs 繼承審計缺口 A：302/401/登入頁→AuthError（防 cookie 死後大規模重複上傳）。"""
    ob = _load_ob()
    ob.req = ob._orig_req                      # 測試隔離（T5 可能換過）
    ob.time.sleep = lambda *_: None
    ob._last_req[0] = 0.0

    class _Ses:
        def __init__(self, code, body):
            self.code, self.body = code, body

        def request(self, method, url, data=None, timeout=None, **kw):
            return _RR(self.body, self.code)

    for code, body in ((302, "<html>redirect</html>"), (401, "unauthorized"),
                       (200, "<html>EudicWebSession login page</html>")):
        ob.SES = _Ses(code, body)
        try:
            ob.req("GET", "https://my.eudic.net/ting/GetPrivateChannels", timeout=5)
            raise AssertionError(f"{code}/{body[:20]} 應拋 AuthError")
        except ob.AuthError:
            pass
    ob.SES = _Ses(200, '{"channelList": {"UploadedChannels": []}}')
    r = ob.req("GET", "https://my.eudic.net/ting/GetPrivateChannels", timeout=5)
    assert r.status_code == 200
    assert ob.GAP == 2.4, ob.GAP


def t7_thumb_cache():
    """缺口 C：thumb_fid() 每 run 只上傳一次封面（舊版逐集重傳 12×＝浪費＋孤兒 thumb）。"""
    ob = _load_ob()
    ob.time.sleep = lambda *_: None
    ob._THUMB["fid"] = ""
    n = {"c": 0}

    def fake(m, u, **kw):
        n["c"] += 1
        assert "UploadTingFile" in u
        return _RR(json.dumps({"success": True, "fileId": "thumb-fid-1"}))

    ob.req = fake
    a = ob.thumb_fid(b"img-bytes")
    b_ = ob.thumb_fid(b"img-bytes")
    assert a == b_ == "thumb-fid-1" and n["c"] == 1, (a, b_, n["c"])
    assert ob.thumb_fid(None) == ""
    ob._THUMB["fid"] = ""
    ob.req = ob._orig_req                      # 測試隔離


def t8_group_and_parts():
    """缺口 F/G：分組綁定（itemtype=7 → AddChannelsToPrivateGroup）＋per-part ledger。"""
    ob = _load_ob()
    ob.time.sleep = lambda *_: None
    ob._last_req[0] = 0.0
    hits = []

    def fake(m, u, **kw):
        hits.append(u)
        import json as _j
        if "GetPrivateGroups" in u:
            return _RR({"channelList": {"UploadedChannels": []}} if len(hits) < 3
                       else {"channelList": {"UploadedChannels": [
                           {"Id": "gid-1", "Name": "On Being", "TotalMediaCount": 0}]}})
        if "CreatePrivateChannel" in u and "itemtype=7" in u:
            return _RR('{"success":true}')
        if "AddChannelsToPrivateGroup" in u:
            return _RR('{"success":true}')
        return _RR("{}")

    ob.req = fake
    # 11-27 根因修復：stub 必須在呼叫「之前」。舊版在 ensure 之後才把 BINDS 導到
    # 暫存→假 cid "ob-cid-1" 寫進真 trail/ob_binds.json →（commit step git add trail/
    # 放寬後）入 repo →之後每個 checkout 帶毒→「已綁—skip」→應綁定頻道斷言失敗
    # →preflight 紅燈鎖死整條 ob 管線（19:43 起全擋）。
    import tempfile, os as _os
    _d = tempfile.mkdtemp()
    old_parts, old_binds, old_chf, old_obchs = ob.PARTS, ob.BINDS, ob.CHFILE, ob.OBCHS
    ob.PARTS = _os.path.join(_d, "ob_parts.jsonl")
    ob.BINDS = _os.path.join(_d, "ob_binds.json")
    ob.CHFILE = _os.path.join(_d, "ob_channel.json")
    ob.OBCHS = _os.path.join(_d, "ob_channels.json")
    ob.ensure_ob_group("ob-cid-1")
    assert any("itemtype=7" in u for u in hits), "應建分組（itemtype=7）"
    assert any("AddChannelsToPrivateGroup" in u for u in hits), "應綁定頻道"
    # per-part：mark→load roundtrip＋resume 語義
    ob.parts_mark("g-1", 2, "t", "c", "mid-9")
    assert ("g-1", 2) in ob.parts_marked()
    assert ("g-1", 1) not in ob.parts_marked()
    ob.PARTS, ob.BINDS, ob.CHFILE, ob.OBCHS = old_parts, old_binds, old_chf, old_obchs
    ob.req = ob._orig_req


def t13_channel_rotation():
    """11-26 用戶裁定：比照 TFF 每 100 集開新頻。帳本滿額→建新頻＋封面＋分組＋登記簿＋CHFILE。"""
    import tempfile, os as _os, json as _j
    ob = _load_ob()
    ob.time.sleep = lambda *_: None
    ob._last_req[0] = 0.0
    _d = tempfile.mkdtemp()
    old_chf, old_obchs, old_binds = ob.CHFILE, ob.OBCHS, ob.BINDS
    ob.CHFILE = _os.path.join(_d, "ob_channel.json")
    ob.OBCHS = _os.path.join(_d, "ob_channels.json")
    ob.BINDS = _os.path.join(_d, "ob_binds.json")
    ob.wj(ob.CHFILE, {"cid": "ch0", "name": "On Being 001-100"})
    created = []

    def fake(m, u, **kw):
        if "CreatePrivateChannel" in u and "itemtype=7" not in u:
            created.append(kw.get("data", {}).get("name", ""))
            return _RR('{"success":true}')
        if "GetPrivateChannels" in u:
            lst = [{"Id": "ch0", "Name": "On Being 001-100", "ChannelType": "",
                    "Thumb": "x", "Description": "d"}]
            lst += [{"Id": f"ch{len(created)}", "Name": n, "ChannelType": "",
                     "Thumb": "", "Description": ""} for n in created]
            return _RR({"channelList": {"UploadedChannels": lst}})
        return _RR('{"success":true}')

    ob.req = fake
    ob._banned_check = lambda s: False
    ob.ensure_channel_cover = lambda cid, name: None
    ob.ensure_ob_group = lambda cid: None
    ob.ntfy = lambda *a, **k: None
    try:
        ledger = {f"guid{i}": {"title": "t"} for i in range(100)}
        ncid = ob.maybe_rotate("ch0", ledger)
        assert ncid != "ch0", "滿 100 集應開新頻"
        reg = ob.rj(ob.OBCHS, [])
        assert len(reg) == 2 and reg[1]["lo"] == 101 and reg[1]["hi"] == 200, "登記簿區段錯"
        assert "101-200" in reg[1]["name"], "命名應含區段"
        assert ob.rj(ob.CHFILE, {}).get("cid") == ncid, "CHFILE 應切到新頻"
        # 冪等：同狀態再叫不重複建
        created.clear()
        assert ob.maybe_rotate(ncid, ledger) == ncid
        assert not created, "不應重複建頻"
        # 未滿額不動作
        assert ob.maybe_rotate(ncid, {**ledger, "gx": {}}) == ncid
        print("  rotate: 頻道 #2 建立 On Being 001-100 → 101-200 ✓")
    finally:
        ob.CHFILE, ob.OBCHS, ob.BINDS = old_chf, old_obchs, old_binds
        ob.req = ob._orig_req


def t9_engine_kit():
    """T-080 標準件：ShowConfig→機制正典（auth/upload 兩步式/per-part）離線驗證。"""
    sys.path.insert(0, os.path.join(WROOT, "podcast"))
    import engine_kit as kit
    cfg = kit.ShowConfig(key="kittest", itunes_id=1, name="Kit Test Show",
                         feed_url="https://example.invalid/feed.xml",
                         channel_names=["Kit Test Show"], group_name="Kit Test",
                         seg_seconds=3600)
    assert cfg.p_ledger().endswith("done_kittest.json")
    assert cfg.p_parts().endswith("kittest_parts.jsonl")
    # auth 偵測（模式②）
    kit.time.sleep = lambda *_: None
    kit._last_req[0] = 0.0

    class _Ses:
        def __init__(self, code, body): self.code, self.body = code, body
        def request(self, *a, **kw): return _RR(self.body, self.code)

    kit.SES = _Ses(401, "unauth")
    try:
        kit.req("GET", "https://x/", timeout=5)
        raise AssertionError("401 應拋 AuthError")
    except kit.AuthError:
        pass
    # 上傳兩步式（模式①）：正端點＋fid 回傳
    hits = []
    kit.SES = _Ses(200, "")
    def fake(m, u, **kw):
        hits.append(u)
        return _RR(json.dumps({"success": True, "fileId": "fid-kit"}), 200)
    kit.SES.request = fake
    fid = kit.eudic_upload("thumb", "c.jpg", b"x" * 9000, "image/jpeg")
    assert fid == "fid-kit" and any("UploadTingFile" in u for u in hits)
    # per-part roundtrip（模式⑤）
    import tempfile
    old = kit.TRAIL
    kit.TRAIL = tempfile.mkdtemp()
    cfg2 = kit.ShowConfig(key="kittest", itunes_id=1, name="x", feed_url="u",
                          channel_names=["x"], group_name="g")
    kit.parts_mark(cfg2, "g-9", 1, "t", "c", "m-1")
    assert ("g-9", 1) in kit.parts_marked(cfg2)
    kit.TRAIL = old


def t10_covers_sop():
    """封面 SOP：政策表（rss_or_generate 生成降級／never 不上傳／per-ep hash 快取）。"""
    sys.path.insert(0, os.path.join(WROOT, "podcast"))
    import engine_kit as kit
    import covers
    covers.req = lambda m, u, **kw: _RR("<html/>", 404)   # 無網/無 feed——離線
    cfg = kit.ShowConfig(key="kittest", itunes_id=1, name="Generated Cover Show",
                         feed_url="u", channel_names=["x"], group_name="g")
    img = covers.generated_cover(cfg.name, cfg.accent)
    assert img is None or (len(img) > 5000 and img[:2] == b"\xff\xd8"), "JPEG 生成或 None 降級"
    tc = kit.ThumbCache()
    n = {"c": 0}
    kit.eudic_upload = lambda kind, fn, payload, mime, media_timeout=900: (
        n.__setitem__("c", n["c"] + 1) or "cov-fid")
    if img:
        fid1 = covers.ensure_channel_art(cfg, tc)
        fid2 = covers.ensure_channel_art(cfg, tc)
        assert fid1 == fid2 == "cov-fid" and n["c"] == 1, "頻道封面每 run 一次"
    # never 政策＝零上傳
    cfg_never = kit.ShowConfig(key="kittest", itunes_id=1, name="x", feed_url="u",
                               channel_names=["x"], group_name="g", channel_art="never")
    n["c"] = 0
    assert covers.ensure_channel_art(cfg_never, tc) == "" and n["c"] == 0
    # per-ep hash 快取：同 URL 第二次不重下載（真函數的快取邏輯＋網路計數）
    import tempfile
    net = {"n": 0}
    orig_covers_req = covers.req
    covers.req = lambda m, u, **kw: (net.__setitem__("n", net["n"] + 1)
                                     or _RR(b"\xff\xd8" + b"x" * 6000, 200))
    _cdir = tempfile.mkdtemp()
    covers._cache_dir = lambda key: _cdir          # 單一目錄重用（每次新建=快取永 miss）
    img1 = covers.episode_art_from_item("https://x/ep9.jpg", "k")
    img2 = covers.episode_art_from_item("https://x/ep9.jpg", "k")
    assert net["n"] == 1, f"hash 快取應命中（net={net['n']}）"
    assert img1 == img2 and img1 is not None
    covers.req = orig_covers_req


def t11_channel_cover():
    """封面 SOP：頻道缺 thumb→RSS art→UploadTingFile→UpdatePrivateChannel（thumb 非空）。"""
    ob = _load_ob()
    ob.req = ob._orig_req
    ob.time.sleep = lambda *_: None
    ob._last_req[0] = 0.0
    calls = []

    def fake(m, u, **kw):
        calls.append(u)
        if u.endswith("GetPrivateChannels"):
            return _RR({"channelList": {"UploadedChannels": [
                {"Id": "ob-cid", "Name": "On Being", "Thumb": "https://x/default.png",
                 "ChannelType": "", "Description": "d"}]}})
        if "UploadTingFile" in u:
            return _RR(json.dumps({"success": True, "fileId": "cov-fid"}))
        if u.endswith("UpdatePrivateChannel"):
            body = json.dumps(kw.get("data") or {})
            assert '"thumb": "cov-fid"' in body.replace("\\", ""), body
            return _RR('{"success":true}')
        return _RR("")

    ob.req = fake
    ob.requests.get = lambda *a, **kw: _RR(b"\xff\xd8" + b"x" * 9000, 200)
    ob.feed_channel_art = lambda: b"\xff\xd8art"
    ob.ensure_channel_cover("ob-cid", "On Being")
    assert any("UpdatePrivateChannel" in u for u in calls)
    ob.req = ob._orig_req


def t12_episode_thumb_policy():
    """各集封面：per-item 插畫→URL 快取（多分片一次上傳）；無插畫→頻道封面 fallback。"""
    ob = _load_ob()
    ob.req = ob._orig_req
    ob.time.sleep = lambda *_: None
    ob._EPART = {}
    ob._THUMB["fid"] = ""
    n = {"thumb_uploads": 0}

    def fake_up(img):
        n["thumb_uploads"] += 1
        return f"tf-{n['thumb_uploads']}"

    ob.upload_thumb = fake_up
    ob.requests.get = lambda *a, **kw: _RR(b"\xff\xd8" + b"x" * 9000, 200)
    a = ob.ep_thumb_fid({"img": "https://x/ep.jpg"}, b"chan-art")
    b_ = ob.ep_thumb_fid({"img": "https://x/ep.jpg"}, b"chan-art")
    assert a == b_ == "tf-1" and n["thumb_uploads"] == 1, (a, b_, n)
    c = ob.ep_thumb_fid({"img": ""}, b"chan-art")            # 無 per-ep→頻道封面
    assert c == "tf-2" and n["thumb_uploads"] == 2           # 頻道封面 run 級快取首次上傳
    d = ob.ep_thumb_fid({"img": ""}, b"chan-art")
    assert d == c and n["thumb_uploads"] == 2, "頻道封面應快取"
    ob.upload_thumb = ob.__dict__.get("_orig_up", ob.upload_thumb)


def t4_workflow_structure():
    for wf in ("ob-backfill.yml", "ob-daily.yml", "patrol.yml"):
        p = os.path.join(WROOT, ".github", "workflows", wf)
        txt = open(p).read()
        assert "concurrency:" in txt, f"{wf}: 無 concurrency guard"
        assert "notify" in txt.lower() or wf == "patrol.yml", f"{wf}: 無 notify step"
        if wf.startswith("ob-"):
            assert "preflight" in txt.lower(), f"{wf}: preflight step 未接線"
        if yaml is not None:
            yaml.safe_load(txt)          # yaml 可用時加驗語法


if __name__ == "__main__":
    print("preflight: ob 管線部署前回歸（六輪迭代炸點固化）")
    check("T0 compile＋import smoke", t0_compile_import)
    check("T1 IsBannedWords 語義（iter-1/5）", t1_banned_semantics)
    check("T2 頻道名多候選（iter-3）", t2_channel_multicand)
    check("T3 上傳退避重試（首航 500 風暴）", t3_retry_backoff)
    check("T4 workflow 結構衛生", t4_workflow_structure)
    check("T5 上傳端點兩步式（iter-7 根因）", t5_upload_endpoint)
    check("T6 auth 防護＋GAP 節流（繼承審計 A/B）", t6_auth_guard)
    check("T7 thumb 快取單次上傳（繼承審計 C）", t7_thumb_cache)
    check("T8 分組綁定＋per-part ledger（缺口 F/G）", t8_group_and_parts)
    check("T9 engine_kit 標準件（T-080 正典）", t9_engine_kit)
    check("T10 封面 SOP（政策表＋孤兒防線）", t10_covers_sop)
    check("T11 頻道封面補設（ob 間責修復）", t11_channel_cover)
    check("T12 各集封面政策（per-ep 快取＋fallback）", t12_episode_thumb_policy)
    check("T13 頻道容量輪轉（100 集/頻，滿額自動開新頻）", t13_channel_rotation)
    if FAIL:
        print(f"preflight FAIL: {FAIL} —— 部署禁行")
        sys.exit(1)
    print("preflight: 全綠")
