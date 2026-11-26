#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ob_face_maint.py — 門面維護一次性工單（2026-11-26 用戶裁定三合一）
① 偵查：頻道/分組現況（用戶已自行改名——平台名稱為權威，本腳本只讀不改名）
② 分組簡介：TFF／HTF／OB 三組套策展人語气介紹（UpdatePrivateChannel?itemtype=7；
   接口與 thumb 規則出自 htf_channel_desc.py 實證）
③ 殭屍 11 集補縮圖：uploadprivatemedia 省略 media＝沿用原音檔、只更新 thumb
   （htf_cover_apply_all 實證；★lrc 必帶編輯頁現值——空值會把字幕清空；
   needAISubtitle=false——AI 字幕已存在，重觸發會佔資源進程）
冪等：簡介重複寫同值無害；縮圖查 thumb_data_src 已有即跳過。
"""
import os
import re
import sys
import time
import html as H

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ob_update as OB                       # noqa: E402

TFF_GP, HTF_GP, BWK_GP = "9007fbda", "de9abbba", "87c5aed8"
MAX_PATCH = 40

TFF_DESC = """一個把自己當實驗室的人，拆解世界頂尖表現者的套路。

Tim Ferriss——《4小時工作週》作者、Newsweek 筆下「世界上最強的人體小白鼠」——每週深訪一位頂尖人物：投資人、運動員、科學家、廚師、軍人。問他們怎麼訓練、怎麼決策、怎麼從失敗裡爬起來，然後親身逐項試給你看。

完整收錄，逐集附逐字稿字幕：邊聽邊跟，複習時直接跳到想重聽的那一段。近千集，不必按順序——挑你佩服的人開始。"""

OB_DESC = """動盪的年代，怎樣活得清醒而溫柔？

每週一場慢訪談：詩人、科學家、神學家、社會運動者，圍繞信仰、科學、修復與意義長談。Krista Tippett 主持超過二十年，從 Mary Oliver 到這個時代最安靜也最重要的聲音。

完整存檔，逐集附逐字稿字幕：邊聽邊跟，複習時直接跳到想重聽的那一段。持續更新中。

不必從第一集聽起——挑一個你此刻需要的問題進場就好。"""

HTF_DESC = """失敗不是意外，只是沒人教過你怎麼失敗。

每週請一位來賓，聊聊他們人生裡那幾次「搞砸了」——以及後來是怎麼站起來的。演員、作家、老闆、藝術家，還有把公司弄倒又重新再來一次的人。

完整收錄，逐集附逐字稿字幕：邊聽邊跟，複習時也能直接跳到想重聽的那一段。持續更新中。

