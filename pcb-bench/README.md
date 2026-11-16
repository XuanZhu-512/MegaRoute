# pcb-bench

**最新进展：** 已实现 [KiCad 原生几何导出](docs/GEOMETRY_EXPORT.md)，并用本机
KiCad 10.0.8 验证 `dataset/test` 合成板。输出是独立的 `kicad-geometry-1.0`
结构化提取协议，尚不能直接输入旧 C++ 路由器；回写和正式外部评测仍待实现。

项目已调整为 **KiCad 输入、KiCad 输出、统一外部 KiCad 评测** 的多算法 bench。当前完成调度层契约、案例快照与版本检查，正式转换/外部路由/外部指标提取尚未接通。详细边界见 [架构说明](docs/ARCHITECTURE.md)。

现有 C++17 几何核心仍可独立运行，覆盖 **P0-P3 最小闭环及部分 P4**；其 JSON 输入、内部 DRC 和 Python 实验工具属于开发测试通道，不代表正式 KiCad benchmark 或完整 MegaRoute。

## 新的公共入口

数据统一存放于相邻的 `../dataset/`，详见 [数据说明](../dataset/README.md)。`../dataset/test/case.json` 已登记现有 KiCad 测试板；旧 JSON 夹具迁移至 `../dataset/geometry-fixtures/`，程序目录不再保留 `data/`。

```powershell
python tools/bench.py --help
python tools/bench.py doctor --toolchain configs/kicad-toolchain.json
python tools/bench.py plan --case ../dataset/test/case.json --backend freerouting --toolchain configs/kicad-toolchain.json
```

正式案例以 `configs/case.example.json` 为模板：`.kicad_pcb` 必须配套同名 `.kicad_pro`，存在 `.kicad_dru` 时必须显式声明。锁文件暂定 KiCad 9.0.8；未检测到本机 KiCad，尚未完成真实外部评测验证。`plan` 输出每个后端的阶段和未实现项，不运行算法。安装 Python 包后也可使用 `pcb-bench` 命令。

## 构建与验证

需要 CMake >=3.20、C++17 编译器和 Ninja；Python >=3.10 用于 CLI 集成测试。JSON 依赖 nlohmann/json **3.11.3** 已内置，构建不会联网下载依赖。

```powershell
cd pcb-bench
cmake --preset dev
cmake --build --preset dev
ctest --preset dev
```

Windows 若只有 MinGW Make（本机已验证的替代路径）：

```powershell
cmake -S . -B build/local -G "MinGW Makefiles" -DCMAKE_MAKE_PROGRAM=D:/Study/MSYS2/mingw64/bin/make.exe -DCMAKE_BUILD_TYPE=Release
cmake --build build/local -j 4
ctest --test-dir build/local --output-on-failure
```

MinGW 的运行时 DLL 所在目录需在 PATH 中。可视化/随机生成依赖通过 `python -m pip install -e .` 安装（锁定的 NumPy 版本要求 Python >=3.11）；纯 C++ CLI、手写夹具生成和集成测试不需要 NumPy/Matplotlib。

## 几何核心开发测试流程（内部诊断）

以下使用 Ninja 构建路径，MinGW Make 构建时将 `build/dev` 换成 `build/local`；Linux 使用无 `.exe` 后缀的入口。

```powershell
build/dev/megaroute_cli.exe validate --board ../dataset/geometry-fixtures/two_net.json
build/dev/megaroute_cli.exe route --board ../dataset/geometry-fixtures/two_net.json --config configs/baseline.json --out results/demo --events
build/dev/megaroute_cli.exe check --board results/demo/board.json --routes results/demo/routes.json
python tools/visualize.py --board results/demo/board.json --routes results/demo/routes.json --metrics results/demo/metrics.json --out results/demo/layers.png
```

输出目录必须为空，以免覆盖已有实验。退出码：`0` 表示校验通过/合法完成；`1` 表示输入、协议或运行错误；`2` 表示 DRC 违规或布线未完成。`validate` 检查输入模型与已有铜 DRC，不要求未布网络已连通。

每次 route 保存 `board.json`、生效的 `config.json`、`routes.json`、`metrics.json`，可选 `events.jsonl`。`check` 重新计算几何 DRC 和铜连通性，不信任搜索成功标志。新增路线与输入固定铜分开存储；零连接时 R 为 null。

