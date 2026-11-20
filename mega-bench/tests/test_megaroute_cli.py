"""CLI/configuration tests; no routing processes or experiments."""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from pcb_bench.cli import main
from pcb_bench.contracts import RunBudget
from pcb_bench.runner import effective_router_config


class MegaRouteCliTests(unittest.TestCase):
    def command(self, *extra, backend="megaroute"):
        return ["run", "--case", "case.json", "--backend", backend,
                "--out", "output", "--toolchain", "toolchain.json",
                "--kicad-python", "python3", "--expected-version", "9.0.8", *extra]

    def test_overrides_reach_runner_with_json_names_and_types(self):
        with patch("pcb_bench.cli.execute_run", return_value={}) as run, \
             contextlib.redirect_stdout(io.StringIO()):
            code = main(self.command(
                "--config", "custom.json", "--megaroute-beta", "2",
                "--megaroute-d-min-mm", "0.0254", "--megaroute-lambda-v", "0",
                "--megaroute-time-limit-s", "3600", "--megaroute-max-iterations", "100",
                "--megaroute-max-expanded-nodes", "2000000", "--megaroute-max-records", "4000000",
                "--megaroute-penalty-l", "1000", "--megaroute-penalty-k", "0.4",
                "--megaroute-penalty-mu", "10", "--megaroute-routing-order", "fixed"))
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.kwargs["config"], Path("custom.json"))
        self.assertEqual(run.call_args.kwargs["megaroute_overrides"], {
            "beta": 2., "d_min_mm": .0254, "lambda_v": 0., "time_limit_s": 3600.,
            "max_iterations": 100, "max_expanded_nodes": 2000000, "max_records": 4000000,
            "penalty_L": 1000., "penalty_k": .4, "penalty_mu": 10., "routing_order": "fixed"})

    def test_omitted_overrides_preserve_existing_behavior(self):
        with patch("pcb_bench.cli.execute_run", return_value={}) as run, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(self.command()), 0)
        self.assertEqual(run.call_args.kwargs["megaroute_overrides"], {})

    def test_invalid_values_rejected_before_execution(self):
        for option, value in (("beta", "0.5"), ("beta", "nan"), ("penalty-l", "inf"),
                              ("penalty-k", "0"), ("d-min-mm", "-1"),
                              ("time-limit-s", "0"), ("max-iterations", "101"),
                              ("max-iterations", "2.5"), ("max-records", "10000001"),
                              ("routing-order", "random")):
            with self.subTest(option=option, value=value), \
                 patch("pcb_bench.cli.execute_run") as run, \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(self.command("--megaroute-" + option, value))
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()

    def test_overrides_for_other_backend_are_rejected(self):
        with patch("pcb_bench.cli.execute_run") as run, \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(self.command("--megaroute-beta", "2", backend="tracemaker"))
        run.assert_not_called()

    def test_precedence_and_watchdog_cap_do_not_mutate_inputs(self):
        config = {"beta": 5, "penalty_L": 200, "time_limit_s": 300}
        overrides = {"beta": 2, "time_limit_s": 3600}
        result = effective_router_config(config, RunBudget(1230, 120), overrides)
        self.assertEqual(result, {"beta": 2, "penalty_L": 200, "time_limit_s": 1220})
        self.assertEqual(config["time_limit_s"], 300)
        self.assertEqual(overrides["time_limit_s"], 3600)
        self.assertEqual(effective_router_config(config, RunBudget(3630, 120), overrides)["time_limit_s"], 3600)


if __name__ == "__main__":
    unittest.main()
