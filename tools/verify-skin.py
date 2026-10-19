#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-skin.py —— c137-virus 皮肤包自检

改完素材或改完标识之后跑一遍，确认这个包还是「能装、能生效」的状态。
覆盖三类最容易踩的坑：
  1. 标识不一致（包名 / skin id / 作用域属性三处必须对齐）
  2. 驼峰作用域属性漏改（CSS 改了、dataset 没改 -> 皮肤装了但完全不生效）
  3. 素材引用悬空（client.js 引用的哈希不在磁盘上或不在白名单里 -> 图裂）

用法:
    python tools/verify-skin.py
退出码 0 = 全部通过。
"""
import os
import re
import sys
import json
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CLIENT = os.path.join(ROOT, "lib", "client.js")
INDEX = os.path.join(ROOT, "lib", "index.js")
SKIN = os.path.join(ROOT, "skin.json")
PKG = os.path.join(ROOT, "package.json")
PATCH = os.path.join(ROOT, "cordis.patch.yml")
RUNTIME = os.path.join(ROOT, "assets", "runtime")
MANIFEST = os.path.join(RUNTIME, "manifest.json")

ok, fail = [], []


def check(cond, msg):
    (ok if cond else fail).append(msg)


def camel(attr):
    """data-dsh-c137-virus -> dshMySkin"""
    parts = attr.split("-")
    if parts and parts[0] == "data":
        parts = parts[1:]
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def main():
    for p in (CLIENT, INDEX, SKIN, PKG, PATCH, MANIFEST):
        if not os.path.exists(p):
            sys.exit(f"缺少文件: {p}")

    client = open(CLIENT, encoding="utf-8").read()
    index = open(INDEX, encoding="utf-8").read()
    skin = json.load(open(SKIN, encoding="utf-8"))
    pkg = json.load(open(PKG, encoding="utf-8"))
    patch = open(PATCH, encoding="utf-8").read()

    pkg_name = pkg.get("name", "")
    skin_id = skin.get("id", "")
    body_attr = skin.get("bodyAttr", "")
    wiring = skin.get("wiring", {}).get("id", "")
    cam = camel(body_attr)

    # --- 1. 标识一致性 ---
    check(bool(pkg_name), "package.json 有 name")
    check(skin.get("package") == pkg_name, f"skin.json package == package.json name ({pkg_name})")
    check(f'id: "{pkg_name}"' in client, "client.js 的 ModuleLoader 模块 id == 包名")
    check(f'"{wiring}"' in patch or wiring in patch, "cordis.patch.yml 声明了 wiring id")
    check(pkg_name in patch, "cordis.patch.yml 指向本包名")
    check(pkg.get("dsh", {}).get("bundle", {}).get("patch") == "./cordis.patch.yml",
          "package.json 声明了 dsh.bundle.patch（否则装上是死的）")

    # --- 2. 作用域属性三处对齐 ---
    check(f"body[{body_attr}]" in client, f"CSS 用作用域选择器 body[{body_attr}]")
    check(f'body.dataset.{cam} = ""' in client, f"JS 用 body.dataset.{cam} 设作用域（驼峰形式）")
    check(f"delete body.dataset.{cam}" in client, f"JS 卸载时清理 body.dataset.{cam}")
    stray = re.findall(r"body\.dataset\.([A-Za-z0-9]+)", client)
    bad = sorted({s for s in stray if s.lower().startswith("dsh") and s != cam})
    check(not bad, f"没有别的 dsh* 驼峰作用域残留 (发现 {bad})" if bad else "没有别的 dsh* 驼峰作用域残留")
    check(f'"{skin_id}"' in client or f"skinId: \"{skin_id}\"" in client, f"client.js 里的 skinId == {skin_id}")
    check(f"/skin-assets/{skin_id}/" in client or f"skin-assets/{skin_id}/" in client,
          f"客户端资源路由前缀指向 /skin-assets/{skin_id}/")
    check(f'installSkinAssets(ctx, "{skin_id}"' in index, "host 侧注册的资源路由 id 一致")

    # --- 3. 素材引用完整性 ---
    refs = {h for h, _ in re.findall(r'skinAssetUrl\(\s*"([a-f0-9]{64})\.(webp|png)"\s*\)', client)}
    disk = {f.split(".")[0] for f in os.listdir(RUNTIME) if f.endswith((".webp", ".png"))}
    man = {f.split(".")[0] for f in json.load(open(MANIFEST, encoding="utf-8"))}
    m = re.search(r"var manifest_default = \[(.*?)\];", index, re.S)
    inl = {x.strip().strip('"').split(".")[0] for x in m.group(1).split(",") if x.strip()} if m else set()

    check(bool(refs), f"解析到 client.js 里的素材引用（{len(refs)} 个）")
    check(not (refs - disk), f"引用都在磁盘上" + (f"，缺 {sorted(refs - disk)}" if refs - disk else ""))
    check(not (refs - man), f"引用都在 manifest.json 白名单里" + (f"，缺 {sorted(refs - man)}" if refs - man else ""))
    check(not (refs - inl), f"引用都在 index.js 内联白名单里" + (f"，缺 {sorted(refs - inl)}" if refs - inl else ""))
    check(man == inl, "runtime/manifest.json 与 index.js 内联白名单一致")

    # --- 4. 语法 ---
    node = shutil.which("node") or shutil.which("node.exe") or \
        r"C:\Users\A\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"
    if node and os.path.exists(node):
        for rel in ("lib/index.js", "lib/client.js"):
            src = os.path.join(ROOT, rel.replace("/", os.sep))
            tmp = src + ".syntaxcheck.mjs"
            shutil.copyfile(src, tmp)
            try:
                r = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
                check(r.returncode == 0, f"{rel} 语法可解析"
                      + ("" if r.returncode == 0 else " :: " + r.stderr.strip()[:300]))
            finally:
                os.remove(tmp)
    else:
        ok.append("跳过语法检查（找不到 node）")

    for x in ok:
        print("  OK   " + x)
    if fail:
        print()
        for x in fail:
            print("  FAIL " + x)
        print(f"\n{len(fail)} 项失败 / 共 {len(ok) + len(fail)} 项")
        sys.exit(1)
    print(f"\n全部 {len(ok)} 项校验通过 —— {skin.get('name')} ({pkg_name}) 可以装。")
    print(f"素材引用 {len(refs)} 个 | 白名单 {len(man)} 项 | 磁盘 {len(disk)} 个文件")


if __name__ == "__main__":
    main()
