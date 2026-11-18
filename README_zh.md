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
| D3-C | 1 | 修复后的 EasyEDA 导入板，用于检查整条流程 |

**布线算法**

- **MegaRoute**：仓库内的 C++ 布线器（自适应步长、协商重布、严格修复）。
- **FreeRouting** 2.1.0：外部 Java 布线器，经 Specctra DSN/SES 接入。
- **KRT**：[KiCadRoutingTools](https://github.com/drandyhaas/KiCadRoutingTools)。
- **TraceMaker** 0.12.1：外部 CPU 布线器。D3-A、D3-B 均已评测，结果见第 5 节。

**配套工具**

- KiCad 9.0.8 的 `kicad-cli` 与 `pcbnew`：几何导出、走线回写、DRC、连通性、线长和过孔统计。运行副本在 `external/kicad-9.0.8/`。
- FreeRouting 需要 Java 21+（`external/freerouting/`）。
- KRT 需要 NumPy、SciPy、Shapely（`external/KiCadRoutingTools/`）。

## 2. MegaRoute 算法

MegaRoute 把每个两端连接放在 `(x, y, 层)` 上搜索，并用基于形状的间距检查决定候选是否可接受。

- 步长只有两档：最近障碍距离不超过 `beta * w` 时 `delta = w`，否则 `delta = beta * w`（`beta = 5`）。
- 当前节点可以做八方向平面扩展、轴向对齐、45° 对齐、换层打过孔，以及直接连到终点。
- 代价包括已走线长、到实际目标铜区域的距离启发、过孔代价，以及随轮次上升的 Logistic 间距惩罚，最多 20 轮。
- 冲突连接成组拆线后重布；停滞时加入历史拥塞并加密采样。最后一轮拒绝剩余违规。
- 固定焊盘、板框和禁布区是硬约束。报告中的线长和过孔只统计本次新增的铜。
- 铜多边形支持外环和内孔，间距与连通性按实际铜区域计算。见[设计与重测命令](mega-bench/docs/COPPER_POLYGON_HOLES.md)。
- 起终点按合法焊盘铜区域接入，不再强制经过标称中心。见[接入模型与测试](mega-bench/docs/TERMINAL_REGIONS.md)。

## 3. 项目架构

```text
MegaRoute/
├── README_en.md
├── README_zh.md
├── dataset/
│   ├── D3-A/                 # 99 个案例：case.json + .kicad_pcb + .kicad_pro
│   ├── D3-B/                 # 10 个案例
│   └── D3-C/                 # 一块修复后的板
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

MegaRoute 二进制（`megaroute` 或 `all` 时，D3 批量脚本会自行编译）：

```bash
cmake -S mega-bench -B mega-bench/build/dev -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build mega-bench/build/dev -j 2
```

## 5. 对比

下表是各板 `evaluation/metrics.json` 的不加权平均。没有完成评测的板不计入，也不补 0。`n` 为已完成评测数 / 该划分板数。D3-A 上四个算法均已评完全部 99 块板。FreeRouting、KRT 的 D3-A 平均按当前全部评测重算；D3-B 上这两项与此前 10 块板的结果一致。

Success 表示每个网络都收成一个焊盘组，且原有焊盘仍在。Routability 是完成连接数除以需求连接数，再对板取平均。Clean pass 表示 Success 且 KiCad DRC error 为 0，警告可以存在。线长和过孔只计新增铜。连通率更低时，更短的线长并不表示更好。

### D3-A（99 块板）

| 算法 | n | Success | Routability | Clean pass | 线长 (mm) | 过孔 | DRC error | 时间 (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MegaRoute | 99/99 | 0.9899 | 0.9986 | 0.9899 | 144.01 | 3.87 | 0.00 | 1.04 |
| FreeRouting | 99/99 | 0.8788 | 0.9759 | 0.8485 | 152.23 | 0.94 | 0.06 | 8.71 |
| KRT | 99/99 | 0.7980 | 0.9192 | 0.6768 | 141.55 | 3.84 | 0.58 | 1.10 |
| TraceMaker | 99/99 | 0.9899 | 0.9949 | 0.9899 | 144.53 | 1.89 | 0.00 | 0.59 |

### D3-B（10 块板）

| 算法 | n | Success | Routability | Clean pass | 线长 (mm) | 过孔 | DRC error | 时间 (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MegaRoute | 10/10 | 1.0000 | 1.0000 | 1.0000 | 497.04 | 20.10 | 0.00 | 5.41 |
| FreeRouting | 10/10 | 0.8000 | 0.9895 | 0.8000 | 531.64 | 3.50 | 0.00 | 15.17 |
| KRT | 10/10 | 0.4000 | 0.7490 | 0.1000 | 398.78 | 10.00 | 2.20 | 2.71 |
| TraceMaker | 10/10 | 1.0000 | 1.0000 | 1.0000 | 503.43 | 11.10 | 0.00 | 8.75 |

## 6. 参考文献

1. Haiyun Li, Jixin Zhang. *MegaRoute: Universal Automated Large-Scale PCB Routing Method with Adaptive Step-Size Search*. DATE 2025. [doi:10.23919/DATE64628.2025.10993225](https://doi.org/10.23919/DATE64628.2025.10993225).
2. KiCad. <https://www.kicad.org/>.
3. FreeRouting. <https://github.com/freerouting/freerouting>.
4. Andrew Haas. KiCadRoutingTools. <https://github.com/drandyhaas/KiCadRoutingTools>.
5. TraceMaker. <https://github.com/DingoOz/TraceMaker>.
