# MegaRoute 路由优化（2026-11-16）

本次保留输入固定铜不变，不降低线宽或间距规则。优化目标为先全部连通且无
KiCad DRC error，再比较耗时、线长和过孔。`clean_pass` 仍允许 warning。

## 实现

- 固定焊盘和固定铜的短路/间距冲突作为硬约束；仅可重布路线之间允许临时软冲突。
- 新增分层铜 AABB 网格索引。长对象和大范围查询使用有界内存的回退扫描；索引
  只做候选筛选，最终仍执行精确几何检查。自适应步长采用阈值查询并提前退出。
- 使用追加式并查集维护连通性；拆线后重建图，提交路径时只更新附近铜对象。
  一次路由内缓存固定连接需求，合法子集使用增量 DRC，避免逐 bundle 全板评估。
- 按冲突连接 bundle 拆线，保留同网其他分支。历史拥塞在轮次间保留；停滞时调整
  搜索顺序并细化采样。密度抑制考虑到达方向，并随细化等级降低阈值。
- 为最终严格修复保留 `min(30 s, 20% 内部预算)`。严格修复从最佳合法结果出发，
  必要时尝试局部拆除阻塞 bundle；最优合法快照始终保留。每对连接有独立时间份额。
- 零板边间距允许铜接触板边，但仍检查完整铜形状的包含关系；凹板框使用边界
  交点分段检查，避免只检查端点而漏掉跨板外的线段/多边形。
- KiCad 连通统计包含直接相接的焊盘；回写按 KiCad 整数坐标、网络、孔径、外径、
  类型和层跨度去重过孔，保留不同网络/尺寸的对象和原有固定铜。
- CLI 发布原子的合法路线检查点；Python watchdog 超时后可回写最后合法检查点，
  结果仍由 KiCad 外部评测。内部时间上限小于进程 watchdog，为序列化留余量。
- 编译时记录源码指纹和构建类型；运行清单记录二进制 SHA-256、原配置哈希及
  实际配置。默认可执行文件与当前源码指纹不符时拒绝运行并提示重新编译。

## 默认参数

`configs/megaroute.json` 使用：

| 参数 | 默认值 |
|---|---:|
| beta / d_min_mm / lambda_v | 5 / 0.0254 / 1 |
| penalty_L / penalty_k / penalty_mu | 1000 / 0.8 / 4 |
| history_weight / history_cell_mm | 0.25 / 1 |
| stagnation_rounds / refinement_levels | 3 / 2 |
| max_iterations | 20 |
| time_limit_s | 300 |

解析器允许 `max_iterations=1..100`、`refinement_levels=0..4`。
细化等级 1、2 在障碍附近分别使用 `w/2`、`w/4` 的采样步长，不改变真实线宽。
`history_weight=0` 可关闭历史拥塞项。`step_mm` 仍仅控制固定步长算法。
Logistic 公式及其函数默认参数保留原定义；工程默认值由配置文件明确指定。

运行入口默认 watchdog 为 300 秒，实际内部上限为 290 秒；更小的外部预算按比例
留余量，并保留原配置中更短的限制。最终解析后的完整参数见 `work/route/config.json`。

## 构建、测试和运行

```bash
cmake --preset dev -S pcb-bench
cmake --build pcb-bench/build/dev -j 2
ctest --test-dir pcb-bench/build/dev --output-on-failure
python -m unittest discover -s pcb-bench/tests -p 'test_*.py'

python pcb-bench/tools/bench.py run \
  --case dataset/test/d3b/d3b_0174_sensorboard_DiffIR/case.json \
  --backend megaroute --out results/new_diffir_run \
  --toolchain pcb-bench/configs/kicad-toolchain.json \
  --kicad-python /usr/bin/python3 --expected-version 9.0.8
```

执行原生 KiCad 测试时还需设置 `KICAD_PYTHON`、`KICAD_VERSION`、
`KICAD_RUN_FROM_BUILD_DIR=1` 和指向对应构建的 `PYTHONPATH`。

新增测试覆盖零/正板边间距、凹板框、胶囊铜越界、索引与全扫描 DRC 的随机对照、
大对象索引回退、多层增量连通性与拆线重建、固定铜不可穿越、细化绕障、
最终严格修复、直接焊盘接触和重复过孔回写。

## 真实板回归与可比性

最终结果保存于仓库根目录 `results/optimization_20261116/`，包括构建身份、
每块板的内部路线/搜索事件、回写板和 KiCad 外部评分；汇总见 `summary.json`。
第一轮结果另存于 `results/optimization_20261116_v1/`，不覆盖原有结果。
完整 Python 管线验证另存于 `results/optimization_20261116_pipeline/`。

历史结果使用不同源码/二进制版本以及 60 或 300 秒预算；与新结果的耗时对比是
历史回归对照，不能视为严格控制变量的单项消融。新参数优先减少冲突并完成布线，
部分板的过孔数会增加。

外部评分新增 `evaluator.json`，标识 `direct_pad_contacts_v2` 及 worker 哈希。
USB Hub 的输入需求由历史的 59 修正为 56，与内部连接需求一致；算法之间重新
比较时，应使用同一新版评测器重评所有后端的输入/输出。
