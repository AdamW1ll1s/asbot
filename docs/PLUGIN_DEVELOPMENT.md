# 功能插件开发

Game Assist 的宿主只负责窗口截图、安全检查、动作执行、预览叠图和审计日志。功能插件负责解释画面并提出动作请求。

## 插件生命周期

每个启用的插件会收到同一张客户区截图：

1. 宿主调用 `reset_session()` 初始化一次运行。
2. 每个识别周期调用 `process_frame(frame, now)`。
3. 插件返回 `PluginResult`，其中可以包含状态摘要、预览框和一个 `ActionRequest`。
4. 宿主确认目标窗口仍在前台后执行动作。
5. 只有动作完整发送后，宿主才调用 `mark_action_completed()`；插件可在此开始自己的冷却。
6. 失焦时宿主调用 `reset_observations()` 并释放所有按键。

需要在截图间隔之间推进等待或循环的插件，可以额外实现 `TimedFeaturePlugin.process_tick()`。宿主会按 `capture.poll_interval_ms` 推进它，不需要插件创建线程或调用 `sleep()`。内置自动按键插件是参考实现。

接口定义在 `src/game_assist/plugins/base.py`，内置自动喝血插件可作为完整示例。

## 新增自动打怪插件

在 `src/game_assist/plugins/` 新建 `monster_combat.py`：

```python
class MonsterCombatPlugin:
    plugin_id = "monster_combat"
    display_name = "自动打怪"

    def __init__(self, config):
        settings = config.plugin_settings(self.plugin_id)
        # 在这里加载模板或 ONNX 模型。

    def reset_session(self): ...
    def reset_observations(self): ...

    def process_frame(self, frame, now):
        # 识别怪物并维护搜索/锁定/战斗状态机。
        # 返回 PluginResult；需要按键时附带 ActionRequest。
        ...

    def mark_action_completed(self, request, now):
        # 记录技能冷却；取消或失败的动作不会调用这里。
        ...
```

然后在 `plugins/registry.py` 增加一个 `PluginDescriptor`。如果插件需要图形化配置，再实现自己的 Tk 设置面板并注册到 `plugins/ui_registry.py`。主运行器和主窗口都不需要增加针对该插件的判断分支。

插件配置放在自己的命名空间，保存配置时未知字段也会被保留：

```yaml
plugins:
  auto_heal:
    enabled: true
  monster_combat:
    enabled: true
    detector: onnx
    model: models/monsters.onnx
    confidence: 0.80
    attack_key: "1"
    skill_rotation: "2,3,4"
```

## 怪物识别建议

- 固定 UI、固定视角和少量怪物：优先使用 OpenCV 模板匹配。
- 怪物会缩放、转向或被特效遮挡：使用 YOLO 训练后导出 ONNX。
- 插件应输出怪物类别、置信度和边界框；边界框通过 `OverlayBox` 交给宿主绘制。
- 技能轮转应使用状态机和独立冷却，不要在每一帧直接发送按键。
- 所有动作仍由宿主统一执行，以保留前台窗口限制、紧急停止和动作审计。

## 自动按键脚本

`auto_key.py` 提供受限 DSL 和非阻塞状态机，可作为通用动作层使用。支持的语法只有：

- `macro <名称>` / `end`
- `trigger start` 或 `trigger every <时间>`
- `when always` 或 `when <plugin>.<metric> <op> <number>`，可用 `and` 连接
- `repeat <次数>` 或 `repeat forever`
- `press <按键> [hold <时间>]`
- `key_down <按键>` / `key_up <按键>`
- `move <x> <y>`（目标窗口客户区相对坐标）
- `mouse_down <button> <x> <y>` / `mouse_up <button> <x> <y>`
- `wheel <delta> <x> <y>` / `hwheel <delta> <x> <y>`
- `wait <时间>`

不要为了增加脚本功能而使用 `eval()`、`exec()`、Shell 或动态 Python。新语法必须进入解析器、产生明确数据结构，并有错误行号和单元测试。

## 键鼠录制与回放

`recording.py` 使用 Windows 低级键盘/鼠标钩子捕获物理输入，并明确丢弃带 injected 标记的事件。只有选定目标窗口处于前台时才会记录；鼠标移动最短每 20ms 采样一次，坐标转换为客户区相对坐标。F10 是录制会话的停止键，不写入结果。单次 5000 个事件上限用于避免生成无法编辑或执行的超大脚本。

录制结果必须先转换成上述受限 DSL，再由 `AutoKeyPlugin` 和宿主执行器回放。录制器不得直接回放，插件也不得绕过 `ActionRequest` 调用输入 API。宿主在停止、失焦和异常时必须同时释放键盘键和鼠标键。

不要加入以规避反作弊、风控或自动化检测为目的的随机延迟、轨迹噪声、驱动伪装或注入标记隐藏。测试系统若需要时间容差，应以明确命名、可复现种子和测试配置实现，不能声称其能让合成输入等同物理输入。
