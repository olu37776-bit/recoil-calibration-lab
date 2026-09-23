"""Bounded, multiscale offline HUD candidates. Never rescales calibration input."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math

import numpy as np

from .contracts import CalibrationError, digest
from .hud import LABELS
from .screenshots import decode_image
from .state import number
from .video import _cv

ENGINE = "adaptive-hud-v1"
MAX_PIXELS = 90_000_000


def _roi(value, shape):
    if not isinstance(value, list) or len(value) != 4 or any(type(v) is not int for v in value):
        raise CalibrationError("Reference ROI must be [x,y,width,height] integers")
    x, y, w, h = value
    if min(x, y) < 0 or not 8 <= w <= 256 or not 8 <= h <= 256 or x+w > shape[1] or y+h > shape[0]:
        raise CalibrationError("Reference ROI must be in bounds and 8..256 pixels per side")
    return x, y, w, h


def _gray(image):
    return _cv().cvtColor(image, _cv().COLOR_BGR2GRAY)


def _pixels_hash(image):
    return sha256(str(image.shape).encode() + image.tobytes()).hexdigest()


def _axis(center, old_extent, new_extent, scale):
    """Anchor to nearest edge, or the center for the middle third."""
    if center < old_extent / 3:
        return center * scale, "start"
    if center > old_extent * 2 / 3:
        return new_extent - (old_extent - center) * scale, "end"
    return new_extent / 2 + (center - old_extent / 2) * scale, "center"


def _overlap(a, b):
    x1, y1, w1, h1 = a
    x2, y2, w2, h2 = b
    intersection = max(0, min(x1+w1, x2+w2)-max(x1, x2)) * max(0, min(y1+h1, y2+h2)-max(y1, y2))
    return intersection / max(1, w1*h1 + w2*h2 - intersection)


@dataclass
class _Reference:
    label: str
    image_size: tuple[int, int]
    roi: tuple[int, int, int, int]
    patch: np.ndarray
    capture_hash: str
    pixel_hash: str


class AdaptiveHUD:
    """References are loaded once per request/batch; no disk or global cache."""
    def __init__(self, payload: dict):
        if not isinstance(payload, dict):
            raise CalibrationError("Expected a JSON object")
        self.field = payload.get("field")
        self.layout = payload.get("layout_id")
        if not isinstance(self.field, str) or self.field not in LABELS:
            raise CalibrationError("field must be pose/action/ads/ammo")
        if not isinstance(self.layout, str) or not self.layout.strip() or len(self.layout) > 160:
            raise CalibrationError("Provide a HUD layout/version identifier")
        self.threshold = number(payload.get("threshold", .9), "threshold")
        self.margin = number(payload.get("margin", .08), "margin")
        if not .8 <= self.threshold <= 1 or not .01 <= self.margin <= .5:
            raise CalibrationError("threshold in [.8,1], margin in [.01,.5] required")
        refs = payload.get("references")
        if not isinstance(refs, list) or not 2 <= len(refs) <= 8:
            raise CalibrationError("Provide 2..8 differently labelled references")
        self.references = []
        self.total_pixels = 0
        seen, hashes = set(), set()
        patch_signatures = []
        for ref in refs:
            if not isinstance(ref, dict) or ref.get("layout_id") != self.layout:
                raise CalibrationError("Reference layout/version must match")
            label = ref.get("label")
            if not isinstance(label, str) or label not in LABELS[self.field] or label in seen:
                raise CalibrationError("Reference labels must be distinct valid states")
            seen.add(label)
            image, capture_hash = self.decode(ref.get("image"))
            pixel_hash = _pixels_hash(image)
            if pixel_hash in hashes:
                raise CalibrationError("Identical reference pixels cannot have different labels")
            hashes.add(pixel_hash)
            box = _roi(ref.get("roi", payload.get("roi")), image.shape)
            x, y, w, h = box
            patch = _gray(image[y:y+h, x:x+w])
            if float(patch.std()) < 4:
                raise CalibrationError("Reference icon lacks texture")
            # Also reject identical icon crops on otherwise different backgrounds.
            signature = _cv().resize(patch, (24, 24)).astype(np.float64)
            signature -= signature.mean()
            norm = float(np.linalg.norm(signature))
            if norm < 1e-8:
                raise CalibrationError("Reference icon lacks distinguishable texture")
            signature /= norm
            if any(float(np.sum(signature * prior)) > .999 for prior in patch_signatures):
                raise CalibrationError("Reference icons are indistinguishable; crop the changing state indicator")
            patch_signatures.append(signature)
            self.references.append(_Reference(label, (image.shape[1], image.shape[0]), box, patch, capture_hash, pixel_hash))
        self.reference_id = digest({"engine": ENGINE, "field": self.field, "layout": self.layout,
                                   "threshold": self.threshold, "margin": self.margin,
                                   "references": [{"label": r.label, "pixels": r.pixel_hash, "roi": r.roi}
                                                  for r in self.references]})

    def decode(self, value):
        image, hashed = decode_image(value)
        self.total_pixels += image.shape[0] * image.shape[1]
        if self.total_pixels > MAX_PIXELS:
            raise CalibrationError("Batch exceeds 90 million decoded pixels; use fewer frames")
        return image, hashed

    def _matches(self, gray, ref):
        cv = _cv()
        qh, qw = gray.shape
        rw, rh = ref.image_size
        x, y, w, h = ref.roi
        # Pixel-constant HUD, resolution-scaled HUD and common independent UI scales.
        bases = {1., qw/rw, qh/rh, 1.25, 1.5, 2.}
        scales = sorted({round(base * variation, 5) for base in bases
                         for variation in (.85, .925, 1., 1.075, 1.15)
                         if .5 <= base * variation <= 3.})
        matches, sizes = [], set()
        budget = 0
        for scale in scales:
            tw, th = max(1, round(w*scale)), max(1, round(h*scale))
            if (tw, th) in sizes or min(tw, th) < 8 or max(tw, th) > 512:
                continue
            sizes.add((tw, th))
            cx, ax = _axis(x+w/2, rw, qw, scale)
            cy, ay = _axis(y+h/2, rh, qh, scale)
            # Bounded neighborhood; not a full-screen random-texture search.
            pad_x, pad_y = min(160, max(24, round(qw*.065))), min(120, max(24, round(qh*.065)))
            left = max(0, math.floor(cx - tw/2 - pad_x))
            top = max(0, math.floor(cy - th/2 - pad_y))
            right = min(qw, math.ceil(cx + tw/2 + pad_x))
            bottom = min(qh, math.ceil(cy + th/2 + pad_y))
            if right-left < tw or bottom-top < th:
                continue
            budget += (right-left)*(bottom-top)
            if budget > 18_000_000:
                raise CalibrationError("Search budget exceeded; use a smaller reference icon")
            template = cv.resize(ref.patch, (tw, th), interpolation=cv.INTER_AREA if scale < 1 else cv.INTER_LINEAR)
            if float(template.std()) < 3:
                continue
            result = cv.matchTemplate(gray[top:bottom, left:right], template, cv.TM_CCOEFF_NORMED)
            result[~np.isfinite(result)] = -1
            for _ in range(2):
                _, score, _, loc = cv.minMaxLoc(result)
                if score < -0.99:
                    break
                px, py = loc
                matches.append({"score": float(np.clip(score, -1, 1)),
                                "roi": [left+px, top+py, tw, th], "scale": scale,
                                "anchor": [ax, ay]})
                # Remove the same peak's immediate neighborhood, retaining spatial alternatives.
                ex, ey = max(2, tw//2), max(2, th//2)
                result[max(0, py-ey):py+ey+1, max(0, px-ex):px+ex+1] = -1
        matches.sort(key=lambda m: m["score"], reverse=True)
        if not matches:
            return {"label": ref.label, "score": -1., "roi": None, "scale": None,
                    "anchor": None, "spatial_margin": 0.}
        best = matches[0]
        alternative = next((m for m in matches[1:] if _overlap(m["roi"], best["roi"]) < .2), None)
        return {"label": ref.label, **best,
                "spatial_margin": best["score"] - (alternative["score"] if alternative else -1.)}

    def compare(self, value):
        image, hashed = self.decode(value)
        gray = _gray(image)
        scores = sorted((self._matches(gray, ref) for ref in self.references),
                        key=lambda m: m["score"], reverse=True)
        best, runner = scores[:2]
        gap = best["score"] - runner["score"]
        reason = ("LOW_SIMILARITY" if best["score"] < self.threshold else
                  "AMBIGUOUS_LABEL" if gap < self.margin else
                  "AMBIGUOUS_LOCATION" if best["spatial_margin"] < .04 else "CANDIDATE")
        pixel_hash = _pixels_hash(image)
        return {"kind": "adaptive_hud_candidate", "engine": ENGINE, "field": self.field,
                "layout_id": self.layout, "reference_set_id": self.reference_id,
                "query_size": [image.shape[1], image.shape[0]], "query_sha256": hashed,
                "pixel_sha256": pixel_hash, "self_match": any(pixel_hash == r.pixel_hash for r in self.references),
                "label": best["label"] if reason == "CANDIDATE" else "unknown", "reason": reason,
                "roi": best["roi"], "scale": best["scale"], "anchor": best["anchor"],
                "score": best["score"], "margin": gap, "spatial_margin": best["spatial_margin"],
                "scores": scores, "score_is_probability": False, "game_verified": False,
                "auto_execution_eligible": False, "units": "native_image_px",
                "notice": "Resolution-aware reference search only. No pretrained game model or calibration-input rescaling."}


def compare_adaptive(payload: dict) -> dict:
    return AdaptiveHUD(payload).compare(payload.get("image"))


def compare_sequence(payload: dict) -> dict:
    from .temporal import CandidateStabilizer
    frames, times = payload.get("images"), payload.get("timestamps")
    if not isinstance(frames, list) or not 2 <= len(frames) <= 24 or not isinstance(times, list) or len(times) != len(frames):
        raise CalibrationError("Provide 2..24 frames and explicit matching timestamps")
    times = [number(t, "timestamp") for t in times]
    if times[0] < 0 or any(b <= a for a, b in zip(times, times[1:])):
        raise CalibrationError("Timestamps must be nonnegative and strictly increasing")
    detector, stabilizer = AdaptiveHUD(payload), CandidateStabilizer()
    trace = []
    for t, image in zip(times, frames):
        candidate = detector.compare(image)
        trace.append({"t_s": t, "candidate": candidate, "temporal": stabilizer.update(t, candidate)})
    return {"kind": "offline_adaptive_sequence", "frames": len(trace), "trace": trace,
            "auto_execution_eligible": False, "game_verified": False,
            "timing": "explicit_media_timestamps", "notice": "Stability is not recognition accuracy or live capture."}
