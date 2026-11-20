# 第三方组件与许可证

本项目（源码，MIT）在运行和分发时用到了下面这些第三方组件。
**发布二进制包（dist 里的 zip）时必须一并附带本文件。**

---

## Spine Runtimes（vendor/spine-webgl-3.8.js）

版本：3.8（对应 Spine 3.8.99 资源）
项目：https://github.com/EsotericSoftware/spine-runtimes
许可证：Spine Runtimes License Agreement

> **重要**：Spine 运行时不是 MIT。随程序分发时**必须保留下面的许可证全文与版权声明**，
> 并且**每个使用者需要自行持有 Spine Editor 授权**才能使用该运行时。
> 如果你的使用场景不接受这一条，可以从仓库中删除 `vendor/spine-webgl-3.8.js`，
> 由使用者自行准备运行时。

```
Spine Runtimes License Agreement
Last updated May 1, 2019. Replaces all prior versions.

Copyright (c) 2013-2019, Esoteric Software LLC

Integration of the Spine Runtimes into software or otherwise creating
derivative works of the Spine Runtimes is permitted under the terms and
conditions of Section 2 of the Spine Editor License Agreement:
http://esotericsoftware.com/spine-editor-license

Otherwise, it is permitted to integrate the Spine Runtimes into software
or otherwise create derivative works of the Spine Runtimes (collectively,
"Products"), provided that each user of the Products must obtain their own
Spine Editor license and redistribution of the Products in any form must
include this license and copyright notice.

THIS SOFTWARE IS PROVIDED BY ESOTERIC SOFTWARE LLC "AS IS" AND ANY EXPRESS
OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN
NO EVENT SHALL ESOTERIC SOFTWARE LLC BE LIABLE FOR ANY DIRECT, INDIRECT,
INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

---

## UnityPy

版本：1.20.26
项目：https://github.com/K0lb3/UnityPy
许可证：MIT License
用途：读取 Unity AssetBundle（`char/` 下的 skel / atlas / 贴图）

```
MIT License

Copyright (c) 2019 K0lb3

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## Pillow

版本：>= 10
项目：https://python-pillow.org/
许可证：MIT-CMU（HPND 变体）

```
The Python Imaging Library (PIL) is

    Copyright (c) 1997-2011 by Secret Labs AB
    Copyright (c) 1995-2011 by Fredrik Lundh and contributors

Pillow is the friendly PIL fork. It is

    Copyright (c) 2010 by Jeffrey A. Clark and contributors

Like PIL, Pillow is licensed under the open source MIT-CMU License:

By obtaining, using, and/or copying this software and/or its associated
documentation, you agree that you have read, understood, and will comply
with the following terms and conditions:

Permission to use, copy, modify and distribute this software and its
documentation for any purpose and without fee is hereby granted, provided
that the above copyright notice appears in all copies, and that both that
copyright notice and this permission notice appear in supporting
documentation, and that the name of Secret Labs AB or the author not be
used in advertising or publicity pertaining to distribution of the software
without specific, written prior permission.

SECRET LABS AB AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS
SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS.
IN NO EVENT SHALL SECRET LABS AB OR THE AUTHOR BE LIABLE FOR ANY SPECIAL,
INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE
OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.
```

---

## PyInstaller

版本：>= 6
项目：https://pyinstaller.org/
许可证：GPL-2.0-or-later，**附带打包例外（Bootloader Exception）**：
把程序用 PyInstaller 打包并分发时，打包产物可以继续使用你自己的许可证。
本项目的发布包（`dist/AzurLaneChibiViewer`）依赖该例外。

---

## Python

版本：3.12
项目：https://www.python.org/
许可证：PSF License Agreement

---

## 游戏素材

本仓库**不包含**任何《碧蓝航线》的游戏资源。角色立绘、骨骼、贴图的版权归
上海蛮啾网络科技 / 勇仕网络及原画作者所有，使用者需自备游戏文件，
并仅将其用于个人学习，不得再分发或商用。
