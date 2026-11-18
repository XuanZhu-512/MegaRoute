# D3-B 当前失败与合规修复（2026-11-18）

按标准路径 `results/D3-B/<case>/megaroute/evaluation/metrics.json` 读取：
10 例均已完成评估，3 例干净通过，7 例未全连通，共缺 18 个连接。最终原生 DRC error 全为 0。
这是本次修改前构建的结果；没有把新代码的合成测试当作数据集重测。

| 案例 | 原生完成连接 | 搜索与协商日志 |
|---|---:|---|
| 0113 Maytal | 20/20 | 干净通过 |
| 0144 ottawa_badge | 30/30 | 干净通过 |
| 0174 DiffIR | 32/32 | 干净通过 |
| 0203 MOD-MPU9150 | 31/38 | 搜索能得到 38/38；最佳诊断方案有 32 条内部违规，20 轮后输出合法子集 |
| 0232 ATtiny461Breakout | 37/38 | `Net-(IC1-Pad10)` 20 次 `search_exhausted` |
| 0260 NiMH-Charger | 42/45 | 搜索能得到 45/45；最佳诊断方案有 4 条内部违规 |
| 0288 raspberrypi_usb_hub | 55/56 | 搜索能得到 56/56；最佳诊断方案有 2 条内部违规，合法子集缺 `+3V3` |
| 0316 fancyboard | 53/55 | `Net-(D2-Pad2)` 20 次 `search_exhausted`；另有 `/BTN1` 残留冲突 |
| 0344 mavbridge | 62/64 | 搜索能得到 64/64；最佳诊断方案有 3 条内部违规 |
| 0376 cat-trainer_teensy | 65/67 | 搜索能得到 67/67；最佳诊断方案有 3 条内部违规 |

这里的诊断违规来自内部几何模型，不是最终输出的原生 DRC。
7 例均因迭代轮数用完结束，耗时约 1.2～28 秒；不是整板 300 秒预算不足。
单纯放大墙钟预算不能让已经结束的 20 轮继续进行。

## AGENTS.md 范围内的改动

当前 AGENTS.md 明确允许调整默认参数，以及对论文未指定部分作工程实现。
本次保留 `(x,y,z)` 几何节点、五类扩展、135° 约束启发式、形状距离、不同网络/铜层障碍区分、
自适应步长、线长/DRC/过孔代价及原 Logistic 公式。

### 必要对齐与密度过滤

原实现对所有新位置应用 `d_min` 过滤，可能把式（4）、（5）的必要小幅对齐也删除。
例如 0316 的失败端点 x 分别为 24.777 与 24.7777 mm，差 0.0007 mm，远小于默认 0.0254 mm；
从同一位置产生该轴向调整时，会被“距离当前节点太近”的条件过滤。
这可以解释一个确定的候选丢失问题，不能单凭这一点证明整个案例的失败只由它造成。

现对显式轴向、对角对齐及终点连接保留必要位置；普通障碍感知扩展继续按固定 `d_min` 剪枝。
精确同位置仍合并，所有候选仍经过完整 DRC 和转角检查，不引入新的扩展操作或一般性网格加密。
回归测试使用与数据集无关的端点小偏移，确认不会因小于密度阈值而失去连接能力。
这是对齐操作与密度约束交界处的工程选择，已明确记录其与“一律过滤邻近位置”的区别。

### 冲突连接的重布顺序

原实现每轮拆除双方冲突连接后，继续按相同顺序重布，可能反复生成相同的占位关系。
论文没有指定具体冲突调度顺序。现只在需要重布的连接集合内作确定性轮换，保留非冲突铜。
这不增加历史代价、不修改搜索公式，也不放宽最终 DRC。

配置项 `routing_order` 支持 `fixed` 与 `rotate_conflicts`，默认后者。
合成相交连接测试验证相邻两轮优先级确实轮换，最终合法性检查仍有效。

### 参数重测配置

`configs/megaroute.json` 仍保留论文数值 `L=200,k=0.4,mu=10,max_iterations=20`。
新增 `configs/megaroute-drc.json`，仅改变三个允许调整的参数：

- `L=1000`，提高后期违反间距的代价；
- `mu=20`、`max_iterations=40`，仍使用相同 Logistic 公式，并在第 40 轮达到设定的 L；
- beta、d_min、线宽、间距、过孔及核心搜索机制不变。

此配置尚未在数据集运行，不能承诺 7 例全部通过。
可以先用默认配置隔离代码修复效果，再换参数配置比较。
没有改动外部路由器，也没有按案例 ID 添加算法分支。

## 验证与重测命令

编译和 15 项 CTest 通过，新增对齐与调度回归测试通过。没有运行数据集实验，未删除或覆盖原结果。

在仓库根目录执行，只重测这 7 例到新目录：

```bash
cmake --build mega-bench/build/dev -j 2
export KICAD_RUN_FROM_BUILD_DIR=1
export PYTHONPATH="$PWD/external/kicad-9.0.8/pcbnew${PYTHONPATH:+:$PYTHONPATH}"
config_file="${MEGAROUTE_CONFIG:-mega-bench/configs/megaroute.json}"
run_root="results/D3-B/megaroute-recheck-$(date +%Y%m%d-%H%M%S)"
for id in 0203 0232 0260 0288 0316 0344 0376; do
  for case_file in dataset/D3-B/d3b_"${id}"_*/case.json; do
    case_dir="${case_file%/case.json}"
    "${BENCH_PYTHON:-python3}" mega-bench/tools/bench.py run \
      --case "$case_file" --backend megaroute \
      --out "$run_root/${case_dir##*/}/megaroute" \
      --toolchain mega-bench/configs/kicad-toolchain.json \
      --kicad-python "${KICAD_PYTHON:-/usr/bin/python3}" --expected-version 9.0.8 \
      --router mega-bench/build/dev/megaroute_cli --config "$config_file" \
      --routing-seconds 600 --evaluation-seconds 120
  done
done
python mega-bench/tools/aggregate_results.py "$run_root"
```

测试更强 DRC 惩罚时，先设置 `export MEGAROUTE_CONFIG=mega-bench/configs/megaroute-drc.json`，
再运行上面的命令，使用另一个新目录。
该目录仅含 7 个失败案例，汇总不能当作全部 10 块板的总体平均。
