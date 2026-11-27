#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jobs/triage.py — 六步一線診斷自動化（runbook 11-27 SOP 的可執行版）。

觸發：①workflow failure hook（TRIAGE_RUN_ID=失敗 run，自動）②triage.yml 手動派工
（可診斷任何 run）。產出：分類＋證據包 → ntfy（分級）＋ trail/triage/<run>.json。
分類：storm｜busy｜refuse｜code｜honesty｜timeout｜ghost（丟火/空log）｜clean｜unknown
第 6 步裁量事項（API 語義、修法設計）不在本件——本件只做機械分類＋舉證。
"""
import os, re, sys, json, time
import requests

API = "https://api.github.com"
REPO = os.environ.get("TRIAGE_REPO") or os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("TRIAGE_TOKEN", "")
RUN = os.environ.get("TRIAGE_RUN_ID", "")
NTFY = os.environ.get("NTFY_URL", "")

# ── 第 2 步：錯誤文本分類表（runbook 表的可執行版；每次裁量診斷後固化加行）──
PATTERNS = [
    ("storm",  ("write operation timed out", "Connection aborted", "Max retries",
                "Connection timed out", "SSLError", "EOF occurred")),
    ("busy",   ("保存异常", "资源进程", "还在处理", "你已有", "处理程序")),
    ("refuse", ("更新失败", "联系客服", "上传文件路径不合法")),
    ("code",   ("NameError", "KeyError", "ValueError", "AssertionError",
                "SyntaxError", "AttributeError", "TypeError", "UnboundLocalError")),
]
HYGIENE_MARKS = ("ob-cid-", "ch0", "/tmp/", ".preflight", "gid-1",
                 "smoke", "ob-cid-1")          # 第 5 步：測試工件特徵

def gh(path):
    try:
        r = requests.get(f"{API}{path}",
                         headers={"Authorization": f"Bearer {TOKEN}",
                                  "Accept": "application/vnd.github+json"},
                         timeout=30)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}

def log_line(s):
    print(f"[triage] {s}", flush=True)

def classify_text(txt):
    for cls, pats in PATTERNS:
        if any(p in txt for p in pats):
            return cls
    return None

def evidence_lines(txt, cls, n=3):
    pats = dict(PATTERNS).get(cls, ())
    out = []
    for line in txt.splitlines():
        if any(p in line for p in pats):
            out.append(re.sub(r"^\S+Z\s+", "", line).strip()[:160])
            if len(out) >= n:
                break
    return out

def ntfy(title, body, prio=3):
    if not NTFY:
        return
    try:
        requests.post("https://ntfy.sh/", timeout=20,
                      data=json.dumps({"topic": NTFY, "title": title,
                                       "priority": prio, "tags": ["mag"]}),
                      )
    except Exception as ex:
        log_line(f"ntfy err: {str(ex)[:60]}")

def main():
    if not (REPO and TOKEN and RUN):
        log_line("need TRIAGE_REPO/GITHUB_REPOSITORY + GH_TOKEN + TRIAGE_RUN_ID")
        sys.exit(2)
    # ── 第 0 步：run 存在？結論？時長？──
    run = gh(f"/repos/{REPO}/actions/runs/{RUN}")
    if not run:
        log_line("run not found（丟火或 id 錯）——class=ghost")
        rep = {"run": RUN, "class": "ghost", "note": "run not found"}
        _emit(rep)
        return
    wf = run.get("name", "?")
    concl = run.get("conclusion")
    started = run.get("run_started_at") or run.get("created_at")
    updated = run.get("updated_at")
    dur_h = 0.0
    try:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        dur_h = (time.mktime(time.strptime(updated, fmt))
                 - time.mktime(time.strptime(started, fmt))) / 3600.0
    except Exception:
        pass
    if concl == "success":
        log_line("run succeeded——無需診斷（class=clean）")
        _emit({"run": RUN, "workflow": wf, "class": "clean"})
        return
    log_line(f"run {RUN} [{wf}] conclusion={concl} duration={dur_h:.1f}h")

    # ── 第 1 步：死在哪個 step？──
    jobs = gh(f"/repos/{REPO}/actions/runs/{RUN}/jobs").get("jobs", [])
    bad = [j for j in jobs if j.get("conclusion") in ("failure", "cancelled")]
    dead_steps = []
    for j in bad:
        for s in j.get("steps", []):
            if s.get("conclusion") in ("failure", "cancelled") and s.get("number", 99) < 17:
                dead_steps.append(f"{j['name']}::{s['name']}")
    log_line(f"dead steps: {dead_steps}")

    # ── 第 2 步：log 文本分類──
    cls, ev = None, []
    for j in bad:
        try:
            r = requests.get(j["url"] + "/logs",
                             headers={"Authorization": f"Bearer {TOKEN}"},
                             timeout=60)
            txt = r.text or ""
        except Exception:
            txt = ""
        if "BlobNotFound" in txt[:500] or not txt.strip():
            cls = cls or "ghost"
            log_line(f"job {j['id']} log 不可讀（BlobNotFound/空）")
            continue
        c = classify_text(txt)
        if c and not cls:
            cls, ev = c, evidence_lines(txt, c)
    if dur_h >= 5.5 and concl == "cancelled" and not cls:
        cls = "timeout"                      # timeout-minutes 準點處決特徵
    if "preflight" in " ".join(dead_steps) and cls in (None, "code"):
        cls = "preflight-gate"               # 紅燈禁 dispatch 觸發
        cls_note = "preflight 紅燈（查 stub 污染或真回歸）"
    else:
        cls_note = ""
    cls = cls or "unknown"
    log_line(f"class={cls}  evidence={ev}")

    # ── 第 3 步：跨艦對照＋帳本新鮮度──
    fleet = []
    try:
        rs = gh(f"/repos/{REPO}/actions/runs?per_page=10").get("workflow_runs", [])
        cut = time.time() - 12 * 3600
        for r_ in rs:
            if r_.get("conclusion") in ("failure", "cancelled") and r_["id"] != int(RUN):
                fleet.append(f"{r_['name']}:{r_['conclusion']}")
    except Exception:
        pass
    same_window = len(fleet) > 0
    log_line(f"cross-fleet（近 12h 其他非綠）: {fleet or '無'}"
             f" → {'平台級疑雲' if same_window else '單坑病傾向'}")

    # ── 第 4 步：head 二分（同 workflow 上一個綠 run）──
    suspects = []
    try:
        prev = gh(f"/repos/{REPO}/actions/workflows/{run['path'].split('/')[-1]}/runs"
                  f"?per_page=20").get("workflow_runs", [])
        last_green = next((r_ for r_ in prev
                           if r_.get("conclusion") == "success"
                           and r_["id"] != int(RUN)), None)
        if last_green and last_green["head_sha"] != run["head_sha"]:
            rng = f"{last_green['head_sha'][:8]}..{run['head_sha'][:8]}"
            g = subprocess.run(["git", "log", "--oneline", rng],
                               capture_output=True, text=True, timeout=20)
            suspects = (g.stdout or "").strip().splitlines()[:5]
    except Exception:
        pass
    log_line(f"head 二分嫌疑 commits: {suspects or '（無差異或不可得）'}")

    # ── 第 5 步：狀態衛生掃描（測試工件毒化）──
    hygiene = []
    tdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "trail")
    if os.path.isdir(tdir):
        for fn in os.listdir(tdir):
            if not fn.endswith(".json"):
                continue
            try:
                body = open(os.path.join(tdir, fn), encoding="utf-8",
                            errors="ignore").read()
            except Exception:
                continue
            for mk in HYGIENE_MARKS:
                if mk in body:
                    hygiene.append(f"{fn} 含 '{mk}'")
                    break
    log_line(f"hygiene: {hygiene or '乾淨'}")

    _emit({"run": RUN, "workflow": wf, "conclusion": concl,
           "duration_h": round(dur_h, 2), "dead_steps": dead_steps,
           "class": cls, "cls_note": cls_note, "evidence": ev,
           "cross_fleet": fleet, "suspects": suspects, "hygiene": hygiene,
           "at": time.strftime("%F %T")})

def _emit(rep):
    cls = rep.get("class", "unknown")
    prio = {"code": 4, "honesty": 4, "preflight-gate": 4, "unknown": 4}.get(cls, 3)
    body = json.dumps({k: v for k, v in rep.items() if v}, ensure_ascii=False)[:2800]
    log_line(f"report: {body[:600]}")
    ntfy(f"triage[{cls}]: {rep.get('workflow', '?')} run {rep.get('run')}", body, prio)
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "trail", "triage")
    os.makedirs(out, exist_ok=True)
    json.dump(rep, open(os.path.join(out, f"{rep.get('run')}.json"), "w"),
              ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
