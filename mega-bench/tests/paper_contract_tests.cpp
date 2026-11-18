#include "megaroute/core.hpp"
#include <iostream>
#include <stdexcept>
using namespace mr;
static void expect(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}
int main() {
    try {
        const auto defaults = parse_config({{"schema_version", "1.0"}, {"algorithm", "megaroute"}});
        expect(defaults.beta == 5 && defaults.d_min == .0254 && defaults.max_iterations == 20,
               "paper step/density/iteration defaults");
        expect(defaults.penalty_L == 200 && defaults.penalty_k == .4 && defaults.penalty_mu == 10,
               "paper logistic parameters");
        expect(logistic_penalty(0) == 0 && std::abs(logistic_penalty(10)-100) < eps &&
               std::abs(logistic_penalty(20)-200) < eps, "paper equation 9 schedule");
        expect(std::abs(heuristic({0,0},{3,2})-(1+2*std::sqrt(2.))) < eps,
               "paper equation 8 octile heuristic");
        for (const auto *key : {"history_weight", "refinement_levels", "stagnation_rounds"}) {
            auto config = config_json(defaults);
            config[key] = 1;
            bool rejected = false;
            try { parse_config(config); } catch (const std::exception &) { rejected = true; }
            expect(rejected, "removed algorithm extensions cannot be enabled silently");
        }
        Board b;
        b.layers = 1; b.outline = {{0,0},{40,0},{40,40},{0,40}};
        b.nets = {{"A",.4,.2}};
        b.document = {{"pads", {{{"id","a"}}, {{"id","b"}}}}};
        Shape source;
        source.id = "a"; source.net = "A"; source.kind = "circle";
        source.a = source.b = {10,10}; source.radius = 2; source.layers = {0};
        auto target = source;
        target.id = "b"; target.a = target.b = {13,10}; target.radius = .2;
        b.copper = {source, target};
        Config c;
        c.algorithm = "adaptive_strict"; c.max_records = 32; c.time_limit = 1;
        int starts = 0;
        auto routed = route(b, c, [&](const Json &event) {
            if (event.at("event") == "search_start") {
                ++starts;
                expect(event.at("source_seed_count") == 1, "one source state per copper layer");
                expect(event.at("target_access_count") == 1, "one fixed target per copper layer");
            }
        });
        expect(starts == 1 && evaluate(b, routed.copper)["C_routed"] == 1,
               "large legal pads must not exhaust the record budget during seeding");
        c.max_records = 1000;
        c.d_min = 10;
        auto dense = route(b, c);
        expect(dense.expanded == 1 && evaluate(b, dense.copper)["C_routed"] == 0,
               "density pruning applies regardless of incoming heading");
        // Endpoint coordinate offsets smaller than d_min still need the
        // explicit axis/diagonal alignment operations in Eq. 4/5.
        b.outline = {{0,0},{12,0},{12,6},{0,6}};
        source.a = source.b = {1,3}; source.radius = .1;
        target.a = target.b = {10.0007,3.0031}; target.radius = .1;
        b.copper = {source,target};
        b.nets[0].width = .2;
        c.d_min = .0254; c.max_records = 10000; c.max_nodes = 10000;
        auto aligned = route(b,c);
        expect(evaluate(b, aligned.copper)["C_routed"] == 1 &&
               evaluate(b, aligned.copper)["DRC"] == 0,
               "sub-density terminal alignment must not be pruned");
        auto rotated = config_json(defaults);
        rotated["routing_order"] = "fixed";
        expect(parse_config(rotated).routing_order == "fixed", "fixed order remains available for comparison");
        rotated["routing_order"] = "unknown";
        bool rejected = false;
        try { parse_config(rotated); } catch (const std::exception &) { rejected = true; }
        expect(rejected, "invalid reroute policy rejected");
        // Two colliding connections must not get the same priority forever.
        b.outline = {{0,0},{30,0},{30,20},{0,20}};
        b.nets = {{"A",.2,.2},{"B",.2,.2}};
        auto pad = [](const char *id, const char *net, Point p) {
            Shape s;
            s.id = id; s.net = net; s.kind = "circle";
            s.a = s.b = p; s.radius = .3; s.layers = {0};
            return s;
        };
        b.copper = {pad("a","A",{5,10}),pad("b","A",{25,10}),
                    pad("c","B",{15,4}),pad("d","B",{15,16})};
        b.document = {{"pads", {{{"id","a"}},{{"id","b"}},{{"id","c"}},{{"id","d"}}}}};
        c.algorithm = "megaroute"; c.max_iterations = 2; c.penalty_L = 1;
        c.max_nodes = 100000; c.max_records = 200000;
        std::map<int,std::string> first_net;
        auto negotiated = route(b,c,[&](const Json &event) {
            if (event.at("event") == "route_committed")
                first_net.emplace(event.at("iteration").get<int>(),event.at("net").get<std::string>());
        });
        expect(first_net.size() == 2 && first_net.at(1) != first_net.at(2),
               "unresolved connections rotate priority across iterations");
        expect(evaluate(b,negotiated.copper)["DRC"] == 0,
               "reroute priority never weakens final DRC validation");
        std::cout << "paper contract checks passed\n";
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n'; return 1;
    }
}
