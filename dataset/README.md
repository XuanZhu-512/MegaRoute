# Dataset

数据集与 `pcb-bench/` 并列存放；程序目录不再保留 `data/`。

- `test/`：用户提供的 KiCad 合成板，以及 `case.json` 公共案例清单。
- `geometry-fixtures/`：从旧 `pcb-bench/data/synthetic/` 迁移的七个 JSON 几何回归案例；仅用于内部开发测试，不是正式 KiCad benchmark 输入。

正式案例包含同名 `.kicad_pcb`、`.kicad_pro`，存在 `.kicad_dru` 时须在清单中声明。保留源文件；离线去除参考走线必须对所有算法一致执行。

从 `pcb-bench/` 目录检查现有测试板的执行计划：

```powershell
python tools/bench.py plan --case ../dataset/test/case.json --backend megaroute --toolchain configs/kicad-toolchain.json
```

当前 `plan` 仅验证文件契约并列出执行阶段，`executable=false`；不解析板几何或执行转换。

`test/board_00000.kicad_pcb` 包含两铜层、4 个非空网络、9 个焊盘（2 个圆形通孔、7 个圆角矩形 SMD）及矩形板框。现已用 KiCad 10.0.8 成功导出原生几何多边形，见 `pcb-bench/docs/GEOMETRY_EXPORT.md`。该提取格式尚不能直接输入旧 C++ 几何核心；反向回写也未实现。原文件的 `generator_version=9.0.5` 只记录来源，不是当前运行的 KiCad 版本。
