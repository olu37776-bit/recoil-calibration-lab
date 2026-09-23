# 执行入口

先读 `docs/CURRENT.md`、`docs/CONTRACTS.md` 和 `docs/ROADMAP.md`。这三个文件是本仓库的实施基线；聊天不是长期 Authority。

本仓库是独立项目。不要修改用户其他仓库，不要引入其 AI 软件工程 OS / GBrain 的实现。

## 当前 WRITE_SCOPE

`src/recoil_lab/`、`tests/`、`examples/`、`docs/`、`tools/`、`.github/workflows/`、`README.md`、`AGENTS.md`、`pyproject.toml`、`.gitignore`、`evidence/`。

## 必须遵守

- 先完成驱动无关功能；不得把鼠标品牌、驱动安装或具体游戏可启动作为核心算法的前置条件。
- V0.2 仍只输出数据及 RecordingSink 事件，不调用操作系统鼠标注入、不读游戏进程，不接反作弊或远端业务服务；UI仅绑定127.0.0.1。
- 不把合成样本、离线预测、录制回放、真实游戏验收混为一谈。`game_verified` 不得因模拟测试而变成 true。
- 校准与验证分开采集；不得通过改文件名、run_id 或从同一录像切片来伪造独立验证。
- 拒绝错误时间戳、低置信度、缺帧、配置不匹配；禁止用补零/静默插值掩盖丢失的画面位移。
- 任何新实现同时更新测试、证据和基线状态；未进行独立审查，不得声称有独立审查结论。
- 不把当前测试夹具里的模拟曲线命名为 Galil / M249 等游戏实测配置。
- 不添加遥测、账号凭证、网络上传或默认公开发布。当前用户已创建并指定公开仓库；保留可见性，禁止提交用户截图或凭据。不要覆盖其他仓库。

## 验证

```bash
python -m pip install -e ".[test,video,ui]"
python -m pytest -q --junitxml=runs/junit.xml --cov=recoil_lab --cov-report=term-missing
python -m recoil_lab demo --out runs/demo
```

本地测试不是 GitHub Actions 已通过的证据。新 HEAD 必须重新运行对应验证；不要复制旧报告冒充新结果。

公开目录维护参见 docs/CATALOG.md；不得做未授权的批量抓取，不复制全站素材。未知兼容/价格必须明确，不能制造确定性。单张弹着图不生成时间曲线。
