#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jobs/ob_bindprobe.py — 分組綁定深診斷（11-28：真組 AddChannelsToPrivateGroup
回 success:false；兩次 GetPrivateGroups 22 秒內組清單自變）。

探針（唯讀為主，只有最後的變體實測是寫入）：
  1. GetPrivateGroups 全欄位 dump（找 GroupId/成員形狀）
  2. GetPrivateChannels 全欄位 dump（找 channel 的分組歸屬欄位）
  3. AddChannelsToPrivateGroup 變體實測（對真組 0b0a37b9，加 001-100）：
     a. form 對組（現行）  b. channelIds 逗號串  c. JSON body  d. 重複欄位
     每變體後以 TotalMediaCount 增量驗證；中一即停。
"""
import os, sys, json, time
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "podcast"))
import ob_update as OB

REAL_GID = "0b0a37b9-7dcb-468d-a9f2-09469232f355"
TARGET_CID = "372fa0de-b091-4d19-89f8-571e3b33b546"   # 001-100


def jdump(x, n=700):
    return json.dumps(x, ensure_ascii=False)[:n]


def main():
    OB.login()
    print("[probe] ═══ 1. GetPrivateGroups 全欄位 ═══", flush=True)
    grps = (OB.req("POST", f"{OB.BASE}/ting/GetPrivateGroups?withDefault=false",
                   data="", timeout=40).json()
            .get("channelList", {}).get("UploadedChannels") or [])
    for g in grps:
        print(f"  GROUP {g.get('Name')!r} id={g.get('Id')} n={g.get('TotalMediaCount')} "
              f"type={g.get('ChannelType')} keys={sorted(g.keys())}", flush=True)
        print(f"    raw={jdump(g)}", flush=True)

    print("[probe] ═══ 2. GetPrivateChannels 全欄位（找分組歸屬欄位）═══", flush=True)
    chs = (OB.req("GET", f"{OB.BASE}/ting/GetPrivateChannels", timeout=45).json()
           .get("channelList", {}).get("UploadedChannels") or [])
    for c in chs:
        nm = c.get("Name") or ""
        if "being" in nm.lower() or "On Being" in nm:
            print(f"  CH {nm!r} id={c.get('Id')} type={c.get('ChannelType')} keys={sorted(c.keys())}", flush=True)
            print(f"    raw={jdump(c)}", flush=True)

    print("[probe] ═══ 3. 對真組的綁定變體實測 ═══", flush=True)
    n0 = next((g.get("TotalMediaCount") or 0 for g in grps if g.get("Id") == REAL_GID), None)
    print(f"  起始 n={n0}", flush=True)
    variants = [
        ("form-pair(現行)", [("groupId", REAL_GID), ("channelIds", TARGET_CID)]),
        ("channelIds-逗號", [("groupId", REAL_GID), ("channelIds", TARGET_CID + ",")]),
        ("json-body", "json:" + json.dumps({"groupId": REAL_GID, "channelIds": [TARGET_CID]})),
        ("重複channelIds", [("groupId", REAL_GID), ("channelIds", TARGET_CID), ("channelIds", TARGET_CID)]),
    ]
    for tag, data in variants:
        if tag.startswith("json-body"):
            r = OB.req("POST", f"{OB.BASE}/ting/AddChannelsToPrivateGroup",
                       data=data[5:], headers={"Content-Type": "application/json"}, timeout=60)
        else:
            r = OB.req("POST", f"{OB.BASE}/ting/AddChannelsToPrivateGroup", data=data, timeout=60)
        time.sleep(2)
        grps2 = (OB.req("POST", f"{OB.BASE}/ting/GetPrivateGroups?withDefault=false",
                        data="", timeout=40).json()
                 .get("channelList", {}).get("UploadedChannels") or [])
        n1 = next((g.get("TotalMediaCount") or 0 for g in grps2 if g.get("Id") == REAL_GID), None)
        hit = n1 is not None and n0 is not None and n1 > n0
        print(f"  [{tag}] {r.status_code} {(r.text or '')[:80]} | n {n0}→{n1} {'←←← 中！' if hit else ''}", flush=True)
        if hit:
            print("[probe] ✓✓✓ 有效形狀找到", flush=True)
            return
        n0 = n1
    print("[probe] 全變體未生效——需要人眼看 raw 回應", flush=True)


if __name__ == "__main__":
    main()
