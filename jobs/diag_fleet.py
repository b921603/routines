"""diag_fleet.py — 唯讀盤點（頻道/分組/指定頻道媒體）。PII 紀律：只印名稱/id/計數。"""
import re, sys, html
sys.path.insert(0, "podcast")
import ob_update as ob

ob.login()

r = ob.req("GET", f"{ob.BASE}/ting/GetPrivateChannels", timeout=45)
chs = r.json().get("channelList", {}).get("UploadedChannels") or []
print(f"== channels ({len(chs)}) ==")
for c in chs:
    print(f"  name={html.unescape(c.get('Name') or '')!r} id={c.get('Id')} "
          f"type={c.get('ChannelType')} thumb={'Y' if (c.get('Thumb') or '').strip() else 'n'} "
          f"desc={html.unescape(c.get('Description') or '')[:50]!r}")

g = ob.req("POST", f"{ob.BASE}/ting/GetPrivateGroups?withDefault=false", data="", timeout=40)
grps = g.json().get("channelList", {}).get("UploadedChannels") or []
print(f"== groups ({len(grps)}) ==")
for c in grps:
    print(f"  name={html.unescape(c.get('Name') or '')!r} id={c.get('Id')} "
          f"thumb={'Y' if (c.get('Thumb') or '').strip() else 'n'} "
          f"desc={html.unescape(c.get('Description') or '')[:80]!r}")
print("== diag done ==")
