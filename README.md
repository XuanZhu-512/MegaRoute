# MegaRoute — PCB Routing Algorithm Reimplementation

A research and reimplementation project based on **MegaRoute: Universal Automated Large-Scale PCB Routing Method with Adaptive Step-Size Search** (DATE 2025).

## 1. Overview

**当前架构决策（2026-11-16）：** 正式 benchmark 统一输入/输出 `.kicad_pcb`，保留配套项目规则；MegaRoute、Freerouting、KRT 共用锁定版本的外部 KiCad 评测。几何 IR 仅作为自研算法内部接口，提供 KiCad -> IR 和原板模板上的 IR 结果回写契约。当前已落地架构契约、案例快照及版本探测，转换器和正式外部评测仍待实现。详见 [`pcb-bench/docs/ARCHITECTURE.md`](pcb-bench/docs/ARCHITECTURE.md)。下文较早规划中的 JSON 输入与内部 DRC 指标仅用于几何核心开发测试，不再定义跨算法正式评测口径。

This project aims to study, reconstruct, and independently implement the MegaRoute algorithm, a universal automated PCB routing method designed for large-scale printed circuit boards (PCBs).

MegaRoute combines adaptive step-size search, shape-based obstacle detection, and routing optimization to achieve high routing completion rates while maintaining strict Design Rule Check (DRC) compliance.

**Original Paper:**