想聽哪一種失敗，就從哪一集開始。"""


def parse_edit_page(text):
    """htf_subs.parse_edit_page 移植（欄位形狀實證）。"""
    out = {}
    m = re.search(r'class="[^"]*media_name[^"]*"[^>]*value="([^"]*)"', text) or \
        re.search(r'id="media_name"[^>]*value="([^"]*)"', text)
    out["title"] = H.unescape(m.group(1)) if m else ""
    m = re.search(r'<textarea[^>]*id="media_textarea"[^>]*>(.*?)</textarea>', text, re.S)
    lrc = m.group(1) if m else ""
    lrc = lrc.replace("&#xD;", "\r").replace("&#xA;", "\n") \
             .replace("&#13;", "\r").replace("&#10;", "\n")
    out["lrc"] = H.unescape(lrc)
    m = re.search(r'class="[^"]*add_channel_textarea_last[^"]*"[^>]*>(.*?)</textarea>', text, re.S)
    out["desc"] = H.unescape(m.group(1)).strip() if m else ""
    m = re.search(r'class="ueditor_text[^"]*"[^>]*>(.*?)</div>', text, re.S)
    out["intros_html"] = m.group(1).strip() if m else ""
    m = re.search(r'class="channel_img_img_last"[^>]*data-src="([^"]*)"', text)
    out["thumb_data_src"] = m.group(1) if m else ""
    # 11-26 三輪教訓：ob 的 edit page 縮圖在 src=（非 data-src）——兩處都看才判定「已有縮圖」
    if not out["thumb_data_src"]:
        m = re.search(r'class="channel_img_img_last"[^>]*src="([^"]*)"', text)
        out["thumb_data_src"] = m.group(1) if m else ""
    m = re.search(r'text_add_img_last"[^>]*data-fileid="([^"]*)"', text)
    out["thumb_fileid"] = m.group(1) if m else ""
    return out


def list_media(cid):
    """[(title, mid)] —— tfs_engine.raw_list 解析移植（mid=data 屬性）。"""
    out, seen = [], set()
    for sb in (0, 1):
        for pg in range(24):
            r = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias"
                             f"?sortby={sb}&page={pg}&channelId={cid}", timeout=45)
            if not (r.text or "").strip():
                break
            got = 0
            for x in re.split(r'<div class="dragBox">', r.text)[1:]:
                tm = re.search(r'rl-title"[^>]*title="([^"]*)"', x)
                mid = re.search(r'media_id"[^>]*data="([^"]+)"', x)
                if tm and mid and mid.group(1) not in seen:
                    bare = ("no-cover" in x) or ("default.png" in x)
                    out.append((H.unescape(tm.group(1)), mid.group(1), bare))
                    seen.add(mid.group(1))
                    got += 1
            if not got:
                break
    return out


def set_group_desc(grps, gid_prefix, desc, tag, get_fid=None):
    try:
        grp = next((c for c in grps if (c.get("Id") or "").startswith(gid_prefix)), None)
        if not grp:
            log(f"  [{tag}] group {gid_prefix} 不在清單——跳過")
            return
        cur = (grp.get("Description") or "").strip()
        if desc.strip()[:24] in cur:
            log(f"  [{tag}] 簡介已是新版——跳過")
            return
        gid = grp["Id"]
        name = grp.get("Name") or ""
        ctype = grp.get("ChannelType") or "2"
        # thumb 三段策略（首輪教訓：分組 Thumb=URL→「上传文件路径不合法」）：
        # 省略 → 空 → 上傳 fileId（htf_channel_desc：thumb 必須是上傳後的檔案 id）
        for shape in ({"id": gid}, {"channelId": gid}):
            for tmode in ("omit", "empty", "fid"):
                data = dict(shape)
                data.update({"name": name, "channelType": ctype, "description": desc})
                if tmode == "empty":
                    data["thumb"] = ""
                elif tmode == "fid":
                    f = get_fid() if get_fid else None
                    if not f:
                        continue
                    data["thumb"] = f
                r = OB.req("POST", f"{OB.BASE}/ting/UpdatePrivateChannel?itemtype=7",
                           data=data, timeout=60)
                ok = r.status_code == 200 and '"success":false' not in (r.text or "")
                log(f"  [{tag}] update({list(shape)[0]}/thumb={tmode}): "
                    f"{r.status_code} {(r.text or '')[:60]}")
                if not ok:
                    continue
                g2 = OB.req("POST", f"{OB.BASE}/ting/GetPrivateGroups?withDefault=false",
                            data="", timeout=40).json() \
                    .get("channelList", {}).get("UploadedChannels", [])
                after = next((c for c in g2 if c.get("Id") == gid), {})
                okc = desc.strip()[:16] in (after.get("Description") or "")
                log(f"  [{tag}] verify: {'✓ 已寫入' if okc else '✗ 未見生效'}")
                if okc:
                    return True
        log(f"  [{tag}] 全部形狀未生效——留下次")
    except Exception as ex:
        log(f"  [{tag}] err（非致命）: {str(ex)[:80]}")


def patch_zombie_thumbs(cid):
    try:
        led = OB.rj(OB.LEDGER, {}) or {}
        targets = {}
        for v in led.values():
            if v.get("how") == "heal":
                targets.setdefault(OB.norm(v.get("title", "")), v.get("title", ""))
        log(f"縮圖補貼：heal 目標 {len(targets)} 集＋頻道裸圖掃描（11-26 泛化）")
        if not targets:
            return
        art = OB.feed_channel_art()
        if not art:
            log("  頻道 logo 抓取失敗——跳過（下輪再試）")
            return
        fid = OB.upload_thumb(art)
        if not fid:
            log("  logo 上傳失敗——跳過")
            return
        log(f"  logo fid={fid}")
        media = list_media(cid)
        log(f"  頻道媒體 listing: {len(media)} 條")
        patched = skipped = 0
        dbg = False
        for title, mid, bare in media:
            if patched + skipped >= MAX_PATCH:
                log("  MAX_PATCH 達上限——留尾（冪等可重跑）")
                break
            key = OB.norm(title)
            hit = next((t for k, t in targets.items() if key.startswith(k)), None)
            if not hit and not bare:
                continue            # 11-26 泛化：heal 配對或 listing 裸圖旗標都補
            ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}"
                               f"&mediaid={mid}&itemType=0", timeout=45).text or ""
            info = parse_edit_page(ep)
            if not dbg:      # 縮圖診斷：edit page 的 img 欄位實際形狀
                mdbg = re.search(r"<img[^>]*channel_img_img_last[^>]*>", ep)
                log(f"  [dbg] img tag: {mdbg.group(0)[:170] if mdbg else '(無 img)'}")
                dbg = True
            if info["thumb_data_src"] and "default" not in info["thumb_data_src"]:
                log(f"  跳過（已有縮圖）: {title[:50]}")
                skipped += 1
                continue
            payload = {"id": mid, "title": info.get("title") or title,
                       "channelId": cid, "thumb": fid,
                       "lrc": info.get("lrc") or "",
                       "needProcessLrc": "false", "needKeepformat": "false",
                       "reformatParagraph": "false", "splitLongSentence": "true",
                       "needMachineTranslation": "false",
                       "allowMachineTranslation": "false",
                       "needAISubtitle": "false",
                       "description": info.get("desc") or "",
                       "mediatype": "0", "intros": info.get("intros_html") or "",
                       "istiming": "false", "timing": "", "html": "",
                       "insertImage": "true", "mdChapterId": ""}
            ok = False
            for attempt in range(20):
                try:
                    r = OB.req("POST", f"{OB.BASE}/ting/uploadprivatemedia",
                               data=payload, timeout=120)
                    txt = r.text or ""
                    if r.status_code == 200 and "保存成功" in txt:
                        ok = True
                        break
                    if "资源" in txt or "处理" in txt:
                        log(f"  資源進程滿 → 等 45s（{attempt + 1}/20）")
                        time.sleep(45)
                        continue
                    log(f"  post: {r.status_code} {txt[:70]}")
                except Exception as ex:
                    log(f"  post err: {str(ex)[:70]}")
                time.sleep(6)
            if ok:
                patched += 1
                log(f"  ✓ {title[:56]}")
            time.sleep(2)
        log(f"殭屍補縮圖完成：補 {patched}／既有 {skipped}")
    except Exception as ex:
        log(f"patch err（非致命）: {str(ex)[:80]}")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    log("=== ① 偵查：頻道與分組現況 ===")
    OB.login()
    cid = OB.channel_id()
    log(f"ob 頻道 cid: {cid}")
    chs = OB.req("GET", f"{OB.BASE}/ting/GetPrivateChannels", timeout=45) \
        .json().get("channelList", {}).get("UploadedChannels", [])
    for c in chs:
        log(f"  CH {c.get('Id')}  {(c.get('Name') or '')[:40]!r}  "
            f"type={c.get('ChannelType')} thumb={'有' if c.get('Thumb') else '無'}")
    # 名稱刷新（用戶改名後 CHFILE 跟上——輪轉命名基底由此而來）
    ob_ch = next((c for c in chs if c.get("Id") == cid), None)
    saved = OB.rj(OB.CHFILE, {}) or {}
    if ob_ch and saved.get("name") != ob_ch.get("Name"):
        OB.wj(OB.CHFILE, {"cid": cid, "name": ob_ch.get("Name"),
                          "at": time.strftime("%F %T")})
        log(f"CHFILE 名稱刷新: {ob_ch.get('Name')!r}")
    grps = OB.req("POST", f"{OB.BASE}/ting/GetPrivateGroups?withDefault=false",
                  data="", timeout=40).json() \
        .get("channelList", {}).get("UploadedChannels", [])
    log(f"分組 {len(grps)} 個：")
    for g in grps:
        log(f"  GP {g.get('Id')}  {(g.get('Name') or '')[:40]!r}  "
            f"desc_len={len(g.get('Description') or '')} "
            f"thumb={'有' if g.get('Thumb') else '無'}")

    log("=== ② 分組簡介（策展語气） ===")
    _fid_cache = []

    def get_fid():
        if _fid_cache:
            return _fid_cache[0]
        art = OB.feed_channel_art()
        f = OB.upload_thumb(art) if art else None
        _fid_cache.append(f or "")
        return _fid_cache[0]

    set_group_desc(grps, TFF_GP, TFF_DESC, "TFF", get_fid)
    set_group_desc(grps, HTF_GP, HTF_DESC, "HTF", get_fid)
    unknown = [g for g in grps if not any((g.get("Id") or "").startswith(p)
                                          for p in (TFF_GP, HTF_GP, BWK_GP))]
    if len(unknown) == 1:
        ob_prefix = unknown[0]["Id"][:8]
        log(f"OB 分組判定: {unknown[0].get('Name')!r} ({ob_prefix})")
        set_group_desc(grps, ob_prefix, OB_DESC, "OB", get_fid)
    elif any("being" in (g.get("Name") or "").lower() for g in unknown):
        g = next(g for g in unknown if "being" in (g.get("Name") or "").lower())
        set_group_desc(grps, g["Id"][:8], OB_DESC, "OB", get_fid)
    else:
        log(f"OB 分組無法唯一判定（unknown={len(unknown)}）——請人工確認名稱")

    log("=== ③ 殭屍 11 集補縮圖 ===")
    patch_zombie_thumbs(cid)
    OB.ntfy("On Being face-maint done",
            "偵查＋三組簡介＋殭屍補縮圖已執行——詳見 Actions log。", 2)
    log("=== MAINT DONE ===")


if __name__ == "__main__":
    main()
