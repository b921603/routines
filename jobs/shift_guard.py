#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jobs/shift_guard.py — 丟班守衛（11-27 用戶問：丟班怎麼辦、會否永遠停擺）。

GitHub schedule 高載會直接丟班（11-26 丟 4 班、11-27 丟 07:30 班實證）。
本守衛掛 housekeeping（4 班/日）：ob 補完未竟且最後一班 >4.5h 無 run 起跑
→ 自動 dispatch 補班＋ntfy；否則靜默（班表健康）。
防重：已有 queued/in_progress 的 ob-backfill run → 不補。
"""
import os, sys, time, json
import requests

API = "https://api.github.com"
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GH_TOKEN", "")
NTFY = os.environ.get("NTFY_URL", "")
WF = "ob-backfill.yml"
STALE_H = 4.5          # 班距 3h＋50% 容忍（GitHub 延遲 15-60 分常態）


def gh(path, method="GET", **kw):
    h = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}
    r = requests.request(method, f"{API}{path}", headers=h, timeout=30, **kw)
    return r


def log(m):
    print(f"[shift-guard] {m}", flush=True)


def main():
    pit = json.load(open("trail/ob-pit.json", encoding="utf-8")) if os.path.exists("trail/ob-pit.json") else {}
    if pit.get("status") == "complete":
        log("ob 補完已竟——守衛休息")
        return
    runs = gh(f"/repos/{REPO}/actions/workflows/{WF}/runs?per_page=10").json() \
        .get("workflow_runs", [])
    if not runs:
        log("無法取得 run 清單——下輪再查")
        return
    live = [r for r in runs if r["status"] in ("queued", "in_progress", "pending")]
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    last_started = max((r.get("run_started_at") or r["created_at"]) for r in runs)
    age_h = (time.time() - time.mktime(time.strptime(last_started, fmt))) / 3600.0
    log(f"last run started {last_started}（{age_h:.1f}h 前）｜live runs: {len(live)}")
    if live:
        log("已有班在動/排隊——不補")
        return
    if age_h < STALE_H:
        log("班表健康（<4.5h）——靜默")
        return
    # 補班
    r = gh(f"/repos/{REPO}/actions/workflows/{WF}/dispatches", method="POST",
           json={"ref": "main"})
    ok = r.status_code == 204
    log(f"丟班偵測（{age_h:.1f}h 無班）→ 補班 dispatch: HTTP {r.status_code} {'✓' if ok else '✗'}")
    if NTFY:
        try:
            requests.post("https://ntfy.sh/", timeout=20,
                          data=json.dumps({"topic": NTFY, "title": "ob drain 丟班守衛",
                                           "priority": 3, "tags": ["alarm_clock"],
                                           "message": f"偵測 {age_h:.1f}h 無班（GitHub 丟班）→ 已自動補班。"}))
        except Exception:
            pass
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
