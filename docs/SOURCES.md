# 来源清单

人工核对日期：2026-09-23。以下社区数据可变化，不等同官方规范；只保留有限事实选项，不复制美术、整站文本或提供爬虫。

- 武器索引：https://wardogs.tools/database/weapons
- 配件事实：https://wardogs.tools/database/attachments
- 解锁表：https://wardogs.tools/progression
- 每把枪的兼容证据：catalog.py 中逐枪 sources 字段（例如 https://wardogs.tools/zh-hans/database/weapons/galil）。
- 数据站性质与条款：https://wardogs.tools/terms
- 光流实现依据：https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html
- 游戏使用边界（不是技术正确性证据）：https://store.steampowered.com/eula/1867240_eula_0

游戏中的截图、用户所选配件及实测轨迹才是配置/校准的最终确认依据。过去聊天中的数值不能替代当前源文件和来源证据。

## V0.3

鼠标官方核对见DEVICE_SUPPORT.md。归一化相关参考：OpenCV Template Matching https://docs.opencv.org/4.x/d4/dc6/tutorial_py_template_matching.html 。本版以NumPy实现固定ROI零均值相关，不等同于已训练识别模型。
