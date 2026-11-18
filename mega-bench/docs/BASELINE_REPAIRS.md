# 后端修复与非评估结果清理（2026-11-18）

本次只清理没有有效外部评估的格式/加载报错及未完成流程目录。
已评估的未连通、DRC 违规结果全部保留；MegaRoute 当前没有此类报错目录，0034 保留。
D3-C FreeRouting 是 600 秒超时、无有效评估产物，单独按流程未完成清理；不能据此认定该板物理无解。

## 删除记录

| 结果目录 | 原状态 | 原因 |
|---|---|---|
| `results/D3-A/d3a_0009_SmartLaserCO2-PCB_WaterCool/freerouting` | started | No completion record |
| `results/D3-A/d3a_0009_SmartLaserCO2-PCB_WaterCool/krt` | started | No completion record |
| `results/D3-A/d3a_0012_kitspace_ir_sensor/krt` | started | No completion record |
| `results/D3-A/d3a_0017_Blink-Eras_AVR_ISP_Pogo/krt` | error | KiCad 无法重载；新增铜使用显示层名 |
| `results/D3-A/d3a_0021_RPi-PWM-Fan-interface_RPi_PWM_Fan_interface/krt` | error | KiCad 无法重载；新增铜使用显示层名 |
| `results/D3-A/d3a_0048_MySRaspiGW_MySRaspiGW/krt` | error | KiCad 无法重载；新增铜使用显示层名 |
| `results/D3-A/d3a_0049_MySRaspiGW_MySRaspiGW_PA_LNA/krt` | error | KiCad 无法重载；新增铜使用显示层名 |
| `results/D3-A/d3a_0050_MySRaspiGW_MySRaspiGW_PA_LNA_Pimoroni/krt` | error | KiCad 无法重载；新增铜使用显示层名 |
| `results/D3-A/d3a_0051_MySRaspiGW_MySRaspiGW_Pimoroni/krt` | error | KiCad 无法重载；新增铜使用显示层名 |
| `results/D3-A/d3a_0067_radio_saw_dcc6c/krt` | error | KiCad 无法重载；新增铜使用显示层名 |
| `results/D3-A/d3a_0100_smt-zvs-driver_IH10-mc/krt` | error | KiCad 无法重载；新增铜使用显示层名 |
| `results/D3-C/freerouting` | error | FreeRouting timed out after 600.0s |

## KRT

在仓库适配器中修复，不改外部 checkout：

- 回写新增 segment/via/arc 时，将源层表的 Top/Bottom、Front/Back、1_top 等显示别名映射为正式层名。未知或歧义层名明确报错。
- 从源板保留全部原有对象，仅追加新增铜；按 UUID 排除重复的既有铜，避免 KRT 把铜文字挪到丝印或改写原有对象。
- 上游 CLI 只有一个全局间距，现取已分配网络间距、板级最小值和焊盘正局部覆盖的最大值。
  这是保守约束，会使低间距网络也使用更大的间距，可能降低布通率；不宣称逐网络规则完全等价。
- 未针对其余网格搜索失败或数微米级几何误差宣称修复。原有未连通/DRC 结果仍保留，需新目录复测。

## FreeRouting

- 原有 launcher 已同时设置 `-mp` 和 `--router.stop_pass_no`，本次保留并验证其合成测试。
- 在原生 KiCad DSN 导出后，从已导出几何添加铜图形 keepout，包括铜文字笔画、填充字形及多边形内孔。
- 保持正确铜层、mm/um 比例及 Y 反向；笔画用外包胶囊多边形，避免低估障碍。
- 图形使用单独的 mrgraphics clearance class；间距规则放在 structure 层级。
  已核对锁定 2.1.0 的 Shape/Structure 解析逻辑：area 内的 rule 会被跳过，必须用 clearance_class。
- 对图形采用最大网络/板级间距，是保守处理；源 PCB 不改写。最终效果仍待原生 KiCad 重测确认。

## MegaRoute 0034 的 search_exhausted 直接原因

现有 `work/route/board.json` 的板框为 x=140..162、y=112..120。
两个失败目标中心分别为 (139.5,116)、(162.5,116)，在左右板边外各 0.5 mm。
它们的固定大焊盘跨过板边，铜的一部分确实在板内；固定输入使用 kicad_edges 策略，因此可被接受。

`search_pair` 仅以 `distance(current.p, target.a) <= eps` 作为到达终点条件；
它没有以接触目标焊盘的任意铜区域作为终止条件。候选新增走线由 `check_shape` 限制在板框内。
本例线宽 0.7 mm，中心线还需距板边至少 0.35 mm，即端点合法 x 范围约为 140.35..161.65。
所以目标焊盘中心必然无法到达；即使路径能接触焊盘在板内的部分，搜索也不会承认完成。

`search_exhausted` 是 open 队列耗尽的直接返回原因，与 node_limit、record_limit、timeout 分开。
加密采样、增加轮数或放大搜索预算不能消除上述矛盾。已有日志中末尾严格修复还有局部 timeout，
是修复阶段每对连接的局部时间预算，不改变两个中心在板外这一确定事实。
正确修复方向是目标铜区域接入（或选择板内可达的合法接入点），并让启发式、终点判断和路径回写一致。
此处记录的是原因分析时的历史状态。后续已完成通用铜区域接入修复，见 [TERMINAL_REGIONS.md](TERMINAL_REGIONS.md)；原有 12/14 结果保留，尚未用新实现重测。

## 验证与重测

只运行编译和合成/模拟单元测试，未运行数据集布线实验。新增测试覆盖 KRT 源对象保留、
层名映射、via 跨层、未知层拒绝、间距传递，以及 DSN 比例/Y 方向、图形孔、笔画和间距类。
以下命令仅供用户执行；批量脚本跳过现有非空结果，因此只会补跑清理后的 D3-A 目录：

```bash
bash dataset/D3-A/run_batch.sh krt
bash dataset/D3-A/run_batch.sh freerouting
```

已有 DRC 违规案例若要检查修复效果，应另选空输出目录，使用 README 的单例命令；不能直接覆盖保留结果。
D3-C 可执行 `bash dataset/D3-C/run_batch.sh freerouting`；默认只运行一轮 FreeRouting，以脚本参数为准。
