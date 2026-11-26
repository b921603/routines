#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""podcast/covers.py — 封面 SOP 模組（11-26 用戶裁定：channel/episode cover 標準化）。

政策表（ShowConfig.channel_art / episode_art，端看各頻道特性）：
  channel_art:
    rss_or_generate（預設）＝RSS 頻道插畫優先 → 無則生成封面（確定性：節目名＋accent 色）
    rss_only              ＝只用 RSS 插畫，無則不設（平台預設）
    never                 ＝不設頻道封面
  episode_art:
    when_available（預設）＝RSS item 有 per-episode 插畫→逐集上傳（URL-hash 快取，防孤兒重複）
                           無 per-ep 插畫的集→沿用頻道封面（**不**上傳空 thumb）
    never                 ＝一律頻道封面（封面極簡型頻道，如純音訊長節目）

孤兒防線：所有 thumb 上傳經 ThumbCache／URL-hash 快取——同封面永不重複上傳。
"""
import os, re, io, json, time, hashlib
from engine_kit import req, eudic_upload, log


def _cache_dir(key):
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "state", "covers", key)
    os.makedirs(d, exist_ok=True)
    return d


def channel_art_from_feed(cfg):
    """RSS 頻道級插畫（itunes:image href）→ bytes|None。"""
    try:
        r = req("GET", cfg.feed_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
        head = (r.text or "")[:40000]
        m = (re.search(r"<channel>.*?<itunes:image[^>]*href=\"([^\"]+)\"", head, re.S | re.I)
             or re.search(r"<channel>.*?<image>.*?<url>([^<]+)</url>", head, re.S | re.I))
        if not m:
            return None
        img = req("GET", m.group(1), headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
        return img.content if img.status_code == 200 and len(img.content) > 5000 else None
    except Exception as ex:
        log(f"cover: feed art err: {str(ex)[:60]}")
        return None


def generated_cover(name, accent="#0f766e", label="PODCAST"):
    """確定性生成封面（Pillow；無 PIL 回 None→政策降級）。600×600 JPEG。"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    W = 600
    img = Image.new("RGB", (W, W), accent)
    d = ImageDraw.Draw(img)
    d.rectangle([0, W - 96, W, W], fill=tuple(max(0, c - 40) for c in
                                              _hex2rgb(accent)))
    d.text((28, 20), label, fill=(255, 255, 255))
    words, lines, cur = name.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if len(t) > 18 and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    y = W // 3
    for ln in lines[:4]:
        d.text((28, y), ln, fill=(255, 255, 255))
        y += 52
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def episode_art_from_item(item_url, key, max_bytes=8_000_000):
    """per-episode 插畫→bytes|None；URL-hash 快取 72h（防逐集重複上傳孤兒）。"""
    if not item_url:
        return None
    h = hashlib.sha1(item_url.encode()).hexdigest()[:16]
    cp = os.path.join(_cache_dir(key), f"ep_{h}.art")
    if os.path.exists(cp) and time.time() - os.path.getmtime(cp) < 72 * 3600:
        return open(cp, "rb").read()
    try:
        img = req("GET", item_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
        if img.status_code == 200 and 5000 < len(img.content) < max_bytes:
            open(cp, "wb").write(img.content)
            return img.content
    except Exception as ex:
        log(f"cover: ep art err: {str(ex)[:60]}")
    return None


def ensure_channel_art(cfg, thumb_cache):
    """政策驅動的頻道封面（每 run 至多一次上傳）。回 thumb fid 或 ''。"""
    if cfg.channel_art == "never":
        return ""
    img = None
    if cfg.channel_art in ("rss_or_generate", "rss_only"):
        img = channel_art_from_feed(cfg)
    if img is None and cfg.channel_art == "rss_or_generate":
        img = generated_cover(cfg.name, cfg.accent)
        if img:
            log("cover: RSS 無頻道插畫 → 生成封面（確定性）")
    if img is None:
        log("cover: 無可用頻道封面（政策降級為平台預設）")
        return ""
    fid = thumb_cache.fid_for(img)
    return fid


def episode_thumb_fid(cfg, art_url, thumb_cache, channel_fid):
    """per-episode 政策：有 per-ep 插畫→快取後上傳取 fid；否則沿用頻道封面。"""
    if cfg.episode_art == "never" or not art_url:
        return channel_fid, False            # False=未上傳（用頻道封面）
    img = episode_art_from_item(art_url, cfg.key)
    if not img:
        return channel_fid, False
    fid = eudic_upload("thumb", "ep.jpg", img, "image/jpeg")
    return (fid or channel_fid), bool(fid)


def _hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
