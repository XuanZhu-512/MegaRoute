# TraceMaker external 后端

已接入固定版本 TraceMaker 0.12.1。它作为独立 CPU 可执行程序运行，不与 MegaRoute
混编，不依赖 CUDA 或 KiCad GUI。几何回读、连通率与 DRC 仍由本项目统一的
KiCad 9.0.8 工具链完成，TraceMaker 自己的摘要只作诊断。

## 本地工具

`external/TraceMaker/` 已从约 95 MB 的嵌套 Git 仓库精简为约 12 MB：

```text
bin/tracemaker          上游 CPU 布线程序
LICENSE / NOTICE        原始许可及第三方声明
manifest.json           来源、固定提交和文件哈希
source-build.tar.gz     约 759 KB 的原始 CMake/源码压缩包，供重建，不参与运行
UPSTREAM_README.md
UPSTREAM_INSTALL.txt
README.md
```

已删除 Git 元数据、测试/benchmark 数据、网站、图片、插件及未使用的 placer/viewer。
保留源码与构建定义的压缩包，解压后可用 `TM_BUILD_TESTS=OFF`、
`TM_BUILD_PYTHON=OFF`、`TM_ENABLE_CUDA=OFF` 构建 `tracemaker` 目标；依赖须另行准备。

受主项目版本管理的 `configs/tracemaker-toolchain.json` 锁定相对可执行路径、版本、
源码提交和 SHA-256。默认程序哈希或版本不匹配时拒绝运行。
`--tracemaker-exe /absolute/path` 可显式指定同版本的其他构建，此时记录实际哈希，
不会把该构建伪称为已锁定的源码提交。

换机器恢复运行包（从 MegaRoute 根目录）：

```bash
curl --fail --location --output /tmp/tracemaker-0.12.1-linux-x86_64.tar.gz \
  https://github.com/DingoOz/TraceMaker/releases/download/v0.12.1/tracemaker-0.12.1-linux-x86_64.tar.gz
python3 mega-bench/tools/install_tracemaker.py \
  --archive /tmp/tracemaker-0.12.1-linux-x86_64.tar.gz
```

安装器先验证可执行版本，再替换目录并记录哈希；已有源码仓库必须是指定提交且
无未提交改动，才会打包源码并精简。整个 external 目录由主项目 Git 忽略。

## 单板运行

从 MegaRoute 根目录执行，输出必须为空目录：

```bash
export KICAD_PYTHON=/home/xuanzhu/miniforge3/envs/pcbworld/bin/python3
"$KICAD_PYTHON" mega-bench/tools/bench.py run \
  --case dataset/D3-C/case.json \
  --backend tracemaker \
  --toolchain mega-bench/configs/kicad-toolchain.json \
  --kicad-python "$KICAD_PYTHON" \
  --expected-version 9.0.8 \
  --routing-seconds 300 --evaluation-seconds 120 \
  --out results/D3-C/run2/tracemaker
```

`run` 自行定位配套 pcbnew，并向 worker 配置模块路径，无需在终端另外设置 PYTHONPATH。

默认参数：`--tracemaker-threads 1 --tracemaker-variants 1 --tracemaker-seed 1`。
固定关闭 GPU、历史知识库和自动生成的元件规则，不改布局、层数或原有铜。
线程和变体可分别设为 1–8。内部 `--time` 会预留加载、优化和保存的时间，并按
变体批次分配；整个子进程仍受 `--routing-seconds` 硬上限约束。CPU 负载会影响
墙钟限时下的结果，这不是跨机器确定性的工作量预算。

固定的 0.12.1 没有 main README 中后来描述的自动 rescue；CLI 只加载显式给定的
配置文件。适配器不传任意上游配置，避免隐含地启用改层数、重新布局、删铜等行为。

## 批量与结果

```bash
bash dataset/D3-C/run_batch.sh tracemaker
RUN_LABEL=run2 bash dataset/D3-C/run_batch.sh tracemaker
bash dataset/D3-A/run_batch.sh tracemaker
bash dataset/D3-B/run_batch.sh tracemaker
```

三套脚本的 `all` 均包含第四后端。已有非空结果目录会跳过，使用新标签或新输出
目录再次测试。D3-C 默认输出 `results/D3-C/tracemaker/`，run2 标签输出
`results/D3-C/run2/tracemaker/`；D3-A/B 保持各自 `<case_id>/tracemaker/` 层级。
`tools/aggregate_results.py` 的算法列表已加入 TraceMaker。

标准产物：`manifest.json`、`report.html`、`routed/<原板名>.kicad_pcb`、
`evaluation/metrics.json`。原生诊断在 `work/tracemaker/`：
`summary.json`、`stdout.log`、`stderr.log` 和 `tracemaker_run.json`。
记录实际程序版本/哈希、命令、线程、变体、seed、耗时、退出码和文件保留检查。

退出码 0 和 3 分别表示上游认为全部或部分完成；只要输出有效，两者都进入统一
KiCad 评估。输入快照及规则必须不变；除新增 segment/arc/via 外，原文件所有顶层
表达式必须保留，已有固定铜不允许删除或修改。输出还须通过原生 KiCad 回读。
超时、程序错误、输出缺失和布局/网络/固定铜变化会写入错误记录并拒绝评分，
不会复制原板来伪装成布线成功。

## 实际验证

2026-11-18，修复后的 D3-C，CPU 单线程、单变体、seed=1，外部 60 秒、内部 50 秒：

- 路由和外部 KiCad 评估均完成，实际路由约 50.41 秒。
- 633 / 991 个连接完成，连通率 63.87%；2,839 段走线、391 个过孔。
- `invalid_output=false`；690 个非走线顶层表达式原样保留。
- KiCad DRC 错误数 6，均为输入中已有的封装庭院重叠；无新增铜短接错误。
- 尚未全部布通，因此 `success=false`、`clean_pass=false`。这不是全连通或制造放行证明。

验证结果位于 `results/D3-C/tracemaker/`。不同工具先前运行的时限、变体和运行时
负载不一致，该次数据仅用于接入验证，不应直接作为公平性能排名。
