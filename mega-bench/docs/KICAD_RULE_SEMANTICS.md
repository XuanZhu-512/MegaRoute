# MegaRoute 与 KiCad 规则衔接

本次修正集中在输入规则解析、固定铜障碍和几何合法性检查；没有修改搜索候选、代价函数或迭代策略。

## 局部间距

导出器从 KiCad API 读取焊盘局部间距；焊盘没有设置时才继承封装值。导出字段为
`local_clearance_mm`、`local_clearance_source`，适配后的形状字段为 `clearance_override`。
缺省表示继承；显式零值会屏蔽封装覆盖，但对象对的间距检查回退到网络规则。

参照 KiCad 9.0.8 `DRC_ENGINE::EvalRules`：双方覆盖值中只要有正值，就用覆盖值的最大值
替代该对象对的网络类别间距，并受板级 `min_clearance` 下限约束。
没有正值覆盖时，继续使用双方网络间距的较大值及板级下限。短路检查保留。
无网络机械焊盘也携带覆盖值；空间索引同时考虑查询对象和被查询对象的覆盖间距。

## 铜层文字

可见的板级、封装文字以及封装字段从 `GetEffectiveTextShape(true)` 提取笔画胶囊和填充三角形，
作为固定铜导入。保留实际字形空隙，不使用整段文字的包络框。
同一文字的组成部分通过 `copper_group` 关联，避免笔画互相报短路；它们仍然阻挡其它铜。
文字笔画不受走线最小宽度约束。隐藏字段不作为铜障碍。

目前明确拒绝 knockout（反相挖空）铜层文字；普通带孔铜多边形现已支持，设计和重测命令见
[COPPER_POLYGON_HOLES.md](COPPER_POLYGON_HOLES.md)。

## 板框与开孔

适配器设置 `rules.fixed_boundary_policy = "kicad_edges"`。固定输入铜按到外板框、内部开孔
边界曲线的距离检查，不再把开孔整个内部当成实体障碍，也不强制固定铜完整包含于板框。
这允许零板边间距的既有矩形焊盘跨过板边，也允许与开孔边缘保持距离的既有机械铜位于开孔内。
正的板边间距仍执行检查。

新增走线与过孔继续严格限制在板框内、开孔外，即使板边间距为零。
手工提供的旧版中间 JSON 默认 `contained`，保留原来的包含判定。
这不是完整 KiCad DRC 等价实现：自定义规则、铣边线宽、金属化半孔例外、钻孔间距等仍需原生 KiCad
最终评估。

## 验证与重跑

本次执行编译和合成单元测试，没有执行 D3 数据集布线实验。
旧 `work/board.json` 和几何导出缺少新规则、文字数据，必须通过 `bench.py run` 重新导出。
建议先复查此前的 0011、0021、0023、0054、0024、0034、0035、0027 八块板，使用新的输出目录。
0026、0098 的带孔铜图形适配已实现，旧结果已删除；重测命令见
[COPPER_POLYGON_HOLES.md](COPPER_POLYGON_HOLES.md)，最终连通率和 DRC 等待重测确认。

在项目根目录执行（`KICAD_PYTHON` 指向与 KiCad 9.0.8 匹配的解释器）：

```bash
cmake --build mega-bench/build/dev -j4
export KICAD_RUN_FROM_BUILD_DIR=1
export PYTHONPATH="$PWD/external/kicad-9.0.8/pcbnew${PYTHONPATH:+:$PYTHONPATH}"
run_dir="results/D3-A/megaroute-rule-fix-$(date +%Y%m%d-%H%M%S)"
for id in 0011 0021 0023 0054 0024 0034 0035 0027; do
  for case_file in dataset/D3-A/d3a_"${id}"_*/case.json; do
    [ -f "$case_file" ] || continue
    case_dir="${case_file%/case.json}"
    "$KICAD_PYTHON" mega-bench/tools/bench.py run \
      --case "$case_file" --backend megaroute \
      --toolchain mega-bench/configs/kicad-toolchain.json \
      --kicad-python "$KICAD_PYTHON" --expected-version 9.0.8 \
      --router mega-bench/build/dev/megaroute_cli \
      --config mega-bench/configs/megaroute.json \
      --out "$run_dir/${case_dir##*/}"
  done
done
```

结果是否改善需以新的 `evaluation/metrics.json`、原生 DRC 报告以及
`work/route/metrics.json` 为准；内部输入检查通过不表示布线必然完成。
