# KiCad-first benchmark architecture

本文件是当前架构决策。上级 README 中更早的“JSON 为平台输入”“内部 DRC 作为实验评分”等描述，现仅适用于几何核心开发测试。正式跨算法比较以本文件为准。

## 1. 公共输入和输出

所有后端接受同一份准备好的 KiCad 案例，输出 routed `.kicad_pcb`。案例包含同名 `.kicad_pro`、存在时必需的 `.kicad_dru`；不能仅复制板文件后使用默认规则。原始输入只读，运行使用副本，保留文件名和哈希。

```text
KiCadCase (.kicad_pcb + .kicad_pro + optional .kicad_dru)
  |
  +-- MegaRoute: KiCad -> GeometryIRBundle -> C++ router -> KiCad
  +-- Freerouting: KiCad -> DSN -> Java router -> SES -> KiCad
  +-- KRT: KiCad -> KiCadRoutingTools -> KiCad
  |
  v
preservation checks -> ONE pinned KiCad external evaluator -> benchmark metrics
```

`krt` 明确表示 KiCadRoutingTools，不等同于 KiCad 自带交互 push-and-shove 引擎；后者若引入，使用独立 backend ID。本阶段不接入 EasyEDA 或其它源格式。

正式管线不强迫 Freerouting/KRT 经过几何 IR。DSN/SES 是后端私有中间文件。Geometry IR 是自研几何算法的内部接口，也可用于开发调试，不能替代 KiCad 作为正式评测输入/输出。

## 2. 已落地的模块边界

```text
python/pcb_bench/
  contracts.py     KiCadCase / GeometryIRBundle / RouterBackend / KiCadEvaluator
  cases.py         案例路径校验、规则文件检查、不可变快照、文件哈希
  converters.py    KiCad <-> IR 双向契约；当前明确抛出未实现错误
  backends.py      megaroute / freerouting / krt 后端身份、执行阶段及阻塞项
  evaluation.py    KiCad 精确版本探测、DRC 命令构造、外部评分接口
  pipeline.py      公共执行计划；适配器完成前 executable=false
  cli.py           plan / snapshot / doctor
src/               现有 C++ 几何与布线核心，内部 DRC 保留
schemas/           原有 geometry IR、routes 和内部诊断协议
configs/           公共 case 模板、KiCad 版本锁、算法内部配置
data/kicad/        正式案例入口（当前没有真实板夹具）
data/synthetic/    旧 JSON 几何测试夹具，不作为跨工具正式数据集
```

不移动/重写已验证的 C++ 文件；Python 调度层与 C++ 算法层通过文件和子进程边界连接。Python 包支持安装入口 `pcb-bench`，也可直接运行 `python tools/bench.py`。

## 3. 双向转换契约

`import_board(case, workdir) -> GeometryIRBundle` 必须产生：

- `board_ir`：可交给 C++ 几何核心的模型；现有 v1 JSON 为起点，不声称已覆盖任意 KiCad 板。
- `source_map`：IR ID 到 KiCad UUID 的映射，网络名称/编号、层索引/名称映射，坐标单位/轴向约定。
- `conversion_report`：转换器与 KiCad 版本、支持特性、拒绝项、有损转换及原因。
- `source_case` 和 `source_hashes`：保留原板模板和精确来源，防止把一个板的路线回写到另一个板。

`export_routes(bundle, result, workdir) -> RoutedKiCadCase` 在原始板副本上应用新增路线，不能从精简 IR 重建整块 PCB 而丢失封装、文本、阻焊、规则及其它未建模信息。必须验证网络/层/UUID 引用及源哈希。

第一版只允许 `preserve_input`：已有铜全部固定，路由结果只追加铜。把已完成板变为未布线板是单独、版本化、所有算法共享的离线准备步骤。之后如需允许重布既有铜，升级契约，显式定义 editable UUID 集合与删除/修改操作，不让外部工具隐式获得不同自由度。

转换器验收：无修改往返后，焊盘、封装位置、网络、层叠、板框、固定铜和规则保持等价；新增走线能被锁定版本 KiCad 重新打开；unsupported 特性明确拒绝，不能静默丢弃。冻结 round-trip fixtures 后才接入官方算法比较。

## 4. 统一外部评测

`KiCadEvaluator.evaluate(original, routed, ...)` 同时接收初始板和结果板。所有后端使用同一个评测器和同一个工具链锁文件，算法配置不能选择其它评分工具。

