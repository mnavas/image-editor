"""Optional ML backends (segmentation, LaMa inpaint).

Everything here is lazily imported and may be absent. Callers must handle
ImportError / RuntimeError and fall back to the classical path. See
docs/analysis.md §3 and §8.
"""
