# Offline check

Checked at 2026-10-02T19:39:08+00:00 on commit `4990f364dbeee9106f6ce2e0db5242d2c638e567`. Verdict: **PASS**.

| check | required | result | detail |
|---|---|---|---|
| python dependencies | True | ok | 10 runtime packages import on Python 3.12.13 |
| ffmpeg / ffprobe | True | ok | ffmpeg C:\Users\thegr\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.EXE; ffprobe C:\Users\thegr\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffprobe.EXE |
| scenario data | True | ok | 22 scenarios, 88 media files, labels and recordings |
| web install + build | True | ok | build tjoJZNJRRJ3Ee4KqgtC84; 34 source and 15 bundle files name no remote font/CDN host |
| local models (Ollama) | False | ok | present in Ollama: ministral-3:3b, ministral-3:8b, qwen3-vl:4b-instruct, qwen3.5:9b |
| fixture run, network refused | True | ok | eval_001 fixture run with non-loopback sockets refused: passenger_dropoff_pickup in 1.8 s, 0 network attempts |
