"""
Images module — AI image pipeline (Phase 5).

Public API:
  base          — AbstractImageGenerator, request/result dataclasses
  preprocessing — background removal via rembg
  factory       — ImageWorkflowFactory (gemini / openai)
  pipeline      — run_image_pipeline (production generation)
  comparison    — run_comparison (side-by-side workflow test)
  alt_text      — generate_alt_text
"""
