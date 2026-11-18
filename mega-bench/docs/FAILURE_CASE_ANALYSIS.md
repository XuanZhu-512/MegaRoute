# 现有失败案例分析（2026-11-18）

D3-A/B 的 MegaRoute 结果现已全部清理，等待论文核心修正版重测；本文件为历史分析记录，见 [PAPER_FIDELITY.md](PAPER_FIDELITY.md)。

清理前的历史快照；其中无有效评估的 12 个目录现已删除，详见 [BASELINE_REPAIRS.md](BASELINE_REPAIRS.md)。下文路径可能对应已清理的旧产物。

范围：D3-A 99 例、D3-B 10 例；只读取现有结果，未重跑实验。以逐例 manifest 和 evaluation/metrics.json 为准，旧 failure_analysis.json 和 README 汇总可能滞后。D3-C 不计入本表。

通过定义：全部连接完成且原生 KiCad DRC error 为零。manifest complete 仅表示流程完成；未完成评估不能当作已证实的布线失败。

| 划分 | 算法 | 已评估 | 干净通过 | 未全连通 | 有 DRC 错误 | 未评估 |
|---|---|---:|---:|---:|---:|---:|
| D3-A | freerouting | 98 | 83 | 12 | 3 | 1 |
| D3-A | krt | 89 | 63 | 15 | 12 | 10 |
| D3-A | tracemaker | 99 | 98 | 1 | 0 | 0 |
| D3-A | megaroute | 99 | 98 | 1 | 0 | 0 |
| D3-B | freerouting | 10 | 8 | 2 | 0 | 0 |
| D3-B | krt | 10 | 1 | 6 | 4 | 0 |
| D3-B | tracemaker | 10 | 10 | 0 | 0 | 0 |
| D3-B | megaroute | 10 | 10 | 0 | 0 | 0 |

未全连通和 DRC 错误可重叠，不能直接相加。

## TraceMaker 与 MegaRoute

TraceMaker 唯一未通过：D3-A 0068 AVR-ISP pogo-plug 1.27mm，3/6、DRC 0。summary.json 明确报告 /MISO、/SCK、/RESET 的 P2 目标端 boxed in，固定铜封闭引脚；这是该路由器的可达性判定，不等于物理上绝对无解。返回码 3，保存了部分结果，耗时约 0.60 s，并非超时。

MegaRoute 唯一未通过：D3-A 0034 NavigationThingBacklight，12/14、DRC 0。Net-(D1-Pad1)、Net-(P1-Pad1) 搜索反复 search_exhausted，10 轮后 stagnation，约 33.96 s。此结果使用此前构建；不能据此判断最新构建重测结果。0026 已为 9/9、DRC 0；0098 已为 19/19、DRC 0。两算法在 D3-B 均全部干净通过。

## FreeRouting 原因

- 0009 仅 started：已有 DSN，无 SES、运行日志、评估结果。只能定位到 DSN 导出后流程未完成，现有证据不能断言超时、崩溃或算法无解。
- 已评估但未连通：Java 正常返回仍可能留下未布线项。0034 日志到 pass 999 仍 10 unrouted，原生评估同为缺 10；0078 内部最终 incomplete_count=4，原生缺 5，内部统计与 KiCad 不能混用。
- 0021：新增 +5V 走线碰到 Bottom 铜文字，实际间距 0，要求 0.06 mm。
- 0026：新增 AC_IN1/AC_IN2 走线与 F.Cu 的 AC_IN 铜文字短路，3 条错误。
- 0088：GND 走线与 F.Cu 的 servo_44_I2C 铜文字短路，2 条错误。三例错误均涉及铜文字障碍。

## KRT 原因

- 未评估 10 例：0009、0012 只有 started，缺少路由完成记录，不能推断中断原因。
- 另 8 例 0017、0021、0048、0049、0050、0051、0067、0100：路由进程均返回 0 并输出文件，后续 KiCad 无法加载。静态检查发现输出 segment 使用 Top/Bottom、1_top、Front/Back 等显示别名，而层表正式名为 F.Cu/B.Cu/In*.Cu，定位为层名回写兼容问题。不是全部搜索失败，例如 0017 内部报告 6/6 完成。
- 未连通：日志常见 no rippable blockers found、多端网 MST 支路失败。0080、0099 所有起终点相邻网格均被判阻塞，分别 0/22、0/24；记录 copied_input=true，评分使用了输入板副本，不能将 complete 当成成功布线。
- DRC：全部为 clearance。适配器传入 Default 间距，对非默认网络仅传线宽，未传对应间距。0046 的 VCC 要求 0.5 mm、Default 只有 0.2 mm，出现 25 条间距错误，规则传递缺失是明确问题。其余部分错误只有数微米，也有大幅不足；网格/精确几何差异是待验证因素，不能仅凭报告归咎于 0.1 mm 网格。

