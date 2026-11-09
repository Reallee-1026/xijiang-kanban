# -*- coding: utf-8 -*-
"""
西江看板数据采集脚本（纯标准库，无需安装任何依赖）

采集内容：
  1. 梧州（四）西江 水位            —— 广西水运门户「水情气象·水文」逐小时（含流量），水利部每日值兜底
  2. 减载模型参数                  —— loading_model.json（水位减载公式），注入 data.js
  3. 三闸 上行/下行 待闸船舶数      —— 广西水运江河海一体化智慧调度【公众服务】公开接口（免登录）
  4. 各方向 优先船 数量             —— 同上，按优先级类型聚合
并把本次快照追加进 history.jsonl，再生成 data.js 供 index.html 直接打开查看。

用法：  python update_data.py
建议： 用 Windows 任务计划程序每天 08:15、20:15 各跑一次。
"""
import json, os, re, ssl, sys, time, urllib.request, urllib.parse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY = os.path.join(BASE_DIR, "history.jsonl")
DATA_JS = os.path.join(BASE_DIR, "data.js")
LOADING_MODEL = os.path.join(BASE_DIR, "loading_model.json")

# hubId 与 gzfw 公众服务接口一致
LOCKS = [
    {"hubId": "9",  "code": "CZ",   "name": "长洲",   "full": "长洲水利枢纽"},
    {"hubId": "8",  "code": "GP",   "name": "桂平",   "full": "桂平航运枢纽"},
    {"hubId": "15", "code": "DTX",  "name": "大藤峡", "full": "大藤峡水利枢纽"},
]

# 优先船类型（与官方 legend 对齐；normal/普通船 不计入优先）
PRIORITY_TYPES = {
    "emergency_rescue", "military_transport", "urgent_material", "passenger_liner",
    "official_task", "lng_non_subsidized", "lng_subsidized",
    "non_mine_container", "mine_container", "points_exchange", "special_ship",
    "dangerOne", "dangerTwo",
}
STATUSES = ["anchor_wait", "pier_wait"]  # 锚地待闸、靠船墩待闸（闸室过闸的不算待闸）

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def http(url, data=None, headers=None, timeout=30, encoding=None):
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = data if isinstance(data, bytes) else urllib.parse.urlencode(data).encode()
        h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as r:
        raw = r.read()
    return raw.decode(encoding or "utf-8", "ignore")


def get_json(url, referer=None):
    h = {"Accept": "application/json"}
    if referer:
        h["Referer"] = referer
        h["Origin"] = "https://gzfw.gxyhzx.cn"
    d = json.loads(http(url, headers=h))
    if d.get("code") not in (1, "1", 200):
        raise RuntimeError(f"{url} -> {d.get('message') or d.get('code')}")
    return d.get("data")


# ---------- 1) 梧州（四）水位 ----------
# 首选：广西水运江河海一体化智慧调度【水情气象·水文】—— 逐小时，且带流量
#   GET https://gzfw.gxyhzx.cn/api/ws/hydrometeorology/hydrology/page?curpage=1&unitpage=24&stnm=梧州
#   返回梧州（四）stcd=80115000 的逐小时记录，08:00 的值与水利部完全一致（同站、同珠江基面）
# 兜底：水利部全国水雨情网，每日 8:00 一个值
PORTAL_API = "https://gzfw.gxyhzx.cn/api"
PORTAL_WATER_PAGE = "https://gzfw.gxyhzx.cn/ship-lock/water"
WZ_STCD = "80115000"


def fetch_wuzhou_portal():
    """门户水文接口：取梧州（四）最新一条逐小时记录。"""
    try:
        url = (PORTAL_API + "/ws/hydrometeorology/hydrology/page?" +
               urllib.parse.urlencode({"curpage": 1, "unitpage": 24, "stnm": "梧州"}))
        d = get_json(url, referer=PORTAL_WATER_PAGE) or {}
        rows = [r for r in (d.get("records") or [])
                if str(r.get("stcd")) == WZ_STCD and r.get("z") is not None]
        if not rows:
            return None
        rows.sort(key=lambda r: str(r.get("tm") or ""), reverse=True)
        r = rows[0]
        return {"ok": True, "z": round(float(r["z"]), 2), "tm": r.get("tm"),
                "q": r.get("q"), "stnm": r.get("stnm") or "梧州（四）", "src": "portal"}
    except Exception as e:
        return {"ok": False, "error": str(e), "src": "portal"}


