# Official benchmark inputs

Add real, prepared KiCad projects here or reference an external dataset from a case
manifest. `configs/case.example.json` is a path template, not an included runnable board.
Do not treat old `data/synthetic/*.json` geometry fixtures as KiCad benchmark cases.

Each case requires a `.kicad_pcb` and a same-basename `.kicad_pro`. Declare the
same-basename `.kicad_dru` whenever present. Initial policy is `preserve_input`:
all input copper stays fixed. Unrouting a reference board is a separate, versioned
offline preparation step, shared by all algorithms. Zones, project variables,
external dependencies, and unsupported rules require explicit converter/evaluator
capability checks before running; a file snapshot alone does not validate them.
