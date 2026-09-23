# Recoil Calibration Lab · 本机校准工作台

V0.5.0-rc1 将配装、项目保存、窗口采集、响应标定、曲线拟合、独立验证、版本回退和导出接入同一界面。新增默认关闭的 Windows 标准输入后端，不依赖雷蛇或罗技专有脚本。

**这是手动监督的产品候选版，不是已经通过 WARDOGS 实机验收的全自动工具。** 没有经过验证的全游戏枪械、姿态和弹量识别；不会依据未验证的HUD候选自动执行。合成演示不能启用真实输出。

仓库：`olu37776-bit/recoil-calibration-lab`，公开可见。不要提交个人截图、录像、输入记录、凭据或购买信息。

## 启动

Windows便携版仅在远端验证、真实浏览器测试和打包程序自检全部通过后，发布到提交绑定的prerelease。下载 `RecoilLab-0.5.0-rc1-Windows-x64.zip` 后解压整个文件夹，双击 `RecoilLab.exe`；不需要安装Python。没有成功的发布资产时，不应把源码ZIP称为便携版。

源码启动需要Python 3.11以上，在项目根目录依次运行：

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[ui,video]"
.\.venv\Scripts\python -m recoil_lab.app
```

程序自动选择空闲端口并打开本机浏览器。保留控制台窗口；关闭即退出。Linux/macOS可用相同模块运行离线工作流，但不提供Windows输入接口。

先点击 **一键跑完整演示**：应出现11条合成记录、2个曲线版本及 `SIMULATED_REPLAY` 报告。关闭后项目可重新打开。演示只证明软件流程，不证明游戏效果。

## 一条实际测量流程

1. 按真实值建立枪械、配件、弹药、倍率、姿态、DPI、灵敏度、分辨率、FOV和游戏构建项目。
2. 在采集页选择目标窗口，明确授权，取得窗口预览并框选稳定墙面纹理。
3. 至少2轮不射击响应记录，至少3轮训练记录；工作台自动保存时间戳和数值，不保存原始图像。
4. 在同一界面自动标定响应、拟合曲线；新增训练可小步修正，旧版本保留。
5. 用3轮独立新采集记录验证当前候选。模型预测、合成结果或不匹配输入不能冒充实际回放。
6. 真实记录且 `RECORDED_REPLAY` 通过后，才允许明确启用手动监督运行。

完整操作与限制见 [Windows使用说明](docs/QUICKSTART.md)，范围与验收见 [产品计划](docs/PRODUCT_V05.md)。

## 输出与停止

默认不发送鼠标输入。响应采集使用 **F7+右键，不开火**；训练、候选验证和手动监督运行使用 **F7+右键+左键**，每轮先释放左键。**F8/Esc急停**，释放使能、失焦、窗口PID/尺寸改变、调度卡顿或工作台心跳失联也会停止，不补发积压动作。

候选验证为有时限的测试；常规运行要求实际独立验证。单条曲线最长6秒、不循环，任务最长120秒。程序不自动点击、不读取游戏进程、不提权、不绕过反作弊。标准输入可能被目标拒绝；不因此关闭系统保护或尝试规避。用户授权采集并不代表游戏官方许可，只能在明确允许的受控场景使用。

换枪、配件、姿态、灵敏度等后须停用并重建或选择对应项目，程序不能仅靠窗口大小自动确认所有设置。当前Ctrl属于中断键，不支持按住Ctrl的蹲姿采集。

## 数据与配装目录

项目、数值轨迹、响应、曲线、报告保存在本机 `%LOCALAPPDATA%\RecoilCalibrationLab`。原始图像默认只在内存中处理，无遥测、默认远端上传或游戏进程访问。项目导出文件可能包含配置数据，分享前自行核对。

保留14把枪械、49个配件、18种弹药的人工核对社区目录，以及原截图三模式、自适应HUD参考比较和状态实验室。每项有来源、解锁与费用，未确认字段明确未知；目录不是完整官方数据库，不将配件百分比直接换成鼠标量。见 [目录说明](docs/CATALOG.md)。

原截图工具仍在首页 `/`，参考图识别在 `/adaptive.html`。它们不自动连接实际输出。单张弹着图不恢复连射时间曲线；只有符合时间、质量、输入记录与配置契约的数据才能进入校准。

旧版 recording-only 项目不隐式变成 `windows-sendinput-v1`：新后端必须重新标定输入响应。HUD跨分辨率定位也不等于可以直接缩放曲线counts。

## 验证

```powershell
.\.venv\Scripts\python -m pip install -e ".[test,ui,video]"
.\.venv\Scripts\python tools/verify.py
.\.venv\Scripts\python tools/check_evidence.py
.\.venv\Scripts\python -m recoil_lab.app --self-test runs/app-self-test.json
```

本地测试报告见 `evidence/verification.json`，源文件指纹必须匹配。本地HTTP自检与受限DOM桥接分别记录；桥接不冒充浏览器网络E2E。GitHub单独执行Linux/Windows测试、真实浏览器访问、Windows构建及打包后的程序自检，再发布带SHA256的资产。

自动化测试、虚拟桌面反馈测试和打包自检不代表真实Windows硬件、WARDOGS、鼠标驱动或独立审查通过。最新验证状态以具体提交的工作流为准，不沿用旧版本结果。

当前状态：[CURRENT](docs/CURRENT.md)；数据与证据：[CONTRACTS](docs/CONTRACTS.md)；参考图状态：[STATE_FEEDBACK](docs/STATE_FEEDBACK.md)；分辨率适配：[AUTOMATION](docs/AUTOMATION.md)。