- KiCad DRC 保存原始 JSON；按统一 severity/exclusion 政策解析，error、warning、excluded 和 unconnected 分开记录。
- 连接率的基准由**输入板的 KiCad 连通性**生成并冻结；最终连接率也从 KiCad 提取。不把 DRC 的未连接提示条数未经验证直接等同于缺失 MST 连接数。
- WL/VC 从 KiCad 加载后的板对象提取，按原始 UUID 区分固定铜与新增铜。CLI DRC 报告本身不是完整 WL/VC/连接率接口；还需要同版本 `pcbnew` 或独立 KiCad engine worker，保持所有算法共用。
- 正式 `metrics.json` 只来自外部 KiCad。现有 C++ `mr::evaluate` 与 `tools/run_experiments.py` 的结果标记为 `internal_geometry_diagnostics`，用于搜索/回归；不能补齐外部指标缺失值。
- 输入/输出不变量检查失败标记 `invalid_output`；工具不存在、版本不符、格式不支持、超时、解析失败、评分不完整分别记录。没有外部评分就不产生正式成功指标。
- 统一记录 prepare、route、export、evaluate 和 total 耗时。路由预算与评测预算分离，工具版本/线程/内存设置写入 manifest。

DRC 命令构造参考：

```text
kicad-cli pcb drc --format json --units mm --severity-all --all-track-errors --exit-code-violations --output drc.json routed.kicad_pcb
```

`--exit-code-violations` 下 5 表示发现违规，不能误判为工具崩溃；0 表示该命令未发现违规，仍不能证明全部网络已连通或全部评测步骤完成。原理图 parity 不在当前 PCB-only 范围。铺铜填充策略、exclusion 处理、DRC severities 和连接率具体实现需在 evaluator 完成时冻结，不能各算法自行选择。

## 5. 版本锁与运行目录

`configs/kicad-toolchain.json` 暂定 **9.0.8**（对齐此前参考的 PCBWorld engine 版本），是待部署目标，不表示本机已安装或本项目已验证该版本。部署时可整体调整为确定可用的补丁版本，然后所有后端及转换/评分 worker 一起锁定，不能在同一实验内混用。

`doctor` 使用 `kicad-cli version` 精确匹配 `major.minor.patch`，记录可执行文件 SHA-256。后续 worker 要同时检查 `pcbnew`/engine 版本、构建信息和依赖镜像/包锁；当前 executable hash 不是整个运行环境的完整锁。缺少工具直接报错，无默认版本回退。

目标输出目录（当前仅输入 snapshot 和执行 plan 已实现）：

```text
results/<run>/
  manifest.json          案例、版本、预算、哈希、阶段状态
  input/                 原始 KiCad 项目快照
  work/                  私有 IR / DSN / SES、source map、转换报告
  routed/                最终同名 .kicad_pcb + 项目规则
  evaluation/            KiCad 原始报告、正式 metrics.json
  diagnostics/           内部 DRC、搜索日志，不作为 benchmark 评分
```

## 6. 使用与后续顺序

```powershell
python tools/bench.py --help
python tools/bench.py doctor --toolchain configs/kicad-toolchain.json
python tools/bench.py plan --case path/to/case.json --backend megaroute --toolchain configs/kicad-toolchain.json
python tools/bench.py snapshot --case path/to/case.json --out results/my-run/input
```

`case.example.json` 是路径模板，不捏造可用的真实 KiCad 板。`plan` 只检查案例文件契约，不做 PCB 语义解析、路由或评分。当前不提供容易误用的正式 `run` 命令；三个 backend 和完整 evaluator 尚未接通，preflight 明确返回未实现。

实现顺序：① 锁定本机 KiCad/worker 工具链和真实夹具；② 外部基线测量及 DRC/指标提取；③ KiCad -> IR 与原板回写的 round-trip 测试；④ 包装现有严格几何路由器作为明确命名的开发基线，再接完整 MegaRoute；⑤ DSN/SES 与 Freerouting；⑥ KRT；⑦ 同板同规则对照实验。

参考：[KiCad 9 CLI 文档](https://docs.kicad.org/9.0/en/cli/cli.html)，[PCBWorld 参考版本](https://github.com/LGAI-Research/PCBWorld/tree/57738250415db0d409f44aca36dd43af25432971)。本次未移植 PCBWorld 源代码或安装外部布线工具。
