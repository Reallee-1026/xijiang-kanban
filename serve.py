"""局域网内查看看板：在本机起一个静态文件服务，同一 Wi-Fi 下的手机/电脑直接用浏览器打开。

用法：双击 start_lan.bat（或 python serve.py [端口]）
"""
import http.server
import os
import socket
import socketserver
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
os.chdir(os.path.dirname(os.path.abspath(__file__)))


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # 手机浏览器缓存很顽固，禁用缓存保证每次都拿到最新 data.js
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):
        print("  [%s] %s" % (self.log_date_time_string(), fmt % args))


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    ip = lan_ip()
    print("=" * 56)
    print(" 西江看板 · 局域网访问已启动")
    print("")
    print(" 手机/其他电脑（需与本机同一个 Wi-Fi/局域网）打开：")
    print("     http://%s:%d/index.html" % (ip, PORT))
    print("")
    print(" 本机自己看：  http://127.0.0.1:%d/index.html" % PORT)
    print(" 首次运行若弹出防火墙提示，请选“允许访问”。")
    print(" 按 Ctrl+C 停止服务。")
    print("=" * 56)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")