- **Title:** MegaRoute: Universal Automated Large-Scale PCB Routing Method with Adaptive Step-Size Search
- **Authors:** Haiyun Li, Jixin Zhang
- **Conference:** DATE 2025
- **DOI:** [10.23919/DATE64628.2025.10993225](https://doi.org/10.23919/DATE64628.2025.10993225)
- **IEEE Xplore:** https://ieeexplore.ieee.org/document/10993225

## 2. Research Objectives

- Develop an end-to-end, universal router for entire PCBs, including mainboards with thousands of nets, heterogeneous components, and multiple layers.
- Achieve nearly complete connectivity and DRC-compliant final routing while keeping computation practical at large scale.
- Combine the path-search capability of grid-based routing with precise geometric obstacle modeling, avoiding fixed-grid precision errors and overly restricted search spaces.
- Minimize wire length and via count while maximizing routability. The paper expresses this as `max R(P) - W(P) - V(P)`, subject to `P` satisfying design rules, given layout `L`, netlist `N`, and rules `D`.

For this reimplementation, the objective is to reconstruct and evaluate these mechanisms against the paper's reported results. Differential-pair support is identified as future work in the paper, not an established capability of MegaRoute.

## 3. Algorithm Overview

The workflow is `layout + netlist + design rules -> initialization -> route generation with geometric obstacle detection -> iterative routing optimization -> final routes`

**Adaptive step-size search.** Each net is decomposed into two-terminal searches over nodes `(x, y, z)`, where `z` is the layer. Five exploration operations generate candidates (Figure 4, Equations 2-7):

1. **Obstacle-aware exploration:** expand in eight planar directions. With wire width `w`, nearest-obstacle distance `d`, and parameter `beta`, use step `delta = w` when `d <= beta * w`, otherwise `delta = beta * w`.
2. **Axis alignment:** align with the target along the axis with the smaller absolute displacement, when both coordinate displacements are nonzero.
3. **Diagonal alignment:** adjust one coordinate so the remaining target direction is 45 degrees, when `0 < abs(abs(dx) - abs(dy)) < delta`.
4. **Layer change:** consider nodes at the same planar coordinates on other layers, using vias.
5. **End connection:** connect directly when the target is on the same layer, closer than the step size, and aligned horizontally, vertically, or diagonally.

**Shape-based obstacle detection.** Represent pins as polygons/circles, boundaries and wires as line geometry, and vias as circles. Compute geometric clearances with wire widths and radii included. Same-layer shapes belonging to different nets obstruct one another; boundaries and restricted areas also constrain routing. Each proposed wire is checked against existing geometry, and a via requires clearance checks across the layers it penetrates.

**Routing optimization.** Prioritize candidates using wire-length cost, DRC-violation cost, and layer-change cost. The A*-like length heuristic is `h = max(abs(dx), abs(dy)) + (sqrt(2) - 1) * min(abs(dx), abs(dy))`. Suppress new nodes within `d_min` of an existing node to limit search density. Iterative rerouting increases the DRC penalty using `alpha_i = L * (f(i) - f(0)) / (f(2*mu) - f(0))`, where `f(x) = 1 / (1 + exp(-k*(x-mu)))`.

Intermediate iterations can tolerate violations at a penalty; DRC-free results refer to the reported final outputs. The paper mentions path refinement but does not provide a separate detailed refinement algorithm.

### 3.1 Algorithm Specification（实现前优先冻结）

下文 **[P]** 表示论文明确给出的机制，**[E]** 表示为形成可执行规范而补充的工程约定。工程约定不代表作者实现；所有算法尚待实现。

#### 搜索状态与节点管理

**[P]** 每个网络分解为若干两端路径问题。位置状态为 `n=(x,y,z)`，起点 `s`、终点 `t`，`z` 是铜层索引。令 `dx=t.x-x`、`dy=t.y-y`、`a=abs(dx)`、`b=abs(dy)`、`q=abs(a-b)`。搜索通过当前节点到候选节点的边构成路径。论文规定：新节点距已有节点小于 `d_min` 时抑制新节点。

**[E]** 搜索上下文保存 net ID、线宽、目标、规则、不可变的本次搜索障碍快照；记录保存 `position, heading, g_length, g_drc, g_via, parent, operation, insertion_id`。`heading` 是当前层的八方向入射方向，起点和换层后的第一段为未定。同位置、同层、不同入射方向是不同状态，避免一个到达挡住另一个合法的 45° 到达。每次两端搜索清空 open/closed 和节点索引。候选先执行规则检查，再进行去重/抑制；同位置且同入射方向的较低累计代价可更新并重新入队。密度查询比较同层的所有已采样位置，不按入射方向过滤，条件为欧氏距离 `< d_min`；目标连接不受密度抑制。同一位置的不同入射方向作为同一几何采样点的不同搜索状态保留。这是为转角约束补充的工程状态管理，不是论文给出的完整状态机。队列按 `(F, h, insertion_id)` 升序，同分时固定插入顺序：八方向按东起逆时针、轴对齐、对角对齐、层号升序换层、末端连接。

终点从优先队列弹出后回溯路径；起终点相同直接判为已连接。open 耗尽仅表示在本搜索策略下未找到路径，不证明连续空间不可达。自适应采样和密度抑制不保证完备性或全局最优性。同一层相邻段的转角不超过 45°（内角至少 135°）。过孔不继承上一层的平面入射方向，下一层的第一段重新自由选向。已有同网焊盘或过孔内部的汇接不作为两条独立路径之间的平面转角；纯线段接头仍检查转角。此角度检查是工程补充，论文未给出分支、接入与细化的完整算法。

#### Adaptive Step Size 与五种探索

**[P, Eq. 2]** 当前网络线宽为 `w>0`，最近障碍距离为 `d_obstacle`：

```text
delta = w         if d_obstacle <= beta*w
        beta*w    if d_obstacle >  beta*w
```

它是两档步长，而非随距离连续插值。**[E]** 论文未精确定义该距离的参考点及是否扣除规则间距；首版取当前节点到同层异网实体铜、板边及禁布区的最小几何距离，不扣除当前线宽半径或 clearance，位于障碍内部时为 0，无障碍时为正无穷。该距离仅控制采样密度，不能替代整段 DRC。记录为 `obstacle_distance_mode=point_to_shape`。

| 探索 | 数学规则 [P] | 前提及实现注意 |
| --- | --- | --- |
| Obstacle-aware，Eq. 3 | `{(x+u,y+v,z) : (u,v) in {-delta,0,delta}², (u,v)!=(0,0)}` | 共八个候选；对角边长度为 `sqrt(2)*delta`，不是 `delta` |
| Axis alignment，Eq. 4 | `a<b` 时 `(x+dx,y,z)`；否则 `(x,y+dy,z)` | 仅当 `a>0 AND b>0`；相等时走 y 分支；论文没有要求该对齐边短于 delta |
| Diagonal alignment，Eq. 5 | `a<b` 时 `(x,y+q*sign(dy),z)`；`b<a` 时 `(x+q*sign(dx),y,z)` | 仅当 `0<q<delta`；调整后到目标的剩余方向为 45° |
| Layer change，Eq. 6 | `{(x,y,z') : z' in Z, z'!=z}` | 候选包括所有其它铜层；[E] 再按允许过孔类型和实际贯穿层筛选，不能默认只检查起止层 |
| End connection，Eq. 7 | 候选为 `t`：`dy=0` 时 `(x+dx,y,z)`；`dx=0` 时 `(x,y+dy,z)`；`a=b` 时 `(x+dx,y+dy,z)` | 要求 `z=t.z`、距离 `<delta`，且满足上述方向之一；[E] 距离采用 `sqrt(dx²+dy²)`，原文未明确范数 |

**[E]** 以上是候选生成规则，不保证候选可接受。所有平面候选，包括长轴对齐边，都要检查整条带宽线段；换层检查完整过孔。相等判断使用几何容差，候选落到目标时使用目标的原始坐标，不累积舍入误差。

#### Heuristic 与 Cost Function

**[P, Eq. 8]** 长度代价由起点到当前节点的历史线长与目标估计距离组成：

```text
h(n,t) = max(a,b) + (sqrt(2)-1)*min(a,b)
```

**[P, IV-C.1]** DRC 代价反映违规数量；换层代价通常与过孔直径成正比。论文没有给出三者相加的完整公式、单位归一化、权重数值或违规累计规则。

**[E]** 首版冻结以下组合（不是论文原公式），几何仍存 mm，成本长度单位 `u_cost=0.0254 mm`：

```text
g_length = sum(planar_edge_length / u_cost)
g_drc    = sum(number_of_unique_violation_keys_for_each_edge)
g_via    = sum(diameter_of_inserted_via / u_cost)
F_i(n)   = g_length + h(n,t)/u_cost + alpha_i*g_drc + lambda_v*g_via
lambda_v = 1
```

每条边内按 `(rule, obstacle_id, layer)` 去重；跨边重复遇到障碍仍可重复计费，因此此搜索代价不等于最终全板 DRC 数量，也会受路径分段影响。层变不增加平面线长；首版每个层变动作计一次过孔成本，最终物理过孔数另行去重。几何硬约束违规直接拒绝；仅异网铜间距违规可作为软冲突。严格模式下 `g_drc=0`，一切间距违规拒绝。不得通过米/mm 单位切换而无声改变代价权重。

#### Logistic DRC Penalty

**[P, Eq. 9]**

```text
f(x)    = 1 / (1 + exp(-k*(x-mu)))
alpha_i = L * (f(i)-f(0)) / (f(2*mu)-f(0))
L=200, k=0.4, mu=10; maximum iterations=20
```

由公式可得 `alpha_0=0`、`alpha_10=100`、`alpha_20=200`。**[E]** 原文未说明首次迭代编号；首版总共最多 20 次布线遍历，编号 `i=1..20`（`alpha_1` 约为 1.79），不额外运行第 0 轮。迭代中 alpha 固定；跨轮重建搜索状态。迭代参数改变需验证分母非零，并记录实际权重序列；不擅自把公式延伸到 `i>20` 后仍称最大权重为 L。

#### 重布线策略

**[P, IV-C.2]** 论文说明顺序布线会挤占后续网络空间，采用多轮布线，并用 Logistic 逐步增大违规惩罚。没有明确给出拆线集合、网络次序、失败回滚、历史拥塞项或完整伪代码；不能直接将 Pathfinder 的所有机制视为 MegaRoute 已定义内容。

**[E]** 首版采用以下可替换的确定性策略 `reroute_policy=conflict_nets_v1`：

1. 输入已有同网铜先构成连通分量；使用端点欧氏距离的最小生成树分解连接需求，同分按端点 ID；网络按需求总长度降序、net ID 升序排列。焊盘首版采用中心作为搜索接入点，中心须在铜内，非凸形状否则需显式接入点。
2. 第 1 轮布线全部待连接网络。每轮结束独立检查连通性和 DRC；未完成网络及所有冲突涉及的可编辑网络构成下一轮集合。板框、焊盘、固定铜、禁布区不可拆除。
3. 下一轮先同时移除选中网络的全部新增铜并更新索引，再按固定顺序重新生成剩余连接需求、逐个布线；未选网络保留。失败网络不恢复旧违规走线，保留部分成果并记录失败原因。
4. 每轮保存工作快照、最佳零违规快照及最佳诊断快照。合法解按 `(完成连接数降序, WL升序, VC升序)` 比较；诊断解按 `(完成连接数降序, DRC升序, WL升序, VC升序)` 比较。预算用尽返回合法解（可为空的新增路线）及独立标记的诊断解，不混用指标。
5. 全部需求连通且 DRC=0 时提前终止；否则直到 20 轮或预算耗尽。不宣称 Logistic 必然消除所有违规。路径细化默认关闭，后续独立评估。

### 3.2 Geometry & DRC Specification

**[P, IV-B，pp. 4-5]** 引脚用圆或多边形，走线/边界用线几何，过孔用圆；对象关联网络和层。异网且同层对象互为障碍，过孔必须检查其穿越的各层。以下实体定义、容差及检查覆盖范围是 **[E]**，将原文描述补全为平台规范。

#### 数学表示与层跨度

设圆盘 `D(c,r)={p:||p-c||<=r}`，线段 `S(a,b)={a+t(b-a):0<=t<=1}`。

| 对象 | 实体表示与属性 |
| --- | --- |
| 圆焊盘 | `D(c,r)`，net ID、pad ID、铜层集合 |
| 多边形焊盘 | 简单闭合多边形的填充区域 P；内孔显式存储；拒绝自交轮廓 |
| 走线 | 胶囊体 `S(a,b) ⊕ D(0,w/2)`，圆端帽，所属单一铜层；折线为各段实体并集 |
| 过孔 | 中心 c、外铜半径 R、钻孔半径 r、起止层及每层铜形状；间距检测保守使用外圆盘，钻孔与镀层连通属性独立保存 |
| 板框/开孔 | 可布线区域 B（外多边形减内部开孔）；边界为有限线段，不能当无限直线 |
| 禁布区 | 闭合区域 K 和适用铜层集合，与 net 无关；无网络铜按障碍处理，不视为同网 |

铜层 `Z={0,...,m-1}` 按 stackup 排序；丝印、阻焊不参与路由层编号。实体 A、B 仅在 `layers(A) ∩ layers(B)` 上检查铜间距。通孔穿越全部铜层，即使搜索仅从层 0 到层 1 也必须检查其它层；盲埋孔使用真实起止层的连续跨度，只能使用输入允许的 via type。首版生成器只用通孔；未声明的层跨度或 via 类型应报错。平面同网铜相交建立连通关系，跨层只通过明确的镀通孔/过孔连通，不能仅凭 x/y 相同判定连接。

#### Clearance 和精确窄相检查

定义 `dist(A,B)=min ||a-b||`（a、b 属于各自闭合实体）；相交或包含时为 0。规则间距 `c_req>=0` 使用 net-class 对称配对规则，未设置配对规则时取两网要求的较大值。数值容差默认 `eps=1e-6 mm`，与 `d_min=0.0254 mm` 完全独立。

| 对象对 | 几何间距计算（未截断量为负代表重叠） |
| --- | --- |
| 圆-圆 | `g=||c1-c2||-r1-r2` |
| 圆-走线 | `g=dist(c,S)-r-w/2`，投影参数钳制到 `[0,1]`，含端点和退化线段 |
| 走线-走线 | `g=dist(S1,S2)-(w1+w2)/2`，先检查交叉，再求端点到线段距离最小值 |
| 多边形-圆 | `g=dist(c,P)-r`；先执行点在填充区域内判断，不能只测轮廓边 |
| 多边形-走线 | `g=dist(S,P)-w/2`；线段与实体相交/包含时底层距离为 0 |
| 多边形-多边形 | `g=dist(P,Q)`；相交、包含先判为 0，否则取边对距离最小值 |
| 铜-板边/开孔 | 先要求整个铜实体包含于 B，再要求到 `boundary(B)` 的距离不小于板边间距 |
| 铜-禁布区 | 不得与 K 相交；若规则另设退让距离，还需 `dist(copper,K)>=c_keepout` |

铜间距使用 `max(0,g)`，其中负值不作为通用穿透深度。间距 `<c_req-eps` 判违规；落在容差带内记录边界诊断。异网实体相交或接触另报短路，即使 `c_req=0` 也不能仅靠非负距离判合格。同网间距豁免不豁免板边、禁布、线宽、钻孔等约束。数值上无法确定的临界几何应保守拒绝候选并报告，不能默认合法。

实现采用扩张 AABB / R-tree 的宽相过滤后进行上述窄相几何判断；查询框必须覆盖线宽半径和最大相关间距。这里“精确”表示检查实际实体而非栅格占用，并不宣称双精度运算具有任意精度算术保证。最终全板检查独立枚举对象关系，小案例以全量对象对检查对照索引结果，覆盖相切、包含、退化线段、长边穿障碍及过孔中间层冲突。

#### 内部 DRC 覆盖与局限

首版支持：异网铜短路/间距、最小线宽、板边/孔洞间距、禁布区、过孔尺寸/铜环下限 `(R-r)`、合法层跨度及端点连通性。断路独立计入未完成连接，不同时计作几何 DRC。固定输入的违规单列，新增或由新增铜参与的违规另列，总体零违规必须两者皆为零。

首版不支持：差分对、等长/时延、阻抗、信号完整性、回流路径、阻焊/丝印、热焊盘、自动铺铜、钻孔到钻孔/铜的完整制造约束、完整角度规则及厂商专有 DRC。圆弧/样条需后续受控转换或明确拒绝；不能静默离散化后声称原始几何精确。过孔外圆盘模型对孔内铜关系是保守近似。报告必须带 `supported_rules`、`unsupported_features` 和容差；内部 `DRC=0` 只表示受支持规则下通过。论文用 EasyEDA 评价，平台结论须在后续真实数据阶段交叉验证。

## 4. Development Environment

| Item | Reported configuration |
| --- | --- |
| Implementation language | C++ |
| Compiler/toolchain | mingw64 (MinGW64); compiler version and flags not specified |
| Operating system | Windows 11 |
| CPU / RAM | Intel Core i9-13900K / 64 GB |
| Input format | EasyEDA Pro project format; its conversion tool exports inputs for other routers |
| Evaluation tool | EasyEDA; reference [20] identifies EasyEDA Pro Edition 2.1.25 |
| Search parameters | `beta = 5`, `d_min = 1 mil` (0.0254 mm) |
| DRC optimization | `L = 200`, `k = 0.4`, `mu = 10`; maximum 20 iterations |

The paper does not specify a C++ standard, build system, third-party geometry libraries, parallelization settings, or an exact build command. These remain implementation decisions for this project.

**Evaluation dataset:** 101 real-world designs from OSHWHub, spanning 7-1564 nets, 2-6 layers, 14-3161 pins, 6-2326 connections, and 42-37845 mm². There are 93 designs below 1000 pins and 8 designs with 1011-3161 pins. Although the abstract uses broader wording, Section V-A specifies 101 designs for the reported experiment.

## 5. Project Structure

**当前实现入口：** [`pcb-bench/README.md`](pcb-bench/README.md)。代码已放在 `pcb-bench/`，提供 C++17 CLI、标准 JSON、几何/DRC、固定步长与严格 DRC 自适应搜索、测试及 Python 实验工具。下面的目录是完整目标设计；已实现范围、工程差异和待办以子目录 README 为准，Logistic 多轮重布线已接入，默认后端使用 `configs/megaroute.json`。

以下为**待实现的项目设计**，并非已经存在的代码或论文指定的工程结构。仿真平台定位为 PCB 几何布线、DRC 检查和算法实验平台，不包含电磁场或信号完整性仿真。先用合成电路板和手写标准数据跑通流程，再接入真实设计；EasyEDA 文件解析、转换和回写脚本暂不实现。

### 5.1 技术方案与模块边界

- **算法核心：** C++17 + CMake + Ninja，优先支持 Windows / MinGW64；以独立库形式实现几何、搜索、重布线和评估，命令行程序负责组织运行。先保证单线程结果可复现，性能优化依据 profiling 再推进。
- **数据与配置：** 采用版本化 JSON，计划使用 nlohmann/json；几何索引计划使用 Boost.Geometry R-tree，精确距离与碰撞判断封装在独立模块内。依赖版本在搭建阶段锁定，不依赖运行时自动下载。
- **实验与展示：** Python 负责合成案例、批量实验和统计；先用 Matplotlib 展示分层走线、过孔、障碍物及 DRC 标记，通过 JSON/事件日志回放算法过程。展示端读取核心输出，不另写一套布线逻辑；无界面模式也能完成全流程。
- **测试：** CTest + Catch2 验证 C++ 核心，Python 实验工具按需测试。内部 DRC 是平台定义规则下的检查结果，不能直接替代后续 EasyEDA 外部验证。

### 5.2 目标目录

数据统一位于与 `pcb-bench/` 并列的 `dataset/`：`dataset/test/` 存放 KiCad 测试板，`dataset/geometry-fixtures/` 存放内部 JSON 几何夹具。以下为程序模块目标，命令示例从 `pcb-bench/` 执行。

```text
MegaRoute/
├── README.md
├── CMakeLists.txt                 # 核心库、CLI、测试目标
├── CMakePresets.json              # 开发/发布构建配置
├── pyproject.toml                # 实验和可视化工具依赖
├── include/megaroute/            # 对外类型、路由器和适配器接口
├── src/
│   ├── model/                    # Board、Layer、Pad、Net、Rules、Route
│   ├── geometry/                 # 图形距离、碰撞、分层空间索引
│   ├── drc/                      # 候选检查与最终全板检查
│   ├── routing/                  # 两端连接分解、搜索状态、五类扩展、代价
│   ├── optimization/             # 冲突记录、拆线重布、惩罚调度、路径简化
│   ├── simulation/               # 场景生命周期、快照、事件、停止条件
│   ├── evaluation/               # 连通性、线长、过孔、DRC、运行开销
│   └── io/                       # 标准 JSON 读写与适配器契约
├── apps/                         # megaroute_cli 入口
├── schemas/                      # board、config、result、event 的 JSON schema
├── adapters/
│   └── easyeda/                  # 仅接口说明与映射约定；暂不写解析脚本
├── configs/                      # 基线、完整算法、消融、规模实验配置
├── tools/
│   ├── generate_cases/           # 标准格式合成板生成
│   ├── experiments/              # 批量运行、超时管理、汇总
│   └── visualization/            # 分层显示、搜索与重布线回放
├── tests/
│   ├── unit/                     # 几何、规则、候选、代价和惩罚函数
│   ├── integration/              # 输入到最终布线的确定性案例
│   └── fixtures/                 # 合法、非法、不可达及边界条件输入
├── docs/                         # 数据协议、算法映射、复现假设记录
└── results/                      # 每次运行的配置、走线、日志与指标
```

`build/` 和 `results/` 的生成内容不纳入版本控制；小型测试夹具与实验配置纳入版本控制。核心依赖方向为 `CLI / simulation -> routing / optimization -> model / geometry / drc`，评估读取模型和结果；核心不得依赖展示工具或 EasyEDA 数据字段。

### 5.3 标准数据与 EasyEDA 预留接口

标准输入 `BoardDocument` 包含 `schema_version`、单位、板框及开孔、铜层顺序、焊盘形状与所属网络、网络端点、禁布区、固定走线和过孔、线宽/间距/过孔规则。坐标统一为 mm，明确原点和轴方向；内部使用双精度几何并配置数值容差，`d_min` 与数值容差独立，不能将搜索节点抑制等同于固定网格量化。焊盘与过孔必须注明占用层/层跨度。

初期规则覆盖线宽、异网铜间距、板边间距及过孔铜环/孔径/层跨度；未支持的规则或图形必须报告，不能静默丢弃。导入时校验 ID 唯一性、网络引用、层引用、几何合法性和单位。固定输入中的违规项单独记录，避免与新增走线违规混淆。

| 接口契约（计划） | 职责 |
| --- | --- |
| `IBoardImporter.load(path, options) -> ImportResult` | 返回标准板数据、来源 ID 映射、警告及不支持项；当前仅实现标准 JSON importer |
| `IRouter.route(board, config, observer) -> RoutingResult` | 接收与 EDA 无关的模型；返回走线、未完成连接、终止原因和统计 |
| `IRouteExporter.save(result, path, options)` | 当前仅输出标准 JSON；保留未来 EasyEDA 导出扩展点 |
| `IRoutingObserver.on_event(event)` | 记录搜索、提交走线、拆线、迭代完成等事件；支持关闭或采样以控制开销 |

EasyEDA 适配器后续负责单位、层、图形、网络和规则到上述模型的映射；保留 `source_id` 与扩展元数据以便追溯和未来回写。现阶段调用未实现的 EasyEDA 适配器应明确返回 `unsupported_format`，不以空板或模拟成功替代。

一次运行输出 `board.json`（规范化输入）、`config.json`（实际生效参数）、`routes.json`、`metrics.json` 和可选 `events.jsonl`。记录随机种子、代码版本、编译配置、机器信息、输入摘要、时间/内存限制及终止状态。原始输入保持不变，动态走线支持按 net 撤销和重建索引。

## 6. Implementation Roadmap

按下列依赖顺序推进，每阶段达到验收条件后再扩展规模。本文只规划实现，不表示以下命令、接口或功能已经可用。

| 阶段 | 实现内容 | 验收条件 |
| --- | --- | --- |
| P0 工程与协议 | 建立 CMake 核心库、CLI、CTest 和 Python 工具环境；冻结首版 schema、单位和错误协议；预留 EasyEDA 接口 | 干净环境可构建和运行测试；标准 JSON 可往返读取；非法引用、未知版本及未支持格式有明确错误 |
| P1 仿真平台最小闭环 | 实现模型、合成板、场景加载、结果输出和分层可视化；可手动注入路线；建立独立连通性与 DRC 检查入口 | 无需路由算法即可完成“加载 -> 注入 -> 检查 -> 展示”；已知短路、断路、越界和间距违规被准确定位 |
| P2 几何与规则引擎 | 实现圆/多边形焊盘、带宽线段、过孔、板框/开孔、禁布区；按层索引；检查完整线段和过孔穿越层 | 覆盖相切、刚好满足间距、窄缝、斜线、多层过孔；索引结果与小规模暴力检查一致；撤销走线后无残留障碍 |
| P3 基线搜索 | 实现固定步长 A*、八方向搜索、目标连接和合法换层；确定性队列规则、父节点回溯、预算限制；先从两端网络开始 | 单层绕障、多层跨越、不可达案例结果正确；输出可由独立检查入口复核；不可达与超时可区分 |
| P4 MegaRoute 自适应搜索 | 按 Section 3 的五类探索实现候选生成；接入几何最近障碍距离、长度启发式、换层代价和 `d_min` 抑制；保留逐项开关 | 五类探索各有确定性案例；长步不能穿过薄障碍；抑制按层处理且不误删目标连接；与基线比较节点数、运行时间、连通率 |
| P5 多网络与迭代优化 | 引入多端网络分解、网络排序、动态占用、冲突归属、拆线重布和递增 DRC 惩罚；保存最佳合法解及诊断快照 | 构造需重布线的冲突案例；最多 20 轮并支持时间预算；最终全板 DRC 与连通性重算；残余违规不能标成 DRC-free |
| P6 规模与消融实验 | 完成批量运行、失败恢复、性能剖析和结果汇总；再优化空间查询、内存分配与事件记录 | 固定输入/种子可复现；输出逐板及分组指标；完整算法与三组消融共享数据、预算和计时口径；超时/失败不被丢弃 |
| P7 真实数据接入（后续） | 平台稳定后实现 EasyEDA 适配器，并接入可获取且有明确来源的真实板；外部 DRC 交叉验证 | 转换前后网络、层、单位、规则可追溯；外部检查与内部检查差异有记录；当前任务不实现该阶段脚本 |

### 6.1 搜索和重布线实现顺序

1. 将输入模型、固定障碍、动态走线分离；建立分层索引和连接需求集合。先采用确定性的多端网络生成树分解与网络排序，记录为本项目假设；对已有同网铜连通分量进行合并，避免重复计数和布线。
2. 从固定步长基线开始，再替换候选生成器为障碍感知步长、轴向对齐、对角对齐、换层和末端连接。队列优先级、同分排序、去重、节点抑制与预算均可追踪；每个候选验证完整几何，不只验证终点。
3. 将约束分为不可放宽的边界/层合法性/禁布约束和明确配置的可惩罚铜冲突。软约束模式保留冲突对象与违规量，不允许直接提交为最终合格结果；初期基线使用严格模式。
4. 实现长度、违规和换层代价及 sigmoid 惩罚调度；初始实验采用 README Section 4 的参数。代价权重、违规量定义、距离单位与迭代下标必须写入配置和假设记录，避免把自行补全的细节当作论文原实现。
5. 每轮定位受冲突影响的网络，撤销其动态铜、更新索引并重布；分别保存最佳合法结果和诊断候选。优先比较连通性，再比较线长与过孔；达到全部连接且无违规、迭代上限或资源预算时停止。超时返回部分结果与未完成原因。
6. 最后加入保持连通性和 DRC 的共线合并、冗余段/过孔消除等可选后处理；每次修改后复核。这属于项目补充方案，论文未给出完整路径细化算法，应独立开关和评价。

### 6.2 实验与验收口径

- **场景递进：** 空板两端连接 -> 单障碍/窄通道 -> 多网络争用 -> 多层过孔 -> 多端网络 -> 随机密集板 -> 真实大规模板。所有随机案例保存生成参数和种子；合成规模扫描覆盖 2/4/6 层及不同引脚、网络和障碍密度，不将合成结果称为论文数据集复现。
- **最终验证：** 由独立于搜索提交逻辑的全板检查入口重新计算电气连通性及 DRC；小案例用暴力几何检查校验空间索引。即使连接完成，存在违规时仍应报告 `completed_with_violations`；同时区分合法完成、部分完成、超时和输入错误。
- **计量：** 保存连接数分子/分母、完全连通网络数、违规类型/数量、总线长、唯一物理过孔数、节点扩展量、峰值内存和耗时。连接完成数由实际铜连通性验证，不直接使用搜索成功次数；零连接和零已布连接时的比率标为不适用。分别记录加载、路由、最终检查和展示耗时。
- **消融：** 对比固定 `1 mil` 步长、关闭代价引导、关闭 DRC 最小化与完整算法。明确关闭项保留哪些行为，例如关闭 DRC 最小化仍执行最终 DRC 检查；其它配置不变，记录与论文未明确细节有关的解释。
- **可比性：** 按 `<1000 pins` 与 `>=1000 pins` 分组，同时保留逐板结果及聚合公式；真实大板实验记录 24 小时限制。只在相同连通性和规则条件下比较线长与过孔，论文数字作为参考而非验收承诺。

平台建成后计划提供如下入口（当前不可执行）：

```text
cmake --preset dev
cmake --build --preset dev
ctest --preset dev
megaroute_cli validate --board ../dataset/geometry-fixtures/two_net.json
megaroute_cli route --board ../dataset/geometry-fixtures/two_net.json --config configs/megaroute.json --out results/demo
megaroute_cli check --board results/demo/board.json --routes results/demo/routes.json
```

**第一交付目标为 P0-P3：** 在不依赖 EasyEDA 的情况下，完成合成板输入、可视化、基线布线、DRC 和指标输出的可重复闭环。随后 P4-P6 实现与评估 MegaRoute；`docs/` 持续记录论文机制到代码模块的映射，以及网络分解、排序、代价细节、重布策略和路径细化等复现假设。

### 6.3 Reproduction & Experiment Protocol

本节所有配置为待实现协议。来源：[P] 论文 V-A/C/F（pp. 5-6）；[E] 本项目约定。实验开始前保存完整配置，实验后不得为某个方法单独改参数而保留同一实验名称。

#### 论文机制与工程假设登记

| 内容 | 论文明确部分 [P] | 本项目补全 [E] |
| --- | --- | --- |
| 搜索 | 三维位置、五类探索、Eq. 2-8、节点密度抑制 | 障碍距离参考点、末端距离范数、容差、队列排序、密度例外、入射方向状态、同方向密度抑制 |
| 成本 | 历史长度+启发式、违规数量、与直径有关的换层成本 | 完整加权公式、mil 成本单位、lambda_v、违规累计方式 |
| 优化 | 多轮布线、Logistic Eq. 9 及参数、最多 20 轮 | 首轮编号、网络/连接排序、拆线对象、回滚和最佳解管理 |
| 几何 | 对象类型、距离计算、同层异网和过孔跨层检查 | 实体包含、数值鲁棒性、规则覆盖和过孔类型模型 |
| 消融 | 固定 1 mil、去掉 Cost Guidance、去掉 DRC Minimization | 后两者的精确开关语义，论文未提供消融代码 |
| 评估 | 101 板、两组规模、指标名称、大板 24 小时限制 | 合成数据、重复次数、聚合公式、内存/节点预算及超时处理 |

假设按配置字段与版本记录在 `docs/`，任何改变都生成新的实验 ID。不能以“实现完成”代替“复现成功”；未获取原始 101 板清单和完全相同规则时，只能称机制复现与独立评估。

#### Baseline 与 Ablation 配置矩阵

共同配置：[P] `beta=5, d_min=0.0254 mm, L=200, k=0.4, mu=10`；[E] `lambda_v=1, u_cost=0.0254 mm, eps=1e-6 mm`，单线程、固定排序、路径细化关闭、通孔默认外径 0.6 mm / 孔径 0.3 mm（仅合成板；真实板遵循自身规则）。固定步长仅替换 Eq. 2；四种辅助候选仍保留，以控制变量。它不是对 Freerouting 或论文其他工具的重实现。

| 配置 ID | 步长与候选 | 搜索优先级 | DRC/重布线策略 |
| --- | --- | --- | --- |
| `baseline_fixed_strict` [E] | 固定 1 mil，保留五类候选 | `g_length+h/u_cost+lambda_v*g_via` | 严格 DRC、单次顺序遍历；作为平台基线，不是论文 Table II 的单项消融 |
| `megaroute_full` | 自适应步长、五类候选 | Section 3.1 的 `F_i` | 可惩罚异网间距、Logistic、最多 20 轮 |
| `ablation_fixed_step` | 仅将 delta 固定为 1 mil | 与 full 相同 | 与 full 相同 |
| `ablation_no_cost_guidance` | 与 full 相同 | [E] FIFO，固定候选顺序，不用 F 选择扩展节点 | 保留冲突检测、迭代和拆线；alpha 仍记录但不影响 FIFO，因此此消融也失去罚权对节点优先级的影响 |
| `ablation_no_drc_minimization` | 与 full 相同 | [E] 使用严格模式下的长度+换层成本 | 严格 DRC、仅一轮，不拆线重布；不是将 alpha 设为 0 并允许最终短路 |

后两种消融只是本项目对论文名称的明确解释，不能保证与作者代码相同；报告须保留该说明。每种模式均使用相同的最终独立检查器、相同输入和资源上限。`baseline_fixed_strict` 同时关闭两个机制，不能拿它的差值归因于单一机制。

#### 数据集生成与冻结规则 [E]

1. **确定性正确性集：** 分别建立空板、水平/对角目标、轴距离相等、`q=delta`、距离恰等于 delta、窄通道、包含关系、长步穿薄障碍、过孔中间层冲突、多端网络、固定铜、不可达、输入自带违规等案例；每例标注预期连接与违规，不依赖随机采样。
2. **规模矩阵：** `layers ∈ {2,4,6}`、两端网络数 `N ∈ {20,100,600}`、方板边长 `S ∈ {50,100} mm`、禁布面积比例 `rho ∈ {0,0.1}`；每组合使用种子 `0..9`，共 360 板。种子 `0..4` 用于开发，`5..9` 冻结为评估集，调参后不回看评估结果继续调参。另用固定夹具覆盖多端网络，避免声称本矩阵代表全部真实板特征。
3. **生成规则：** 使用固定版本 NumPy PCG64，记录版本、seed 与 schema；按 x 再 y 抽样中心坐标，均匀分布于 `[1,S-1]²` mm。生成 `2N` 个半径 0.3 mm 圆焊盘，各在顶层/底层中等概率选择；线宽 0.2 mm、铜间距及板边间距 0.2 mm、过孔尺寸见上表。按全层几何排斥放置焊盘，保证中心距至少 0.8 mm，预留区内不得放置。
4. **障碍与连线：** `rho=0.1` 时在板中心放置跨所有铜层的正方形禁布区，边长 `S*sqrt(rho)`；rho=0 时无禁布区。放置完成后用同一 RNG 打乱焊盘 ID，按相邻 ID 配成 N 个两端网络。禁止先布线成功再决定是否接纳案例，生成集不保证可布通。
5. **失败与追溯：** 每板最多尝试 `10000*N` 次焊盘采样，超限记录 `generation_failed`，不通过更换种子隐藏失败。记录所有生成参数、失败数、板面积、层/网络/引脚数、输入 SHA-256；冻结后各方法读取完全相同 JSON。合成数据不套用论文 98% 的验收目标。
6. **真实数据：** 后续清单记录来源 URL、获取日期、文件哈希、规则、许可证、转换器版本、排除原因及固定铜处理方式；不得假设 OSHWHub 任意 101 个设计就是论文原集。EasyEDA 暂留接口，不开发处理脚本。

#### 运行预算与可复现记录

| 项目 | 首版实验约定 [E，注明例外] |
| --- | --- |
| 单板墙钟预算 | 正确性集 60 秒；规模矩阵每种方法每板 3600 秒；真实大板 86400 秒（24 小时为论文设置 [P]） |
| 搜索资源 | 单次两端搜索最多扩展 1,000,000 节点；进程内存上限 8 GiB；单线程；达到限制记录具体原因，不记作已证明不可达 |
| 迭代预算 | full 与对应消融最多 20 轮，严格单轮配置 1 轮；预算从规范化输入加载后开始，包含初始化、布线及轮间检查；最终验证另计时 |
| 重复运行 | 每板每配置 3 次独立进程，关闭事件详录；报告时间中位数及范围，几何结果哈希应相同；若不同，保留全部结果并调查非确定性 |
| 环境 | 保存 CPU/RAM/OS、编译器版本、Release 编译选项、依赖版本、git commit 与工作区差异摘要；不同时运行其它基准任务 |
| 中止与恢复 | 超时/内存/节点上限/崩溃单独记录；按轮写快照；已完成实验可跳过，恢复到半途继续运行的结果另标记，不混入冷启动耗时 |

资源上限是本地评估选择，不是论文参数。最终检查若无法完成，结果为 `validation_incomplete`，不得报告 DRC=0。可增加其它预算档，但同一对照组必须共享上限且分别汇总。

#### 指标的可计算定义 [E，指标名称承接论文]

- **连接需求：** 输入固定铜连通分量经固定 MST 得到不可变的需求端点对清单 Q；`C_total=|Q|`。最终对同网实体做跨层连通性检查，Q 中两端在同一连通分量内即计一次 `C_routed`，禁止通过异网短路获得连通性；另报短路和违规数。此口径是项目约定，未验证与 EasyEDA 的连接计数完全一致。
- **Routability：** `R=C_routed/C_total`；同时报告全部端点连通的网络数/需布线网络数。若 `C_total=0`，R 为 null（不适用），不强填 1。
- **DRC：** 铜对象对按 `(rule, min(object_id), max(object_id), layer)` 去重，单对象违规按 `(rule, object_id, layer)` 去重；同一异网接触只计 short，不再重复计 clearance。一个对象对同层多处违规计一项，跨层分别计数。保存位置、测量值及规则阈值。对象分段可能影响数量，需固定规范化流程；该数值不保证等同 EasyEDA 报告条数。
- **WL：** 新增铜走线中心线总长，`sum(sqrt((x2-x1)^2+(y2-y1)^2))`，含未完成网络的已提交线段；同网同层完全重叠/共线重叠部分先规范化合并，不重复计数。过孔竖直长度不计入 WL，固定输入铜的线长单列。
- **VC：** 新增物理过孔数量，以中心、实际层跨度、类型与网络规范化去重，不能按穿越层数或搜索层变边数直接计数。固定已有过孔单列。
- **meanWL / meanVC：** 分别为 `WL/C_routed`、`VC/C_routed`；`C_routed=0` 时为 null，仍保留 WL/VC。这是项目明确采用的总量比值口径，不能由 Table I 的分组均值反推逐板定义。
- **时间与资源：** 使用单调墙钟分别记录 load、init、route（含轮间检查）、final_check、export；总流水线时间为上述之和，绘图不计入路由。论文只写 total routing time，比较时须注明计时边界差异。另报扩展节点量、峰值内存及终止原因。
- **汇总：** 逐板保存全部原始数值，再按 `<1000` / `>=1000` pins 分组；主报告采用逐板 R 的算术平均，另报 `sum(C_routed)/sum(C_total)` 加权值，二者不混用。WL、VC、meanWL、meanVC 报告逐板均值并注明 null 排除数量；时间采用每板三次中位数再做组均值。论文没有充分说明所有聚合细节，不强称该口径完全一致。
- **失败与超时：** 使用可验证的预算内最佳合法快照计算部分指标，无快照则注明缺失，不静默删样本；诊断快照另表展示。超时的运行时间属于截尾数据，单列超时率/失败率及截尾耗时，成功样本耗时均值必须注明样本数。任何线长/过孔改善都同时给出 R 与 DRC，避免因漏连而显得更优。

## 7. Evaluation Metrics

The paper evaluates metrics using EasyEDA. This project's initial internal evaluation follows Section 6.3; external EasyEDA validation is deferred. Let `C_routed` be the number of successfully routed connections and `C_total` the number of required connections.

| Metric | Definition | Desired direction |
| --- | --- | --- |
| Routability | `C_routed / C_total`; connection-based, not the fraction of fully routed nets | Higher |
| DRC | Number of design-rule violations in the routing result | Zero |
| WL | Total wire length (mm) | Lower, with comparable connectivity |
| VC | Total via count | Lower, with comparable connectivity |
| meanWL | Wire length per routed connection (mm/connection) | Lower |
| meanVC | Via count per routed connection | Lower |
| Runtime | Total routing time; reported in minutes | Lower |

Interpret length and via metrics together with routability: incomplete routing can appear cheaper simply because fewer connections were completed. Large-PCB experiments impose a 24-hour runtime limit; timed-out runs should be marked explicitly.

**Published reference results, not results of this repository** (Table I, PDF p. 6):

| MegaRoute group | Routability | DRC | meanWL (mm) | meanVC | WL (mm) | VC | Runtime (min) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pin count < 1000 | 0.9885 | 0 | 9.4917 | 0.4609 | 2718.5300 | 133 | 3.0827 |
| Pin count >= 1000 | 0.9943 | 0 | 11.2119 | 0.4151 | 10493.3533 | 453 | 46.3188 |

These are grouped results; they should not be interpreted as per-board guarantees. MegaRoute is slower than Allegro X and Altium Designer on the large-board group, despite its stronger reported routability and DRC compliance.

The eight comparison methods are Altium Designer, Allegro X, ELECTRA, EasyEDA, Freerouting, FanoutNet, Lin's algorithm, and He's algorithm. The authors reimplemented the last two because their implementations were unavailable.

**Ablation reference results** (Table II, PDF p. 6; reported averages across all cases):

| Configuration | Routability | Runtime (min) |
| --- | --- | --- |
| Without adaptive step-size (`delta = 1 mil`) | 0.9861 | 12.3002 |
| Without cost guidance | 0.9747 | 10.7732 |
| Without DRC minimization | 0.9092 | 1.3748 |
| Full MegaRoute | 0.9890 | 6.5073 |

Reproduction should report both scale groups and the three ablations, retaining per-board measurements and documenting aggregation. The paper does not fully specify the aggregation procedure for every metric in Table I.

## 8. References

1. Li, H., and Zhang, J. *MegaRoute: Universal Automated Large-Scale PCB Routing Method with Adaptive Step-Size Search*. DATE 2025.
2. Hart, P. E., Nilsson, N. J., and Raphael, B. *A Formal Basis for the Heuristic Determination of Minimum Cost Paths*. IEEE Transactions on Systems Science and Cybernetics, 1968.
3. McMurchie, L., and Ebeling, C. *Pathfinder: A Negotiation-Based Performance-Driven Router for FPGAs*. FPGA, 1995.

---

**Project Status:** Initial simulation and strict-routing prototype in `pcb-bench/`; full MegaRoute negotiation and large-scale reproduction remain in progress.
