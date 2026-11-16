# KiCad-native geometry export

已实现读取端，使用指定 KiCad Python 的 `pcbnew.LoadBoard`、
`GetBoardPolygonOutlines` 和 `TransformShapeToPolygon`。不是自行解析
`.kicad_pcb` 文本，也不使用外接矩形代替焊盘几何。

本机验证环境：`D:/Program Files/KiCad/10.0/bin/python.exe`，`pcbnew.Version()`
为 **10.0.8**。这与正式评测暂定 9.0.8 锁分开记录；未修改该评测锁。
9.x 板框 API 分支已保留，但尚未在真实 9.x 安装上验证。

从 `pcb-bench/` 运行（输出目录必须不存在）：

```powershell
python tools/bench.py export-geometry --case ../dataset/test/case.json --out results/kicad-export-test --kicad-python "D:/Program Files/KiCad/10.0/bin/python.exe" --expected-version 10.0.8 --max-error-mm 0.005
```

输出：

| 文件 | 内容 |
| --- | --- |
| `geometry.json` | 板框、多边形内孔、铜层映射、网络、逐层焊盘/走线/过孔/铜图形轮廓及电气属性 |
| `source_map.json` | 几何对象 ID 与 KiCad UUID、网络和层的映射 |
| `project_rules.json` | 项目设置的原始 JSON；不是已解析的逐对象有效规则 |
| `conversion_report.json` | 实际版本、源文件哈希、误差策略、数量、限制与警告 |
| `source/` | 原板、项目文件及存在时的自定义规则原样快照，供未来回写 |

**范围与语义：**

- 坐标是 KiCad 板级全局坐标，单位 mm，不翻转 Y 轴。层编号按 `CuStack()`
  获取，不能硬编码 KiCad F.Cu/B.Cu 的内部数字（大版本间可能改变）。
- 铜轮廓使用 KiCad 按层生成的 `SHAPE_POLY_SET`，含多轮廓/内孔；曲线按
  `max_error_mm` 外逼近，`clearance=0`，避免重复膨胀规则间距。
- 板框单独通过 KiCad 轮廓 API 获取，不使用铜外逼近误差设置推断其精度。
- 焊盘保存镀通属性、钻孔尺寸/形状代码/位置、网络、封装与焊盘 UUID。
  铜多边形是外部铜包络，钻孔信息单独表示，不能把孔内区域误当实体铜。
- 当前支持普通/自定义焊盘的 KiCad 铜轮廓、直线/圆弧走线、过孔和铜层
  PCB_SHAPE 图形；不支持的铜图形、铺铜和规则区域明确拒绝，不静默省略。
- 非铜绘图不进入障碍几何，在报告中列出且保留于源文件；完整规则、热连接、
  铺铜填充策略和制造约束尚未解析。导出不代表 DRC 或布线成功。

**与旧 C++ IR 的区别：** 新提取协议 `kicad-geometry-1.0` 保存多层焊盘和
多轮廓数据，不能直接输入目前 `megaroute_cli` 的 `1.0` JSON 模型。
报告明确输出 `cpp_geometry_v1_compatible=false`。后续需要升级几何模型及
路由接入层，不能通过删去通孔层来强行兼容。IR -> KiCad 回写仍未实现。

测试（使用真实 KiCad，未设置环境变量时 native 测试会跳过）：

```powershell
$env:KICAD_PYTHON = "D:/Program Files/KiCad/10.0/bin/python.exe"
$env:KICAD_VERSION = "10.0.8"
python tests/test_geometry_export.py
```
