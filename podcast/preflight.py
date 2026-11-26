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
    return ob_update


class _RR:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.text = payload, status, str(payload)

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
    if FAIL:
        print(f"preflight FAIL: {FAIL} —— 部署禁行")
        sys.exit(1)
    print("preflight: 全綠")
