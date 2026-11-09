"""一键更新并打包：采集最新数据 + 生成单文件看板。

供 打包.bat 调用（双击即可），也可直接 python build_all.py。
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    path = os.path.join(HERE, name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    os.chdir(HERE)
    print("=" * 46)
    print("  西江看板 · 一键更新并打包单文件")
    print("=" * 46)
    print("")
    print("[1/2] 采集最新数据（水位 / 待闸 / 减载 / 历史）...")
    print("")
    try:
        load("update_data").main()
    except SystemExit:
        raise
    except Exception as e:
        print("")
        print("[失败] 采集出错，未打包：%s" % e)
        print("      请检查网络能否打开 xxfb.mwr.cn 和 gzfw.gxyhzx.cn 后重试。")
        return 1

    print("")
    print("[2/2] 打包成单文件 西江看板.html ...")
    print("")
    try:
        load("build_standalone").main()
    except SystemExit as e:
        print("")
        print("[失败] 打包出错（data.js 可能损坏），exit=%s" % e.code)
        return 1

    print("")
    print("-" * 46)
    print("  完成！西江看板.html 已更新")
    print("  双击打开，或发给手机 / 别人 / 传网盘")
    print("-" * 46)
    return 0


if __name__ == "__main__":
    sys.exit(main())
