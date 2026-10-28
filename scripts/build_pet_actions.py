"""Build the desktop pet's animated WebP actions from transparent PNG frames.

两种素材来源都支持:

1. 透明 PNG 序列(已带 alpha):data/pet/<动作>/*.png
2. matte-studio 导出(分离 RGB 帧 + 独立蒙版):
   <job-root>/<中文动作名>/frames/*.png  +  <job-root>/<中文动作名>/alpha/*.png
   脚本用 ffmpeg 的 alphamerge 把蒙版合回 RGB,得到透明序列再编码。

输出:apps/web/public/assets/pet/<动作>.webp(透明动画、循环)、manifest.json、
      preview.html。

脚本只做四件事(去背/抠像由 matte-studio 完成,这里不碰):
1. 按文件名自然排序,必要时重采样到 12fps;
2. 统一缩放并底部对齐到同一画布(contain,不裁切、不拉伸);
3. 按动作决定循环方式(idle/sleep 用 ping-pong,其余按单次播放);
4. 编码成带 alpha 的动画 WebP,并校验左上角确实透明。

用法:
    # matte-studio 来源(推荐)
    python scripts/build_pet_actions.py idle --job-root "D:/王金赛/matte-studio/jobs"
    python scripts/build_pet_actions.py idle thinking explaining --job-root "..."

    # 透明 PNG 来源
    python scripts/build_pet_actions.py                  # 构建全部有帧的动作
    python scripts/build_pet_actions.py idle thinking    # 只构建指定动作
    python scripts/build_pet_actions.py --preview        # 只重建预览页
    python scripts/build_pet_actions.py idle --src-fps 24  # 源是 24fps,自动抽到 12
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO, "data", "pet")
OUT_ROOT = os.path.join(REPO, "apps", "web", "public", "assets")

CANVAS = (480, 640)
FPS = 12
QUALITY = 78

# loop: pingpong = 正放后倒放,保证首尾无缝;none = 按原顺序播放。
# 待机与睡眠用 pingpong;一次性动作(greet/drop/error)不需要循环。
ACTIONS = [
    {"id": "idle",        "loop": "pingpong"},
    {"id": "thinking",    "loop": "pingpong"},
    {"id": "explaining",  "loop": "pingpong"},
    {"id": "writing",     "loop": "pingpong"},
    {"id": "waiting",     "loop": "pingpong"},
    {"id": "no-evidence", "loop": "none"},
    {"id": "error",       "loop": "none"},
    {"id": "drag",        "loop": "pingpong"},
    {"id": "drop",        "loop": "none"},
    {"id": "greet",       "loop": "none"},
    {"id": "sleep",       "loop": "pingpong"},
]

# matte-studio 导出的动作目录用中文命名;这里把英文 id 映射到它的中文子目录。
JOB_NAME_MAP = {
    "idle": "待机",
    "thinking": "思考",
    "explaining": "讲解",
    "error": "出错",
    "drag": "被拎起",
    "greet": "行礼",
    "writing": "写笔记",
    "waiting": "待确认",
    "no-evidence": "无依据",
    "drop": "落地",
    "sleep": "打盹",
}


def run(argv, check=False):
    result = subprocess.run(argv, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-800:] or "ffmpeg failed")
    return result


def run_raw(argv):
    return subprocess.run(argv, capture_output=True).stdout


def probe(path):
    result = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,pix_fmt",
        "-of", "json", path,
    ], check=True)
    data = json.loads(result.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "pix_fmt": stream.get("pix_fmt") or "",
    }


def natural_key(path: str):
    name = os.path.basename(path)
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", name)]


def list_frames(directory: str):
    frames = [
        path for path in glob.glob(os.path.join(directory, "*"))
        if path.lower().endswith(".png")
    ]
    return sorted(frames, key=natural_key)


def composite_alpha(frames_dir, alpha_dir, out_dir, fps):
    """把 matte-studio 的 RGB 帧与独立灰度蒙版合成成带透明通道的 PNG 序列。

    frames 是 rgb24、alpha 是灰度蒙版(白=不透明);ffmpeg 用 alphamerge 把蒙版
    作为 alpha 通道合回。合成产物是中间帧,放在调用方提供的临时目录里。
    """
    os.makedirs(out_dir, exist_ok=True)
    vf = "[1:v]alphaextract[mask];[0:v]format=rgba[bg];[bg][mask]alphamerge"
    run([
        "ffmpeg", "-y", "-v", "error",
        "-framerate", str(fps), "-i", os.path.join(frames_dir, "frame_%06d.png"),
        "-framerate", str(fps), "-i", os.path.join(alpha_dir, "frame_%06d.png"),
        "-filter_complex", vf,
        os.path.join(out_dir, "%06d.png"),
    ], check=True)
    return sorted(glob.glob(os.path.join(out_dir, "*.png")), key=natural_key)


def resample(frames, src_fps: int, dst_fps: int):
    """把任意源帧率抽/补到目标帧率。src_fps=0 时按帧数猜。"""
    guessed = False
    if src_fps <= 0:
        src_fps = 24 if len(frames) > 36 else 12
        guessed = True
    if src_fps == dst_fps or not frames:
        return frames, src_fps, guessed
    step = src_fps / dst_fps
    if step >= 1:
        count = int(len(frames) / step)
        picked = [frames[min(len(frames) - 1, int(index * step))] for index in range(count)]
        return picked, src_fps, guessed
    copies = max(1, int(round(dst_fps / src_fps)))
    expanded = []
    for frame in frames:
        expanded.extend([frame] * copies)
    return expanded, src_fps, guessed


def loop_order(frames, loop: str):
    if loop == "pingpong" and len(frames) > 2:
        return frames + list(reversed(frames[1:-1]))
    return frames


def encode(frames, out_path, canvas, fps, quality):
    """把帧序列缩放/补边到统一画布后编码成动画 WebP。"""
    width, height = canvas
    with tempfile.TemporaryDirectory(prefix="pet-seq-") as tmp:
        for index, path in enumerate(frames, start=1):
            shutil.copyfile(path, os.path.join(tmp, f"{index:04d}.png"))
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={width}:{height}:(ow-iw)/2:oh-ih:color=0x00000000"
        )
        run([
            "ffmpeg", "-y", "-v", "error",
            "-framerate", str(fps), "-i", os.path.join(tmp, "%04d.png"),
            "-vf", vf,
            "-c:v", "libwebp_anim", "-lossless", "0", "-quality", str(quality),
            "-loop", "0", "-pix_fmt", "yuva420p", "-an", out_path,
        ], check=True)


def verify(out_path, frame_count, fps):
    info = probe(out_path)
    if "a" not in info["pix_fmt"].lower():
        raise RuntimeError(f"{out_path} 没有透明通道(pix_fmt={info['pix_fmt']})")
    raw = run_raw([
        "ffmpeg", "-v", "error", "-i", out_path,
        "-vf", "alphaextract,crop=1:1:0:0", "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ])
    corner_alpha = raw[0] if raw else -1
    return {
        "width": info["width"],
        "height": info["height"],
        "pix_fmt": info["pix_fmt"],
        "corner_alpha": corner_alpha,
        "duration": round(frame_count / fps, 2),
        "bytes": os.path.getsize(out_path),
    }


def write_manifest(out_dir, character, built, canvas, fps):
    manifest_path = os.path.join(out_dir, "manifest.json")
    existing = {"actions": {}}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as handle:
                existing = json.load(handle)
        except json.JSONDecodeError:
            pass
    actions = existing.get("actions") or {}
    for item in built:
        actions[item["id"]] = item
    actions = {
        key: value for key, value in actions.items()
        if os.path.exists(os.path.join(out_dir, value.get("file", "")))
    }
    manifest = {
        "character": character,
        "canvas": list(canvas),
        "fps": fps,
        "actions": dict(sorted(actions.items())),
    }
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest


def write_preview(out_dir, character, manifest):
    rows = []
    for action_id, item in manifest["actions"].items():
        rows.append(f"""
    <figure class="card">
      <div class="stage"><img src="{item['file']}" alt="{action_id}" loading="lazy"></div>
      <figcaption>
        <strong>{action_id}</strong>
        <span>{item.get('outputFrames', '?')} 帧 · {item.get('duration', '?')}s · {item['bytes'] / 1024:.0f} KB</span>
        <button type="button" onclick="replay(this)">重播</button>
      </figcaption>
    </figure>""")
    html = f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<title>{character} · 动作预览</title>
<style>
  body {{ margin: 0; padding: 32px; background: #F4F6F3; color: #1B2A22;
         font: 14px/1.6 system-ui, "Microsoft YaHei", sans-serif; }}
  h1 {{ font-size: 18px; font-weight: 600; margin: 0 0 4px; }}
  p.meta {{ color: #55635A; margin: 0 0 24px; }}
  .grid {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); }}
  .card {{ margin: 0; background: #fff; border: 1px solid #E6EAE4; border-radius: 12px; overflow: hidden; }}
  .stage {{ height: 220px; display: grid; place-items: end center;
           background-color: #fff;
           background-image: linear-gradient(45deg, #EDF1EC 25%, transparent 25%),
                             linear-gradient(-45deg, #EDF1EC 25%, transparent 25%),
                             linear-gradient(45deg, transparent 75%, #EDF1EC 75%),
                             linear-gradient(-45deg, transparent 75%, #EDF1EC 75%);
           background-size: 16px 16px;
           background-position: 0 0, 0 8px, 8px -8px, -8px 0; }}
  .stage img {{ max-height: 200px; max-width: 90%; }}
  figcaption {{ display: flex; align-items: center; gap: 8px; padding: 10px 12px;
               border-top: 1px solid #EFF3EE; }}
  figcaption strong {{ font-size: 13px; }}
  figcaption span {{ flex: 1; color: #6B7A6E; font-size: 11px; }}
  button {{ border: 1px solid #CFE0D6; background: #F2F8F4; color: #174534;
           border-radius: 7px; padding: 4px 9px; font-size: 11px; cursor: pointer; }}
</style>
<h1>{character} · 动作预览</h1>
<p class="meta">{manifest['canvas'][0]} × {manifest['canvas'][1]} · {manifest['fps']} fps · 棋盘格即透明区域</p>
<div class="grid">{''.join(rows)}
</div>
<script>
function replay(button) {{
  const img = button.closest('.card').querySelector('img');
  const src = img.src.split('?')[0];
  img.src = '';
  requestAnimationFrame(() => {{ img.src = src + '?t=' + Date.now(); }});
}}
</script>
</html>
"""
    path = os.path.join(out_dir, "preview.html")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)
    return path


