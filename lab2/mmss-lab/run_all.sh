#!/usr/bin/env bash
# ЛР2: одна команда замість кількох.
# Бере data/raw.* -> data/source.mp4 (20 кадр/с, 60 с) -> конвеєр -> потік HLS.
# Запуск з кореня репозиторію (з активованим .venv):  bash run_all.sh
set -e
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
FPS=20

# 1. Знайти вихідне відео
RAW=$(ls data/raw.* 2>/dev/null | head -n 1 || true)
if [ -z "$RAW" ]; then
  echo "ПОМИЛКА: немає файлу data/raw.mp4 (або .mov/.mkv/.webm)."
  echo "Завантажте ролик з pexels.com/videos і збережіть його як data/raw.mp4"
  exit 1
fi
echo ">>> Вихідний файл: $RAW"

# 2. Тривалість; якщо коротша за 60 с, ролик зациклюється
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$RAW")
LOOPS=$(awk -v d="$DUR" 'BEGIN{n=int(60/d); if (n*d<60) n++; print n-1}')
if [ "$LOOPS" -gt 0 ]; then
  echo ">>> УВАГА: ролик ${DUR} с коротший за 60 с, зациклюю ${LOOPS} раз(и)."
  echo ">>> Запишіть це в docs/pipeline.md (розділ «Вихідний матеріал»)."
fi

# 3. Єдиний формат: <=1080 рядків, 20 кадр/с, 60 с, без звуку
echo ">>> Готую data/source.mp4"
ffmpeg -y -hide_banner -loglevel error -stream_loop "$LOOPS" -i "$RAW" -t 60 \
  -vf "scale=-2:'min(1080,ih)',fps=$FPS,format=yuv420p" \
  -c:v libx264 -crf 18 -preset medium -an data/source.mp4
ffprobe -v error -of compact -show_entries \
  stream=width,height,r_frame_rate:format=duration data/source.mp4
echo ">>> Це вставте в docs/pipeline.md, розділ «Вихідний матеріал»"

# 4. Конвеєр (кілька хвилин)
echo ">>> Запускаю конвеєр"
python pipeline/pipeline.py

# 5. Потік HLS
echo ">>> Збираю HLS"
bash stream/package.sh hls
cat stream/hls/master.m3u8

echo
echo "================ ГОТОВО ================"
echo "Таблиця вимірювань: results/encoding.csv"
cat results/encoding.csv
echo
echo "Далі:"
echo "  1) перенесіть таблицю в docs/pipeline.md і напишіть висновок"
echo "  2) git add -A && git commit -m \"ЛР2: конвеєр оброблення медіаданих\""
echo "  3) cd stream && python -m http.server 8000   (і вимірювання в браузері)"
