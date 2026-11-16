#include "megaroute/core.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
int main(int argc, char **argv) {
    using namespace mr;
    try {
        if (argc < 2 || std::string(argv[1]) == "--help") {
            std::cout << "megaroute_cli validate --board board.json\nmegaroute_cli route --board board.json "
                         "--config config.json --out results/run [--events]\nmegaroute_cli check --board "
                         "board.json --routes routes.json\n";
            return argc < 2 ? 1 : 0;
        }
        std::string command = argv[1];
        if (command != "validate" && command != "route" && command != "check")
            throw std::runtime_error("unknown command");
        std::map<std::string, std::string> args;
        bool events = false;
        for (int i = 2; i < argc; ++i) {
            std::string k = argv[i];
            if (k == "--events" && command == "route") {
                events = true;
                continue;
            }
            if (k != "--board" && !(command == "route" && (k == "--config" || k == "--out")) &&
                !(command == "check" && k == "--routes"))
                throw std::runtime_error("unknown option: " + k);
            if (++i == argc || args.count(k))
                throw std::runtime_error("missing/duplicate option value");
            args[k] = argv[i];
        }
        auto required = [&](const std::string &k) {
            if (!args.count(k))
                throw std::runtime_error("missing " + k);
            return args.at(k);
        };
        JsonImporter importer;
        auto load_start = std::chrono::steady_clock::now();
        auto board = importer.load(required("--board"));
        double load_s = std::chrono::duration<double>(std::chrono::steady_clock::now() - load_start).count();
        if (command == "validate") {
            auto metrics = evaluate(board, {});
            std::cout << Json({{"valid_schema", true},
                               {"input_DRC", metrics["DRC"]},
                               {"violations", metrics["violations"]}})
                             .dump(2)
                      << '\n';
            return metrics["DRC"] == 0 ? 0 : 2;
        }
        if (command == "check") {
            auto metrics = evaluate(board, parse_routes(read_json(required("--routes")), board));
            std::cout << metrics.dump(2) << '\n';
            return metrics["DRC"] == 0 && metrics["C_routed"] == metrics["C_total"] ? 0 : 2;
        }
        auto config = parse_config(read_json(required("--config")));
        std::filesystem::path out = required("--out");
        if (std::filesystem::exists(out) && !std::filesystem::is_empty(out))
            throw std::runtime_error("output directory is not empty; choose a new run directory");
        std::filesystem::create_directories(out);
        write_json((out / "board.json").string(), board.document);
        write_json((out / "config.json").string(), config_json(config));
        std::ofstream log;
        if (events) {
            log.open(out / "events.jsonl");
            if (!log)
                throw std::runtime_error("cannot create event log");
        }
        auto begin = std::chrono::steady_clock::now();
        auto result = route(board, config,
                            events ? Observer([&](const Json &e) { log << e.dump() << '\n'; }) : Observer{});
        double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
        auto check_start = std::chrono::steady_clock::now();
        auto metrics = evaluate(board, result.copper);
        metrics["timing_s"] = {
            {"load", load_s},
            {"route_including_init", seconds},
            {"final_check",
             std::chrono::duration<double>(std::chrono::steady_clock::now() - check_start).count()}};
        metrics["termination_reason"] = result.reason;
        metrics["expanded_nodes"] = result.expanded;
        metrics["iterations"] = result.iterations;
        metrics["last_path_drc"] = result.last_path_drc;
        metrics["search_failures"] = result.failures;
        if (result.has_diagnostic) {
            auto diagnostic = evaluate(board, result.diagnostic);
            metrics["diagnostic"] = {{"C_routed", diagnostic["C_routed"]},
                                     {"DRC", diagnostic["DRC"]},
                                     {"WL_mm", diagnostic["WL_mm"]},
                                     {"VC", diagnostic["VC"]}};
            write_json((out / "diagnostic_routes.json").string(), routes_json(result.diagnostic));
        }
        metrics["implementation"] = "pcb-bench-0.1.0";
        metrics["compiler"] =
#ifdef __VERSION__
            __VERSION__;
#else
            "MSVC";
#endif
        write_json((out / "routes.json").string(), routes_json(result.copper));
        write_json((out / "metrics.json").string(), metrics);
        std::cout << metrics.dump(2) << '\n';
        return metrics["DRC"] == 0 && metrics["C_routed"] == metrics["C_total"] ? 0 : 2;
    } catch (const std::exception &e) {
        std::cerr << mr::Json({{"error", e.what()}}).dump() << '\n';
        return 1;
    }
}
