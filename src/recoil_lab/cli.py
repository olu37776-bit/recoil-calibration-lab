"""Local-only CLI: CSV/JSON, prerecorded video and a deterministic test rig."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import sys

from .calibration import fit_profile, fit_response, refine_profile, validate_profile
from .contracts import (CalibrationError, Response, load_profile, load_trial, read_json,
                        save_profile, save_trial, write_json)
from .demo import run_demo
from .playback import dry_run
from .report import write_html


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="recoil-lab", description="不依赖鼠标驱动的离线校准实验室")
    s = p.add_subparsers(dest="command", required=True)
    demo = s.add_parser("demo", help="运行完整合成数据闭环，不控制鼠标")
    demo.add_argument("--out", type=Path, default=Path("runs/demo"))
    response = s.add_parser("response", help="从无开火输入试验测量像素/输入单位")
    response.add_argument("--trials", nargs="+", required=True, type=Path)
    response.add_argument("--latency", type=float, default=0., help="已知延迟秒；本版不自动估计")
    response.add_argument("--out", type=Path, required=True)
    fit = s.add_parser("fit", help="用至少三轮训练数据生成初始曲线")
    fit.add_argument("--trials", nargs="+", required=True, type=Path)
    fit.add_argument("--response", type=Path, required=True)
    fit.add_argument("--out", type=Path, required=True)
    refine = s.add_parser("refine", help="用新训练证据小步修正曲线")
    refine.add_argument("--trials", nargs="+", required=True, type=Path)
    refine.add_argument("--profile", type=Path, required=True)
    refine.add_argument("--out", type=Path, required=True)
    val = s.add_parser("validate", help="使用隔离的验证会话评估，不用训练数据自证")
    val.add_argument("--trials", nargs="+", required=True, type=Path)
    val.add_argument("--profile", type=Path, required=True)
    val.add_argument("--previous", type=Path)
    val.add_argument("--out", type=Path, required=True)
    replay = s.add_parser("replay", help="仅输出模拟回放事件，不注入系统输入")
    replay.add_argument("--profile", type=Path, required=True)
    replay.add_argument("--out", type=Path, required=True)
    replay.add_argument("--tick-ms", type=float, default=10.)
    vid = s.add_parser("video", help="从静止靶面录屏提取无补偿训练轨迹")
    vid.add_argument("--input", type=Path, required=True)
    vid.add_argument("--context", type=Path, required=True)
    vid.add_argument("--roi", nargs=4, type=int, required=True, metavar=("X", "Y", "W", "H"))
    vid.add_argument("--run-id", required=True)
    vid.add_argument("--start", type=float, required=True, help="手工确定的首发参考时刻，秒")
    vid.add_argument("--duration", type=float, required=True)
    vid.add_argument("--uncompensated", action="store_true")
    vid.add_argument("--assumed-fps", type=float, help="仅在明确已知恒定帧率时覆盖媒体时间戳")
    vid.add_argument("--out", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "demo":
            report = run_demo(args.out)
            print(f"{report['decision']} | {report['evidence_kind']} | {args.out / 'report.html'}")
            return 0 if report["passed"] else 2
        if args.command == "response":
            response = fit_response([load_trial(x) for x in args.trials], args.latency)
            write_json(args.out, asdict(response))
        elif args.command == "fit":
            profile = fit_profile([load_trial(x) for x in args.trials], Response(**read_json(args.response)))
            save_profile(args.out, profile)
        elif args.command == "refine":
            profile = refine_profile(load_profile(args.profile), [load_trial(x) for x in args.trials])
            save_profile(args.out, profile)
        elif args.command == "validate":
            report = validate_profile(load_profile(args.profile), [load_trial(x) for x in args.trials],
                                      previous=load_profile(args.previous) if args.previous else None)
            write_json(args.out, report)
            write_html(args.out.with_suffix(".html"), report)
            print(f"{report['decision']} | {report['evidence_kind']} | {args.out}")
            return 0 if report["passed"] else 2
        elif args.command == "replay":
            profile = load_profile(args.profile)
            write_json(args.out, {"mode": "recording_only", "profile_id": profile.profile_id,
                                  "events": dry_run(profile, args.tick_ms/1000.)})
        elif args.command == "video":
            from .video import extract_video
            trial = extract_video(args.input, context=read_json(args.context), roi=tuple(args.roi),
                                  run_id=args.run_id, start_s=args.start, duration_s=args.duration,
                                  declared_uncompensated=args.uncompensated, assumed_fps=args.assumed_fps)
            save_trial(args.out, trial)
        print(f"Saved: {args.out}")
        return 0
    except (CalibrationError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
