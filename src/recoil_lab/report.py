"""Standalone HTML report. No external scripts, network calls or telemetry."""
from __future__ import annotations

from html import escape
from pathlib import Path


def write_html(path: str | Path, report: dict) -> None:
    rows = []
    for trial in report["trials"]:
        cells = [escape(trial["run_id"]), f'{trial["baseline_rms_px"]:.3f}',
                 f'{trial["residual_rms_px"]:.3f}', f'{trial["peak_abs_px"]:.3f}',
                 f'{100*trial["improvement"]:.1f}%', "通过" if trial["passed"] else "未通过"]
        rows.append("<tr>" + "".join(f"<td>{v}</td>" for v in cells) + "</tr>")
    content = f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Recoil Calibration Lab · 验证报告</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1000px;margin:48px auto;padding:0 24px;line-height:1.65}}
table{{border-collapse:collapse;width:100%}}th,td{{padding:10px;text-align:left;border-bottom:1px solid}}
code{{overflow-wrap:anywhere}}aside{{border-left:4px solid;padding:8px 18px;margin:24px 0}}
</style>
<h1>后坐力校准 · V0.1 验证报告</h1>
<aside><strong>本报告不是 WARDOGS 实机压枪效果证明。</strong><br>
证据类型：{escape(report['evidence_kind'])}；来源：{escape(report['source'])}。<br>
只评估垂直画面位移，不评估弹着精度、命中率或在线兼容性。</aside>
<p>结论：<strong>{escape(report['decision'])}</strong></p>
<p>Profile ID：<code>{escape(report['profile_id'])}</code></p>
<table><thead><tr><th>验证样本</th><th>基线 RMS/px</th><th>残差 RMS/px</th><th>最大偏移/px</th><th>改善</th><th>门禁</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<h2>本版边界</h2>
<p>训练与验证按采集会话、文件哈希和内容哈希隔离。低置信度和超过100毫秒的采样缺口拒绝进入校准。
鼠标输入响应和延迟只在固定配置下成立。模拟回放、离线模型预测、实际录制回放分别标注，不能互相替代。</p>
<p>自动输入驱动、实时画面采集、游戏内验收均未接入。只在自行控制或明确获准的测试环境执行自动化。</p>
</html>'''
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
