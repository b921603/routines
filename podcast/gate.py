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
import os, json, time
import requests
from bulwark_update import ntfy, log

POL = "policies/policies.json"
PSTATE = os.environ.get("PATROL_STATE", "state/patrol-state.json")
GSTATE = "state/gate-state.json"
CAND = "state/candidates.json"


def eligible_top(n=5):
    """候選 DB → 合格開坑候選（fresh＋非 major＋非 avoid＋活躍 cadence）。"""
    try:
        db = json.load(open(CAND))
    except Exception:
        return []
    out = []
    for k, v in db.items():
        if not isinstance(v, dict):
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
        out.append({"itunes_id": int(k), "name": v.get("name"),
                    "artist": v.get("artist"),
                    "score": (v.get("score") or {}).get("v2"),
                    "cadence": rss.get("eps_week"),
                    "legal": v.get("publisher_class"),
                    "desc": (v.get("description") or "")[:300]})
    out.sort(key=lambda x: -(x["score"] or 0))
    return out[:n]


def llm_decide(pits, steady, cands, pol):
    """Gemini 在政策額度內挑選（response_mime_type=json 強制結構化輸出）。"""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key or not cands:
        return None
    prompt = (
        "你是播客搬運管線的開坑審核官。政策數字已由代碼驗證（WIP 上限/預算/"
        "既有坑位 steady 全達標）——你只在合格候選中挑選或建議觀望，無權放寬約束。\n"
        f"現有坑位：{json.dumps(pits, ensure_ascii=False)}\n"
        f"steady 判定：{json.dumps(steady, ensure_ascii=False)}\n"
        f"合格候選 Top{len(cands)}：{json.dumps(cands, ensure_ascii=False)}\n"
        "評選規則：學習價值＞更新穩定性＞法律低風險（independent＞mid＞major）；"
        "避免與現有坑位主題高度重疊；可以推薦 none（觀望，並說明缺什麼證據）。\n"
        '僅輸出 JSON：{"recommend": <itunes_id 或 0>, "reasons": "...", '
        '"risks": "...", "done_when": "..."}'
    )
    model = os.environ.get("GEMINI_MODEL") or pol.get("gate", {}).get("llm", "gemini-2.0-flash")
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.4,
                                       "response_mime_type": "application/json"}},
            timeout=60)
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        d = json.loads(txt)
        rid = int(d.get("recommend") or 0)
        valid = any(c["itunes_id"] == rid for c in cands) if rid else True
        return {"recommend": rid, "reasons": (d.get("reasons") or "")[:400],
                "risks": (d.get("risks") or "")[:300],
                "done_when": (d.get("done_when") or "")[:300],
                "valid": valid, "model": model}
    except Exception as ex:
        log(f"llm decide err: {str(ex)[:110]}")
        return None


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

    # LLM 決策（僅 OPEN＋本月未決時；無 key → 決策包留給人類）
    dec = None
    if open_gate and not gs.get("month_decided") and eligible_top():
        dec = llm_decide(pits, steady, eligible_top(), pol)
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