def main():
    parser = argparse.ArgumentParser(description="透明 PNG / matte-studio -> 透明动画 WebP")
    parser.add_argument("actions", nargs="*", help="只构建这些动作 id,默认全部")
    parser.add_argument("--character", default="pet", help="输出子目录名,默认 pet")
    parser.add_argument("--src-root", default=SRC_DIR, help="透明 PNG 帧根目录,默认 data/pet")
    parser.add_argument("--job-root", default="",
                        help="matte-studio jobs 根目录;<中文动作名>/{frames,alpha} 自动映射")
    parser.add_argument("--out-root", default=OUT_ROOT, help="输出根目录")
    parser.add_argument("--canvas", default=f"{CANVAS[0]}x{CANVAS[1]}")
    parser.add_argument("--fps", type=int, default=FPS)
    parser.add_argument("--quality", type=int, default=QUALITY)
    parser.add_argument("--src-fps", type=int, default=0, help="源帧率;0=自动猜")
    parser.add_argument("--trim-seconds", type=float, default=0,
                        help="只取每个动作前 N 秒再循环(0=不裁,保留整段)")
    parser.add_argument("--loop", choices=["auto", "pingpong", "none"], default="auto",
                        help="循环方式;auto 按动作清单")
    parser.add_argument("--preview", action="store_true", help="只重建预览页")
    args = parser.parse_args()

    if args.job_root:
        args.src_fps = args.src_fps or 24  # matte-studio 默认 24fps

    width, height = (int(value) for value in args.canvas.lower().split("x"))
    if width % 2 or height % 2:
        print("[fail] 画布宽高必须是偶数(WebP 的 yuva420p 需要)")
        return 1
    canvas = (width, height)
    out_dir = os.path.join(args.out_root, args.character)
    os.makedirs(out_dir, exist_ok=True)

    if args.preview:
        manifest_path = os.path.join(out_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            print(f"[fail] 没有 manifest:{manifest_path}")
            return 1
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        print(f"[ok] 预览页 -> {write_preview(out_dir, args.character, manifest)}")
        return 0

    tmp_root = tempfile.mkdtemp(prefix="pet-build-")
    try:
        wanted = set(args.actions)
        if wanted and not any(spec["id"] in wanted for spec in ACTIONS):
            print(f"[fail] 未知动作:{', '.join(sorted(wanted))}")
            return 1

        specs = [spec for spec in ACTIONS if not wanted or spec["id"] in wanted]
        sources = {}
        for spec in specs:
            action_id = spec["id"]
            if args.job_root:
                cn = JOB_NAME_MAP.get(action_id)
                if not cn:
                    print(f"[skip] {action_id}: 没有对应的 matte-studio 中文目录")
                    continue
                frames_dir = os.path.join(args.job_root, cn, "frames")
                alpha_dir = os.path.join(args.job_root, cn, "alpha")
                if os.path.isdir(frames_dir) and os.path.isdir(alpha_dir):
                    comp_dir = os.path.join(tmp_root, action_id)
                    try:
                        frames = composite_alpha(frames_dir, alpha_dir, comp_dir,
                                                 args.src_fps)
                    except Exception as error:  # noqa: BLE001
                        print(f"[fail] {action_id}: 合成失败 - {error}")
                        continue
                    if frames:
                        sources[action_id] = (comp_dir, frames)
                        continue
                print(f"[skip] {action_id}: {args.job_root}/{cn} 缺少 frames/alpha")
                continue
            directory = os.path.join(args.src_root, action_id)
            frames = list_frames(directory)
            if frames:
                sources[action_id] = (directory, frames)
            else:
                print(f"[skip] {action_id}: {directory} 里没有 PNG")

        if not sources:
            print("[fail] 没有可用的动作帧(检查 --src-root 或 --job-root)")
            return 1

        # 所有动作应当同尺寸、同机位;不一致时明确警告,避免切状态时角色跳大小
        ref_id = "idle" if "idle" in sources else next(iter(sources))
        ref_info = probe(sources[ref_id][1][0])
        for action_id, (_, frames) in sources.items():
            info = probe(frames[0])
            if (info["width"], info["height"]) != (ref_info["width"], ref_info["height"]):
                print(f"[warn] {action_id}: {info['width']}x{info['height']} 与 {ref_id} 的 "
                      f"{ref_info['width']}x{ref_info['height']} 不一致,缩放后角色大小会变")

        built = []
        for spec in specs:
            action_id = spec["id"]
            if action_id not in sources:
                continue
            directory, frames = sources[action_id]
            try:
                source_count = len(frames)
                frames, src_fps, guessed = resample(frames, args.src_fps, args.fps)
                if args.trim_seconds > 0:
                    keep = int(round(args.trim_seconds * args.fps))
                    frames = frames[:max(2, keep)]
                loop = spec["loop"] if args.loop == "auto" else args.loop
                ordered = loop_order(frames, loop)
                out_path = os.path.join(out_dir, action_id + ".webp")
                encode(ordered, out_path, canvas, args.fps, args.quality)
                info = verify(out_path, len(ordered), args.fps)
            except Exception as error:  # noqa: BLE001 - 单个动作失败不影响其他动作
                print(f"[fail] {action_id}: {error}")
                continue

            if info["corner_alpha"] != 0:
                print(f"[warn] {action_id}: 左上角 alpha={info['corner_alpha']},可能帧本身带底色")
            built.append({
                "id": action_id,
                "file": action_id + ".webp",
                "loop": loop == "pingpong",
                "outputFrames": len(ordered),
                "duration": info["duration"],
                "width": info["width"],
                "height": info["height"],
                "bytes": info["bytes"],
            })
            fps_note = f"{src_fps}{'?' if guessed else ''}→{args.fps}fps" if src_fps != args.fps else f"{args.fps}fps"
            print(f"[ok] {action_id}  {source_count} 源帧 → {len(ordered)} 帧  "
                  f"{fps_note}  {info['duration']}s  {info['bytes'] / 1024:.0f} KB  {info['pix_fmt']}")

        if not built:
            print("[fail] 本轮没有构建出任何动作")
            return 1

        manifest = write_manifest(out_dir, args.character, built, canvas, args.fps)
        preview = write_preview(out_dir, args.character, manifest)
        total = sum(item["bytes"] for item in manifest["actions"].values()) / 1048576
        print(f"[ok] manifest -> {os.path.join(out_dir, 'manifest.json')}  "
              f"({len(manifest['actions'])} 个动作, {total:.1f} MB)")
        print(f"[ok] 预览页 -> {preview}")
        return 0
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
