# AzurLane Chibi Viewer · 碧蓝航线小人动画预览器

<p align="center"><img src="docs/icon.png" width="96" alt="icon"></p>

一个本地运行的《碧蓝航线》Q 版小人（SD）动画预览器：直接读取游戏
`AssetBundles/char/` 里的 Spine 3.8 资源，在浏览器/独立窗口里播放、
逐帧查看、导出透明 GIF。

> **非官方工具**，与上海蛮啾网络科技、勇仕网络无关。
> 本仓库不附带任何游戏素材，使用时需要你自备游戏文件，仅供个人学习，请勿商用。

**English**: A local viewer for Azur Lane SD (chibi) Spine animations. It reads
`AssetBundles/char/` directly, plays the animations in a desktop window, supports
frame stepping, and exports transparent GIFs. No game assets are included.

---

## 功能

- 直接读取 `char/` 下的 AssetBundle，按需解包并缓存，不需要提前导出
- 角色列表按**角色**折叠（约 1550 个），皮肤下拉列出全部版本
  （原版 / 皮肤 N / 改造 / 婚纱 / 和谐 / 左 / 右 / 异格 / 联动）
- 动作切换（`normal` / `attack` / `skill` / `dance` …），带时长
- 逐帧步进（← / →），可切换 24/30/60fps 采样
- 播放速度 0.1~2×，0.5× / 1× / 2× 一键预设
- 滚轮缩放、拖动平移，截图保存 PNG
- 导出**透明背景、30fps** 的循环 GIF（按角色外框裁剪）
- 自动按贴图内容处理预乘 alpha，避免边缘发灰

> 截图待补：`docs/screenshot.png`（请用自己截的界面图，不要用游戏原画）。

## 快速开始（Windows 发布包）

1. 从 [Releases](../../releases) 下载 `AzurLaneChibiViewer-win64.zip` 并解压到任意普通目录；
2. 双击 `AzurLaneChibiViewer.exe`；
3. 选择游戏的 `AssetBundles` 目录（里面应有 `char/`），点“启动”；
4. 会自动打开一个无地址栏的应用窗口。

Release 页面附 SHA256 校验值。exe 未做代码签名，首次运行可能被 SmartScreen
拦截，选择“仍要运行”即可；也可以按下面的步骤自行构建。

## 从源码运行

需要 Windows 10/11 64 位、Python 3.11+。

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python launcher.py
```

## 构建 exe

```powershell
pip install -r requirements.txt -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

产物在 `dist\AzurLaneChibiViewer\`（exe + `_internal`）和
`dist\AzurLaneChibiViewer-win64.zip`。也可以手动指定解释器：

```powershell
.\build.ps1 -Python "C:\Python312\python.exe"
```

## 工作原理

| 部分 | 说明 |
| --- | --- |
| `server.py` | 本地 HTTP 服务：按需用 UnityPy 解包 `char/<名字>`，导出 skel / atlas / 贴图（贴图预先转成预乘 alpha），并缓存到 `%LOCALAPPDATA%\ALChibiViewer\cache` |
| `app.js` + `index.html` | 用官方 spine-webgl 3.8 运行时解析二进制骨架并渲染；负责列表、动作、逐帧、GIF 取帧 |
| `launcher.py` | 启动服务，用 Edge/Chrome 应用模式打开窗口；找不到浏览器时退回小窗口 + 复制地址 |
| `/api/gif` | 浏览器把逐帧 PNG 发回服务端，Pillow 合成透明 GIF（单一调色板 + 保留透明索引） |

## 已知限制

- 只支持 **Spine 3.8.x** 资源（本游戏的 `char/` 全部是 3.8.99）；换成 4.x 运行时会读不了
- 个别资源有脏数据，例如 region 名带尾随空格（`meimao_11 `），代码里做了 trim 兜底
- 老角色贴图只有 1024×256，放大后模糊是素材分辨率决定的
- GIF 只有 1 位透明，抗锯齿边缘会被二值化，换 APNG/WebP 才能保留半透明
- 游戏内的描边/染色等 shader 效果未复刻，预览是素材原样

## 目录结构

```
.
├─ server.py              本地服务 / 解包 / 缓存 / GIF 合成
├─ launcher.py            启动器（服务 + 浏览器应用窗口）
├─ index.html app.js style.css
├─ vendor/
│  └─ spine-webgl-3.8.js  官方 Spine 运行时（见 THIRD_PARTY_NOTICES.md）
├─ assets/app.ico
├─ build.ps1              PyInstaller 打包脚本
├─ requirements.txt
├─ 使用说明.txt            给最终用户的简版说明
├─ LICENSE                MIT（仅本项目代码）
└─ THIRD_PARTY_NOTICES.md 第三方许可证（含 Spine Runtimes 全文）
```

## 免责声明

本项目仅用于学习与本机素材整理，不提供、不托管、不再分发任何游戏资源。
游戏素材的版权归上海蛮啾网络科技 / 勇仕网络及原画作者所有。
请勿将导出的素材用于商业用途或公开传播。

## 许可证

- 本项目代码：[MIT](LICENSE)
- 第三方组件：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
  - **注意**：`vendor/spine-webgl-3.8.js` 使用 Spine Runtimes License，
    再分发必须附上该许可证，且使用者需自行持有 Spine Editor 授权。