## 逐例非通过结果

路径可用于查阅 manifest、routing.log 和原生 drc.json。案例名称包含完整标识。

### freerouting

| 案例 | 流程状态 | 完成连接 | DRC error | 直接证据 / 分类 |
|---|---|---:|---:|---|
| [D3-A/d3a_0009_SmartLaserCO2-PCB_WaterCool](../../results/D3-A/d3a_0009_SmartLaserCO2-PCB_WaterCool/freerouting/manifest.json) | started | — | — | 无完成记录；中断原因未证实 |
| [D3-A/d3a_0014_hardware-designs_m-trigger](../../results/D3-A/d3a_0014_hardware-designs_m-trigger/freerouting/evaluation/metrics.json) | complete | 7/8 | 0 | 连接未完成 |
| [D3-A/d3a_0021_RPi-PWM-Fan-interface_RPi_PWM_Fan_interface](../../results/D3-A/d3a_0021_RPi-PWM-Fan-interface_RPi_PWM_Fan_interface/freerouting/evaluation/metrics.json) | complete | 10/10 | 1 | clearance×1 |
| [D3-A/d3a_0024_memsarray_mems_modules](../../results/D3-A/d3a_0024_memsarray_mems_modules/freerouting/evaluation/metrics.json) | complete | 4/10 | 0 | 连接未完成 |
| [D3-A/d3a_0026_PCB_constant_current_ac_hv](../../results/D3-A/d3a_0026_PCB_constant_current_ac_hv/freerouting/evaluation/metrics.json) | complete | 9/9 | 3 | shorting_items×3 |
| [D3-A/d3a_0034_NavigationThing_NavigationThingBacklight](../../results/D3-A/d3a_0034_NavigationThing_NavigationThingBacklight/freerouting/evaluation/metrics.json) | complete | 4/14 | 0 | 连接未完成 |
| [D3-A/d3a_0046_mearm-base-pcb_ServoPCB](../../results/D3-A/d3a_0046_mearm-base-pcb_ServoPCB/freerouting/evaluation/metrics.json) | complete | 12/14 | 0 | 连接未完成 |
| [D3-A/d3a_0049_MySRaspiGW_MySRaspiGW_PA_LNA](../../results/D3-A/d3a_0049_MySRaspiGW_MySRaspiGW_PA_LNA/freerouting/evaluation/metrics.json) | complete | 12/13 | 0 | 连接未完成 |
| [D3-A/d3a_0050_MySRaspiGW_MySRaspiGW_PA_LNA_Pimoroni](../../results/D3-A/d3a_0050_MySRaspiGW_MySRaspiGW_PA_LNA_Pimoroni/freerouting/evaluation/metrics.json) | complete | 12/13 | 0 | 连接未完成 |
| [D3-A/d3a_0052_breakout-boards_50-to-100](../../results/D3-A/d3a_0052_breakout-boards_50-to-100/freerouting/evaluation/metrics.json) | complete | 9/10 | 0 | 连接未完成 |
| [D3-A/d3a_0059_marlin-neopixel-bridge_ATtiny85_Marneo](../../results/D3-A/d3a_0059_marlin-neopixel-bridge_ATtiny85_Marneo/freerouting/evaluation/metrics.json) | complete | 15/16 | 0 | 连接未完成 |
| [D3-A/d3a_0063_stlinkv2_breakout_stlink_breakout](../../results/D3-A/d3a_0063_stlinkv2_breakout_stlink_breakout/freerouting/evaluation/metrics.json) | complete | 16/17 | 0 | 连接未完成 |
| [D3-A/d3a_0077_HaveSome_PCB_HaveSomePCB](../../results/D3-A/d3a_0077_HaveSome_PCB_HaveSomePCB/freerouting/evaluation/metrics.json) | complete | 18/19 | 0 | 连接未完成 |
| [D3-A/d3a_0078_Hardware_Playground_buck_led_driver](../../results/D3-A/d3a_0078_Hardware_Playground_buck_led_driver/freerouting/evaluation/metrics.json) | complete | 10/15 | 0 | 连接未完成 |
| [D3-A/d3a_0086_BB-PWR-8009_BB-PWR-8009_revA](../../results/D3-A/d3a_0086_BB-PWR-8009_BB-PWR-8009_revA/freerouting/evaluation/metrics.json) | complete | 21/22 | 0 | 连接未完成 |
| [D3-A/d3a_0088_DA_Lamp_attiny44a_servo_i2c](../../results/D3-A/d3a_0088_DA_Lamp_attiny44a_servo_i2c/freerouting/evaluation/metrics.json) | complete | 20/20 | 2 | shorting_items×2 |
| [D3-B/d3b_0203_MOD-MPU9150](../../results/D3-B/d3b_0203_MOD-MPU9150/freerouting/evaluation/metrics.json) | complete | 35/38 | 0 | 连接未完成 |
| [D3-B/d3b_0232_ATtiny461Breakout](../../results/D3-B/d3b_0232_ATtiny461Breakout/freerouting/evaluation/metrics.json) | complete | 37/38 | 0 | 连接未完成 |

