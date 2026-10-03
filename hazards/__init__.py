"""Safety hazard review: a GB10 port of the teammate's astra-1.1 single-camera pipeline.

Stages (``hazards.pipeline.review_clip``):

1. ``scan``    - decode every frame, temporal background, motion, zone proposals, evidence
                 images and the processed video, exactly as ``astra_video_hazard.py``.
2. ``review``  - local Qwen review + audit over the evidence (vLLM OpenAI API).
3. ``report``  - ``hazard_report.json`` in the upstream shape, manifests, final assertions.

The upstream script lives verbatim in ``third_party/astra_safety_hazard/`` and is never
imported at runtime. Nothing here imports torch; YOLO runs in the local detector service.
"""
