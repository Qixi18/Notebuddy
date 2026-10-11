"""Build AI teacher idle sprite sheets from frame sequences.

把 data/frames/<人物>/ 里的连续帧合成雪碧图(WebP,带透明通道),
输出到 apps/web/public/assets/teacher/,前端 TeacherCharacter 直接加载。

用法:
    python scripts/build_teacher_sheets.py            # 重建全部人物
    python scripts/build_teacher_sheets.py doubao     # 只重建指定人物

说明:
- 源帧目录 data/frames/ 在 .gitignore 内(体积大,源文件走网盘共享,不入仓);
- 输出的 webp 是构建产物,随代码一起提交;
- 网格(列×行)或帧数变化时,需同步 apps/web/src/styles.css 里对应的
  keyframes 停靠点数量与 .teacher-character-sprite 的 background-size。
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMES_DIR = os.path.join(REPO, "data", "frames")
OUT_DIR = os.path.join(REPO, "apps", "web", "public", "assets", "teacher")

# 每个人物一条配置:源帧目录名、雪碧图网格(列×行)、单帧缩放尺寸、帧率、输出文件名。
# 新增人物:在 data/frames/ 放好帧序列后,在这里加一行即可。
CHARACTERS = [
    {"id": "teacher-idle", "cols": 10, "rows": 6, "cell": (576, 768), "fps": 12, "out": "teacher-idle-sheet.webp"},
    {"id": "doubao-idle", "cols": 10, "rows": 4, "cell": (576, 768), "fps": 12, "out": "doubao-idle-sheet.webp"},
    {"id": "feiyu-idle", "cols": 10, "rows": 6, "cell": (576, 1024), "fps": 12, "out": "feiyu-idle-sheet.webp"},
]


def run(argv):
    return subprocess.run(argv, capture_output=True, text=True)


def build(spec):
    frames = sorted(glob.glob(os.path.join(FRAMES_DIR, spec["id"], "*.png")))
    cols, rows = spec["cols"], spec["rows"]
    total = cols * rows
    if not frames:
        return f"[skip] {spec['id']}: data/frames/{spec['id']}/ 没有源帧"
    if len(frames) > total:
        return f"[fail] {spec['id']}: {len(frames)} 帧超出 {cols}×{rows}={total} 格,请调整网格或抽帧"

    with tempfile.TemporaryDirectory() as tmp:
        # 源帧文件名常带跳号(如 0,2,4…),先顺序重命名;帧数不足网格时
        # 循环补齐开头帧,保证播放收尾与开头衔接。
        for i in range(total):
            shutil.copyfile(frames[i % len(frames)], os.path.join(tmp, f"seq_{i:04d}.png"))
        out = os.path.join(OUT_DIR, spec["out"])
        w, h = spec["cell"]
        result = run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-framerate", str(spec["fps"]), "-i", os.path.join(tmp, "seq_%04d.png"),
            "-frames:v", "1",
            "-vf", f"scale={w}:{h}:flags=lanczos,tile={cols}x{rows}",
            "-c:v", "libwebp", "-q:v", "82", out,
        ])
        if result.returncode != 0:
            return f"[fail] {spec['id']}: {result.stderr[-300:]}"
        probe = run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0", out,
        ])
        size = os.path.getsize(out) / 1048576
        return f"[ok] {spec['id']} -> {spec['out']}  {probe.stdout.strip()}  {size:.2f} MB  ({len(frames)} 源帧 / {total} 格)"


def main():
    wanted = set(sys.argv[1:])
    os.makedirs(OUT_DIR, exist_ok=True)
    for spec in CHARACTERS:
        if wanted and spec["id"] not in wanted:
            continue
        print(build(spec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
