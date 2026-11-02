# 舷窗Plus

万米高空，没网也能一起开黑。六款多人对战小游戏（卡丁车、炸弹人、坦克大战、英雄对决、彩弹大作战、王国争霸），连同一个 Wi-Fi 或安卓热点，身边最多 8 人扫码进房，不用流量、不用注册。

- 宣传页：https://porthole.gxlself.com/（GitHub 副本 https://gxlself.github.io/porthole-plus/）
- iPhone 安装：https://porthole.gxlself.com/ios/（点一下自动登记设备，不用手动查 UDID）
- 安装包：[Releases](https://github.com/gxlself/porthole-plus/releases)

这个仓库只放宣传页和安装页，游戏源码不在这里。

## 目录

- `index.html`、`assets/`：宣传页
- `ios/`：iPhone 安装页
- `server/enroll.py`：iPhone 自动登记 + 重签服务，部署在 `porthole.gxlself.com`（nginx → 127.0.0.1:8795，systemd `porthole-enroll`）。凭据只在服务器 `/opt/porthole/secrets`，不进仓库。
