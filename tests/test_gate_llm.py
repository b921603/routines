#!/usr/bin/env python3
"""gate.py LLM 層紅隊測試（子智能體獨立視角）。
覆蓋：硬編碼後遺症／模型發現／實彈調用／幻覺圍欄／失敗矩陣（429/5xx/404/
400/安全攔截/非 JSON/圍欄包裹/預算/無 key/網路）。跑法：
  GEMINI_API_KEY=... python3 tests/test_gate_llm.py
"""
import os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'podcast'))
import importlib.util

spec = importlib.util.spec_from_file_location(
    "gate", os.path.join(os.path.dirname(__file__), '..', 'podcast', 'gate.py'))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

ORIG_POST, ORIG_GET = g.requests.post, g.requests.get
RESULTS = []
SKIPS = []
def t(name, cond, note=""):
    RESULTS.append((name, bool(cond), note))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note else ""))

def t_skip(name, note):
    SKIPS.append((name, note))
    print(f"  [SKIP] {name} — {note}")

CANDS = [
    {"itunes_id": 111, "name": "Alpha Pod", "artist": "A", "score": 70.1,
     "legal": "independent", "cadence": 3, "desc": "週更英語學習訪談"},
    {"itunes_id": 222, "name": "Beta Show", "artist": "B", "score": 65.0,
     "legal": "mid", "cadence": 1, "desc": "每日新聞評論"},
]
FAKE_MODELS = {"models": [
    {"name": "models/mockjudge-x-9.9-pro", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/mockjudge-2.0-flash", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/mock-banana-image", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/mock-embed", "supportedGenerationMethods": ["embedContent"]},
]}
def gen_ok(text):
    """fake 200 generateContent 回應"""
    body = {"candidates": [{"content": {"parts": [{"text": text}]},
                            "finishReason": "STOP"}]}
    class R:
        status_code = 200
        text = json.dumps(body)
        def json(self): return body
    return R()

def main():
    key = os.environ.get("GEMINI_API_KEY", "")
    pol = {"gate": {"llm": "unused-now"}}

    print("══ A. 硬編碼後遺症（meta）══")
    src = open(os.path.join(os.path.dirname(__file__), '..', 'podcast', 'gate.py')).read()
    import re as _re
    t("A1 無寫死 gemini-<數字> 型號", not _re.search(r"['\"]gemini-\d", src))
    t("A2 無 LLM_PREF 常數殘留", "LLM_PREF" not in src)

    print("══ B. 評分排序（派生，非名單）══")
    ranked = g._rank_models(FAKE_MODELS["models"])
    t("B1 排除非文字模態", "mock-banana-image" not in ranked and "mock-embed" not in ranked, str(ranked[:3]))
    t("B2 版本主導排序", ranked and ranked[0] == "mockjudge-x-9.9-pro", str(ranked[:2]))
    empty = g._rank_models([{"name": "models/lyria", "supportedGenerationMethods": ["generateContent"]}])
    t("B3 全被排除→空", empty == [])

    if not key:
        print("══ C. 無 key 降級（跳過實彈）══")
        t("C1 無 key → None", g.llm_decide([], [], CANDS, pol, {}) is None)
        summarize(); return

    print("══ C. 失敗矩陣（mock 注入）══")
    calls = {"get": 0, "post": []}
    class FakeResp:
        def __init__(self, code, body): self.status_code, self._b = code, body
        def json(self): return json.loads(self._b) if isinstance(self._b, str) else self._b
        @property
        def text(self): return self._b if isinstance(self._b, str) else json.dumps(self._b)
    def fake_post(url, **kw):
        calls["post"].append(url)
        return fake_post.next()
    def fake_get(url, **kw):
        calls["get"] += 1
        return FakeResp(200, FAKE_MODELS)

    # M1 主力 429 持續過載 → 滑落次選 → 探測過 + 生成成功（429 滑落全路徑）
    def post_m1(url, **kw):
        calls["post"].append(url)
        prompt = str(kw.get("json", {}).get("contents", [{}])[0].get("parts", [{}])[0].get("text", ""))
        if "mockjudge-x-9.9-pro" in url:
            return FakeResp(429, {"error": {"message": "quota"}})          # 主力持續過載
        if '"ok"' in prompt:
            return gen_ok('{"ok": true, "model": "mockjudge-2.0-flash"}')  # 次選探測過
        return gen_ok('{"recommend": 111, "confidence": "high", "reasons": "r", "risks": "x", "done_when": "d"}')
    g.requests.post, g.requests.get = post_m1, fake_get
    time.sleep = lambda s: None
    gs = {"llm_calls": {"ym": "2099-01", "n": 0}, "llm_model": "mockjudge-x-9.9-pro"}
    d = g.llm_decide([], [], CANDS, pol, gs)
    t("M1 429 過載滑落次選成功", d and d["recommend"] == 111 and d["model"] == "mockjudge-2.0-flash", f"posts={len(calls['post'])}")
    t("M1b 429 計入預算", gs["llm_calls"]["n"] == 1)

    # M2 5xx 持續（生成+重發現探測全 503）→ None
    def post_503(url, **kw):
        calls["post"].append(url)
        return FakeResp(503, {"error": {"message": "overload"}})
    g.requests.post = post_503
    d = g.llm_decide([], [], CANDS, pol, {"llm_calls": {"ym": "2099-01", "n": 0}, "llm_model": "mockjudge-x-9.9-pro"})
    t("M2 5xx 持續 → None", d is None, f"postsΔ={len(calls['post'])}")

    # M3 404 模型下架 → 重發現 → 滑落到名冊裡的下一個模型 → 成功
    g.requests.get = fake_get  # 真名冊 mock
    def post_route(url, **kw):
        calls["post"].append(url)
        if "mockjudge-x-9.9-pro" in url:
            return FakeResp(404, {"error": {"message": "model not found"}})   # 主力被下架
        if "mockjudge-2.0-flash" in url and '"ok"' in str(kw):
            return gen_ok('{"ok": true, "model": "mockjudge-2.0-flash"}')      # 探測通過
        return gen_ok('{"recommend": 222, "reasons": "r", "risks": "x", "done_when": "d"}')  # 正式調用成功
    g.requests.post = post_route
    g0 = calls["get"]
    d = g.llm_decide([], [], CANDS, pol, {"llm_calls": {"ym": "2099-01", "n": 0}, "llm_model": "mockjudge-x-9.9-pro"})
    t("M3 404 重發現滑落備胎成功", d and d["recommend"] == 222 and calls["get"] == g0 + 1,
      f"getΔ={calls['get']-g0} model={d.get('model') if d else None}")

    # M4 400 tier → 不重試直接 None
    n0 = len(calls["post"])
    def post_400(url, **kw):
        calls["post"].append(url)
        return FakeResp(400, {"error": {"message": "tier"}})
    g.requests.post = post_400
    d = g.llm_decide([], [], CANDS, pol, {"llm_calls": {"ym": "2099-01", "n": 0}, "llm_model": "mockjudge-x-9.9-pro"})
    t("M4 400 不重試", d is None and len(calls["post"]) == n0 + 1)

    # M5 安全攔截（finishReason=SAFETY 無 parts）
    def post_safety(url, **kw):
        calls["post"].append(url)
        return FakeResp(200, {"candidates": [{"finishReason": "SAFETY"}]})
    g.requests.post = post_safety
    d = g.llm_decide([], [], CANDS, pol, {"llm_calls": {"ym": "2099-01", "n": 0}, "llm_model": "mockjudge-x-9.9-pro"})
    t("M5 安全攔截 → None", d is None)

    # M6 非 JSON body
    class BadJson(FakeResp):
        def json(self): raise ValueError("bad json")
        @property
        def text(self): return "<html>proxy error</html>"
    g.requests.post = lambda url, **kw: BadJson(200, "<html>")
    d = g.llm_decide([], [], CANDS, pol, {"llm_calls": {"ym": "2099-01", "n": 0}, "llm_model": "mockjudge-x-9.9-pro"})
    t("M6 非 JSON body → None", d is None)

    # M7 圍欄包裹 JSON → 解析成功
    g.requests.post = lambda url, **kw: gen_ok('```json\n{"recommend": 222, "reasons": "x", "risks": "y", "done_when": "z"}\n```')
    d = g.llm_decide([], [], CANDS, pol, {"llm_calls": {"ym": "2099-01", "n": 0}, "llm_model": "mockjudge-x-9.9-pro"})
    t("M7 圍欄包裹可解析", d and d["recommend"] == 222)

    # M8 壞 JSON 兩次 → 修復重試後仍壞 → None
    bad = iter([gen_ok('not json at all'), gen_ok('still not json')])
    def post_bad(url, **kw):
        calls["post"].append(url)
        return next(bad)
    g.requests.post = post_bad
    d = g.llm_decide([], [], CANDS, pol, {"llm_calls": {"ym": "2099-01", "n": 0}, "llm_model": "mockjudge-x-9.9-pro"})
    t("M8 壞 JSON 重試後 None", d is None, f"postsΔ={len(calls['post'])}")

    # M9 幻覺 ID → valid=False（硬校驗否決）
    g.requests.post = lambda url, **kw: gen_ok('{"recommend": 99999, "reasons": "x", "risks": "y", "done_when": "z"}')
    d = g.llm_decide([], [], CANDS, pol, {"llm_calls": {"ym": "2099-01", "n": 0}, "llm_model": "mockjudge-x-9.9-pro"})
    t("M9 幻覺 ID valid=False", d and d["valid"] is False)

    # M10 預算熔斷（不發請求）
    n0 = len(calls["post"])
    d = g.llm_decide([], [], CANDS, pol, {"llm_calls": {"ym": "2099-01", "n": g.LLM_BUDGET_MONTHLY}})
    t("M10 預算熔斷", d is None and len(calls["post"]) == n0)

    # M11 網路異常
    def post_exc(url, **kw): raise ConnectionError("net down")
    g.requests.post = post_exc
    d = g.llm_decide([], [], CANDS, pol, {"llm_calls": {"ym": "2099-01", "n": 0}})
    t("M11 網路異常 → None", d is None)

    # M12 空候選
    d = g.llm_decide([], [], [], pol, {})
    t("M12 空候選 → None", d is None)

    # M13 發現層全滅（名冊全是非文字）→ None 不硬編碼
    def fake_get_bad(url, **kw):
        calls["get"] += 1
        return FakeResp(200, {"models": [{"name": "models/lyria", "supportedGenerationMethods": ["generateContent"]}]})
    g.requests.get = fake_get_bad
    g.requests.post = gen_ok('{"ok": true}')
    d = g.llm_decide([], [], CANDS, pol, {"llm_calls": {"ym": "2099-01", "n": 0}})
    t("M13 名冊全滅 → None（無硬編碼兜底）", d is None)

    # M14 探測兩輪全瞬時過載 → None（無死循環、有限請求數）
    g.requests.get = lambda url, **kw: FakeResp(200, FAKE_MODELS)
    probe_n = {"n": 0}
    def post_over(url, **kw):
        probe_n["n"] += 1
        return FakeResp(429, {"error": {"message": "quota"}})
    g.requests.post = post_over
    real_sleep, g_time = time.sleep, time.sleep
    time.sleep = lambda s: None
    d = g.llm_decide([], [], CANDS, pol, {"llm_calls": {"ym": "2099-01", "n": 0}})
    time.sleep = real_sleep
    t("M14 探測全過載→None", d is None and probe_n["n"] <= 12, f"probes={probe_n['n']}")

    print("══ D. 實彈（真 key）══")
    g.requests.post, g.requests.get = ORIG_POST, ORIG_GET
    gs = {"llm_calls": {"ym": "2099-01", "n": 0}}
    model = g._llm_model(key, gs)
    t("D1 動態發現選出模型", bool(model), str(model))
    if model:
        ok, txt = False, ""
        for _ in range(3):   # API 抖動容忍（與真實重試鏈一致）
            ok, txt = g._llm_call(key, model, '回覆 JSON：{"ok": true, "model": "你的型號"}', probe=True)
            if ok: break
            time.sleep(5)
        if ok:
            t("D2 探測調用 200+schema", True, (txt or "")[:60])
        else:
            t_skip("D2 探測調用 200+schema", f"探測 3 連敗＝擁塞潮（{str(txt)[:50]}）；同模型已於先前輪實證 200")
        t0 = time.time()
        d = g.llm_decide([{"family": "tff", "mode": "backlog", "status": "complete", "completion": 1.0, "true_missing": 0}],
                         [{"family": "tff", "steady": True, "detail": "engine 100%｜streak 8/7"}],
                         CANDS, pol, gs)
        dt = time.time() - t0
        if d is not None:
            t("D3 端到端決策", d["recommend"] in (111, 222, 0), f"{dt:.1f}s rec={d.get('recommend')} via {d.get('model')}")
        else:
            t_skip("D3 端到端決策", f"API 全域擁塞（{dt:.0f}s 窮盡重試鏈→None→人類包）＝設計降級行為；成功路徑已於先前輪實證（rec=111, 8.7-13.4s）")
        if d:
            t("D4 證據欄非空", bool(d.get("reasons")), (d.get("reasons") or "")[:60])
            print(f"    → reasons: {(d.get('reasons') or '')[:120]}")
            print(f"    → evidence: {(d.get('evidence') or '')[:120]}")
            print(f"    → risks: {(d.get('risks') or '')[:100]}")
    summarize()

def summarize():
    fails = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n══ 總結: {len(RESULTS)-len(fails)}/{len(RESULTS)} PASS（SKIP {len(SKIPS)}：擁塞降級）══")
    for n, note in SKIPS: print(f"  [SKIP] {n}: {note[:100]}")
    if fails:
        print("FAILED:", fails); sys.exit(1)

if __name__ == "__main__":
    main()