```powershell
python tools/generate_cases.py --fixture multilayer --out results/multilayer.json
python tools/generate_cases.py --nets 20 --layers 2 --size 50 --rho 0.1 --seed 0 --out results/random.json
python tools/run_experiments.py --exe build/dev/megaroute_cli.exe --boards ../dataset/geometry-fixtures/two_net.json --configs configs/baseline.json configs/adaptive_strict.json --out results/batch --repeats 3
```

批量工具保存配置/输入/程序哈希、环境、逐次指标、路线哈希、错误与超时记录。大规模运行前应先做 profiling；当前全量几何检查偏重正确性，不适合直接执行论文规模性能比较。

## 已实现与明确边界

| 模块 | 当前状态 |
| --- | --- |
| 工程与数据 | C++ 库/CLI、CTest；版本化 mm JSON；拒绝未知字段/版本、悬空引用、非法层及自交多边形；JSON import/export 与 EasyEDA 占位接口 |
| 几何 | 圆、简单多边形焊盘、胶囊走线、通孔、非矩形板框、板内孔洞、分层禁布区；完整线段距离及包含判断 |
| DRC | 短路、铜间距、最小线宽、板边/孔洞、禁布、铜环及输入层校验；固定输入违规单列；无异网连接捷径 |
| 布线 | 固定 1 mil 基线、五类候选、长度/换层代价、节点密度抑制、目标例外、确定性优先队列、节点/记录/时间预算 |
| 自适应搜索 | `adaptive_strict` 实现两档步长，始终严格拒绝违规；它不是 `megaroute_full` 或完整论文消融 |
| 网络处理 | 固定铜连通分量、确定性 MST 需求、多端网络、顺序布线；新增相邻共线段合并 |
| 评估 | 独立全板 DRC、几何连通性、WL（同网共线重叠去重）、物理过孔数、R、meanWL/meanVC、扩展节点、耗时、失败原因 |
| 实验/展示 | 手写场景、PCG64 合成数据、独立进程重复运行与哈希记录、分层 PNG/SVG 和违规对象标红、提交事件日志 |

**尚未实现：** Logistic 多轮冲突网络拆线重布（仅公式函数及测试已实现）、FIFO/DRC 最小化消融、R-tree、8 GiB 进程内存硬限制与峰值内存统计、完整 360 板批量生成入口、聚合报告、断点恢复、事件逐步动画、EasyEDA 转换与外部 DRC。当前 `max_records` 是搜索记录数量限制，不是内存字节上限。`megaroute_full` 等未支持配置会明确报错。

输入首版限制：只生成/接收通孔；焊盘只允许单层（多层焊盘的镀通属性尚未实现）；多边形焊盘不支持内孔；不支持 net-class 配对矩阵和其它上级规范列出的高级制造/电气规则。图形和网格无关，但双精度并非任意精度计算。临界接触采用保守容差；板边距离在容差内视为接触并拒绝。拓扑端点以 pad 的 center 为接入点，非凸焊盘需显式提供铜内 center。

工程差异：首版使用全量对象对几何检查作为后续索引实现的参照；CTest 驱动独立 C++ 断言测试及 Python CLI 集成测试，尚未引入 Catch2。计时暂合并初始化与路由，不统计导出/峰值内存。布局生成/路由本身可复现，时间和元数据不参与路线哈希。

## 代码导航

```text
include/megaroute/core.hpp   公共模型、几何、路由与适配器契约
src/model.cpp               严格 JSON 解析与语义检查
src/geometry.cpp            有限线段、圆、多边形实体距离
src/drc.cpp                 全板检查、连通分量、MST 需求与指标
src/router.cpp              候选生成、基线/自适应严格搜索
apps/main.cpp               validate / route / check
schemas/                    输入和输出 JSON Schema
tests/                      数学边界测试与端到端回归
tools/                      生成、批量运行、可视化
```

下一步按上级规范推进：完善几何与支持范围回归 -> R-tree 与暴力检查对照 -> 冻结搜索代价诊断 -> 接入 Logistic 与 conflict_nets_v1 -> 完成对应消融及规模实验。新增机制必须先在小板上以最终 DRC 和连通性验证。
