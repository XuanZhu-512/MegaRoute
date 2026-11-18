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
        auto zero_minimum = sample(true);
        zero_minimum["rules"]["min_width"] = 0;
        auto zero_minimum_board = parse_board(zero_minimum);
        expect(zero_minimum_board.min_width == 0 && zero_minimum_board.nets[0].width == .2,
               "zero KiCad minimum preserves positive net width");
        auto rejects_board = [](const Json &input) {
            try {
                parse_board(input);
            } catch (const std::runtime_error &) {
                return true;
            }
            return false;
        };
        auto invalid_width = zero_minimum;
        invalid_width["rules"]["min_width"] = -.1;
        expect(rejects_board(invalid_width), "negative global minimum rejected");
        for (double width : {0., -.1}) {
            invalid_width = zero_minimum;
            invalid_width["nets"][0]["width"] = width;
            expect(rejects_board(invalid_width), "nonpositive net width rejected with zero minimum");
        }
        invalid_width = zero_minimum;
        invalid_width["nets"][0].erase("width");
        expect(rejects_board(invalid_width), "zero inherited net width rejected");
        invalid_width = sample(true);
        invalid_width["nets"][0]["width"] = .1;
        expect(rejects_board(invalid_width), "net width below positive minimum rejected");
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
        strict.d_min = .0254;
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
        expect(evaluate(blocked, denied.copper)["DRC"] == 0,
               "strict search never exports a conflicting corridor");
        Config soft = strict;
        soft.algorithm = "megaroute";
        soft.max_iterations = 1;
        soft.penalty_L = 1;
        auto allowed = route(blocked, soft);
        expect(evaluate(blocked, allowed.copper)["DRC"] == 0,
               "one negotiated pass cannot accept immutable copper conflicts");
        expect(evaluate(blocked, allowed.diagnostic)["DRC"] == 0,
               "fixed-pad conflicts are never accepted into diagnostics");
        auto angle_of = [](Point a, Point b, Point c, Point d) {
            Shape left, right;
            left.id = "left";
            right.id = "right";
            left.net = right.net = "A";
            left.kind = right.kind = "segment";
            left.fixed = right.fixed = false;
            left.a = a;
            left.b = b;
            right.a = c;
            right.b = d;
            left.radius = right.radius = .1;
            left.layers = right.layers = {0};
            return std::vector<Shape>{left, right};
        };
        Board angles;
        angles.layers = 1;
        angles.outline = {{0, 0}, {6, 0}, {6, 6}, {0, 6}};
        angles.nets = {{"A", .2, .2}};
        auto has_angle = [](const std::vector<Violation> &vs) {
            return std::any_of(vs.begin(), vs.end(),
                               [](const Violation &v) { return v.rule == "interior_angle"; });
        };
        expect(has_angle(check_board(angles, angle_of({1, 2}, {2, 2}, {2, 2}, {2, 3}))),
               "90 degree corner is rejected");
        expect(!has_angle(check_board(angles, angle_of({1, 2}, {2, 2}, {2, 2}, {3, 2}))), "collinear corner passes");
        expect(!has_angle(check_board(angles, angle_of({1, 2}, {2, 2}, {2, 2}, {3, 3}))), "45 degree corner passes");
        auto overlap = angle_of({1, 2}, {4, 2}, {1, 2}, {3, 2});
        expect(!has_angle(check_board(angles, overlap)), "same-ray overlap is not a corner");
        expect(interior_turn_ok(overlap[0], overlap[1]), "search accepts same-ray overlap");
        auto pad_joint = angle_of({1, 2}, {2, 2}, {2, 2}, {2, 3});
        Shape joint_pad;
        joint_pad.id = "joint_pad";
        joint_pad.net = "A";
        joint_pad.kind = "circle";
        joint_pad.a = joint_pad.b = {2, 2};
        joint_pad.radius = .3;
        joint_pad.layers = {0};
        angles.copper = {joint_pad};
        expect(!has_angle(check_board(angles, pad_joint)), "separate pad exits are not a planar corner");
        expect(interior_turn_ok(pad_joint[0], pad_joint[1], angles.copper), "search permits pad junction");
        angles.copper[0].layers = {1};
        expect(has_angle(check_board(angles, pad_joint)), "pad on another layer does not exempt a corner");
        angles.copper.clear();
        expect(!has_angle(check_board(angles, angle_of({1, 2}, {4, 2}, {1.5, 2}, {3, 2}))),
               "contained collinear segment is not a corner");
        auto fixed_corner = angle_of({1, 2}, {2, 2}, {2, 2}, {2, 3});
        fixed_corner[0].fixed = fixed_corner[1].fixed = true;
        expect(!has_angle(check_board(angles, fixed_corner)), "input copper keeps its own right angle");
        Board open;
        open.layers = 1;
        open.outline = {{0, 0}, {10, 0}, {10, 10}, {0, 10}};
        open.nets = {{"A", .2, .2}};
        open.document = {{"pads", {{{"id", "src"}}, {{"id", "dst"}}}}};
        Shape src_pad;
        src_pad.id = "src";
        src_pad.net = "A";
        src_pad.kind = "circle";
        src_pad.a = src_pad.b = {2, 2};
        src_pad.radius = .3;
        src_pad.layers = {0};
        Shape dst_pad = src_pad;
        dst_pad.id = "dst";
        dst_pad.a = dst_pad.b = {8, 5};
        open.copper = {src_pad, dst_pad};
        auto opened = route(open, strict);
        auto opened_metrics = evaluate(open, opened.copper);
        expect(opened_metrics["C_routed"] == 1 && opened_metrics["DRC"] == 0, "open diagonal stays legal");
        bool bent = false;
        for (size_t i = 0; i < opened.copper.size(); ++i)
            for (size_t j = i + 1; j < opened.copper.size(); ++j) {
                expect(interior_turn_ok(opened.copper[i], opened.copper[j]), "open route turn exceeds 45 degrees");
                if (opened.copper[i].kind == "segment" && opened.copper[j].kind == "segment" &&
                    (distance(opened.copper[i].b, opened.copper[j].a) <= eps ||
                     distance(opened.copper[i].a, opened.copper[j].b) <= eps ||
                     distance(opened.copper[i].a, opened.copper[j].a) <= eps ||
                     distance(opened.copper[i].b, opened.copper[j].b) <= eps)) {
                    Point u = opened.copper[i].b - opened.copper[i].a;
                    Point v = opened.copper[j].b - opened.copper[j].a;
                    double nu = norm(u), nv = norm(v);
                    if (nu > eps && nv > eps) {
                        double c = std::abs(u.x * v.x + u.y * v.y) / (nu * nv);
                        bent = bent || c < 1 - 1e-6;
                    }
                }
            }
        expect(bent, "open diagonal uses a 45 degree bend");
        Board narrow;
        narrow.layers = 1;
        narrow.outline = {{0, 0}, {10, 0}, {10, 10}, {0, 10}};
        narrow.nets = {{"A", .2, .2}};
        narrow.document = {{"pads", {{{"id", "src"}}, {{"id", "dst"}}}}};
        Shape nsrc = src_pad;
        nsrc.a = nsrc.b = {1.5, 2};
        Shape ndst = dst_pad;
        ndst.a = ndst.b = {6, 7.5};
        narrow.copper = {nsrc, ndst};
        auto block = [](const char *id, Point a, Point b) {
            Shape k;
            k.id = id;
            k.kind = "polygon";
            k.polygon = {{a.x, a.y}, {b.x, a.y}, {b.x, b.y}, {a.x, b.y}};
            k.layers = {0};
            return k;
        };
        narrow.keepouts = {block("bottom", {0, 0}, {10, 1.3}),
                           block("left", {0, 1.3}, {.9, 2.7}),
                           block("under", {2.6, 1.3}, {10, 1.85}),
                           block("over_start", {0, 2.15}, {.9, 2.7}),
                           block("over_hall", {2.6, 2.15}, {5.85, 2.7}),
                           block("above", {0, 2.7}, {5.85, 6.6}),
                           block("right", {6.15, 1.85}, {10, 6.6}),
                           block("top_left", {0, 6.6}, {5.3, 10}),
                           block("top_right", {6.7, 6.6}, {10, 10}),
                           block("top", {5.3, 8.6}, {6.7, 10})};
        auto squeezed = route(narrow, strict);
        auto squeezed_metrics = evaluate(narrow, squeezed.copper);
        expect(squeezed_metrics["DRC"] == 0, "narrow corner is not emitted as a 90 degree route");
        for (size_t i = 0; i < squeezed.copper.size(); ++i)
            for (size_t j = i + 1; j < squeezed.copper.size(); ++j)
                expect(interior_turn_ok(squeezed.copper[i], squeezed.copper[j]),
                       "narrow route emits a turn above 45 degrees");
        Board cross;
        cross.layers = 1;
        cross.outline = {{0, 0}, {20, 0}, {20, 10}, {0, 10}};
        cross.nets = {{"A", .2, .2}, {"B", .2, .2}};
        cross.document = {{"pads", {{{"id", "a1"}}, {{"id", "a2"}}, {{"id", "b1"}}, {{"id", "b2"}}}}};
        auto terminal = [](const char *id, const char *net, Point p) {
            Shape s;
            s.id = id;
            s.net = net;
            s.kind = "circle";
            s.a = s.b = p;
            s.radius = .3;
            s.layers = {0};
            return s;
        };
        cross.copper = {terminal("a1", "A", {2, 5}), terminal("a2", "A", {18, 5}), terminal("b1", "B", {10, 2}),
                        terminal("b2", "B", {10, 8})};
        Config one = strict;
        one.algorithm = "megaroute";
        one.max_iterations = 1;
        one.penalty_L = 1;
        auto mixed = route(cross, one);
        auto diagnostic_metrics = evaluate(cross, mixed.diagnostic);
        auto kept_metrics = evaluate(cross, mixed.copper);
        expect(mixed.has_diagnostic && diagnostic_metrics["C_routed"] == 2 && diagnostic_metrics["DRC"] > 0,
               "diagnostic keeps both crossing connections");
        expect(kept_metrics["C_routed"] == 1 && kept_metrics["DRC"] == 0,
               "single negotiated pass exports only the legal subset");
        Board negotiation_board = cross;
        negotiation_board.copper[0].a = negotiation_board.copper[0].b = {6, 5};
        negotiation_board.copper[1].a = negotiation_board.copper[1].b = {14, 5};
        Config negotiation = one;
        negotiation.penalty_L = 200;
        negotiation.max_iterations = 20;
        bool initial_conflict = false;
        auto resolved = route(negotiation_board, negotiation, [&](const Json &event) {
            if (event.at("event") == "route_committed" && event.at("iteration") == 1 &&
                event.at("drc_cost").get<double>() > 0)
                initial_conflict = true;
        });
        auto resolved_metrics = evaluate(negotiation_board, resolved.copper);
        expect(initial_conflict && resolved.iterations > 1, "negotiation begins with a conflict and reroutes");
        expect(resolved_metrics["C_routed"] == 2 && resolved_metrics["DRC"] == 0,
               "increasing logistic penalty resolves the conflict without losing connectivity");
        Board climb;
        climb.layers = 2;
        climb.outline = {{0, 0}, {10, 0}, {10, 10}, {0, 10}};
        climb.nets = {{"A", .2, .2}};
        climb.via_diameter = .3;
        climb.via_drill = .1;
        climb.document = {{"pads", {{{"id", "src"}}, {{"id", "dst"}}}}};
        Shape climb_src = src_pad;
        climb_src.a = climb_src.b = {1.5, 5};
        Shape climb_dst = dst_pad;
        climb_dst.a = climb_dst.b = {6, 8};
        climb_dst.layers = {1};
        climb.copper = {climb_src, climb_dst};
        auto keepout_rect = [](const char *id, Point a, Point b, int layer) {
            Shape k;
            k.id = id;
            k.kind = "polygon";
            k.polygon = {{a.x, a.y}, {b.x, a.y}, {b.x, b.y}, {a.x, b.y}};
            k.layers = {layer};
            return k;
        };
        climb.keepouts = {keepout_rect("l0_bottom", {0, 0}, {10, 4.3}, 0),
                          keepout_rect("l0_top", {0, 5.7}, {10, 10}, 0),
                          keepout_rect("l0_left", {0, 4.3}, {.8, 5.7}, 0),
                          keepout_rect("l0_under", {2.2, 4.3}, {10, 4.8}, 0),
                          keepout_rect("l0_over", {2.2, 5.2}, {10, 5.7}, 0),
                          keepout_rect("l0_end", {6.2, 4.8}, {10, 5.2}, 0),
                          keepout_rect("l1_left", {0, 0}, {5.8, 7.3}, 1),
                          keepout_rect("l1_right", {6.2, 0}, {10, 7.3}, 1),
                          keepout_rect("l1_below", {5.8, 0}, {6.2, 4.8}, 1),
                          keepout_rect("l1_high_left", {0, 7.3}, {5.3, 10}, 1),
                          keepout_rect("l1_high_right", {6.7, 7.3}, {10, 10}, 1),
                          keepout_rect("l1_above", {5.3, 8.8}, {6.7, 10}, 1)};
        Config climb_config = strict;
        climb_config.d_min = .0254; // Paper's 1 mil spatial sampling threshold.
        auto climbed = route(climb, climb_config);
        auto climbed_metrics = evaluate(climb, climbed.copper);
        expect(climbed_metrics["C_routed"] == 1 && climbed_metrics["DRC"] == 0,
               "layer change clears the incoming heading");
        std::cout << "All core checks passed\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
