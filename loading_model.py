# -*- coding: utf-8 -*-
"""水位减载公式 —— 3000 吨集装箱驳船（满载 85 柜）梧州三港装载量测算

核心公式（每个港口一套参数）：

    减载柜数  d_i(h) = D_i * (1 - exp(-a_i * x_i ^ p_i)),   x_i = max(0, h0_i - h)
    装载柜数  L_i(h) = clamp(85 - d_i(h), 0, 85)

    h     : 梧州站水位（m）
    h0_i  : 该港"开始减载"的临界水位（m），h >= h0 时不减载
    D_i   : 该港减载上限（柜），水位无限低时最多减这么多
    a_i   : 减载陡峭系数
    p_i   : 曲线形状（p<1 先陡后缓，p>1 先缓后陡）

参数由历史观测（两份文档 + 用户经验 + 每次实际配载反馈）拟合得到，
每次调用 update() 会用新观测按"越新权重越大"的方式重新拟合（指数遗忘），
所以公式会随使用不断自我校准。

命令行：
    python loading_model.py predict 2.45
    python loading_model.py update 2.45 16 34 13        # 水位 梧州 大利口 紫金村（实际减载柜数）
    python loading_model.py show
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "loading_model.json")

PORTS = [("wz", "梧州(李家庄)"), ("dlk", "大利口"), ("zjc", "紫金村")]
FULL = 85                 # 满载柜数
DECAY = 0.92              # 每条新观测相对上一条的权重衰减
BOUNDS = {                # (下限, 上限)
    "D": (20.0, 70.0),
    "a": (0.05, 8.0),
    "p": (0.35, 2.50),
    "h0": (2.55, 3.45),
}
# 各港减载上限先验（柜）：来自文档中该港最大减载率（李家庄≈30%、大利口≈50%、紫金村≈20%）
D_PRIOR = {"wz": 30.0, "dlk": 42.0, "zjc": 18.0}
D_SPREAD = (0.85, 1.15)   # D 允许在先验的 85%~115% 之间调整
P_RANGE = (0.85, 1.60)    # 形状指数下限 0.85：避免 p<1 时在临界水位处出现"垂直悬崖"
H0_MARGIN = 0.30          # h0 不得高于"最高观测水位 + 0.30m"，否则曲线被拉平
HUBER = 2.0

# ---------------------------------------------------------------- 数据装载

def _mid(rng):
    return (rng[0] + rng[1]) / 2.0


def _width(rng):
    return max(0.0, rng[1] - rng[0])


SRC_W = {"1234": 1.0, "123": 0.35, "anchor": 6.0, "feedback": 1.0}
TOP_H = 2.65        # 高水位段（样本少、决定临界水位）额外加权
TOP_BOOST = 2.0


def build_samples(obs, port):
    """把观测区间转成加权样本 (h, y, w)。

    权重规则：
      * 文档类（123/1234/专家口径）是同一批历史证据，按来源给固定基础权重，
        不随时间衰减 —— 它们的价值在于覆盖高水位段；
      * 实际配载反馈（feedback）是流式数据，越新权重越大（DECAY^age，下限 0.2）；
      * 区间越宽（原文只给了大概范围）权重越低。
    """
    fb_age = {i: 0 for i in range(len(obs))}
    k = 0
    for i in range(len(obs) - 1, -1, -1):
        if obs[i].get("src") == "feedback":
            fb_age[i] = k
            k += 1
    hs, ys, ws = [], [], []
    for i, o in enumerate(obs):
        rng = o.get(port)
        if not rng:
            continue
        src = o.get("src", "1234")
        base = SRC_W.get(src, 1.0)
        if src == "feedback":
            base = max(DECAY ** fb_age[i], 0.2)
        w = base * float(o.get("wmult", 1.0)) / (1.0 + 0.6 * _width(rng))
        if float(o["h"]) >= TOP_H and src not in ("anchor",):
            w *= TOP_BOOST
        hs.append(float(o["h"]))
        ys.append(_mid(rng))
        ws.append(w)
    return np.array(hs), np.array(ys), np.array(ws)


# ---------------------------------------------------------------- 模型函数

def curve(params, h):
    D, a, p, h0 = params["D"], params["a"], params["p"], params["h0"]
    x = np.maximum(0.0, h0 - np.asarray(h, dtype=float))
    with np.errstate(over="ignore"):
        d = D * (1.0 - np.exp(-a * np.power(x, p)))
    return np.clip(np.nan_to_num(d, nan=0.0), 0.0, 85.0)


def bounds_for(port, obs=None):
    """参数边界。h0 用数据驱动窗口：必须高于最高观测水位附近的点位，
    又不得比最高观测水位高太多（h0 越远曲线越平，高水位段会严重高估装载）。"""
    lo, hi = D_SPREAD
    b = dict(BOUNDS)
    b["D"] = (lo * D_PRIOR[port], hi * D_PRIOR[port])
    b["p"] = P_RANGE
    if obs:
        hs = [float(o["h"]) for o in obs if o.get(port)]
        if hs:
            hmax = max(hs)
            b["h0"] = (max(BOUNDS["h0"][0], hmax - 0.05),
                       min(BOUNDS["h0"][1], hmax + H0_MARGIN))
    return b


def _loss(params, hs, ys, ws, bnd=None):
    bnd = bnd or BOUNDS
    if not all(bnd[k][0] <= params[k] <= bnd[k][1] for k in ("D", "a", "p", "h0")):
        return 1e12
    r = ys - curve(params, hs)
    ar = np.abs(r)
    hub = np.where(ar <= HUBER, 0.5 * r ** 2, HUBER * (ar - 0.5 * HUBER))
    return float(np.sum(ws * hub))


def _nelder_mead(f, x0, step, iters=600, tol=1e-10):
    """无约束 Nelder-Mead（边界由 f 内部惩罚）。"""
    n = len(x0)
    simplex = [np.array(x0, dtype=float)]
    for i in range(n):
        v = np.array(x0, dtype=float)
        v[i] += step[i]
        simplex.append(v)
    fvals = [f(v) for v in simplex]
    for _ in range(iters):
        order = np.argsort(fvals)
        simplex = [simplex[i] for i in order]
        fvals = [fvals[i] for i in order]
        if abs(fvals[-1] - fvals[0]) <= tol * (abs(fvals[0]) + 1e-12):
            break
        centroid = np.mean(simplex[:-1], axis=0)
        xr = centroid + 1.0 * (centroid - simplex[-1])
        fr = f(xr)
        if fr < fvals[0]:
            xe = centroid + 2.0 * (centroid - simplex[-1])
            fe = f(xe)
            simplex[-1], fvals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < fvals[-2]:
            simplex[-1], fvals[-1] = xr, fr
        else:
            xc = centroid + 0.5 * (simplex[-1] - centroid)
            fc = f(xc)
            if fc < fvals[-1]:
                simplex[-1], fvals[-1] = xc, fc
            else:
                for i in range(1, n + 1):
                    simplex[i] = simplex[0] + 0.5 * (simplex[i] - simplex[0])
                    fvals[i] = f(simplex[i])
    return simplex[0], fvals[0]


def fit(obs, port, starts=None):
    hs, ys, ws = build_samples(obs, port)
    if len(hs) < 3:
        raise ValueError(f"{port}: 观测不足")
    bnd = bounds_for(port, obs)
    f = lambda v: _loss(dict(D=v[0], a=v[1], p=v[2], h0=v[3]), hs, ys, ws, bnd)
    best, best_f = None, float("inf")
    seed = starts or [
        (D0, a0, p0, h0_0)
        for D0 in (0.85 * D_PRIOR[port], 1.05 * D_PRIOR[port])
        for a0 in (0.5, 1.5, 3.5)
        for p0 in (0.6, 1.0, 1.5)
        for h0_0 in (2.70, 2.85, 3.00, 3.15, 3.30)
    ]
    for s in seed:
        v, fv = _nelder_mead(f, s, step=(4.0, 0.5, 0.3, 0.10), iters=400)
        if fv < best_f:
            best, best_f = v, fv
    params = dict(D=float(best[0]), a=float(best[1]), p=float(best[2]), h0=float(best[3]))
    # 残差标准差 -> 预测区间
    r = ys - curve(params, hs)
    sigma = float(np.sqrt(np.average(r ** 2, weights=ws))) if len(r) else 0.0
    return params, sigma, float(best_f)


# ---------------------------------------------------------------- 预测/状态

def predict_from(params, sigma, h, z=1.2816):
    out = {}
    for key, name in PORTS:
        d = float(curve(params[key], h))
        half = max(1.2, z * sigma[key])
        lo = max(0.0, d - half)
        hi = min(85.0, d + half)
        out[key] = {
            "name": name,
            "shed": round(d, 1),
            "shed_range": [round(lo, 1), round(hi, 1)],
            "load_range": [int(round(85 - hi)), int(round(85 - lo))],
            "load": int(round(85 - d)),
        }
    return out


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_state(state):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def refit(state):
    for key, _ in PORTS:
        p, s, f = fit(state["obs"], key)
        state["params"][key] = p
        state["sigma"][key] = s
        state["fit"][key] = f
    state["n_obs"] = len(state["obs"])
    state["fitted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return state


def display(state, h):
    res = predict_from(state["params"], state["sigma"], h)
    print(f"\n梧州站水位 {h:.2f} m  →  3000t 驳船（满载 {FULL} 柜）可用装载")
    if h < 1.8 or h > 3.3:
        print("⚠ 该水位超出历史数据范围（1.8~3.3m），结果仅供参考，请以现场吃水为准")
    print("-" * 62)
    print(f"{'港口':<14}{'减载(柜)':<16}{'可装(柜)':<14}")
    for key, _ in PORTS:
        r = res[key]
        print(f"{r['name']:<12}{r['shed']:>4} ({r['shed_range'][0]:.0f}~{r['shed_range'][1]:.0f})"
              f"{'':<4}{r['load']:>4} ({r['load_range'][0]}~{r['load_range'][1]})")
    print("-" * 62)
    return res


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "show"
    state = load_state()
    if state is None:
        sys.exit("没有模型状态，先运行 bootstrap.py 初始化")
    if cmd == "predict":
        display(state, float(argv[2]))
    elif cmd == "update":
        h = float(argv[2])
        vals = [float(x) for x in argv[3:6]]
        row = {"h": h, "src": "feedback",
               "ts": datetime.now().strftime("%Y-%m-%d %H:%M")}
        for (key, _), v in zip(PORTS, vals):
            row[key] = [v, v]
        state["obs"].append(row)
        state = refit(state)
        save_state(state)
        print(f"[已学习] 新增观测 水位={h}m  减载=({vals[0]}, {vals[1]}, {vals[2]})，"
              f"共 {state['n_obs']} 条，参数已更新。")
        display(state, h)
    else:
        print(json.dumps({"params": state["params"], "sigma": state["sigma"],
                          "n_obs": state["n_obs"], "fitted_at": state["fitted_at"]},
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv)
