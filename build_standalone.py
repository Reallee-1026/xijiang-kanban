"""把 index.html + data.js 打成一个自包含的单文件 HTML（方便微信/网盘分享、丢到任意静态托管）。

用法：python build_standalone.py
输出：西江看板.html
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "index.html")
DATA = os.path.join(HERE, "data.js")
OUT = os.path.join(HERE, "西江看板.html")


def main():
    with open(SRC, encoding="utf-8") as f:
        html = f.read()
    with open(DATA, encoding="utf-8") as f:
        js = f.read().strip()

    # 校验 data.js 能解析，避免把坏数据打进单文件
    payload = js.split("=", 1)[1].strip().rstrip(";") if "=" in js else ""
    try:
        meta = json.loads(payload)
    except Exception as e:
        print("data.js 解析失败，先跑一次 update_data.py:", e)
        sys.exit(1)

    if '<script src="data.js"></script>' not in html:
        print("index.html 里没找到 <script src=\"data.js\"></script>，脚本可能已改过")
        sys.exit(1)

    inline = "<script>\n" + js + "\n</script>"
    html = html.replace('<script src="data.js"></script>', inline)

    # 单文件版加一句提示，说明水位是打进包里的快照
    stamp = meta.get("updated", "")
    note = ("<!-- 单文件版，生成时间 %s；待闸数为打开时实时拉取，水位为打包时快照 -->\n" % stamp)
    html = note + html

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    # 同步一份到 _pub/：发布到 Netlify 时直接拖这个文件（必须叫 index.html 才会当首页）
    pub_dir = os.path.join(HERE, "_pub")
    os.makedirs(pub_dir, exist_ok=True)
    with open(os.path.join(pub_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    kb = os.path.getsize(OUT) / 1024
    print("已生成 %s（%.1f KB，快照时间 %s）" % (os.path.basename(OUT), kb, stamp))
    print("已同步发布文件 _pub/index.html")


if __name__ == "__main__":
    main()
