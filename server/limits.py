"""Internal resource limits shared by the host camera pipeline.

These are defensive process limits, not camera-tuning parameters. Keeping them
out of ``tool_vision.cfg`` preserves the teach-once workflow while preventing a
malformed or misconfigured source from allocating an unbounded decoded frame.
"""


# 16 megapixels accepts common 4K sources while bounding one decoded BGR frame
# to roughly 48 MiB before OpenCV/NumPy overhead.
MAX_FRAME_PIXELS = 16 * 1024 * 1024
