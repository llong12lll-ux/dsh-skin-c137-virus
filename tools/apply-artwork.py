#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply-artwork.py —— c137-virus 皮肤素材替换工具

把 artwork/ 目录里做好的图接进皮肤包：
  1. 按槽位名认领文件（支持中文名、大小写随意）
  2. 转成 WebP（保留透明通道）、按内容算 sha256
  3. 写入 assets/runtime/
  4. 重写 lib/index.js 与 assets/runtime/manifest.json 的白名单
  5. 重写 lib/client.js 里的素材引用
  6. 清掉不再被引用的旧素材

用法:
    python tools/apply-artwork.py --dry-run     # 只看它打算做什么，不改任何文件
    python tools/apply-artwork.py               # 真正执行
    python tools/apply-artwork.py --fit         # 尺寸不一的按原素材尺寸等比缩放
    python tools/apply-artwork.py --preview     # 顺带用新背景重做皮肤预览图

素材文件名用槽位名即可，例如 PALACE_LIGHT.png / MAID_LEFT.webp / 左立绘.png
完整槽位清单见 artwork/README.md
"""
import os
import re
import sys
import json
import shutil
import hashlib
import argparse

try:
    from PIL import Image
except ImportError:
    sys.exit("缺少 Pillow。请用 DSH 自带的 python 运行本脚本。")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ARTWORK = os.path.join(ROOT, "artwork")
RUNTIME = os.path.join(ROOT, "assets", "runtime")
CLIENT = os.path.join(ROOT, "lib", "client.js")
INDEX = os.path.join(ROOT, "lib", "index.js")
MANIFEST = os.path.join(RUNTIME, "manifest.json")

WEBP_QUALITY = 90
SIZE_TOLERANCE = 0.20          # 尺寸偏差超过 20% 就提醒

# 中文别名 -> 变量名后缀（方便直接用中文文件名的场景）
ALIASES = {
    "亮色背景": "PALACE_LIGHT", "亮色聊天背景": "PALACE_LIGHT",
    "暗色背景": "PALACE_DARK", "暗色聊天背景": "PALACE_DARK",
    "左立绘": "MAID_LEFT", "右立绘": "MAID_RIGHT", "高清右立绘": "MAID_RIGHT_VISION",
    "吉祥物": "CHIBI", "侧栏吉祥物": "CHIBI",
    "角饰": "SIDEBAR_CORNER", "侧栏角饰": "SIDEBAR_CORNER",
    "挂饰": "SIDEBAR_SWAG", "侧栏挂饰": "SIDEBAR_SWAG",
    "输入框外壳": "COMPOSER_FRAME_SHELL",
    "蕾丝": "COMPOSER_LACE_TILE", "输入器蕾丝": "COMPOSER_LACE_TILE",
    "缎带左端": "COMPOSER_RIBBON_LEFT_CAP", "缎带左中段": "COMPOSER_RIBBON_LEFT_FILL",
    "缎带右中段": "COMPOSER_RIBBON_RIGHT_FILL", "缎带右端": "COMPOSER_RIBBON_RIGHT_CAP",
    "设置页外框": "SETTINGS_FRAME", "新建会话底纹": "NEW_SESSION",
    "顶边装饰条": "TOP_TRIM_TILE", "底边装饰条": "BOTTOM_TRIM_TILE",
    "底部徽章": "BOTTOM_CREST", "蝴蝶结": "BOW_CLEAN",
    "工作区盾牌": "WORKSPACE_SHIELD", "工作区缎带": "WORKSPACE_RIBBON",
    "容错页左立绘": "BOOT_ERROR_LEFT", "容错页右立绘": "BOOT_ERROR_RIGHT",
}


def norm(s):
    """规范化成大写下划线形式，便于和变量名比对。"""
    s = os.path.splitext(os.path.basename(s))[0]
    s = s.strip()
    if s in ALIASES:
        s = ALIASES[s]
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_").upper()
    return s


def build_slot_table(client_src):
    """从 client.js 里挖出 变量名 -> (hash, ext) 的全部映射。"""
    table = {}
    for m in re.finditer(
        r'const\s+([A-Z][A-Z0-9_]*)\s*=\s*skinAssetUrl\(\s*"([a-f0-9]{64})\.(webp|png)"\s*\)',
        client_src,
    ):
        table[m.group(1)] = (m.group(2), m.group(3))
    return table


def resolve(norm_name, table):
    """把规范化文件名对到变量名上。"""
    if norm_name in table:
        return norm_name
    suffix = "_" + norm_name
    hits = [k for k in table if k.endswith(suffix)]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        return ("AMBIGUOUS", hits)
    return None


def convert(src_path, slot, old_size, use_fit):
    im = Image.open(src_path)
    im.load()
    has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)

    w, h = im.size
    ow, oh = old_size
    scaled = False
    if use_fit and (w, h) != (ow, oh):
        # 等比缩放，最长边贴合原素材
        r = min(ow / w, oh / h)
        im = im.resize((max(1, int(round(w * r))), max(1, int(round(h * r)))), Image.Resampling.LANCZOS)
        scaled = True
    elif ow and oh:
        dw = abs(w - ow) / ow
        dh = abs(h - oh) / oh
        if max(dw, dh) > SIZE_TOLERANCE:
            print(f"    ! 尺寸 {w}x{h} 与原素材 {ow}x{oh} 偏差较大"
                  f"（{'可用 --fit 自动缩放到原尺寸' if not use_fit else '已缩放'}）")

    im = im.convert("RGBA") if has_alpha else im.convert("RGB")
    buf = os.path.join(RUNTIME, "_tmp_convert.webp")
    im.save(buf, "WEBP", quality=WEBP_QUALITY, method=6)
    digest = hashlib.sha256(open(buf, "rb").read()).hexdigest()
    target = os.path.join(RUNTIME, f"{digest}.webp")
    return buf, target, digest, (im.size[0], im.size[1]), scaled, has_alpha


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--dry-run", action="store_true", help="只预览改动，不写任何文件")
    ap.add_argument("--fit", action="store_true", help="尺寸不一的按原素材尺寸等比缩放")
    ap.add_argument("--preview", action="store_true", help="用新背景重做 preview/ 预览图")
    args = ap.parse_args()

    if not os.path.isdir(ARTWORK):
        sys.exit(f"找不到素材目录: {ARTWORK}")
    if not os.path.exists(CLIENT):
        sys.exit(f"找不到 {CLIENT}")

    client_src = open(CLIENT, encoding="utf-8").read()
    table = build_slot_table(client_src)
    if not table:
        sys.exit("没能从 client.js 里解析出任何素材槽位，文件是不是被改动过？")

    files = [f for f in sorted(os.listdir(ARTWORK))
             if f.lower().endswith((".png", ".webp", ".jpg", ".jpeg", ".avif", ".bmp", ".tif", ".tiff"))
             and os.path.isfile(os.path.join(ARTWORK, f))]
    if not files:
        sys.exit(f"{ARTWORK} 里没有找到图片。把做好的图放进去再跑。")

    print(f"素材目录: {ARTWORK}")
    print(f"发现 {len(files)} 个候选文件，皮肤里共 {len(table)} 个图片槽位\n")

    plan, problems, unmatched = [], [], []
    for fn in files:
        src = os.path.join(ARTWORK, fn)
        n = norm(fn)
        slot = resolve(n, table)
        if slot is None:
            unmatched.append(fn)
            continue
        if isinstance(slot, tuple):
            problems.append(f"{fn}: 同时匹配到 {slot[1]}，请把文件名写得更具体")
            continue
        old_hash, old_ext = table[slot]
        old_path = os.path.join(RUNTIME, f"{old_hash}.{old_ext}")
        try:
            old_size = Image.open(old_path).size if os.path.exists(old_path) else (0, 0)
        except Exception:
            old_size = (0, 0)
        plan.append((fn, src, slot, old_hash, old_ext, old_size))

    if unmatched:
        print("!! 认不出这些文件该放哪个槽位（已跳过）：")
        for f in unmatched:
            print("   -", f)
        print("   文件名请对着 artwork/README.md 的槽位清单写。\n")
    if problems:
        print("!! 有歧义，无法处理：")
        for f in problems:
            print("   -", f)
        print()
    if not plan:
        sys.exit("没有任何文件能对上槽位，未做改动。")

    print("将要处理的映射：")
    for fn, _, slot, old_hash, _, old_size in plan:
        sz = f"{old_size[0]}x{old_size[1]}" if old_size[0] else "?"
        print(f"  {fn:<34} -> {slot:<38} (原素材 {sz})")
    print()

    if args.dry_run:
        print("== --dry-run：以上是它打算做的事，没有改动任何文件 ==")
        print("   去掉 --dry-run 即真正执行。")
        return

    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    hash_to_newfile = {}
    new_size_report = []

    print("转换中：")
    for fn, src, slot, old_hash, old_ext, old_size in plan:
        tmp, target, digest, size, scaled, alpha = convert(src, slot, old_size, args.fit)
        if os.path.exists(target):
            os.remove(tmp)
        else:
            shutil.move(tmp, target)
        hash_to_newfile[old_hash] = f"{digest}.webp"
        new_size_report.append((slot, size, scaled, alpha))
        print(f"  {fn:<34} -> {digest[:12]}…  {size[0]}x{size[1]}"
              f"{'  (已缩放)' if scaled else ''}{'' if alpha else '  [不透明]'}")

    # 1) 重写 client.js 引用（旧哈希字符串唯一，全局替换安全）
    updated = client_src
    for old_hash, new_file in hash_to_newfile.items():
        updated = updated.replace(old_hash, new_file.split(".")[0])
    with open(CLIENT, "w", encoding="utf-8", newline="") as f:
        f.write(updated)

    # 2) 重写 manifest（保持原有顺序，被替换的换新）
    new_manifest = [hash_to_newfile.get(f.split(".")[0], f) for f in manifest]
    new_manifest = sorted(set(new_manifest))
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(new_manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # 3) 重写 index.js 里的内联白名单
    index_src = open(INDEX, encoding="utf-8").read()
    arr = ",\n\t".join(f'"{x}"' for x in new_manifest)
    new_index, cnt = re.subn(
        r"(var manifest_default = \[)[^\]]*(\];)",
        lambda m: m.group(1) + "\n\t" + arr + "\n" + m.group(2),
        index_src,
        count=1,
    )
    if cnt != 1:
        print("\n!! 没能改到 index.js 里的白名单，请手动检查（client.js 与 manifest 已更新）")
    else:
        with open(INDEX, "w", encoding="utf-8", newline="") as f:
            f.write(new_index)

    # 4) 清掉不再被引用的旧素材
    keep = {x.split(".")[0] for x in new_manifest}
    removed = 0
    for f in os.listdir(RUNTIME):
        if f == "manifest.json" or f.startswith("_tmp_"):
            continue
        if f.split(".")[0] not in keep:
            os.remove(os.path.join(RUNTIME, f))
            removed += 1
            print(f"  清理旧素材 {f[:12]}…")

    # 5) 可选：重做预览图
    if args.preview:
        made = 0
        for slot, out in (("MAID_ATELIER_PALACE_LIGHT", "light.webp"),
                          ("MAID_ATELIER_PALACE_DARK", "dark.webp")):
            n2 = build_slot_table(open(CLIENT, encoding="utf-8").read()).get(slot)
            if not n2:
                continue
            src = os.path.join(RUNTIME, f"{n2[0]}.{n2[1]}")
            if not os.path.exists(src):
                continue
            im = Image.open(src).convert("RGB")
            tw, th = 1920, 1034
            r = max(tw / im.width, th / im.height)
            im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1), Image.Resampling.LANCZOS)
            left = (im.width - tw) // 2
            top = (im.height - th) // 2
            im.crop((left, top, left + tw, top + th)).save(
                os.path.join(ROOT, "preview", out), "WEBP", quality=88, method=6)
            made += 1
        print(f"  预览图已重做 {made} 张")

    print(f"\n完成：替换 {len(plan)} 张，清理旧素材 {removed} 个，白名单现有 {len(new_manifest)} 项。")
    print("现在去 DSH 里按 Ctrl+Shift+R 硬刷新看效果（皮肤是热切换的，不用重启 DSH）。")


if __name__ == "__main__":
    main()