### krt

| 案例 | 流程状态 | 完成连接 | DRC error | 直接证据 / 分类 |
|---|---|---:|---:|---|
| [D3-A/d3a_0009_SmartLaserCO2-PCB_WaterCool](../../results/D3-A/d3a_0009_SmartLaserCO2-PCB_WaterCool/krt/manifest.json) | started | — | — | 无完成记录；中断原因未证实 |
| [D3-A/d3a_0012_kitspace_ir_sensor](../../results/D3-A/d3a_0012_kitspace_ir_sensor/krt/manifest.json) | started | — | — | 无完成记录；中断原因未证实 |
| [D3-A/d3a_0016_breakout-boards_avr-isp-x2](../../results/D3-A/d3a_0016_breakout-boards_avr-isp-x2/krt/evaluation/metrics.json) | complete | 5/6 | 0 | 连接未完成；双向起步阻塞；无可拆除阻挡物 |
| [D3-A/d3a_0017_Blink-Eras_AVR_ISP_Pogo](../../results/D3-A/d3a_0017_Blink-Eras_AVR_ISP_Pogo/krt/manifest.json) | error | — | — | 输出层别名；KiCad 重载失败 |
| [D3-A/d3a_0018_Hardware_Playground_hy_adapter](../../results/D3-A/d3a_0018_Hardware_Playground_hy_adapter/krt/evaluation/metrics.json) | complete | 6/6 | 3 | clearance×3 |
| [D3-A/d3a_0020_Cherry-Mx-Bitboard_Cherry_Mx_Bitboard](../../results/D3-A/d3a_0020_Cherry-Mx-Bitboard_Cherry_Mx_Bitboard/krt/evaluation/metrics.json) | complete | 4/11 | 5 | 连接未完成；clearance×5；无可拆除阻挡物 |
| [D3-A/d3a_0021_RPi-PWM-Fan-interface_RPi_PWM_Fan_interface](../../results/D3-A/d3a_0021_RPi-PWM-Fan-interface_RPi_PWM_Fan_interface/krt/manifest.json) | error | — | — | 输出层别名；KiCad 重载失败 |
| [D3-A/d3a_0024_memsarray_mems_modules](../../results/D3-A/d3a_0024_memsarray_mems_modules/krt/evaluation/metrics.json) | complete | 5/10 | 0 | 连接未完成；无可拆除阻挡物 |
| [D3-A/d3a_0034_NavigationThing_NavigationThingBacklight](../../results/D3-A/d3a_0034_NavigationThing_NavigationThingBacklight/krt/evaluation/metrics.json) | complete | 11/14 | 0 | 连接未完成；无可拆除阻挡物 |
| [D3-A/d3a_0037_hardware-designs_spsgrf-board](../../results/D3-A/d3a_0037_hardware-designs_spsgrf-board/krt/evaluation/metrics.json) | complete | 10/10 | 2 | clearance×2 |
| [D3-A/d3a_0043_breakout-boards_swd-and-uart](../../results/D3-A/d3a_0043_breakout-boards_swd-and-uart/krt/evaluation/metrics.json) | complete | 11/11 | 2 | clearance×2 |
| [D3-A/d3a_0044_blink-errr_blink-errr](../../results/D3-A/d3a_0044_blink-errr_blink-errr/krt/evaluation/metrics.json) | complete | 15/15 | 4 | clearance×4 |
| [D3-A/d3a_0045_retroreflectors_TANGOFLOCK](../../results/D3-A/d3a_0045_retroreflectors_TANGOFLOCK/krt/evaluation/metrics.json) | complete | 14/14 | 2 | clearance×2 |
| [D3-A/d3a_0046_mearm-base-pcb_ServoPCB](../../results/D3-A/d3a_0046_mearm-base-pcb_ServoPCB/krt/evaluation/metrics.json) | complete | 14/14 | 25 | clearance×25 |
| [D3-A/d3a_0048_MySRaspiGW_MySRaspiGW](../../results/D3-A/d3a_0048_MySRaspiGW_MySRaspiGW/krt/manifest.json) | error | — | — | 输出层别名；KiCad 重载失败 |
| [D3-A/d3a_0049_MySRaspiGW_MySRaspiGW_PA_LNA](../../results/D3-A/d3a_0049_MySRaspiGW_MySRaspiGW_PA_LNA/krt/manifest.json) | error | — | — | 输出层别名；KiCad 重载失败 |
| [D3-A/d3a_0050_MySRaspiGW_MySRaspiGW_PA_LNA_Pimoroni](../../results/D3-A/d3a_0050_MySRaspiGW_MySRaspiGW_PA_LNA_Pimoroni/krt/manifest.json) | error | — | — | 输出层别名；KiCad 重载失败 |
| [D3-A/d3a_0051_MySRaspiGW_MySRaspiGW_Pimoroni](../../results/D3-A/d3a_0051_MySRaspiGW_MySRaspiGW_Pimoroni/krt/manifest.json) | error | — | — | 输出层别名；KiCad 重载失败 |
| [D3-A/d3a_0052_breakout-boards_50-to-100](../../results/D3-A/d3a_0052_breakout-boards_50-to-100/krt/evaluation/metrics.json) | complete | 10/10 | 1 | clearance×1 |
| [D3-A/d3a_0054_induction-hob_temperature-sensor](../../results/D3-A/d3a_0054_induction-hob_temperature-sensor/krt/evaluation/metrics.json) | complete | 9/15 | 0 | 连接未完成；无可拆除阻挡物 |
| [D3-A/d3a_0057_tepmachcha_tepmachcha](../../results/D3-A/d3a_0057_tepmachcha_tepmachcha/krt/evaluation/metrics.json) | complete | 12/12 | 5 | clearance×5 |
| [D3-A/d3a_0067_radio_saw_dcc6c](../../results/D3-A/d3a_0067_radio_saw_dcc6c/krt/manifest.json) | error | — | — | 输出层别名；KiCad 重载失败 |
| [D3-A/d3a_0077_HaveSome_PCB_HaveSomePCB](../../results/D3-A/d3a_0077_HaveSome_PCB_HaveSomePCB/krt/evaluation/metrics.json) | complete | 11/19 | 0 | 连接未完成；无可拆除阻挡物 |
| [D3-A/d3a_0078_Hardware_Playground_buck_led_driver](../../results/D3-A/d3a_0078_Hardware_Playground_buck_led_driver/krt/evaluation/metrics.json) | complete | 13/15 | 0 | 连接未完成；无可拆除阻挡物 |
| [D3-A/d3a_0080_kitspace_RPi_shield](../../results/D3-A/d3a_0080_kitspace_RPi_shield/krt/evaluation/metrics.json) | complete | 0/22 | 0 | 连接未完成；双向起步阻塞；无可拆除阻挡物；复制输入作为输出 |
| [D3-A/d3a_0082_firefly-jar_solar_lamp](../../results/D3-A/d3a_0082_firefly-jar_solar_lamp/krt/evaluation/metrics.json) | complete | 20/20 | 3 | clearance×3 |
| [D3-A/d3a_0083_DustSensorShield_DustSensorShield](../../results/D3-A/d3a_0083_DustSensorShield_DustSensorShield/krt/evaluation/metrics.json) | complete | 14/17 | 0 | 连接未完成；无可拆除阻挡物 |
| [D3-A/d3a_0084_kitspace__autosave-nunchuk_breakout](../../results/D3-A/d3a_0084_kitspace__autosave-nunchuk_breakout/krt/evaluation/metrics.json) | complete | 17/21 | 0 | 连接未完成 |
| [D3-A/d3a_0086_BB-PWR-8009_BB-PWR-8009_revA](../../results/D3-A/d3a_0086_BB-PWR-8009_BB-PWR-8009_revA/krt/evaluation/metrics.json) | complete | 21/22 | 0 | 连接未完成 |
| [D3-A/d3a_0087_solar-lanterns_proto1](../../results/D3-A/d3a_0087_solar-lanterns_proto1/krt/evaluation/metrics.json) | complete | 17/21 | 0 | 连接未完成；无可拆除阻挡物 |
| [D3-A/d3a_0088_DA_Lamp_attiny44a_servo_i2c](../../results/D3-A/d3a_0088_DA_Lamp_attiny44a_servo_i2c/krt/evaluation/metrics.json) | complete | 20/20 | 2 | clearance×2 |
| [D3-A/d3a_0090_keyboard_converter_adapter_ibm4704_converter_adapter_ibm4704](../../results/D3-A/d3a_0090_keyboard_converter_adapter_ibm4704_converter_adapter_ibm4704/krt/evaluation/metrics.json) | complete | 8/19 | 0 | 连接未完成；无可拆除阻挡物 |
| [D3-A/d3a_0093_kitspace_nunchuk_breakout](../../results/D3-A/d3a_0093_kitspace_nunchuk_breakout/krt/evaluation/metrics.json) | complete | 17/21 | 0 | 连接未完成 |
| [D3-A/d3a_0098_MSGEQ7-Breakout-Board_MSGEQ7_Breakout_Board](../../results/D3-A/d3a_0098_MSGEQ7-Breakout-Board_MSGEQ7_Breakout_Board/krt/evaluation/metrics.json) | complete | 19/19 | 1 | clearance×1 |
| [D3-A/d3a_0099_SparkSwitch_SparkProtectionSwitch](../../results/D3-A/d3a_0099_SparkSwitch_SparkProtectionSwitch/krt/evaluation/metrics.json) | complete | 0/24 | 0 | 连接未完成；双向起步阻塞；无可拆除阻挡物；复制输入作为输出 |
| [D3-A/d3a_0100_smt-zvs-driver_IH10-mc](../../results/D3-A/d3a_0100_smt-zvs-driver_IH10-mc/krt/manifest.json) | error | — | — | 输出层别名；KiCad 重载失败 |
| [D3-B/d3b_0113_maytal_Maytal](../../results/D3-B/d3b_0113_maytal_Maytal/krt/evaluation/metrics.json) | complete | 20/20 | 7 | clearance×7 |
| [D3-B/d3b_0144_ottawa_badge](../../results/D3-B/d3b_0144_ottawa_badge/krt/evaluation/metrics.json) | complete | 30/30 | 1 | clearance×1 |
| [D3-B/d3b_0174_sensorboard_DiffIR](../../results/D3-B/d3b_0174_sensorboard_DiffIR/krt/evaluation/metrics.json) | complete | 32/32 | 1 | clearance×1 |
| [D3-B/d3b_0203_MOD-MPU9150](../../results/D3-B/d3b_0203_MOD-MPU9150/krt/evaluation/metrics.json) | complete | 21/38 | 0 | 连接未完成；无可拆除阻挡物 |
| [D3-B/d3b_0232_ATtiny461Breakout](../../results/D3-B/d3b_0232_ATtiny461Breakout/krt/evaluation/metrics.json) | complete | 27/38 | 0 | 连接未完成；无可拆除阻挡物 |
| [D3-B/d3b_0260_NiMH-Charger](../../results/D3-B/d3b_0260_NiMH-Charger/krt/evaluation/metrics.json) | complete | 42/45 | 0 | 连接未完成；无可拆除阻挡物 |
| [D3-B/d3b_0316_kicad-workshop_fancyboard](../../results/D3-B/d3b_0316_kicad-workshop_fancyboard/krt/evaluation/metrics.json) | complete | 15/55 | 0 | 连接未完成；无可拆除阻挡物 |
| [D3-B/d3b_0344_mavbridge](../../results/D3-B/d3b_0344_mavbridge/krt/evaluation/metrics.json) | complete | 8/64 | 0 | 连接未完成；双向起步阻塞；无可拆除阻挡物 |
| [D3-B/d3b_0376_cat-trainer_teensy](../../results/D3-B/d3b_0376_cat-trainer_teensy/krt/evaluation/metrics.json) | complete | 60/67 | 13 | 连接未完成；clearance×13；无可拆除阻挡物 |

## 后续优先级

先修 KRT 输出层名和网络间距传递，再区分恢复未完成流程与改善搜索。FreeRouting 优先核对 DSN 中铜文字障碍表达及导入后的保护；连接残留需单独分析搜索和端点接入。所有修正均需使用新结果目录复测确认，本次未修改算法、删除结果或运行实验。
