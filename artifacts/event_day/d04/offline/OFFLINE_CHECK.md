# Offline check

Checked at 2026-10-03T18:25:40+00:00 on commit `0db0851a1b15aa16e36eac4a6a364687d7106ef6`. Verdict: **PASS**.

| check | required | result | detail |
|---|---|---|---|
| python dependencies | True | ok | 10 runtime packages import on Python 3.12.3 |
| ffmpeg / ffprobe | True | ok | ffmpeg /usr/bin/ffmpeg; ffprobe /usr/bin/ffprobe |
| scenario data | True | ok | 22 scenarios, 88 media files, labels and recordings |
| web install + build | True | ok | build siEt70nTtMT6eepEH1li2; 57 source and 18 bundle files name no remote font/CDN host |
| local models (Ollama) | False | FAIL | ConnectError: [Errno 111] Connection refused |
| fixture run, network refused | True | ok | eval_001 fixture run with non-loopback sockets refused: passenger_dropoff_pickup in 1.2 s, 0 network attempts |
