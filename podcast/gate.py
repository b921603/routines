#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""podcast/gate.py — 開坑 gate（P4.3 治理層）。

權責三層：政策數字在代碼（硬約束）→ LLM 在額度內判斷 → 人類保例外權。
防無限開坑：全部既有坑位 steady（補完率≥目標＋審計連綠）＋ WIP 上限
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
        sc = (v.get("score") or {}).get("v2")
        if isinstance(sc, dict):                 # v2=8 維分項 → 取總分
            sc = sc.get("total")
        out.append({"itunes_id": int(k), "name": v.get("name"),
                    "artist": v.get("artist"),
                    "score": sc,
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
                        "回覆 JSON：{\"ok\": true, \"model\": \"你的型號\"}", probe=True)
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


def _llm_call(key, model, prompt, probe=False):
    """單發調用；回 (ok, text|err)。處理：HTTP 錯誤矩陣／安全攔截／非 JSON body。"""
    cfg = {"temperature": 0.4,
           "response_mime_type": "application/json",
           "response_schema": SCHEMA}
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
        "既有坑位 steady 全達標）——你只在合格候選中挑選或建議觀望，"
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
    for attempt in range(4):  # 退避重試鏈（含模型滑落）
        ok, res = _llm_call(key, model, prompt)
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
            time.sleep(4 * (attempt + 1))
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
                    "重新輸出，僅 JSON，無其他文字。"))
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


def main():
    pol = json.load(open(POL)).get("pipeline", {})
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
        if p["mode"] == "backlog":
            if p.get("source") == "engine":
                # 引擎回報為真相源：status=complete 且跟進延遲 ≤7 天
                lag_ok = (p.get("follow_lag_days") is None
                          or p.get("follow_lag_days") <= 7)
                ok = (p.get("status") == "complete") and lag_ok
                detail = (f"engine completion {p.get('completion')} "
                          f"（缺 {p.get('true_missing')}｜lag {p.get('follow_lag_days')}d）")
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
    active = len(pits)
    wip = int(pol.get("wip_limit", 4))
    now = time.time()
    appr = [a for a in (gs.get("approvals") or []) if now - a.get("at", 0) < 30 * 86400]
    budget = int(pol.get("monthly_pit_budget", 1))
    open_gate = all(s["steady"] for s in steady) and active < wip and len(appr) < budget

    # 狀態遷移才通知（HOLD↔OPEN，避免日日噪音）
    if open_gate != gs.get("last_open"):
        if open_gate:
            cands = eligible_top()
            lines = [f"開坑許可 OPEN（WIP {active}/{wip}｜月預算 {len(appr)}/{budget}）"]
            lines += [f"• {c['name']}（{c['artist']}）v2={c['score']}｜{c['legal']}｜{c['cadence']}ep/週"
                      for c in cands[:3]]
        else:
            lines = [f"開坑許可 HOLD（WIP {active}/{wip}｜月預算 {len(appr)}/{budget}）"]
            lines += [f"• {s['family']}: {s['detail']}" for s in steady if not s["steady"]]
        ntfy(f"gate: {'OPEN' if open_gate else 'HOLD'}", "\n".join(lines), 3)

    # key 失效告警（狀態遷移才報，避免噪音）
    if gs.get("llm_key_dead") and not gs.get("llm_key_dead_notified"):
        ntfy("gate: GEMINI key 失效", "LLM 決策層已自動降級為人類決策包。請重新提供 key（舊 key 已吊銷或無效）。", 4)
        gs["llm_key_dead_notified"] = True
    # gate OPEN 但合格候選為空＝鏈路故障訊號（sweep/schema/覆蓋 probe）——主動告警
    if open_gate and not eligible_top():
        if not gs.get("empty_eligible_notified"):
            ntfy("gate: OPEN 但零合格候選",
                 "海選→裁決鏈路疑似故障（sweep 停擺/DB schema/覆蓋 probe 全剔）。請查 sweep 與 candidates.json。", 4)
            gs["empty_eligible_notified"] = True
    # LLM 決策（僅 OPEN＋本月未決時；無 key → 決策包留給人類）
    dec = None
    if open_gate and not gs.get("month_decided") and eligible_top():
        dec = llm_decide(pits, steady, eligible_top(), pol, gs)
        if dec and dec["valid"] and dec["recommend"]:
            c = next((c for c in eligible_top() if c["itunes_id"] == dec["recommend"]), None)
            gs.setdefault("approvals", []).append(
                {"at": now, "itunes_id": dec["recommend"], "name": c["name"],
                 "reasons": dec["reasons"], "done_when": dec["done_when"]})
            gs["month_decided"] = True
            ntfy(f"gate: 核准開坑 {c['name']}",
                 f"LLM（{dec['model']}）決策：\n理由：{dec['reasons']}\n風險：{dec['risks']}\n"
                 f"完成態：{dec['done_when']}\n執行：回對話說「開坑 {c['name']}」"
                 f"（核准≠自動開坑）", 3)
        elif dec and not dec["valid"]:
            ntfy("gate: LLM 建議未通過硬校驗", f"recommend={dec['recommend']} 不在合格清單——已否決，待人類決策", 4)
        elif dec:
            ntfy("gate: LLM 建議觀望", dec["reasons"], 3)
        elif not os.environ.get("GEMINI_API_KEY"):
            cands = eligible_top()
            if cands:
                ntfy("gate: 待人類決策（無 LLM key）",
                     "開坑許可 OPEN。Top 候選：\n" +
                     "\n".join(f"• {c['name']} v2={c['score']}（{c['legal']}）" for c in cands[:3]) +
                     "\n提供 GEMINI_API_KEY 即啟用自動決策", 3)
    gs["last_open"] = open_gate
    gs.setdefault("log", []).append(
        {"at": time.strftime("%F %T"), "open": open_gate, "streak": streak,
         "active": active, "wip": wip, "budget_used": len(appr),
         "pits": steady, "decision": dec and {k: dec[k] for k in ("recommend", "valid")}})
    gs["log"] = gs["log"][:60]
    os.makedirs(os.path.dirname(GSTATE) or ".", exist_ok=True)
    json.dump(gs, open(GSTATE, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"open": open_gate, "streak": streak, "active": active,
                      "wip": wip, "budget_used": len(appr),
                      "steady": steady, "decision": dec}, ensure_ascii=False, indent=1))
    log("gate done")


if __name__ == "__main__":
    main()
