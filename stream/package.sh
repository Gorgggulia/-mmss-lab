#!/usr/bin/env bash
# Драбина якостей і сегменти для адаптивного потокового передавання.
# Запуск з кореня репозиторію: bash stream/package.sh hls (або dash)
set -e
FORMAT=${1:-hls}
SRC=data/source.mp4
SEG=2                  # тривалість сегмента, с
FPS=20                 # частота кадрів джерела (ЛР 1: 20 кадр/с)
GOP=$((SEG * FPS))     # ключовий кадр на початку кожного сегмента

# Три рівні якості: бітрейт (кбіт/с) — за результатами заняття 1.
# Верхній рівень 1000k: SSIM 0,993 за encoding.csv (h264_1000k).
# Стала кількість біт на піксель: 1000k / (1280*720*20) = 0,054 біт/піксель
LADDER=(
  -map "[v1]" -b:v:0 1000k -maxrate:v:0 1100k -bufsize:v:0 2000k
  -map "[v2]" -b:v:1 445k  -maxrate:v:1 490k  -bufsize:v:1 890k
  -map "[v3]" -b:v:2 250k  -maxrate:v:2 275k  -bufsize:v:2 500k
)
SCALE="[0:v]split=3[a][b][c];[a]scale=-2:720[v1];"
SCALE+="[b]scale=-2:480[v2];[c]scale=-2:360[v3]"
CODEC=(-c:v libx264 -preset veryfast -pix_fmt yuv420p
       -g $GOP -keyint_min $GOP -sc_threshold 0 -an)

cd "$(dirname "$0")/.."
rm -rf "stream/$FORMAT" && mkdir -p "stream/$FORMAT"

if [ "$FORMAT" = hls ]; then
  ffmpeg -y -hide_banner -loglevel error -i $SRC -filter_complex "$SCALE" \
    "${LADDER[@]}" "${CODEC[@]}" \
    -f hls -hls_time $SEG -hls_playlist_type vod \
    -hls_segment_filename "stream/hls/v%v/seg_%03d.ts" \
    -master_pl_name master.m3u8 -var_stream_map "v:0 v:1 v:2" \
    "stream/hls/v%v/index.m3u8"
else
  ffmpeg -y -hide_banner -loglevel error -i $SRC -filter_complex "$SCALE" \
    "${LADDER[@]}" "${CODEC[@]}" \
    -f dash -seg_duration $SEG -use_template 1 -use_timeline 0 \
    -adaptation_sets "id=0,streams=v" "stream/dash/manifest.mpd"
fi
echo "Готово: stream/$FORMAT"
