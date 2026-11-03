#!/usr/bin/env python3
"""用舷窗Plus 的 iPhone 安装页生成另一个 App 的安装站点。
用法：make-app-site.py <输出目录> <icon-1024.png> <配置.json>
配置：title brand home home_label apk（安卓安装包地址） testflight（TestFlight 公开链接） testflight_ready（测试版过审后设 true，iPhone 才直接跳 TestFlight） step4（可空） faq_extra（可空）
"""
import json, os, re, shutil, subprocess, sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out, icon, cfg = sys.argv[1], sys.argv[2], json.load(open(sys.argv[3]))
t = cfg["title"]
shutil.rmtree(out, ignore_errors=True)
os.makedirs(os.path.join(out, "assets"))
os.makedirs(os.path.join(out, "ios"))
shutil.copy(os.path.join(root, "assets/site.css"), os.path.join(out, "assets/site.css"))
shutil.copy(os.path.join(root, "ios/install.css"), os.path.join(out, "ios/install.css"))
shutil.copy(os.path.join(root, "ios/install.js"), os.path.join(out, "ios/install.js"))
for n in (512, 180, 64, 57):
    subprocess.run(["sips", "-s", "format", "png", "-z", str(n), str(n), icon, "--out", os.path.join(out, f"assets/icon-{n}.png")],
                   check=True, capture_output=True)

s = open(os.path.join(root, "ios/index.html"), encoding="utf-8").read()
home = cfg["home"]
s = s.replace('<a class="brand" href="../">', f'<a class="brand" href="{home}">')
s = s.replace('<span>舷窗<b>Plus</b></span>', f'<span>{cfg["brand"]}</span>')
s = re.sub(r'<nav>.*?</nav>', f'<nav><a href="{home}">{cfg["home_label"]}</a></nav>', s, flags=re.S)
s = s.replace('回桌面看图标转完就能玩', '回桌面等图标转完就能用')
step4 = re.search(r'\s*<li>\s*<b>第一次建房时.*?</li>', s, re.S).group(0)
s = s.replace(step4, ("\n      <li>\n        <b>" + cfg["step4"][0] + "</b>\n        <span>" + cfg["step4"][1] + "</span>\n      </li>") if cfg.get("step4") else "")
s = s.replace("直接下载安装包。", "直接下载安装包。" + cfg.get("faq_extra", ""))
s = s.replace('<footer class="foot"><p><a href="../">返回舷窗Plus 首页</a></p></footer>', f'<footer class="foot"><p><a href="{home}">{cfg["home_label"]}</a></p></footer>')
s = s.replace("https://github.com/gxlself/porthole-plus/releases/latest/download/PortholePlus.apk", cfg["apk"])
s = s.replace("https://testflight.apple.com/join/cyyEwAxw", cfg["testflight"])
s = s.replace('data-ready="0"', 'data-ready="%s"' % ("1" if cfg.get("testflight_ready") else "0"))
s = s.replace("舷窗Plus", t).replace("../assets/", "/assets/")
assert "舷窗Plus" not in s and "porthole-plus/releases" not in s and "cyyEwAxw" not in s and 'href="../' not in s, "还有没替换掉的舷窗Plus 链接"
open(os.path.join(out, "ios/index.html"), "w", encoding="utf-8").write(s)
open(os.path.join(out, "index.html"), "w").write('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=/ios/"><a href="/ios/">安装</a>\n')
print("ok", out)
