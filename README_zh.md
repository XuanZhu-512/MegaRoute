# MegaRoute

<p>
  <a href="./README_en.md"><img alt="English" src="https://img.shields.io/badge/English-555?style=for-the-badge"></a>
  <a href="./README_zh.md"><img alt="中文" src="https://img.shields.io/badge/中文-1f6feb?style=for-the-badge"></a>
</p>

PCB 布线 benchmark，以及 MegaRoute 算法的复现。各路由器读取同一块 KiCad 板，写出布线后的 `.kicad_pcb`，并由同一套锁定版本的 KiCad 评分。

## 1. 简介

本仓库在未布线的 KiCad 板上比较自动布线器。一个案例包含 `.kicad_pcb` 与同名 `.kicad_pro`；案例声明了 `.kicad_dru` 时一并使用。原有铜保持不动。指标来自 KiCad 9.0.8，不采用各路由器自带的摘要。

**数据集**

| 划分 | 板数 | 用途 |
| --- | ---: | --- |
| D3-A | 99 | PCBWorld `easy.test` |
| D3-B | 10 | PCBWorld `medium.test` |
| D3-C | 10 | PCBWorld `hard.test` |
| Tier-D | 22 | PCBench 较难的一组板 |

**布线算法**

- **MegaRoute**：仓库内按论文核心机制实现的 C++ 布线器（自适应步长、形状检查、迭代 DRC 最小化）。
- **FreeRouting** 2.1.0：外部 Java 布线器，经 Specctra DSN/SES 接入。
- **KRT**：[KiCadRoutingTools](https://github.com/drandyhaas/KiCadRoutingTools)。
- **TraceMaker** 0.12.1：外部 CPU 布线器。D3-A、D3-B、D3-C 已评完；Tier-D 的 22 块板见第 5 节，其中两块没有布线结果，按失败计入。

**配套工具**

- KiCad 9.0.8 的 `kicad-cli` 与 `pcbnew`：几何导出、走线回写、DRC、连通性、线长和过孔统计。运行副本在 `external/kicad-9.0.8/`。
- FreeRouting 需要 Java 21+（`external/freerouting/`）。
- KRT 需要 NumPy、SciPy、Shapely（`external/KiCadRoutingTools/`）。

## 2. MegaRoute 算法

MegaRoute 按论文第 IV 节保留自适应步长、五类候选扩展、形状障碍检测、代价引导和迭代 DRC 最小化。

- 近障碍步长为 `w`，远处为 `beta*w`，默认 `beta=5`；节点密度固定为 `d_min=1 mil`。
- 候选包括八方向平面扩展、轴向对齐、45° 对齐、换层及直接终点连接。
- 启发式使用论文的八方向距离；代价包含线长、DRC 和过孔，不加入历史拥塞项。
- Logistic 参数恢复为 `L=200,k=0.4,mu=10`，最多 20 轮；不再停滞加密或追加严格修复搜索。
- 焊盘中心合法时直接使用；否则在实际铜区域选取每层一个固定合法接入点，再执行点到点搜索。
- 保留带孔铜多边形、铜文字、板框和间距适配；最终输出只保留合法铜，线长与过孔仅统计新增部分。

论文机制、工程实现边界、测试及重测命令见[论文核心对齐说明](mega-bench/docs/PAPER_FIDELITY.md)。

## 3. 项目架构

```text
MegaRoute/
├── README_en.md
├── README_zh.md
├── dataset/
│   ├── D3-A/                 # 99 个案例：case.json + .kicad_pcb + .kicad_pro
│   ├── D3-B/                 # 10 个案例
│   ├── D3-C/                 # 10 个案例
│   └── Tier-D/               # 22 个案例
├── mega-bench/
│   ├── apps/main.cpp         # megaroute_cli：validate / route / check
│   ├── include/megaroute/
│   ├── src/                  # 模型、几何、空间索引、DRC、布线器
│   ├── python/pcb_bench/     # 案例读写、四个后端、KiCad 评分
│   ├── tools/                # bench.py、汇总、可视化
│   ├── configs/              # megaroute.json，以及 KiCad、TraceMaker 版本锁
│   ├── schemas/
│   ├── tests/
│   ├── adapters/easyeda/     # 仅保留接口；导入未实现
│   └── third_party/nlohmann/
├── external/                 # KiCad、FreeRouting、KRT、TraceMaker（不入库）
└── results/                  # 布线板、报告、evaluation/metrics.json
```

`mega-bench/build/` 与 `results/` 为生成目录。`external/` 是本机工具链，已被 Git 忽略。

## 4. CLI

在仓库根目录执行。`BACKEND` 取 `megaroute`、`freerouting`、`krt`、`tracemaker` 或 `all`。结果目录非空时会跳过。

```bash
bash dataset/D3-A/run_batch.sh megaroute
bash dataset/D3-B/run_batch.sh freerouting
bash dataset/D3-A/run_batch.sh all
```

单块板：

```bash
python mega-bench/tools/bench.py run \
  --case dataset/D3-B/d3b_0113_maytal_Maytal/case.json \
  --backend megaroute \
  --out results/D3-B/d3b_0113_maytal_Maytal/megaroute \
  --toolchain mega-bench/configs/kicad-toolchain.json \
  --kicad-python "${KICAD_PYTHON:-python3}" \
  --expected-version 9.0.8 \
  --routing-seconds 600 \
  --evaluation-seconds 120
```

输出目录必须为空。分数在 `evaluation/metrics.json`。`KICAD_PYTHON` 需要能导入锁定的 `pcbnew` 9.0.8。KRT 另需 NumPy、SciPy、Shapely；FreeRouting 需要 `PATH` 中有 `java`。

MegaRoute 超参数可以直接追加到上方单板示例的 `bench.py run` 命令。D3-A/B/C 批处理脚本也支持在 `megaroute` 或 `all` 后追加这些选项；选择 `all` 时，追加选项只传给 MegaRoute。已有非空结果目录会跳过；可用 `RESULTS_ROOT` 指定独立输出根目录（默认 `results/`）。

```bash
# D3-C：使用独立目录保存调参结果
RESULTS_ROOT="$PWD/results/tuning-beta2" bash dataset/D3-C/run_batch.sh megaroute \
  --megaroute-beta 2 \
  --megaroute-penalty-l 1000 \
  --megaroute-max-iterations 100 \
  --megaroute-time-limit-s 3600 \
  --routing-seconds 3630
```

优先级为：命令行覆盖值 > `--config` 指定的配置（默认 `mega-bench/configs/megaroute.json`）。未指定的参数沿用配置值，不会改写原配置文件。最终生效参数记录在 `work/effective_config.json` 和 manifest 的 router identity 中。内部时限仍受外部 `--routing-seconds` 约束，并预留最多 10 秒保存结果，因此长时间运行需同时提高两个时限。

| 命令行选项 | JSON 字段 | 允许值 |
| --- | --- | --- |
| `--megaroute-beta` | `beta` | ≥ 1 |
| `--megaroute-d-min-mm` | `d_min_mm` | ≥ 0，单位 mm |
| `--megaroute-lambda-v` | `lambda_v` | ≥ 0 |
| `--megaroute-time-limit-s` | `time_limit_s` | > 0，单位秒 |
| `--megaroute-max-iterations` | `max_iterations` | 整数 1–100 |
| `--megaroute-max-expanded-nodes` | `max_expanded_nodes` | 整数 1–10000000 |
| `--megaroute-max-records` | `max_records` | 整数 1–10000000 |
| `--megaroute-penalty-l` | `penalty_L` | > 0 |
| `--megaroute-penalty-k` | `penalty_k` | > 0 |
| `--megaroute-penalty-mu` | `penalty_mu` | > 0 |
| `--megaroute-routing-order` | `routing_order` | `fixed`、`rotate_conflicts` |

Tier-D 的 MegaRoute 长预算重测使用 `--config mega-bench/configs/megaroute-tier-d.json --routing-seconds 1210`：内部布线时限为 1200 秒（20 分钟），最多 100 轮，外层额外留 10 秒用于最终检查和结果保存。其余搜索参数与默认配置一致，DRC 惩罚公式及参数不变。仅提高预算不会解除 `input_drc_violations` 阻塞，也不会提高单次搜索的节点/记录上限。默认 `megaroute.json` 保持不变。

MegaRoute 二进制（`megaroute` 或 `all` 时，D3 批量脚本会自行编译）：

```bash
cmake -S mega-bench -B mega-bench/build/dev -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build mega-bench/build/dev -j 2
```

## 5. 对比

下表是各板 `evaluation/metrics.json` 的不加权平均。没有完成评测的板不计入，也不补 0。`n` 为计入的板数 / 该划分板数。D3-A、D3-B、D3-C 上四个算法均已评完当前全部板。Tier-D 上还没有完成评测的算法先留空。Tier-D 的 MegaRoute 有 8 块板因输入 DRC 在布线前停止，这 8 块不计入该行。TraceMaker 在 Tier-D 有两块板没有写出布线结果，这两块按失败计入：连通率、新增铜、过孔和 DRC 记为 0，时间用该次进程记录的耗时。

Success 表示每个网络都收成一个焊盘组，且原有焊盘仍在。Routability 是完成连接数除以需求连接数，再对板取平均。Clean pass 表示 Success 且 KiCad DRC error 为 0，警告可以存在。线长和过孔只计新增铜。连通率更低时，更短的线长并不表示更好。

### D3-A（99 块板）

| 算法 | n | Success | Routability | Clean pass | 线长 (mm) | 过孔 | DRC error | 时间 (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MegaRoute | 99/99 | 0.9899 | 0.9990 | 0.9899 | 142.41 | 3.22 | 0.00 | 0.20 |
| FreeRouting | 99/99 | 0.8788 | 0.9759 | 0.8485 | 152.23 | 0.94 | 0.06 | 8.71 |
| KRT | 99/99 | 0.7980 | 0.9192 | 0.6768 | 141.55 | 3.84 | 0.58 | 1.10 |
| TraceMaker | 99/99 | 0.9899 | 0.9949 | 0.9899 | 144.53 | 1.89 | 0.00 | 0.59 |

### D3-B（10 块板）

| 算法 | n | Success | Routability | Clean pass | 线长 (mm) | 过孔 | DRC error | 时间 (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MegaRoute | 10/10 | 1.0000 | 1.0000 | 1.0000 | 495.08 | 17.30 | 0.00 | 1.31 |
| FreeRouting | 10/10 | 0.8000 | 0.9895 | 0.8000 | 531.64 | 3.50 | 0.00 | 15.17 |
| KRT | 10/10 | 0.4000 | 0.7490 | 0.1000 | 398.78 | 10.00 | 2.20 | 2.71 |
| TraceMaker | 10/10 | 1.0000 | 1.0000 | 1.0000 | 503.43 | 11.10 | 0.00 | 8.75 |

### D3-C（10 块板）

| 算法 | n | Success | Routability | Clean pass | 线长 (mm) | 过孔 | DRC error | 时间 (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MegaRoute | 10/10 | 0.8000 | 0.9776 | 0.8000 | 1214.91 | 71.20 | 0.00 | 142.03 |
| FreeRouting | 10/10 | 0.2000 | 0.8789 | 0.2000 | 1243.01 | 21.20 | 0.00 | 18.11 |
| KRT | 10/10 | 0.0000 | 0.5419 | 0.0000 | 753.88 | 38.20 | 1.50 | 4.64 |
| TraceMaker | 10/10 | 0.9000 | 0.9940 | 0.9000 | 1268.48 | 55.40 | 0.00 | 249.82 |

### Tier-D（22 块板）

| 算法 | n | Success | Routability | Clean pass | 线长 (mm) | 过孔 | DRC error | 时间 (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MegaRoute | 14/22 | 0.3571 | 0.9341 | 0.0000 | 7139.26 | 247.71 | 524.14 | 706.27 |
| FreeRouting | 12/22 | 0.0833 | 0.9473 | 0.0000 | 6149.66 | 90.42 | 338.08 | 209.30 |
| KRT |  |  |  |  |  |  |  |  |
| TraceMaker | 22/22 | 0.3636 | 0.8870 | 0.0455 | 6546.58 | 205.27 | 1477.68 | 379.51 |

## 6. 参考文献

1. Haiyun Li, Jixin Zhang. *MegaRoute: Universal Automated Large-Scale PCB Routing Method with Adaptive Step-Size Search*. DATE 2025. [doi:10.23919/DATE64628.2025.10993225](https://doi.org/10.23919/DATE64628.2025.10993225).
2. KiCad. <https://www.kicad.org/>.
3. FreeRouting. <https://github.com/freerouting/freerouting>.
4. Andrew Haas. KiCadRoutingTools. <https://github.com/drandyhaas/KiCadRoutingTools>.
5. TraceMaker. <https://github.com/DingoOz/TraceMaker>.
