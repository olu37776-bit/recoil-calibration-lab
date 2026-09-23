"""Offline fixed-ROI reference comparison. Not a pretrained WARDOGS detector."""
from __future__ import annotations

import numpy as np

from .contracts import CalibrationError
from .screenshots import decode_image
from .state import number

LABELS = {
    "pose": {"standing", "crouching", "prone"},
    "action": {"ready", "reload", "inventory", "grenade", "melee", "heal", "sprint", "dead", "vehicle"},
    "ads": {"ads", "hipfire"},
    "ammo": {"empty", "nonempty"},
}


def compare_hud(payload: dict) -> dict:
    """Compare SAME-SIZE user-provided references in a small fixed HUD region.

    NCC/margin are similarity diagnostics, NOT correctness probabilities. Unknown
    game states may resemble a reference. Positive output is a candidate only;
    this endpoint is intentionally not wired into StatePlayback.
    """
    field = payload.get("field")
    if not isinstance(field, str) or field not in LABELS:
        raise CalibrationError("field must be pose/action/ads/ammo")
    layout = payload.get("layout_id")
    if not isinstance(layout, str) or not layout.strip() or len(layout) > 160:
        raise CalibrationError("Provide a game-build / HUD-layout identifier")
    refs = payload.get("references")
    if not isinstance(refs, list) or not 2 <= len(refs) <= 8:
        raise CalibrationError("Provide 2..8 differently labelled references")
    threshold = number(payload.get("threshold", .9), "threshold")
    margin = number(payload.get("margin", .08), "margin")
    if not .8 <= threshold <= 1 or not .01 <= margin <= .5:
        raise CalibrationError("threshold in [.8,1], margin in [.01,.5] required")
    query, qhash = decode_image(payload.get("image"))
    roi = payload.get("roi")
    if not isinstance(roi, list) or len(roi) != 4 or any(type(n) is not int for n in roi):
        raise CalibrationError("ROI must be [x,y,width,height] integers")
    x, y, w, h = roi
    if min(x,y) < 0 or not 8 <= w <= 512 or not 8 <= h <= 512 or x+w > query.shape[1] or y+h > query.shape[0]:
        raise CalibrationError("HUD ROI must be in image bounds and 8..512 pixels per side")

    def vector(image):
        region = image[y:y+h, x:x+w].mean(axis=2).astype(float)
        if region.std() < 3:
            return None
        region -= region.mean()
        return region.ravel() / np.linalg.norm(region)

    q = vector(query)
    scores, seen_labels, seen_hashes = [], set(), set()
    total_pixels = query.shape[0] * query.shape[1]
    for ref in refs:
        if not isinstance(ref, dict) or ref.get("layout_id") != layout:
            raise CalibrationError("Reference HUD layout must match query layout")
        label = ref.get("label")
        if not isinstance(label, str) or label not in LABELS[field] or label in seen_labels:
            raise CalibrationError("Reference labels must be distinct valid states of the selected field")
        seen_labels.add(label)
        image, hashed = decode_image(ref.get("image"))
        total_pixels += image.shape[0] * image.shape[1]
        if total_pixels > 48_000_000:
            raise CalibrationError("Total decoded images exceed 48 million pixels")
        if image.shape != query.shape:
            raise CalibrationError("All screenshots must have identical native dimensions")
        if hashed in seen_hashes:
            raise CalibrationError("The same reference image cannot have conflicting labels")
        seen_hashes.add(hashed)
        v = vector(image)
        if v is None:
            raise CalibrationError("Reference ROI lacks texture; select the actual state icon")
        score = float(np.clip(np.dot(q, v), -1, 1)) if q is not None else -1.
        scores.append({"label": label, "score": score, "capture_sha256": hashed})
    scores.sort(key=lambda row: row["score"], reverse=True)
    best = scores[0]
    gap = best["score"] - scores[1]["score"]
    reason = "LOW_TEXTURE" if q is None else "LOW_SIMILARITY" if best["score"] < threshold else "AMBIGUOUS" if gap < margin else "CANDIDATE"
    return {"kind": "offline_hud_candidate", "field": field, "layout_id": layout, "roi": roi,
            "label": best["label"] if reason == "CANDIDATE" else "unknown", "reason": reason,
            "score": best["score"], "margin": gap, "scores": scores,
            "query_sha256": qhash, "self_match": qhash in seen_hashes,
            "score_is_probability": False, "game_verified": False,
            "auto_execution_eligible": False,
            "notice": "Only compares supplied references. Requires independent real-screenshot validation; not wired to playback."}
