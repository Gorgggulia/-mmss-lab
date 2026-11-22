"""Конвеєр «декодування — перетворення — кодування» і вимірювання якості.
Предметна область: контроль якості на виробничій лінії (камера над конвеєром).
Запуск з кореня репозиторію: python pipeline/pipeline.py
Вхід: data/source.mp4
Вихід: data/reference.mkv, data/out/*.mp4, results/encoding.csv
"""
import csv
import os
import re
import subprocess
import time
from pathlib import Path

import cv2

SRC = Path("data/source.mp4")
REF = Path("data/reference.mkv")  # еталон: перетворені кадри без втрат
OUT = Path("data/out")
CSV_FILE = Path("results/encoding.csv")

# Параметри перетворення (ЛР 1: камера 20 кадр/с, реєстр даних)
WIDTH, HEIGHT, FPS = 1280, 720, 20
SECONDS = 20  # тривалість фрагмента для порівняння, с
DEPTH = 24  # біт на піксель нестисненого кадру (BGR)

# Зона контролю: частка кадру, що лишається після обрізання (x0, y0, x1, y1)
ROI = (0.15, 0.15, 0.85, 0.85)

os.environ.setdefault("SVT_LOG", "1")  # без службових повідомлень SVT-AV1

# Алгоритмічні варіанти: назва, кодек, цільовий бітрейт
VARIANTS = [
    ("h264_1000k", "h264", "1000k"),
    ("h264_2000k", "h264", "2000k"),
    ("av1_1000k", "av1", "1000k"),
    ("av1_2000k", "av1", "2000k"),
]


def process(frame, t):
    """Перетворення одного кадру. У ЛР 4 сюди підключається модель ONNX.

    Обрізання до зони контролю на кадрі джерела (до зменшення, без
    збільшення) зі збереженням співвідношення сторін 16:9.
    """
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = ROI
    frame = frame[int(h * y0):int(h * y1), int(w * x0):int(w * x1)].copy()
    # мітка часу запису; вбудовані шрифти OpenCV — лише латиниця
    cv2.putText(frame, f"{t:6.2f} s", (20, 50), cv2.FONT_HERSHEY_SIMPLEX,
                1.2, (255, 255, 255), 2, cv2.LINE_AA)
    return frame


def transform():
    """Декодування (OpenCV) → перетворення → еталон без втрат (FFmpeg)."""
    cap = cv2.VideoCapture(str(SRC))
    if not cap.isOpened():
        raise SystemExit(f"Не вдалося відкрити {SRC}")
    src_fps = cap.get(cv2.CAP_PROP_FPS)
    if src_fps < FPS - 0.01:
        raise SystemExit(f"FPS = {FPS} більша за частоту джерела {src_fps}")
    step = src_fps / FPS  # скільки вхідних кадрів на один вихідний
    writer = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", str(REF)],
        stdin=subprocess.PIPE)
    index, frames, next_index = 0, 0, 0.0
    while frames < SECONDS * FPS:
        ok, frame = cap.read()  # декодування
        if not ok:
            break
        index += 1
        if index - 1 < next_index:  # зменшення частоти кадрів
            continue
        next_index += step
        frame = process(frame, frames / FPS)  # обрізання на кадрі джерела
        frame = cv2.resize(frame, (WIDTH, HEIGHT),
                           interpolation=cv2.INTER_AREA)
        writer.stdin.write(frame.tobytes())
        frames += 1
    cap.release()
    writer.stdin.close()
    writer.wait()
    return frames


def av1_encoder():
    """Обирає наявний кодер AV1: SVT-AV1, а якщо його немає — libaom."""
    names = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                           capture_output=True, text=True).stdout
    if "libsvtav1" in names:
        return ["-c:v", "libsvtav1", "-preset", "8"]
    if "libaom-av1" in names:
        return ["-c:v", "libaom-av1", "-cpu-used", "6", "-row-mt", "1"]
    raise SystemExit("У збірці FFmpeg немає кодера AV1")


def encode(codec, bitrate, out):
    """Кодування еталона одним варіантом; повертає час кодування, с."""
    args = (["-c:v", "libx264", "-preset", "medium"] if codec == "h264"
            else av1_encoder())
    start = time.perf_counter()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(REF),
                    *args, "-b:v", bitrate, "-an", str(out)], check=True)
    return time.perf_counter() - start


def quality(out):
    """PSNR (дБ) і SSIM закодованого файлу відносно еталона засобами FFmpeg."""
    result = {}
    for name, pattern in (("psnr", r"average:(\S+)"), ("ssim", r"All:(\S+)")):
        cmd = ["ffmpeg", "-hide_banner", "-i", str(out), "-i", str(REF),
               "-lavfi", name, "-f", "null", "-"]
        log = subprocess.run(cmd, capture_output=True, text=True).stderr
        result[name] = float(re.findall(pattern, log)[-1])
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
    frames = transform()
    duration = frames / FPS
    raw_kbps = WIDTH * HEIGHT * FPS * DEPTH / 1000
    print(f"Еталон: {frames} кадрів, {duration:.1f} с, "
          f"{WIDTH}x{HEIGHT}, {FPS} кадр/с")
    rows = []
    for name, codec, bitrate in VARIANTS:
        out = OUT / f"{name}.mp4"
        seconds = encode(codec, bitrate, out)
        size = out.stat().st_size
        kbps = size * 8 / duration / 1000
        q = quality(out)
        rows.append({
            "variant": name, "codec": codec,
            "target_kbps": int(bitrate[:-1]), "size_kb": round(size / 1024),
            "actual_kbps": round(kbps), "compression": round(raw_kbps / kbps),
            "encode_s": round(seconds, 1), "psnr_db": round(q["psnr"], 2),
            "ssim": round(q["ssim"], 4)})
        print(rows[-1])
    with CSV_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Результати: {CSV_FILE}")


if __name__ == "__main__":
    main()
