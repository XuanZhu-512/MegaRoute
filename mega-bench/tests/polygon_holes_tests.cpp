#include "megaroute/core.hpp"
#include <algorithm>
#include <iostream>
#include <stdexcept>
using namespace mr;
static void expect(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}
int main() {
    try {
        expect(simple_polygon({{0,0},{1,0},{1,0.000001},{1,1},{0,1}}),
               "KiCad one-nanometer edge is valid topology");
        expect(!simple_polygon({{0,0},{1,0},{1,0},{1,1},{0,1}}),
               "duplicate adjacent vertices remain invalid");
        Shape ring;
        ring.id = "ring"; ring.kind = "polygon"; ring.net = "A"; ring.layers = {0};
        ring.polygon = {{1,1},{9,1},{9,9},{1,9}};
        ring.holes = {{{3,3},{7,3},{7,7},{3,7}}};
        Shape probe;
        probe.id = "probe"; probe.net = "B"; probe.kind = "via";
        probe.layers = {0,1}; probe.a = probe.b = {5,5}; probe.radius = .2;
        probe.drill = .2;
        expect(!inside_copper({5,5}, ring), "hole interior is empty");
        expect(inside_copper({3,5}, ring), "hole boundary is copper");
        expect(std::abs(gap(probe, ring) - 1.8) < eps, "via inside hole distance");
        expect(gap(ring, probe) == gap(probe, ring), "distance symmetry");
        Board b;
        b.outline = {{0,0},{10,0},{10,10},{0,10}};
        b.layers = 2; b.nets = {{"A",.2,.2},{"B",.2,.2}};
        std::vector<Shape> copper{ring};
        CopperIndex index(copper);
        expect(index.query(probe, .2).size() == 1, "outer bounds retain hole candidates");
        expect(check_shape(b, probe, copper, &index).empty(), "via allowed inside hole");
        probe.a = probe.b = {3.3,5};
        expect(!check_shape(b, probe, copper, &index).empty(), "hole wall clearance enforced");
        probe.a = probe.b = {3.1,5};
        expect(gap(probe, ring) < 0, "probe overlaps inner wall");
        probe.kind = "segment"; probe.a = {4,5}; probe.b = {6,5};
        expect(std::abs(gap(probe, ring) - .8) < eps, "segment inside hole");
        probe.b = {8,5};
        expect(gap(probe, ring) < 0, "segment crossing hole wall");
        Shape island = ring;
        island.id = "island"; island.holes.clear();
        island.polygon = {{4,4},{6,4},{6,6},{4,6}};
        expect(std::abs(gap(island, ring) - 1) < eps, "polygon island inside hole");
        expect(gap(island, ring) == gap(ring, island), "polygon symmetry");
        Connectivity graph({ring, island});
        expect(!graph.connected("ring", "island"), "hole does not falsely connect copper");
        probe.net = "A"; probe.a = {5,5}; probe.b = {8,5}; probe.layers = {0};
        graph.add(probe);
        expect(graph.connected("ring", "island"), "bridge to hole wall connects copper");
        expect(std::abs(boundary_gap(ring, island.polygon) - 1) < eps,
               "board edge in cutout measures to inner boundary");
        std::reverse(ring.holes[0].begin(), ring.holes[0].end());
        expect(std::abs(gap(island, ring) - 1) < eps, "ring winding independent");
        auto doc = Json::parse(R"({"schema_version":"1.0","units":"mm","layers":1,
          "outline":[[0,0],[10,0],[10,10],[0,10]],"nets":[],
          "fixed_copper":[{"id":"r","kind":"polygon","layers":[0],"center":[1,1],
            "points":[[1,1],[9,1],[9,9],[1,9]],
            "holes":[[[3,3],[7,3],[7,7],[3,7]]]}],
          "rules":{"min_width":0.2,"clearance":0.2,"edge_clearance":0.2,
            "via_diameter":0.6,"via_drill":0.3,"min_annular":0.1}})");
        expect(parse_board(doc).copper[0].holes.size() == 1, "parser preserves holes");
        auto rejects = [](const Json &j) {
            try { parse_board(j); return false; } catch (const std::exception &) { return true; }
        };
        auto invalid = doc;
        invalid["fixed_copper"][0]["center"] = {5,5};
        expect(rejects(invalid), "access point in hole rejected");
        for (auto hole : {Json::parse("[[0,3],[4,3],[4,4],[0,4]]"),
                          Json::parse("[[1,3],[4,3],[4,4],[1,4]]"),
                          Json::parse("[[4,4],[6,6],[4,6],[6,4]]")}) {
            invalid = doc; invalid["fixed_copper"][0]["holes"] = Json::array({hole});
            expect(rejects(invalid), "outside/touching/self-intersecting hole rejected");
        }
        invalid = doc;
        invalid["fixed_copper"][0]["holes"].push_back({{4,4},{6,4},{6,6},{4,6}});
        expect(rejects(invalid), "nested holes rejected");
        invalid["fixed_copper"][0]["holes"][1] = {{6,4},{8,4},{8,6},{6,6}};
        expect(rejects(invalid), "overlapping holes rejected");
        doc["fixed_copper"][0].erase("holes");
        expect(parse_board(doc).copper[0].holes.empty(), "legacy polygons remain supported");
        std::cout << "polygon holes passed\n";
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n'; return 1;
    }
}
