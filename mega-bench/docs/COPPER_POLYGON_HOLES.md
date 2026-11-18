# 带孔铜多边形

## 设计与实现

中间板模型的 `polygon` 保留原有 `points` 外环，并新增可选 `holes` 内环数组。
铜区域定义为闭合外环区域减去各孔的内部；孔边界属于铜边界。
省略 `holes` 等价于空数组，旧输入兼容。坐标单位仍为 mm，不要求环的方向。

- KiCad 适配器保留铜图形和自定义多边形焊盘的内环；圆形快捷路径不丢弃显式内孔。
  带孔焊盘选外环第一个顶点作为布线接入点，源焊盘位置仍保存在原始几何中。
- C++ 模型校验每个环简单且非退化，孔严格位于外环内部，孔之间不能接触、相交或嵌套。
  拓扑检查使用独立的 `1e-9 mm` 数值阈值，保留 KiCad 的 `1e-6 mm`（1 nm）短边；
  DRC 容差仍为 `1e-6 mm`，不通过简化顶点修改原始坐标。
  接入点必须位于铜区域或边界，不能在孔内部。
- `gap` 对外环和所有内环计算边界距离，并按实际铜区域检查包含关系。
  圆、胶囊走线和过孔可以位于孔内，仍须满足到孔壁的铜间距；跨孔壁会碰撞。
  多边形落在另一形状孔内时不会被误报为短路，也不会产生虚假电连接。
- 搜索、DRC、连通性共用 `gap`。空间索引继续使用外环包围盒作为粗筛，精确检查保留内孔。
  板边距离检查同时考虑内环。中间板可视化使用带孔路径，孔透明显示。

本次范围是单外环带多个互不相交内孔的铜形状。多外环焊盘、反相挖空铜文字仍按已有能力限制处理；
板框开孔和制造钻孔规则保持各自语义。

## 验证

已编译并运行合成测试 `polygon_holes`、`rule_semantics`、`routing_adapter` 和
`native_geometry_export` 及既有 `core` 单元测试。覆盖孔内圆/走线/过孔、孔壁间距、跨壁碰撞、孔内多边形、
电连接、环方向、非法孔、旧格式兼容、1 nm 短边和适配器内环保留。
另用 0026、0098 已有几何导出进行静态适配与 CLI 输入校验，两者均通过且内部输入 DRC 为 0。
未执行数据集布线实验。

0034 的已有报告为 12/14、内部 DRC 0，因 `search_exhausted` 后停滞退出。
其已有几何导出没有带孔铜形状，因此本次改动不宣称解决其剩余两个连接。
0026、0098 各有一个带孔铜图形；此前在适配阶段退出，需重新运行整条流程确认最终结果。

## 0026、0098 重测

这两例标准路径下旧的 `megaroute` 结果已删除。项目根目录运行下列命令，重新导出、适配、布线并用 KiCad 评分：

```bash
cmake -S mega-bench -B mega-bench/build/dev -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build mega-bench/build/dev -j 2
export KICAD_RUN_FROM_BUILD_DIR=1
export PYTHONPATH="$PWD/external/kicad-9.0.8/pcbnew${PYTHONPATH:+:$PYTHONPATH}"
for id in 0026 0098; do
  for case_file in dataset/D3-A/d3a_"${id}"_*/case.json; do
    case_dir="${case_file%/case.json}"
    "${BENCH_PYTHON:-python3}" mega-bench/tools/bench.py run \
      --case "$case_file" --backend megaroute \
      --out "results/D3-A/${case_dir##*/}/megaroute" \
      --toolchain mega-bench/configs/kicad-toolchain.json \
      --kicad-python "${KICAD_PYTHON:-/usr/bin/python3}" --expected-version 9.0.8 \
      --router mega-bench/build/dev/megaroute_cli \
      --config mega-bench/configs/megaroute.json \
      --routing-seconds 600 --evaluation-seconds 120
  done
done
```

最终结果看各输出目录的 `evaluation/metrics.json` 和原生 DRC；
`work/route/metrics.json` 仅是内部几何诊断。0034 若要复测，应另选空输出目录保留已有结果。
