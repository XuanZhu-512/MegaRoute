#include "megaroute/core.hpp"
#include <algorithm>
#include <iostream>
#include <random>
#include <stdexcept>
#include <set>
using namespace mr;
static void expect(bool ok, const char *name) {
    if (!ok) throw std::runtime_error(name);
}
static std::set<std::tuple<std::string, std::string, int>> keys(const std::vector<Violation> &vs) {
    std::set<std::tuple<std::string, std::string, int>> result;
    for (const auto &v : vs) result.emplace(v.rule, v.b, v.layer);
    return result;
}
int main() {
    try {
        Board b;
        b.layers = 3;
        b.outline = {{-20, -20}, {20, -20}, {20, 20}, {-20, 20}};
        b.edge_clearance = 0;
        b.nets = {{"A", .2, .1}, {"B", .2, .7}};
        Shape pad;
        pad.id = "edge-pad"; pad.net = "A"; pad.kind = "polygon"; pad.layers = {0};
        pad.a = pad.b = {-19, 0};
        pad.polygon = {{-20, -1}, {-18, -1}, {-18, 1}, {-20, 1}};
        expect(check_shape(b, pad, {}).empty(), "zero-clearance fixed pad may touch board edge");
        b.edge_clearance = .01;
        expect(!check_shape(b, pad, {}).empty(), "positive board-edge clearance is enforced");
        b.edge_clearance = 0;
        auto outside = pad; outside.polygon[0].x -= .1;
        expect(!check_shape(b, outside, {}).empty(), "zero clearance does not allow copper outside outline");
        Shape capsule;
        capsule.kind = "segment"; capsule.net = "A"; capsule.layers = {0}; capsule.radius = .1;
        capsule.a = {-19.9, -2}; capsule.b = {-19.9, 2};
        expect(check_shape(b, capsule, {}).empty(), "tangent capsule is inside closed board");
        capsule.a.x = capsule.b.x = -19.95;
        expect(!check_shape(b, capsule, {}).empty(), "capsule radius crossing edge is rejected");
        std::vector<Point> notch{{0, 0}, {8, 0}, {8, 8}, {5, 8}, {5, 3}, {3, 3}, {3, 8}, {0, 8}};
        Shape chord;
        chord.a = {1, 6}; chord.b = {7, 6};
        expect(!contained_in(chord, notch), "segment cannot bridge exterior of concave board");
        chord.polygon = {{1, 5}, {7, 5}, {7, 6}, {1, 6}};
        expect(!contained_in(chord, notch), "polygon vertices inside do not imply whole polygon inside");
        chord.polygon = {{1, 1}, {7, 1}, {7, 2}, {1, 2}};
        expect(contained_in(chord, notch), "interior polygon remains legal on concave board");

        std::mt19937 rng(12345);
        std::uniform_real_distribution<double> pos(-12, 12);
        std::vector<Shape> copper;
        for (int i = 0; i < 100; ++i) {
            Shape s;
            s.id = std::to_string(i); s.net = i % 2 ? "A" : "B";
            s.kind = "segment"; s.radius = .1 + .05 * (i % 4);
            s.a = {pos(rng), pos(rng)}; s.b = s.a + Point{pos(rng) / 5, pos(rng) / 5};
            s.layers = {i % 3};
            if (i % 5 == 0) s.layers = {0, 1, 2};
            if (i % 7 == 0) {
                s.kind = "polygon"; s.radius = 0;
                s.polygon = {{s.a.x - .4, s.a.y - .2}, {s.a.x + .4, s.a.y - .2},
                             {s.a.x + .4, s.a.y + .2}, {s.a.x - .4, s.a.y + .2}};
            }
            copper.push_back(s);
        }
        // Large objects and queries take the bounded-memory index fallback.
        Shape wide;
        wide.id = "wide"; wide.net = "B"; wide.kind = "segment";
        wide.a = {-10000, -10000}; wide.b = {10000, 10000}; wide.radius = .2; wide.layers = {1};
        copper.push_back(wide);
        CopperIndex index(copper);
        for (int i = 0; i < 200; ++i) {
            Shape candidate;
            candidate.id = "query"; candidate.kind = "segment"; candidate.net = "A";
            candidate.radius = .1; candidate.a = {pos(rng), pos(rng)};
            candidate.b = i % 10 ? candidate.a + Point{pos(rng) / 4, pos(rng) / 4} : Point{10000, 10000};
            candidate.layers = i % 4 ? std::vector<int>{i % 3} : std::vector<int>{0, 1, 2};
            expect(keys(check_shape(b, candidate, copper)) == keys(check_shape(b, candidate, copper, &index)),
                   "spatial broad phase must exactly match full DRC scan");
        }
        Shape first;
        first.id = "a"; first.net = "A"; first.kind = "circle";
        first.a = first.b = {0, 0}; first.radius = .2; first.layers = {0};
        Shape second = first; second.id = "b"; second.a = second.b = {2, 0}; second.layers = {1};
        Connectivity graph({first, second});
        expect(!graph.connected("a", "b"), "separate pad groups initially disconnected");
        Shape via = first; via.id = "via"; via.kind = "via"; via.layers = {0, 1, 2};
        graph.add(via);
        Shape wire = first; wire.id = "wire"; wire.kind = "segment"; wire.b = {2, 0}; wire.layers = {1};
        graph.add(wire);
        expect(graph.connected("a", "b"), "incremental connectivity includes through-via middle layers");
        Connectivity after_ripup({first, second, wire});
        expect(!after_ripup.connected("a", "b"), "rebuilding after ripup removes stale connectivity");
        auto config = parse_config({{"schema_version", "1.0"}, {"max_iterations", 40},
                                   {"refinement_levels", 2}, {"history_weight", .25}});
        expect(config.max_iterations == 40 && parse_config(config_json(config)).refinement_levels == 2,
               "extended iteration and repair controls round-trip");
        std::cout << "Routing regression checks passed\n";
        return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
