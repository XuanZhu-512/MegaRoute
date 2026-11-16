#include "megaroute/core.hpp"
#include <algorithm>
#include <iostream>
#include <stdexcept>
using namespace mr;
static void expect(bool value, const char *name) {
    if (!value)
        throw std::runtime_error(name);
}
int main() {
    try {
        expect(std::abs(point_segment({3, 1}, {0, 0}, {2, 0}) - std::sqrt(2.)) < eps,
               "finite segment endpoint distance");
        expect(segment_distance({0, 0}, {2, 2}, {0, 2}, {2, 0}) == 0, "crossing segments");
        expect(!simple_polygon({{0, 0}, {2, 2}, {0, 2}, {2, 0}}), "reject self intersection");
        Shape polygon;
        polygon.polygon = {{0, 0}, {4, 0}, {4, 4}, {0, 4}};
        Shape circle;
        circle.a = circle.b = {2, 2};
        circle.radius = .2;
        expect(gap(circle, polygon) < 0, "contained circle is collision");
        circle.a = circle.b = {5, 2};
        expect(std::abs(gap(circle, polygon) - .8) < eps, "polygon circle distance");
        Shape wire;
        wire.a = {-1, 2};
        wire.b = {5, 2};
        wire.radius = .1;
        expect(gap(wire, polygon) < 0, "whole segment crossing");
        auto c = candidates({0, 0}, 0, {2, 2}, 0, 1, 2);
        auto axis = std::find_if(c.begin(), c.end(), [](auto &x) { return x.operation == "axis"; });
        expect(axis != c.end() && axis->p.x == 0 && axis->p.y == 2, "axis tie uses y");
        auto count = [](auto &list, const std::string &op) {
            return std::count_if(list.begin(), list.end(), [&](auto &x) { return x.operation == op; });
        };
        c = candidates({0, 0}, 0, {2, 3}, 0, 1, 3);
        expect(count(c, "diagonal") == 0, "strict q < delta");
        expect(count(c, "layer") == 2, "all layer candidates");
        c = candidates({0, 0}, 0, {.5, .5}, 0, 1, 2);
        expect(count(c, "end") == 1, "diagonal end");
        c = candidates({0, 0}, 0, {1, 0}, 0, 1, 2);
        expect(count(c, "end") == 0, "strict end distance");
        expect(std::abs(heuristic({0, 0}, {2, 1}) - (1 + std::sqrt(2.))) < eps, "octile heuristic");
        expect(logistic_penalty(0) == 0 && std::abs(logistic_penalty(10) - 100) < eps &&
                   std::abs(logistic_penalty(20) - 200) < eps,
               "logistic endpoints midpoint");
        Board b;
        b.outline = {{0, 0}, {10, 0}, {10, 10}, {0, 10}};
        b.layers = 3;
        b.nets = {{"A", .2, .2}, {"B", .2, .2}};
        Shape via;
        via.id = "via";
        via.net = "A";
        via.kind = "via";
        via.a = via.b = {5, 5};
        via.radius = .3;
        via.drill = .3;
        via.layers = {0, 1, 2};
        Shape obstacle;
        obstacle.id = "middle";
        obstacle.net = "B";
        obstacle.kind = "circle";
        obstacle.a = obstacle.b = {5, 5};
        obstacle.radius = .3;
        obstacle.layers = {1};
        expect(!check_shape(b, via, {obstacle}).empty(), "via middle layer collision");
        obstacle.layers = {0};
        via.layers = {2};
        expect(check_shape(b, via, {obstacle}).empty(), "different layers do not collide");
        bool rejected = false;
        try {
            EasyEdaImporter{}.load("foo.epro");
        } catch (...) {
            rejected = true;
        }
        expect(rejected, "EasyEDA explicit rejection");
        auto sample = [](bool plated) {
            Json pad = {{"id", "p"}, {"net", "A"}, {"kind", "circle"}, {"center", {5, 5}},
                        {"radius", .4}, {"layers", {0, 1}}};
            if (plated)
                pad["plated"] = true;
            return Json{{"schema_version", "1.0"},
                        {"units", "mm"},
                        {"layers", 2},
                        {"outline", {{0, 0}, {10, 0}, {10, 10}, {0, 10}}},
                        {"nets", {{{"id", "A"}, {"width", .2}, {"clearance", .2}}}},
                        {"rules",
                         {{"min_width", .2},
                          {"clearance", .2},
                          {"edge_clearance", .2},
                          {"via_diameter", .6},
                          {"via_drill", .3},
                          {"min_annular", .1}}},
                        {"pads", {pad}}};
        };
        bool unplated = false;
        try {
            parse_board(sample(false));
        } catch (...) {
            unplated = true;
        }
        expect(unplated, "unplated multilayer pad rejected");
        auto plated = parse_board(sample(true));
        expect(plated.copper[0].plated && plated.copper[0].layers.size() == 2, "plated pad keeps both layers");
        Shape link;
        link.id = "wire";
        link.net = "A";
        link.kind = "segment";
        link.a = {5, 5};
        link.b = {8, 5};
        link.radius = .1;
        link.layers = {1};
        Shape other;
        other.id = "q";
        other.net = "A";
        other.kind = "circle";
        other.a = other.b = {8, 5};
        other.radius = .4;
        other.layers = {1};
        plated.copper.push_back(link);
        plated.copper.push_back(other);
        expect(connected(plated, {}, "p", "q"), "plated pad connects copper on its second layer");
        Board finish;
        finish.layers = 2;
        finish.outline = {{0, 0}, {14, 0}, {14, 10}, {0, 10}};
        finish.nets = {{"A", .2, .2}};
        finish.document = {{"pads", {{{"id", "src"}}, {{"id", "dst"}}}}};
        Shape src;
        src.id = "src";
        src.net = "A";
        src.kind = "circle";
        src.plated = true;
        src.a = src.b = {2, 5};
        src.radius = .4;
        src.layers = {0, 1};
        Shape dst;
        dst.id = "dst";
        dst.net = "A";
        dst.kind = "circle";
        dst.a = dst.b = {12, 5};
        dst.radius = .4;
        dst.layers = {1};
        Shape wall;
        wall.id = "wall";
        wall.kind = "polygon";
        wall.polygon = {{4, 0}, {8, 0}, {8, 10}, {4, 10}};
        wall.layers = {0};
        finish.copper = {src, dst};
        finish.keepouts = {wall};
        Config strict;
        strict.algorithm = "adaptive_strict";
        strict.time_limit = 10;
        strict.d_min = .2;
        auto clean = route(finish, strict);
        auto metrics = evaluate(finish, clean.copper);
        expect(metrics["C_routed"] == 1 && metrics["DRC"] == 0 && metrics["VC"] == 0,
               "search starts on every plated layer");
        Board blocked;
        blocked.layers = 1;
        blocked.outline = {{0, 0}, {12, 0}, {12, 8}, {0, 8}};
        blocked.nets = {{"A", .2, .2}, {"B", .2, .2}};
        blocked.document = {{"pads", {{{"id", "left"}}, {{"id", "right"}}}}};
        Shape left;
        left.id = "left";
        left.net = "A";
        left.kind = "circle";
        left.a = left.b = {1.5, 4};
        left.radius = .4;
        left.layers = {0};
        Shape right = left;
        right.id = "right";
        right.a = right.b = {10.5, 4};
        Shape lump;
        lump.id = "lump";
        lump.net = "B";
        lump.kind = "polygon";
        lump.a = lump.b = {6, 4};
        lump.polygon = {{5.2, 3.3}, {6.8, 3.3}, {6.8, 4.7}, {5.2, 4.7}};
        lump.layers = {0};
        blocked.copper = {left, right, lump};
        Shape above;
        above.id = "above";
        above.kind = "polygon";
        above.polygon = {{4, 5}, {8, 5}, {8, 7.5}, {4, 7.5}};
        above.layers = {0};
        Shape below = above;
        below.id = "below";
        below.polygon = {{4, .5}, {8, .5}, {8, 3}, {4, 3}};
        blocked.keepouts = {above, below};
        auto denied = route(blocked, strict);
        expect(evaluate(blocked, denied.copper)["C_routed"] == 0, "strict search rejects the only conflicting corridor");
        Config soft = strict;
        soft.algorithm = "megaroute";
        soft.max_iterations = 1;
        soft.penalty_L = 1;
        auto allowed = route(blocked, soft);
        expect(allowed.has_diagnostic && allowed.last_path_drc > 0, "soft clearance is counted");
        expect(evaluate(blocked, allowed.diagnostic)["DRC"] > 0, "conflicting corridor is retained");
        std::cout << "All core checks passed\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
