# Game Assist — 第一版

后续 AI 或开发者开始修改前，请先阅读 [项目说明与后续 AI 开发指引](AI_PROJECT_GUIDE.md)。该文档记录当前真实架构、已知技术债、插件约束和实施路线图。

这是一个仅用于自有程序、离线/单机游戏或已获授权自动化测试的 Windows 视觉自动化起步项目。它不读取目标进程内存、不注入进程、不尝试绕过反作弊或安全机制。

第一版已实现：

- 通过窗口标题绑定可见目标窗口；
- 从目标窗口的客户区截图；
- 在固定 ROI 中按 HSV 颜色和横向填充长度估算血条百分比；
- F8 启停、F12 紧急停止（均可在配置中修改）；
- 每次等待均可取消；停止、失焦和异常时都会发送已按下键的 key-up；
- 血量低于阈值时按一次指定治疗键，并有冷却时间。

## 安装与运行（Windows）

需要 Python 3.11+：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item config\profile.example.yaml config\profile.yaml
python -m game_assist.main --config config\profile.yaml
```

先将 `config/profile.yaml` 中的 `window.title_contains` 改为目标窗口标题的一部分，再根据实际 UI 调整 `health_bar.roi`。坐标以**窗口客户区左上角**为原点，单位为像素。

将 `save_debug_frame` 暂时设为 `true`，启动后会按秒更新 `debug/latest-frame.png` 和 `debug/latest-overlay.png`；也可以在实时预览中先框选完整血条 ROI，再切换到取色模式单击有色填充部分。预览中直接滚动鼠标滚轮缩放，按住右键拖拽移动画面，也可以使用缩放按钮和滚动条。完成后关闭调试截图选项并保存配置。

运行后：F8 开始/停止；F12 立即停止。目标窗口失去前台焦点时，程序会释放按键并暂停；切回目标窗口后自动继续。

桌面界面分为“运行控制、功能插件、运行日志”。自动喝血是第一个内置功能插件，可以独立启停；插件内部拥有自己的识别、规则、状态和冷却。新增怪物识别或技能释放时，通过插件注册接入，不需要修改主运行器。开发接口和示例见 [功能插件开发文档](docs/PLUGIN_DEVELOPMENT.md)。

另一个内置基础插件是“自动按键”。它使用安全的小型宏脚本编排按键、等待、定时触发、插件状态条件和循环：

```text
macro 示例连招
trigger every 5s
when auto_heal.percent < 50 and auto_heal.confidence >= 0.8
repeat 3
press 1
wait 300ms
press CTRL+2 hold 80ms
end
```

脚本不是 Python、Shell 或完整 AutoHotkey，不会执行任意系统命令。动作仍由宿主统一检查和发送，支持 F12 立即取消。定时精度受 `capture.poll_interval_ms` 影响，默认约为 100ms。

`capture.recognition_interval_ms` 控制截图与识别的间隔，默认 `500` 毫秒。桌面界面中的“判断间隔”可直接修改该值；静态截图校准时可适当调大到 `1000` 毫秒。

治疗规则仅在连续多帧满足 `HP < 治疗阈值` 且置信度达标时触发；HP 与阈值相等时不会触发。每条规则独立冷却，多条规则同时满足时优先执行阈值更低的紧急规则。每次触发都会在界面的“触发日志”中显示，并追加写入 `logs/actions.log`，内容包括 HP、阈值、置信度、规则名、实际按键和执行结果。

按键支持 `0-9`、`A-Z`、`F1-F24`、方向键、`Ctrl/Shift/Alt` 等常用键，也支持组合键和序列，例如 `CTRL+1` 或 `1,2`。配置在启动时会完整校验，危险或无法执行的数值会直接给出错误，而不会带着无效配置运行。

## 测试与打包

```powershell
pytest
```

已提供 [Windows GitHub Actions 工作流](.github/workflows/windows.yml)：它在 `windows-latest` 运行测试、用 Nuitka 构建 `game-assist.exe`，并上传构建产物。

下一步可在不改变执行器的前提下增加模板匹配、OCR 和 YOLO/ONNX 检测器；它们都只需输出统一的识别结果，规则层再决定动作。
