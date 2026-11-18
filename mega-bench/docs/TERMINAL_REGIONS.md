# 铜区域接入模型（旧实现记录）

**当前实现已更新**：下文的多源区域搜索、动态最近铜点和加密策略已移除。当前仅在中心不可用时选择每层一个固定接入点，核心搜索遵循论文。见 [PAPER_FIDELITY.md](PAPER_FIDELITY.md)。

连接条件是同网络、同铜层的实体铜连通，不要求走线到达焊盘的标称中心。
本实现让走线中心线的端点落在目标铜区域或边界（采用模型既有数值容差），
而不是只依赖线宽边缘擦碰；完整线宽仍参与所有几何检查。
KiCad 的连通性及端点检查同样使用形状碰撞：
[connectivity_data.cpp](https://docs.kicad.org/doxygen/connectivity__data_8cpp_source.html)。

## 实现

- 起点采用多源搜索：源焊盘中心、朝向目标的最近铜点、外环及孔边界的顶点/中点，
  加上与板框包围盒相交区域的有限采样。矩形采样每轴最多 16 段，采样分辨率随加密等级改变。
  包围盒仅作粗筛，每个点必须在源铜区域，并通过完整线宽的板框、开孔、禁布区和间距检查。
  因此源焊盘中心在板外或开孔内时，也能从其合法铜区域接入。
- 根节点只表示可选接入位置，不生成虚拟导线，也不直接算作完成连接。
  首段实体铜或过孔必须实际接触源焊盘。
- 启发式改为到实际目标铜区域的欧氏距离下界。候选对齐使用最近铜点；
  同时保留原有八方向、换层和加密搜索，不把某一个最近点设为唯一终点。
- 任意候选中心线首次接触目标铜时，用前缀二分截短到首次接触区域，
  然后对截短后的完整铜形状执行原有转角和 DRC 检查。目标之后的候选延长部分不会误阻挡合法接入。
- 目标层必须与实际实体铜共享。异层同坐标不能靠虚拟换层完成连接，必须有真实过孔。
  带孔多边形按外环减内孔处理，孔内部不算目标铜，凹形轮廓也不使用包围盒代替。
- 完成状态与普通状态分别保存，避免空间去重误丢已完成连接的候选。
  重建路径后，再用实际输出铜的连通图验证两端已连接；序列化不补回指向标称中心的尾线。

三个搜索模式均使用相同接入模型。严格模式保留全部约束；协商模式仍只允许原有的可重布铜软冲突，
固定铜、板框和禁布区不放宽，最终输出仍经严格检查。
没有根据案例 ID、板名或特定坐标分支，也没有修改源焊盘、网络或板框。

这是有限采样和有限预算搜索，不保证所有连续空间可行解都能找到。
源铜区域的极窄可达部分仍可能需要加密；制造商的特殊接入、热焊盘或最小连接宽度要求
应由对应规则另行约束，本改动不替代完整制造 DRC。

## 验证

只运行合成测试和临时文件中的原生 KiCad 测试，没有运行 D3 数据集布线实验。

- `terminal_regions`：跨板边目标、交换起终点、两端中心均在板外、正板边间距、
  旋转焊盘、圆焊盘、板内开孔、整体旋转和平移、带孔铜、跨层过孔、阻塞路径、完全板外目标。
  所有完成结果都检查 DRC、实际连通性和 JSON 序列化后的连通性。
- `core`、`rule_semantics`、`routing_regressions`、`polygon_holes`、`cli_integration` 均通过。
  既有 core 中一个断言原本依赖中心采样找不到路径；区域采样现在可找到合法绕行，
  已改为要求布通且 DRC 为零，没有放宽安全检查。
- 原生 KiCad 9.0.8 合成测试确认：走线起终点偏离焊盘中心、接触焊盘边界/内部时确实连通；
  留有间隙或只在另一铜层重叠时仍不连通。

## 重测

0034 的旧结果保留。以下仅供用户在仓库根目录执行，使用新的空输出目录：

```bash
cmake --build mega-bench/build/dev -j 2
export KICAD_RUN_FROM_BUILD_DIR=1
export PYTHONPATH="$PWD/external/kicad-9.0.8/pcbnew${PYTHONPATH:+:$PYTHONPATH}"
for case_file in dataset/D3-A/d3a_0034_*/case.json; do
  "${BENCH_PYTHON:-python3}" mega-bench/tools/bench.py run \
    --case "$case_file" --backend megaroute \
    --out "results/D3-A/terminal-regions-0034-$(date +%Y%m%d-%H%M%S)" \
    --toolchain mega-bench/configs/kicad-toolchain.json \
    --kicad-python "${KICAD_PYTHON:-/usr/bin/python3}" --expected-version 9.0.8 \
    --router mega-bench/build/dev/megaroute_cli \
    --config mega-bench/configs/megaroute.json \
    --routing-seconds 600 --evaluation-seconds 120
done
```

最终结果以原生 `evaluation/metrics.json` 为准，不能把合成测试通过当作 0034 已重测成功。