def fetch_wuzhou_mwr():
    """水利部全国水雨情网，每日 8:00 更新（兜底）。"""
    try:
        # 该接口是 POST 风格 ajax，GET 同样可用；用 POST 更贴近官方页面
        raw = http("http://xxfb.mwr.cn/hydroSearch/mapSearch",
                   data={"name": "梧州"},
                   headers={"Referer": "http://xxfb.mwr.cn/sq_dtcx.html",
                            "X-Requested-With": "XMLHttpRequest"})
        resp = json.loads(raw)
        arr = resp.get("result") or resp.get("data") or []
        for s in arr:
            if s.get("stnm") == "梧州（四）":
                return {"z": float(s["z"]), "tm": s["tm"], "stnm": s["stnm"], "q": None,
                        "alertValue": s.get("alertValue"), "src": "mwr", "ok": True}
        if arr:
            s = arr[0]
            return {"z": float(s["z"]), "tm": s["tm"], "stnm": s.get("stnm"), "q": None,
                    "alertValue": s.get("alertValue"), "src": "mwr", "ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e), "src": "mwr"}


def fetch_wuzhou_history(days=20):
    """门户水文接口：取梧州（四）历史逐小时记录，**每天以 08:00 的值为准**。

    接口一次可返回该站全部记录（当前约 461 条，覆盖约半年），unitpage=1000 足够。
    某天没有 08:00 记录时，退而取当天最接近 08:00 的那一条，并在 tm/exact 里标明。
    """
    try:
        url = (PORTAL_API + "/ws/hydrometeorology/hydrology/page?" +
               urllib.parse.urlencode({"curpage": 1, "unitpage": 1000, "stnm": "梧州"}))
        d = get_json(url, referer=PORTAL_WATER_PAGE) or {}
        rows = [r for r in (d.get("records") or [])
                if str(r.get("stcd")) == WZ_STCD and r.get("z") is not None]

        def minutes(tm):                     # "HH:MM:00" -> 距 00:00 的分钟数
            hh, mm = str(tm)[11:16].split(":")
            return int(hh) * 60 + int(mm)

        by_day = {}
        for r in rows:
            day = str(r.get("tm") or "")[:10]
            if day:
                by_day.setdefault(day, []).append(r)

        out = []
        for day in sorted(by_day)[-days:]:
            recs = by_day[day]
            # 优先精确 08:00，否则取距 08:00 最近的一条
            best = min(recs, key=lambda r: abs(minutes(r["tm"]) - 480))
            out.append({"date": day[5:], "z": round(float(best["z"]), 2),
                        "tm": str(best["tm"])[11:16], "exact": minutes(best["tm"]) == 480,
                        "n": len(recs)})
        return out
    except Exception as e:
        print("读取水位历史失败:", e)
        return []


def fetch_wuzhou_level():
    """梧州（四）水位：门户逐小时优先，失败退回水利部每日值。"""
    p = fetch_wuzhou_portal()
    if p and p.get("ok"):
        return p
    m = fetch_wuzhou_mwr()
    if m and m.get("ok"):
        m["fallback_note"] = "门户取数失败，已退回水利部每日值"
        return m
    return {"ok": False, "src": "none",
            "error": "门户: %s / 水利部: %s" % ((p or {}).get("error"), (m or {}).get("error"))}


# ---------- 2) 待闸统计与优先船 ----------
def fetch_waiting():
    ref = "https://gzfw.gxyhzx.cn/ship-lock/schedule-info"
    api = "https://gzfw.gxyhzx.cn/api"
    stats = get_json(api + "/ws/sched/declareQueue/open/statistics/list", referer=ref)
    stat_map = {str(s["hubId"]): s for s in (stats or [])}

    result = {}
    for lk in LOCKS:
        hid = lk["hubId"]
        st = stat_map.get(hid, {})

        detail = {"todayPassedCount": st.get("todayPassedCount"),
                  "yesterdayPassedCount": st.get("yesterdayPassedCount"),
                  "directions": {}}

        for direction in ("up", "down"):
            b = st.get(direction) or {}
            d = {"total": 0, "priority": 0, "normal": 0, "byStatus": {}, "priorityBreakdown": {},
                 "waitingCount": b.get("waitingCount"),
                 "newWaitingCount": b.get("newWaitingCount"),
                 "preRegisteredCount": b.get("preRegisteredCount")}
            for status in STATUSES:
                qs = {"pageNo": 1, "pageSize": 1, "lockageStatus": status,
                      "direction": direction, "hubId": hid}
                try:
                    pg = get_json(api + "/ws/ship/lock/schedule-info/ships/page?" +
                                  urllib.parse.urlencode(qs), referer=ref)
                    pg = pg or {}
                    total = int(pg.get("total") or 0)
                    d["byStatus"][status] = total
                    d["total"] += total
                except Exception as e:
                    d["byStatus"][status] = None
                    d.setdefault("errors", []).append(f"{status}: {e}")
                time.sleep(0.25)

            # 优先船：分页拉取锚地待闸全量（接口单页上限100），按官方优先级类型聚合
            try:
                anchor_total = d["byStatus"].get("anchor_wait") or 0
                prio = {}
                page_no, page_size, fetched = 1, 100, 0
                while fetched < anchor_total:
                    qs = {"pageNo": page_no, "pageSize": page_size,
                          "lockageStatus": "anchor_wait", "direction": direction, "hubId": hid}
                    pg = get_json(api + "/ws/ship/lock/schedule-info/ships/page?" +
                                  urllib.parse.urlencode(qs), referer=ref) or {}
                    rows = pg.get("list") or []
                    if not rows:
                        break
                    for r in rows:
                        t = r.get("effectivePriorityType") or "normal"
                        if t in PRIORITY_TYPES:
                            prio[t] = prio.get(t, 0) + 1
                    fetched += len(rows)
                    page_no += 1
                    time.sleep(0.15)
                d["priorityBreakdown"] = prio
                d["priority"] = sum(prio.values())
                d["normal"] = max(0, anchor_total - d["priority"])
            except Exception as e:
                d.setdefault("errors", []).append(f"priority: {e}")

            detail["directions"][direction] = d
        result[lk["code"]] = detail
    return result


# ---------- 3) 梧州三断面水位（广西水运发展中心，85高程，每日8:00） ----------
# 用于减载估算的水位口径：统一采用梧州（四）站（珠江基面），与页面顶部水位卡一致。
# 早期版本曾抓《梧州航道和船检管理中心航道水情信息》的龙圩/梧州/界首三断面（85高程），
# 与梧州（四）相差约 0.03m 会造成两个数字打架，已按用户要求统一为梧州（四）。


def load_model_params():
    """读取 loading_model.json 里拟合好的水位减载参数，供页面直接计算。"""
    try:
        with open(LOADING_MODEL, encoding="utf-8") as f:
            m = json.load(f)
        if not m.get("params"):
            return None
        return {"params": m["params"], "sigma": m.get("sigma"),
                "n_obs": m.get("n_obs"), "fitted_at": m.get("fitted_at")}
    except Exception as e:
        print("读取装载模型失败（页面将用内置默认参数）:", e)
        return None


def main():
    print("采集时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    wz = fetch_wuzhou_level()
    print("梧州水位:", wz)
    waiting = fetch_waiting()
    for code, d in waiting.items():
        print(code, "上", d["directions"]["up"]["total"], "下", d["directions"]["down"]["total"],
              "优先上", d["directions"]["up"]["priority"], "优先下", d["directions"]["down"]["priority"])

    wz_daily = fetch_wuzhou_history(20)
    print("水位历史（近20天）:", len(wz_daily), "天",
          ("%s → %s" % (wz_daily[0]["date"], wz_daily[-1]["date"])) if wz_daily else "")

    snap = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "wuzhou": wz,
        "locks": waiting,
    }

    # 追加历史（同一天重复跑则覆盖当天最后一条：简单起见仅追加，页面按日期取最新）
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(snap, ensure_ascii=False) + "\n")

    # 组装 data.js：最新快照 + 按天历史（水位/待闸总量）
    history = []
    try:
        with open(HISTORY, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    history.append(json.loads(line))
    except FileNotFoundError:
        pass
    # 每天只保留最后一条
    by_day = {}
    for s in history:
        by_day[s["date"]] = s
    daily = []
    for day in sorted(by_day):
        s = by_day[day]
        row = {"date": day, "wuzhou": (s.get("wuzhou") or {}).get("z"), "locks": {}}
        for code in ("CZ", "GP", "DTX"):
            dd = (s.get("locks") or {}).get(code)
            if dd:
                row["locks"][code] = {
                    "upTotal": dd["directions"]["up"]["total"],
                    "downTotal": dd["directions"]["down"]["total"],
                    "upPrio": dd["directions"]["up"]["priority"],
                    "downPrio": dd["directions"]["down"]["priority"],
                    "todayPassed": dd.get("todayPassedCount"),
                }
        daily.append(row)

    payload = {"updated": snap["ts"], "latest": snap, "daily": daily[-180:],
               "wuzhouDaily": wz_daily, "loadModel": load_model_params()}
    with open(DATA_JS, "w", encoding="utf-8") as f:
        f.write("// 由 update_data.py 自动生成，请勿手改\n")
        f.write("window.BOARD_DATA = ")
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write(";\n")
    print("已生成 data.js，历史天数:", len(daily))


if __name__ == "__main__":
    main()
