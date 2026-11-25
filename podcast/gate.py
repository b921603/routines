#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""podcast/gate.py — 開坑 gate（P4.3 治理層）。

權責三層：政策數字在代碼（硬約束）→ LLM 在額度內判斷 → 人類保例外權。
防無限開坑（11-25 用戶裁示細則）：全部既有坑位補完（status=complete，
可補完性制約：dead link／音檔遺失不計債）＋ WIP 上限——補完前不開新坑
＋月度開坑預算，三者同時滿足才 OPEN；否則 HOLD（附每個坑位的債務進度）。

零平台寫入：只讀 patrol-state.json／candidates.json／policies.json＋
 iTunes Search API。核准≠自動開坑——執行需人類於對話觸發。
無 GEMINI_API_KEY → 自動退回人類 gate（ntfy 附完整決策包）。
"""
import os, json, time, re
import requests
from bulwark_update import ntfy, log

POL = "policies/policies.json"
PSTATE = os.environ.get("PATROL_STATE", "state/patrol-state.json")
GSTATE = "state/gate-state.json"
CAND = "state/candidates.json"


def eligible_top(n=5):
    """候選 DB → 合格開坑候選（fresh＋非 major＋非 avoid＋活躍 cadence）。
    v1.1 schema（db.items=嵌套 dict）；兼容舊 flat 版。"""
    try:
        db = json.load(open(CAND))
    except Exception:
        return []
    raw = db.get("items") if isinstance(db, dict) else None
    entries = raw if isinstance(raw, dict) else {
        k: v for k, v in (db or {}).items()
        if isinstance(v, dict) and "name" in v}
    out = []
    for k, v in entries.items():
        if not isinstance(v, dict) or not str(k).isdigit():
            continue
        cov = v.get("coverage") or {}
        if any((w or {}).get("present") for w in cov.values() if isinstance(w, dict)):
            continue                              # 平台已轉載
        if (v.get("publisher_class") or "") == "major":
            continue                              # 法律風險 → 永遠人類
        if (v.get("status") or "").lower() in ("avoid", "excluded"):
            continue
        rss = v.get("rss") or {}
        if not (rss.get("eps_week") or 0) > 0:
            continue                              # 停更/死鏈
        v2 = (v.get("score") or {}).get("v2")
        sc = v2.get("total") if isinstance(v2, dict) else v2
        out.append({"itunes_id": int(k), "name": v.get("name"),
                    "artist": v.get("artist"),
                    "score": sc,
                    "perennial": v2.get("perennial") if isinstance(v2, dict) else None,
                    "learning": v2.get("learning") if isinstance(v2, dict) else None,
                    "cadence": rss.get("eps_week"),
                    "legal": v.get("publisher_class"),
                    "median_min": rss.get("median_min"),          # 決策證據：單集時長
                    "transcript_tag": rss.get("transcript_tag"),  # 決策證據：官方逐字稿有無
                    "chart_rank": (v.get("chart_rank") or {}),    # 決策證據：榜單熱度
                    "desc": (v.get("description") or "")[:300]})
    out.sort(key=lambda x: -(x["score"] or 0))
    return out[:n]


# —— 動態模型選擇（零硬編碼：名字一律來自 Models API 實查）——
# 排除清單是「模態關鍵詞」不是型號名（模態穩定；型號代號會被下架）
EXCL = re.compile(r"(image|banana|tts|transcribe|audio|live|embed|aqa|robotics|"
                  r"genie|lyria|research|antigravity|computer-use|streaming|"
                  r"realtime|decision|customtools|vision|video|voice|music|omni)", re.I)
VER = re.compile(r"gemini-(\d+)(?:\.(\d+))?")
BASE = "https://generativelanguage.googleapis.com/v1beta"
# 用途匹配：評審任務＝文字推理＋JSON 結構輸出。家族由名字派生：
# pro=旗艦(質量優先) flash=均衡(月度評審剛好) lite=輕量 其他=未標家族
TIER = [("flash-lite", 100), ("lite", 100), ("pro", 300), ("flash", 200)]
LLM_BUDGET_MONTHLY = 60          # 額度保險絲（數字在代碼；日常 ≤31 次/月）
# 現實語境（事實層，供 LLM 決策；不含政策數字——數字只能由代碼執行）
FLEET_CONTEXT = (
    "既有坑位語義：TFF＝英語學習主坑（起點錨定、劇集長壽命）；"
    "HTF＝失敗美學／情感共鳴（名人訪談）；Bulwark＝時事評論（日更、法律 major 風源）。"
    "用戶優先級：比賽展示第一、完成度債優先清償、維護預算保守。"
    "平台現實：歐路免費帳號每頻道資源上限小、上傳帶寬有限→新坑日更成本高，"
    "週更/長錄製節目優於日更（Bulwark 類時事坑除外，已有專線）。"
)


def _rank_models(models):
    """從名冊派生評分排序：版本×家族層＋preview 穩定懲罰；排除非文字模態。"""
    ranked = []
    for m in models or []:
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        name = (m.get("name") or "").replace("models/", "")
        low = name.lower()
        disp = (m.get("displayName") or "").lower()
        if EXCL.search(low) or EXCL.search(disp) or "-exp" in low:
            continue
        v = VER.search(low)
        ver = (int(v.group(1)) + int(v.group(2) or 0) / 10.0) if v else 0.0
        tier = 150                                   # 未標家族（如代號款）
        for pat, sc in TIER:
            if pat in low:
                tier = sc
                break
        if "preview" in low:
            tier -= 50                               # preview 穩定性懲罰
        ranked.append((round(ver * 1000 + tier, 1), name))
    ranked.sort(key=lambda x: -x[0])
    return [n for _, n in ranked]


def _probe_ok(key, model):
    """實彈探測：極小 schema 調用，驗證真的能出結構化 JSON（不聽名字聽行為）。
    回 (ok, err)：err 前綴 http400/404/blocked＝永久性（跳過）；429/5xx＝瞬時（可再試）。"""
    ok, res = _llm_call(key, model,
                        "回覆 JSON：{\"ok\": true, \"model\": \"你的型號\"}", probe=True, node="model_probe")
    if ok:
        try:
            return json.loads(res).get("ok") is True, ""
        except Exception:
            return False, "exc:badjson"
    return False, res


LLM_MODEL_TTL_DAYS = 7            # 模型快取效期：AI 迭代 3-4 週/代 → 7 天必重查名冊


def _llm_model(key, gs):
    """發現鏈：快取（TTL 7 天）→ Models API 實查 → 評分排序 → 逐個探測取首個可用。
    探測兩輪：瞬時過載（429/5xx）退避重試一輪；結構性失效（400/404/攔截）直接出局。
    無硬編碼名字；全部探測失敗回 None（上層降級人類決策包）。"""
    c = gs.get("llm_model")
    at = gs.get("llm_model_at") or 0
    fresh = (time.time() - at) < LLM_MODEL_TTL_DAYS * 86400
    if c and fresh:
        return c
    try:
        r = requests.get(f"{BASE}/models?key={key}&pageSize=200", timeout=30)
        if r.status_code != 200:
            log(f"llm listing http{r.status_code}")
            return None
        ranked = _rank_models(r.json().get("models"))
        log(f"llm discovery: {len(ranked)} candidates: {ranked[:5]}")
        dead = set()
        for round_ in range(2):
            transient = []
            for cand in ranked[:10]:
                if cand in dead:
                    continue
                ok, err = _probe_ok(key, cand)
                if ok:
                    gs["llm_model"] = cand
                    gs["llm_model_at"] = time.time()
                    log(f"llm model selected: {cand}")
                    return cand
                if err.startswith(("http400", "http404", "blocked")):
                    dead.add(cand)                      # 永久：下架/tier 不符/攔截
                else:
                    transient.append((cand, err[:50]))  # 瞬時：過載/超時
            if not transient:
                break
            log(f"llm probe round{round_} transient: {transient[:3]} — backoff 15s")
            time.sleep(15)
        log("llm probe exhausted (all dead or overloaded)")
    except Exception as ex:
        log(f"llm discovery err: {str(ex)[:90]}")
    return None


def _llm_budget_ok(gs):
    ym = time.strftime("%Y-%m")
    b = gs.get("llm_calls") or {}
    if b.get("ym") != ym:
        b = {"ym": ym, "n": 0}
    if b["n"] >= LLM_BUDGET_MONTHLY:
        log("llm budget exhausted this month")
        return False, b
    return True, b


SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "recommend": {"type": "INTEGER"},
        "confidence": {"type": "STRING", "enum": ["high", "med", "low"]},
        "reasons": {"type": "STRING"},
        "risks": {"type": "STRING"},
        "done_when": {"type": "STRING"},
        "evidence": {"type": "STRING"},
    },
    "required": ["recommend", "reasons", "risks", "done_when"],
}

# 裁決網絡各節點的 response schema（API 級強制輸出形狀——11-25 demo 實證：
# 全局 SCHEMA 會把 N1 shortlist 壓成 decision 形 → 節點永遠解析為空）
NET_SCHEMAS = {
    "N1_screen": {"type": "OBJECT", "properties": {
        "shortlist": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "note": {"type": "STRING"}}, "required": ["shortlist"]},
    "N2_deep": {"type": "OBJECT", "properties": {
        "ranked": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "itunes_id": {"type": "INTEGER"}, "score_100": {"type": "INTEGER"},
            "learn": {"type": "STRING"}, "perennial_arg": {"type": "STRING"},
            "risk": {"type": "STRING"}},
            "required": ["itunes_id", "score_100"]}},
        "note": {"type": "STRING"}}, "required": ["ranked"]},
    "N3_redteam": {"type": "OBJECT", "properties": {
        "veto": {"type": "BOOLEAN"}, "fatal_risks": {"type": "STRING"},
        "hardening": {"type": "STRING"}}, "required": ["veto"]},
    "N4_taste": {"type": "OBJECT", "properties": {
        "final_pick": {"type": "INTEGER"}, "five_year_case": {"type": "STRING"},
        "taste_note": {"type": "STRING"}}, "required": ["final_pick", "five_year_case"]},
    "decision": SCHEMA,
}


def _llm_call(key, model, prompt, probe=False, node="llm", schema=None):
    """帶節點追蹤的單發調用：每次 LLM 調用記 node/model/ok/延遲/原始 output → TRACE。"""
    t0 = time.time()
    ok, res = _llm_call_raw(key, model, prompt, probe, schema)
    _trace_node(node, model, ok, "" if ok else res,
                int((time.time() - t0) * 1000), len(prompt), res if ok else "")
    return ok, res


def _llm_call_raw(key, model, prompt, probe=False, schema=None):
    """單發調用；回 (ok, text|err)。處理：HTTP 錯誤矩陣／安全攔截／非 JSON body。"""
    cfg = {"temperature": 0.4,
           "response_mime_type": "application/json",
           "response_schema": schema or SCHEMA}
    if probe:
        cfg = {"temperature": 0.0, "maxOutputTokens": 2000,
               "response_mime_type": "application/json",
               "response_schema": {"type": "OBJECT", "properties": {
                   "ok": {"type": "BOOLEAN"}, "model": {"type": "STRING"}}}}
    try:
        r = requests.post(
            f"{BASE}/models/{model}:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": cfg},
            timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            return False, f"http{r.status_code}"
        if r.status_code != 200:
            try:
                msg = str(r.json().get("error", {}).get("message", ""))[:80]
            except Exception:
                msg = (r.text or "")[:80]
            return False, f"http{r.status_code}:{msg}"
        try:
            j = r.json()
        except Exception:
            return False, "exc:non-json body"
        cand = (j.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        if cand.get("finishReason") in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT",
                                        "BLOCKLIST", "SPII") or not parts:
            return False, f"blocked:{cand.get('finishReason')}"
        return True, (parts[0].get("text") or "").strip()
    except Exception as ex:
        return False, f"exc:{str(ex)[:80]}"


def _strip_fences(t):
    """防模型自作主張包 ```json 圍欄。"""
    t = (t or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t


# —— LLM 節點追蹤（11-25 用戶要求：每個 LLM 節點的 output 與生成模型必須可見）——
TRACE = []

def _trace_node(node, model, ok, err, latency_ms, prompt_chars, output):
    TRACE.append({"node": node, "model": model, "ok": ok,
                  "err": (err or "")[:80], "latency_ms": latency_ms,
                  "prompt_chars": prompt_chars, "output": (output or "")[:4000],
                  "at": time.strftime("%H:%M:%S")})


def llm_decide(pits, steady, cands, pol, gs=None):
    """Gemini 在政策額度內挑選。圍欄：schema 強制結構＋硬校驗＋一次修復重試＋
    失敗矩陣（429/5xx 退避→人類包；404 模型下架→重發現；任何失敗只降級不阻塞）。"""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key or not cands:
        return None
    gs = gs if gs is not None else {}
    ok_b, calls = _llm_budget_ok(gs)
    if not ok_b:
        return None
    model = os.environ.get("GEMINI_MODEL") or _llm_model(key, gs)
    if not model:
        return None
    prompt = (
        "你是播客搬運管線的開坑審核官。政策數字已由代碼驗證（WIP 上限/月預算/"
        "既有坑位補完=complete，可補完性制約）——你只在合格候選中挑選或建議觀望，"
        "\n\n【策展核心＝雋永的亮點（用戶 2026-11-25，源於 Tools of Titans 初心）】"
        "\n推薦前必須回答：『5 年後這檔還值得聽嗎？』"
        "\n- perennial 維度（0-15）是硬證據：≥10 才推薦；<6 除非人類例外"
        "\n- 時事/新聞/政治類：須證明珍珠層（恆久內容占比≥30%，如深度專家訪談）"
        "且提供語言浸潤價值，否則 recommend=0 並註明 reason"
        "\n- 優先：心智/科學/歷史/哲學/意義/失敗與復原類"
        "\n- 受眾是英語學習者：發音清晰度與敘事品質是加分項（評估不可及時標 unknown）"
        "無權放寬任何約束（政策否決權屬於代碼與人類）。\n"
        + FLEET_CONTEXT + "\n"
        f"現有坑位：{json.dumps(pits, ensure_ascii=False)}\n"
        f"steady 判定：{json.dumps(steady, ensure_ascii=False)}\n"
        f"合格候選 Top{len(cands)}：{json.dumps(cands, ensure_ascii=False)}\n"
        "評選規則：學習價值＞更新穩定性＞法律低風險（independent＞mid＞major）；"
        "避免與既有坑位語義重疊；節目型態需匹配上傳帶寬現實。"
        "證據紀律：理由必須引用輸入欄位（evidence 欄註明引用了哪些欄位）；"
        "輸入不足就 recommend=0（觀望）並在 done_when 說明缺什麼證據。\n"
        '僅輸出 JSON：{"recommend": <itunes_id 或 0>, "confidence": "high|med|low", '
        '"reasons": "...", "risks": "...", "done_when": "...", "evidence": "..."}'
    )
    calls["n"] += 1
    gs["llm_calls"] = calls
    txt = None
    transient = 0
    for attempt in range(6):  # 退避重試鏈（含模型滑落；503 過載窗需更長冷卻）
        ok, res = _llm_call(key, model, prompt, node="decision")
        if ok:
            txt = res
            break
        log(f"llm call attempt{attempt} [{model}]: {res[:90]}")
        if res.startswith("http404") or res.startswith("http400:models/"):
            gs.pop("llm_model", None)          # 模型下架/tier 收回→重發現→續鏈
            model = _llm_model(key, gs)
            if not model:
                return None
            continue
        if "API key not valid" in res:
            gs["llm_key_dead"] = time.time()   # key 被吊銷——上層發 ntfy 告警
            return None
        if res.startswith("http429") or res.startswith("http5") or res.startswith("exc:Read"):
            transient += 1                     # 瞬時過載
            time.sleep(8 * (attempt + 1))      # 503 過載窗：加長退避
            if transient >= 2:                 # 連續過載→換模型（可能是 tier 額度）
                gs.pop("llm_model", None)
                model = _llm_model(key, gs)
                if not model:
                    return None
                transient = 0
            continue
        break                                  # 400 tier／安全攔截——交人類
    if not txt:
        return None
    d = None
    for round_ in range(2):
        try:
            d = json.loads(_strip_fences(txt))
            int(d.get("recommend") or 0)
            break
        except Exception:
            if round_ == 0:                    # 一次修復重試（帶錯誤回饋）
                ok, res = _llm_call(key, model, prompt + (
                    f"\n你的上一個輸出不是合法 JSON（錯誤：{txt[:60]}）。"
                    "重新輸出，僅 JSON，無其他文字。"), node="decision_repair")
                if not ok:
                    return None
                txt = res
            else:
                return None
    if not isinstance(d, dict):
        return None
    try:
        rid = int(d.get("recommend") or 0)
    except Exception:
        return None
    valid = any(c["itunes_id"] == rid for c in cands) if rid else True
    return {"recommend": rid,
            "confidence": (d.get("confidence") or "")[:10],
            "reasons": (d.get("reasons") or "")[:400],
            "risks": (d.get("risks") or "")[:300],
            "done_when": (d.get("done_when") or "")[:300],
            "evidence": (d.get("evidence") or "")[:200],
            "valid": valid, "model": model}


# —— 裁決網絡 v1（11-25 用戶授權：完全由 gate 裁斷；品味被授權可高於人類）——
# N1 初篩 → N2 深評 → N3 紅隊 → N4 審美；每節點 output＋生成模型全落 TRACE。
# 降級梯：任一節點失敗 → 單節點 llm_decide → 仍失敗 → 人類決策包。
NET_BUDGET_PER_RUN = 40          # 單次 gate 運行的網絡調用上限（防網絡失控）


def _net_call(key, model, prompt, node, gs):
    """網絡節點共用調用：預算護欄＋JSON 解析。回 dict 或 None（None=節點失敗）。"""
    if (gs.get("net_calls") or 0) >= NET_BUDGET_PER_RUN:
        log(f"net {node}: budget cap")
        return None
    gs["net_calls"] = (gs.get("net_calls") or 0) + 1
    ym = time.strftime("%Y-%m")
    b = gs.get("llm_calls") or {}
    if b.get("ym") != ym:
        b = {"ym": ym, "n": 0}
    b["n"] += 1
    gs["llm_calls"] = b                       # 網絡呼叫計入月額度（11-25 補漏）
    ok, txt = _llm_call(key, model, prompt, node=node, schema=NET_SCHEMAS.get(node, SCHEMA))
    if not ok:
        return None
    try:
        d = json.loads(_strip_fences(txt))
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def node_screen(key, model, cands, gs):
    """N1 初篩（輕量）：候選 → 值得深評的 shortlist。id 硬校驗（必在清單內）。"""
    rows = [{"id": c["itunes_id"], "name": c["name"], "v2": c["score"],
             "perennial": c.get("perennial"), "learning": c.get("learning"),
             "legal": c["legal"], "ep_wk": c["cadence"],
             "min": c["median_min"], "desc": (c.get("desc") or "")[:120]}
            for c in cands]
    prompt = ("你是播客開坑管線的初篩節點。策展核心＝雋永的亮點（5 年後還值得聽）。\n"
              "任務：挑出值得深評的 4-6 個（排除：時事耗品、與既有坑位語義重疊、純娛樂無學習價值）。\n"
              + FLEET_CONTEXT +
              "\n候選：" + json.dumps(rows, ensure_ascii=False) +
              '\n僅輸出 JSON：{"shortlist": [id...], "note": "一句話篩選邏輯"}')
    d = _net_call(key, model, prompt, "N1_screen", gs)
    if not d:
        return None
    ids = [int(i) for i in (d.get("shortlist") or []) if str(i).isdigit()]
    ids = [i for i in ids if any(c["itunes_id"] == i for c in cands)]     # 硬校驗
    return {"ids": ids, "note": (d.get("note") or "")[:200]}


def node_deep(key, model, short, gs):
    """N2 深評：三項論證（學習/雋永/風險）＋排序。id 硬校驗。"""
    rows = [{"id": c["itunes_id"], "name": c["name"], "v2": c["score"],
             "perennial": c.get("perennial"), "learning": c.get("learning"),
             "legal": c["legal"], "ep_wk": c["cadence"], "min": c["median_min"],
             "transcript": c["transcript_tag"], "desc": (c.get("desc") or "")[:300]}
            for c in short]
    prompt = ("你是開坑管線的深評節點。對每個候選論證：學習價值（英語學習者獲得什麼）、"
              "雋永論證（5 年後為何還值得聽——必須引用 perennial 分與節目型態）、風險。按價值排序。\n"
              + FLEET_CONTEXT +
              "\n候選：" + json.dumps(rows, ensure_ascii=False) +
              '\n僅輸出 JSON：{"ranked": [{"itunes_id": <id>, "score_100": <0-100>, '
              '"learn": "...", "perennial_arg": "...", "risk": "..."}], "note": "..."}')
    d = _net_call(key, model, prompt, "N2_deep", gs)
    if not d:
        return None
    ids = {c["itunes_id"] for c in short}
    ranked = []
    for r in (d.get("ranked") or []):
        try:
            if int(r.get("itunes_id")) in ids:
                ranked.append({"itunes_id": int(r["itunes_id"]),
                               "score_100": int(r.get("score_100") or 0),
                               "learn": (r.get("learn") or "")[:300],
                               "perennial_arg": (r.get("perennial_arg") or "")[:300],
                               "risk": (r.get("risk") or "")[:200]})
        except Exception:
            continue
    ranked.sort(key=lambda x: -x["score_100"])
    return {"ranked": ranked, "note": (d.get("note") or "")[:200]}


def node_redteam(key, model, pick, pits, steady, gs):
    """N3 紅隊：對抗審查——找致命風險；veto=True 否決該候選。節點失敗默認放行待人類複核。"""
    prompt = ("你是紅隊審查節點。攻擊以下開坑推薦：找致命風險（版權/頻道資源上限/帶寬/"
              "語義重疊/主講人依賴/棄坑跡象）。存在不可緩解的致命風險才 veto；否則給強化建議。\n"
              + FLEET_CONTEXT +
              f"\n現有坑位：{json.dumps(pits, ensure_ascii=False)}"
              f"\n穩定性：{json.dumps(steady, ensure_ascii=False)}"
              "\n推薦：" + json.dumps(pick, ensure_ascii=False) +
              '\n僅輸出 JSON：{"veto": <true|false>, "fatal_risks": "...", "hardening": "..."}')
    d = _net_call(key, model, prompt, "N3_redteam", gs)
    if not d:
        return {"veto": False, "fatal_risks": "(紅隊節點失敗——放行待人類複核)", "hardening": ""}
    return {"veto": bool(d.get("veto")),
            "fatal_risks": (d.get("fatal_risks") or "")[:300],
            "hardening": (d.get("hardening") or "")[:300]}


def node_taste(key, model, survivors, deep_by_id, gs):
    """N4 審美終審：5 年判詞；品味被授權可高於人類直覺。id 硬校驗。"""
    rows = [{"id": c["itunes_id"], "name": c["name"], "perennial": c.get("perennial"),
             "deep": deep_by_id.get(c["itunes_id"], {})} for c in survivors]
    prompt = ("你是策展人終審節點，品味標準＝雋永的亮點（Tools of Titans 初心）。"
              "選出最終推薦並寫 5 年判詞：為什麼它值得長期佔用一個坑位。"
              "容許選出與人類直覺不同但更雋永的選擇（你的品味被授權可高於人類）。\n"
              + FLEET_CONTEXT +
              "\n倖存候選：" + json.dumps(rows, ensure_ascii=False) +
              '\n僅輸出 JSON：{"final_pick": <id>, "five_year_case": "...", "taste_note": "..."}')
    d = _net_call(key, model, prompt, "N4_taste", gs)
    if not d:
        return None
    try:
        fid = int(d.get("final_pick"))
    except Exception:
        return None
    if fid not in {c["itunes_id"] for c in survivors}:
        return None                                                    # 硬校驗
    return {"final_pick": fid,
            "five_year_case": (d.get("five_year_case") or "")[:400],
            "taste_note": (d.get("taste_note") or "")[:200]}


def _fallback_decide(pits, steady, cands, pol, gs, why):
    dec = llm_decide(pits, steady, cands, pol, gs)
    if dec:
        dec["evidence"] = f"[降級 {why}] " + (dec.get("evidence") or "")
    return dec


def net_decide(pits, steady, cands, pol, gs=None):
    """裁決網絡 v1 編排：N1→N2→N3→N4。任一環節失敗→降級單節點→再失敗→人類包。"""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key or not cands:
        return None
    gs = gs if gs is not None else {}
    ok_b, calls = _llm_budget_ok(gs)
    if not ok_b:
        return None
    model = os.environ.get("GEMINI_MODEL") or _llm_model(key, gs)
    if not model:
        return None
    gs["net_calls"] = 0
    s1 = node_screen(key, model, cands, gs)
    if not s1 or not s1["ids"]:
        log("net: N1 empty → single-node fallback")
        return _fallback_decide(pits, steady, cands, pol, gs, "N1_empty")
    short = [c for c in cands if c["itunes_id"] in s1["ids"]][:6]
    r2 = node_deep(key, model, short, gs)
    ranked = (r2 or {}).get("ranked") or []
    if not ranked:
        log("net: N2 empty → single-node fallback")
        return _fallback_decide(pits, steady, cands, pol, gs, "N2_empty")
    deep_by_id = {r["itunes_id"]: r for r in ranked}
    order = [next(c for c in short if c["itunes_id"] == r["itunes_id"]) for r in ranked]
    survivors, rt_log = list(order), []
    for pick in list(order):
        rt = node_redteam(key, model, pick, pits, steady, gs)
        rt_log.append({"pick": pick["itunes_id"], **rt})
        if rt["veto"]:
            survivors.remove(pick)
        if len(survivors) <= 1:
            break
    if not survivors:
        log("net: 紅隊全否決 → 觀望")
        return {"recommend": 0, "confidence": "high", "model": model,
                "reasons": "紅隊否決全部深評推薦（詳見 gate-llm-trace.json）",
                "risks": "; ".join(r["fatal_risks"] for r in rt_log if r.get("fatal_risks"))[:300],
                "done_when": "出現更強候選或紅隊風險緩解後重審", "evidence": "N1→N2→N3 全鏈",
                "valid": True, "net": {"N1": s1["note"], "N2": r2["note"], "redteam": rt_log}}
    t4 = node_taste(key, model, survivors, deep_by_id, gs)
    if not t4:
        log("net: N4 fallback → deep order top")
        final = survivors[0]
        five_year = deep_by_id.get(final["itunes_id"], {}).get("perennial_arg", "")
        taste_note = "(N4 失敗—沿用 N2 排序)"
    else:
        final = next(c for c in survivors if c["itunes_id"] == t4["final_pick"])
        five_year = t4["five_year_case"]
        taste_note = t4["taste_note"]
    d2 = deep_by_id.get(final["itunes_id"], {})
    return {"recommend": final["itunes_id"], "confidence": "high", "model": model,
            "reasons": (f"[網絡] {final['name']}：{d2.get('learn','')}｜五判詞：{five_year}")[:400],
            "risks": (d2.get("risk", "") + "｜紅隊：" +
                      next((r["hardening"] for r in rt_log if r["pick"] == final["itunes_id"]), ""))[:300],
            "done_when": "full 模式自動出 work order；propose 模式待人類點頭",
            "evidence": f"N1={s1['note']}｜N2 score={d2.get('score_100')}｜perennial={final.get('perennial')}",
            "valid": True,
            "net": {"N1": s1["note"], "N2": r2["note"], "redteam": rt_log, "taste": taste_note}}


def _emit_work_order(gs, dec, c):
    """autonomy=full：核准 → work order（自動 onboarding 引擎的合約檔）。"""
    try:
        db = json.load(open(CAND))
        it = (db.get("items") or {}).get(str(dec["recommend"])) or {}
        wo = {"v": 1, "at": time.time(), "itunes_id": dec["recommend"],
              "name": c["name"], "channel_name": c["name"],
              "feed_url": it.get("feed_url") or "", "genre": it.get("genre"),
              "median_min": c["median_min"], "eps_week": c["cadence"],
              "approved_by": "gate-net-v1", "nodes": dec.get("net"),
              "human_veto": "對話說「停更/撤銷 <名>」即停（Bulwark 先例）"}
        json.dump(wo, open("state/pit-work-order.json", "w"), ensure_ascii=False, indent=1)
        return True
    except Exception as ex:
        log(f"work order err: {str(ex)[:80]}")
        return False


def main():
    pol = json.load(open(POL)).get("pipeline", {})
    autonomy = (pol.get("gate_autonomy") or "propose")
    ps = json.load(open(PSTATE)) if os.path.exists(PSTATE) else {"runs": []}
    gs = json.load(open(GSTATE)) if os.path.exists(GSTATE) else {}
    runs = ps.get("runs") or []
    latest = runs[0] if runs else {}
    streak = 0
    for r in runs:
        if r.get("verdict") == "GREEN":
            streak += 1
        else:
            break
    crit = pol.get("steady_criteria", {})
    need_streak = int(crit.get("audit_green_days", 7))
    pits = latest.get("pits") or []
    steady = []
    for p in pits:
        if p.get("mode") == "paused":
            steady.append({"family": p["family"], "steady": True,
                           "detail": "paused（用戶裁示 11-25）——不計入補完條件"})
            continue
        if p["mode"] == "backlog":
            if p.get("source") == "engine":
                # 引擎回報為真相源：status=complete 且跟進延遲 ≤7 天
                lag_ok = (p.get("follow_lag_days") is None
                          or p.get("follow_lag_days") <= 7)
                ok = (p.get("status") == "complete") and lag_ok
                _lag = p.get('follow_lag_days')
                detail = (f"engine completion {p.get('completion')} "
                          f"（缺 {p.get('true_missing')}｜lag {'—' if _lag is None else f'{_lag}d'}）")
            else:
                ok = p.get("completion") is not None and \
                    p["completion"] >= float(crit.get("completion_target", 0.95))
                detail = f"completion {p.get('completion')}（本地估算）"
        else:
            miss = len((latest.get("bulwark_rss") or {}).get("missing") or [])
            ok = miss <= int(crit.get("fresh_sla_missing_max", 0))
            detail = f"RSS 4天缺 {miss}"
        steady.append({"family": p["family"], "steady": bool(ok and streak >= need_streak),
                       "detail": f"{detail}｜streak {streak}/{need_streak}"})
    active = len([p for p in pits if p.get("mode") != "paused"])
    wip = int(pol.get("wip_limit", 4))
    now = time.time()
    appr = [a for a in (gs.get("approvals") or []) if now - a.get("at", 0) < 30 * 86400]
    budget = int(pol.get("monthly_pit_budget", 1))
    open_gate = all(s["steady"] for s in steady) and active < wip and len(appr) < budget

    # 狀態遷移才通知（HOLD↔OPEN，避免日日噪音）
    top = eligible_top()
    if open_gate != gs.get("last_open"):
        if open_gate:
            lines = [f"開坑許可 OPEN（WIP {active}/{wip}｜月預算 {len(appr)}/{budget}）"]
            lines += [f"• {c['name']}（{c['artist']}）v2={c['score']}｜peren {c.get('perennial')}｜{c['legal']}｜{c['cadence']}ep/週"
                      for c in top[:3]]
        else:
            lines = [f"開坑許可 HOLD（WIP {active}/{wip}｜月預算 {len(appr)}/{budget}）"]
            lines += [f"• {s['family']}: {s['detail']}" for s in steady if not s["steady"]]
        ntfy(f"gate: {'OPEN' if open_gate else 'HOLD'}", "\n".join(lines), 3)

    # key 失效告警（狀態遷移才報，避免噪音）
    if gs.get("llm_key_dead") and not gs.get("llm_key_dead_notified"):
        ntfy("gate: GEMINI key 失效", "LLM 決策層已自動降級為人類決策包。請重新提供 key（舊 key 已吊銷或無效）。", 4)
        gs["llm_key_dead_notified"] = True
    # gate OPEN 但合格候選為空＝鏈路故障訊號（sweep/schema/覆蓋 probe）——主動告警
    if open_gate and not top:
        if not gs.get("empty_eligible_notified"):
            ntfy("gate: OPEN 但零合格候選",
                 "海選→裁決鏈路疑似故障（sweep 停擺/DB schema/覆蓋 probe 全剔）。請查 sweep 與 candidates.json。", 4)
            gs["empty_eligible_notified"] = True
    # LLM 決策（僅 OPEN＋本月未決時；無 key → 決策包留給人類）
    dec = None
    if open_gate and not gs.get("month_decided") and top:
        dec = net_decide(pits, steady, top, pol, gs)
        if dec and dec["valid"] and dec["recommend"]:
            c = next((c for c in top if c["itunes_id"] == dec["recommend"]), None)
            gs.setdefault("approvals", []).append(
                {"at": now, "itunes_id": dec["recommend"], "name": c["name"],
                 "reasons": dec["reasons"], "done_when": dec["done_when"],
                 "model": dec.get("model"),            # 決策日誌：基座型號（回看迴路用）
                 "perennial": c.get("perennial"),      # 決策當下的雋永分（對照 90 天後實績）
                 "score": c.get("score"), "auto": autonomy == "full"})
            gs["month_decided"] = True
            if autonomy == "full" and _emit_work_order(gs, dec, c):
                ntfy(f"gate: 全權核准開坑 {c['name']}",
                     f"裁決網絡（{dec.get('model')}）：\n{dec['reasons']}\n風險：{dec['risks']}\n"
                     f"work order 已出 → onboarding 引擎自動開坑並長期維護。"
                     f"\n人類否決通道：對話說「停更 {c['name']}」。", 3)
            else:
                ntfy(f"gate: 核准開坑 {c['name']}",
                     f"LLM（{dec['model']}）決策：\n理由：{dec['reasons']}\n風險：{dec['risks']}\n"
                     f"完成態：{dec['done_when']}\n執行：回對話說「開坑 {c['name']}」"
                     f"（核准≠自動開坑）", 3)
        elif dec and not dec["valid"]:
            ntfy("gate: LLM 建議未通過硬校驗", f"recommend={dec['recommend']} 不在合格清單——已否決，待人類決策", 4)
        elif dec:
            ntfy("gate: LLM 建議觀望", dec["reasons"], 3)
        elif not os.environ.get("GEMINI_API_KEY"):
            if top:
                ntfy("gate: 待人類決策（無 LLM key）",
                     "開坑許可 OPEN。Top 候選：\n" +
                     "\n".join(f"• {c['name']} v2={c['score']}（{c['legal']}）" for c in top[:3]) +
                     "\n提供 GEMINI_API_KEY 即啟用自動決策", 3)
    # DEMO（GATE_NET_DEMO=1）：非 OPEN 決策時以真實 API 示範網絡——無核准副作用，預算照計（11-25 用戶：要見真模型）
    if os.environ.get("GATE_NET_DEMO") and not dec and top:
        dec = net_decide(pits, steady, top, pol, gs)
        if dec:
            dec["demo"] = True
    gs["last_open"] = open_gate
    gs.setdefault("log", []).append(
        {"at": time.strftime("%F %T"), "open": open_gate, "streak": streak,
         "active": active, "wip": wip, "budget_used": len(appr),
         "pits": steady, "decision": dec and {k: dec[k] for k in ("recommend", "valid")}})
    gs["log"] = gs["log"][:60]
    os.makedirs(os.path.dirname(GSTATE) or ".", exist_ok=True)
    json.dump(gs, open(GSTATE, "w"), ensure_ascii=False, indent=1)
    try:
        json.dump(TRACE, open("state/gate-llm-trace.json", "w"), ensure_ascii=False, indent=1)
    except Exception as ex:
        log(f"trace dump err: {str(ex)[:60]}")
    # 人類可讀決策過程（11-25 用戶要求：清楚看到結果怎麼出來）——patrol keep 自動 commit
    try:
        md = ["# Gate 決策過程 " + time.strftime("%F %T"), "",
              f"**裁定：{'✅ OPEN' if open_gate else '⌛ HOLD'}** ｜ 連綠 streak {streak}/{need_streak} ｜ WIP {active}/{wip} ｜ 月預算 {len(appr)}/{budget}",
              "", "## 1. 坑位債務判定（補完前提）"]
        for s_ in steady:
            md.append(f"- **{s_['family']}**: {'✅ steady' if s_['steady'] else '⌛ 未穩'} — {s_['detail']}")
        md += ["", "## 2. 合格候選（fresh＋非 major＋非 avoid＋活躍）Top5",
               "", "| 節目 | v2 總分 | perennial | legal | 更新 | 時長中位 |",
               "|---|---|---|---|---|---|"]
        md += [f"| {c['name']} | {c['score']} | {c.get('perennial')} | {c['legal']} | {c['cadence']}ep/週 | {c['median_min']}min |" for c in top] or ["（無合格候選）"]
        md += ["", "## 3. 決策"]
        if dec:
            md += [f"- 基座：`{dec.get('model')}` ｜ recommend：**{dec['recommend']}** ｜ valid：{dec['valid']} ｜ confidence：{dec.get('confidence')} ｜ autonomy：**{autonomy}**"]
            if dec.get("demo"):
                md += ["- ⚠ **DEMO 運行**：非裁決（HOLD／已決狀態下的網絡示範；無核准副作用，LLM 額度照計）"]
            md += [f"- 理由：{dec.get('reasons')}", f"- 風險：{dec.get('risks')}",
                   f"- 完成態（done_when）：{dec.get('done_when')}", f"- 證據引用：{dec.get('evidence')}"]
            net = dec.get("net") or {}
            if net:
                md += [f"- **N1 初篩**：{net.get('N1')}",
                       f"- **N2 深評**：{net.get('N2')}",
                       f"- **N3 紅隊**：{json.dumps(net.get('redteam'), ensure_ascii=False)[:300]}",
                       f"- **N4 審美**：{net.get('taste')}"]
        elif open_gate:
            md.append("- OPEN 但無 LLM 決策（key 缺／額度盡／本月已決）——ntfy 已附人類決策包")
        else:
            md.append("- HOLD：未進入決策層（先清坑位債＋patrol 連綠）")
        md += ["", "## 3.2 LLM 節點明細（每節點 output＋生成模型）",
               "", "| 節點 | 模型 | 結果 | 延遲 | output（節錄） |", "|---|---|---|---|---|"]
        md += [f"| {t['node']} | `{t['model']}` | {'✅' if t['ok'] else '❌ ' + t['err'][:24]} | {t['latency_ms']}ms | {(t['output'] or '')[:70].replace('|', '\\|')} |"
               for t in TRACE] or ["（本輪無 LLM 調用）"]
        md += ["", f"## 4. 近期核准日誌（autonomy={autonomy}；人類否決通道＝對話說「停更 <名>」）"]
        md += [f"- {time.strftime('%F', time.localtime(a['at']))}：{a.get('name')}（perennial {a.get('perennial')}｜v2 {a.get('score')}｜model {a.get('model')}{'｜🤖 auto' if a.get('auto') else ''}）" for a in appr] or ["（本月尚無核准）"]
        open("state/gate-decision.md", "w", encoding="utf-8").write("\n".join(md) + "\n")
    except Exception as ex:
        log(f"gate trace emit err: {str(ex)[:80]}")
    print(json.dumps({"open": open_gate, "streak": streak, "active": active,
                      "wip": wip, "budget_used": len(appr),
                      "steady": steady, "decision": dec}, ensure_ascii=False, indent=1))
    log("gate done")


if __name__ == "__main__":
    main()
