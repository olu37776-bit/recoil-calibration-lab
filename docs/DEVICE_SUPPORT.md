# 设备支持核对：雷蛇炼狱蝰蛇标准版

核对日期：2026-09-23。依据用户商品页文字判断系列为 Razer DeathAdder Essential；没有实机设备枚举，具体底部RZ型号和已安装驱动版本未知。

## 官方可确认

- Razer产品页列5个独立可编程按键与6400 DPI传感器。
- 官方DeathAdder Essential手册第14页明确Macro功能；安装Macro模块后可分配按键。手册是Synapse 3文档，不据此冒充已核对任意Synapse 4版本。
- 官方资料支持基础宏，不证明能自动读取游戏姿态、弹药、枪械或可靠执行某卖家脚本。

## 本项目兼容结论

离线选枪、截图测量、校准与状态回放不依赖鼠标品牌，可继续开发；雷蛇实机驱动适配未完成。

不能把商品中的Logitech G HUB说明当成通用格式。应把Razer和Logitech作为不同后端，分别验证：当前版本能否记录/导入所需移动、相对/绝对坐标、前台游戏是否接收、按下和松开停止行为、时间分辨率与实际单位响应。未验证前不导出虚构Synapse格式，不声称Lua可直接执行。

无需为继续开发先换鼠标。后续适配时再提供底部RZ型号（不需要序列号）和Synapse版本即可。

## 来源

- 产品规格：https://www.razer.com/gaming-mice/razer-deathadder-essential
- 官方手册：https://dl.razerzone.com/master-guides/RazerSynapse3/DeathAdderEssential-00000152-en.pdf （第6、14页；宏段落已核对页面）
- G HUB产品页：https://www.logitechg.com/en-us/software/ghub （面向Logitech G设备配置；不作为Razer兼容证明）
- 官方新版设备支持页：https://mysupport.razer.com/app/answers/detail/a_id/6120/~/razer-synapse-4-supported-devices （本次正文被站点前置检查挡住，未据此声称具体硬件子型号已支持）

无第三方商品安全保证；不复用用户上传的商品图片到公开仓库。
