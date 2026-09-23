"""Synthetic fixtures for the state lab; no learned game or hardware curves."""
from __future__ import annotations

from .contracts import CalibrationError, Profile, Response, context_id
from .demo import example_context
from .state import StatePlayback

SCENARIOS = ["normal", "empty", "reload", "grenade", "inventory", "melee", "hipfire", "unknown", "stale", "pose_change", "switch", "semi", "release", "heal", "unfocus", "inference"]


def profiles() -> list[Profile]:
    result = []
    for pose, end in [("standing", 40.), ("crouching", 22.), ("prone", 15.)]:
        c = dict(example_context(), pose=pose)
        r = Response(c, "synthetic", 1., 0., 0., ["synthetic-response"])
        result.append(Profile(c, "synthetic", r, [0., .4, 1.], [0., end*.4, end],
                              ["synthetic-train"], ["synthetic-session"], ["synthetic-content"],
                              ["synthetic-capture"], 100.))
    return result


def run_state_demo(payload: dict) -> dict:
    scenario = payload.get("scenario", "normal")
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        raise CalibrationError("Unknown state-demo scenario")
    bank = profiles()
    player = StatePlayback(bank)
    ids = [context_id(p.context) for p in bank]
    trace = []
    for n in range(81):
        t = round(n*.02, 4)
        o = {"observed_s": t, "context_id": ids[0], "pressed": n != 0,
             "ads": True, "focused": True, "item_kind": "firearm", "action": "ready",
             "fire_mode": "auto", "ammo": 35, "confidence": 1., "source": "synthetic"}
        if 20 <= n < 40:
            if scenario == "empty": o["ammo"] = 0
            elif scenario in {"reload", "inventory", "melee", "grenade", "heal"}: o["action"] = scenario
            elif scenario == "hipfire": o["ads"] = False
            elif scenario == "unfocus": o["focused"] = False
            elif scenario == "unknown": o["ammo"] = None
            elif scenario == "stale": o["observed_s"] = 0.
            elif scenario == "pose_change": o["context_id"] = ids[1]
            elif scenario == "switch": o["context_id"] = "unregistered-loadout"
            elif scenario == "semi": o["fire_mode"] = "semi"
            elif scenario == "release": o["pressed"] = False
            elif scenario == "inference": o["source"] = "input_inference"
        # Holding through recovery cannot auto-restart. Release at 1.0 s to rearm.
        if n == 50: o["pressed"] = False
        trace.append(player.tick(t, o))
    return {"kind": "synthetic_state_demo", "scenario": scenario, "trace": trace,
            "events": player.sink.events, "source": "synthetic", "game_verified": False,
            "notice": "Synthetic curves unrelated to selected armory weapon; no OS mouse output."}
