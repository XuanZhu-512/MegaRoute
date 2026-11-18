#include "megaroute/core.hpp"
#include <algorithm>
#include <iostream>
#include <stdexcept>
using namespace mr;
static void expect(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}
static Shape rectangle(std::string id, Point center, double x0, double y0, double x1, double y1) {
    Shape pad;
    pad.id = id; pad.net = "A"; pad.kind = "polygon";
    pad.a = pad.b = center; pad.layers = {0};
    pad.polygon = {{x0,y0},{x1,y0},{x1,y1},{x0,y1}};
    return pad;
}
static Board fixture() {
    Board b;
    b.layers = 1; b.edge_clearance = 0; b.kicad_fixed_edges = true;
    b.outline = {{0,0},{20,0},{20,20},{0,20}};
    b.nets = {{"A",.4,.2}};
    b.document = {{"pads", {{{"id","source"}}, {{"id","target"}}}}};
    b.copper = {rectangle("source", {3,10}, 2,9,4,11),
                rectangle("target", {20.5,10}, 17,8,22,12)};
    return b;
}
static Config config(std::string algorithm) {
    Config c;
    c.algorithm = algorithm; c.step = .4; c.max_nodes = 20000;
    c.max_records = 80000; c.time_limit = 2; c.max_iterations = 2;
    return c;
}
static Result completes(const Board &b, const std::string &algorithm = "adaptive_strict") {
    auto result = route(b, config(algorithm));
    auto metrics = evaluate(b, result.copper);
    expect(metrics["C_routed"] == 1, "terminal copper regions must connect");
    expect(metrics["DRC"] == 0, "region access must retain all DRC constraints");
    expect(!result.copper.empty(), "virtual source seeds must produce real copper");
    auto restored = parse_routes(routes_json(result.copper), b);
    expect(connected(b, restored, "source", "target"), "serialized copper retains actual connectivity");
    for (const auto &s : result.copper) {
        expect(!s.fixed && contained_in(s, b.outline), "new copper stays inside board");
        expect(boundary_gap(s, b.outline) >= b.edge_clearance-eps, "edge clearance applies to full width");
    }
    return result;
}
int main() {
    try {
        // Centers outside the board are tested on either side and as either end.
        for (auto algorithm : {"baseline_fixed_strict", "adaptive_strict", "megaroute"}) {
            auto b = fixture();
            completes(b, algorithm);
            std::swap(b.copper[0], b.copper[1]);
            completes(b, algorithm);
        }
        auto b = fixture();
        b.copper[0] = rectangle("source", {-.5,10}, -2,8,3,12);
        completes(b); // Both nominal centers are outside, on opposite sides.
        b.edge_clearance = .3;
        // Fixed copper touching the board edge is an existing input violation
        // with positive clearance. Test positive clearance with interior pads.
        b.kicad_fixed_edges = false;
        b.copper = {rectangle("source", {3,10}, 2,9,4,11),
                    rectangle("target", {16,10}, 15,9,17,11)};
        completes(b);

        b = fixture();
        b.copper[1] = rectangle("target", {16,10}, 14,8,18,12);
        b.copper[1].polygon = {{14,10},{16,8},{18,10},{16,12}};
        completes(b); // Rotated, non-axis-aligned polygon.
        b.copper[1].polygon.clear(); b.copper[1].kind = "circle";
        b.copper[1].radius = 1;
        completes(b);

        // Interior board cutouts can also make a nominal pad center unusable.
        b = fixture();
        b.holes = {{{12,8},{14,8},{14,12},{12,12}}};
        b.copper[1] = rectangle("target", {13,10}, 11,7,15,13);
        completes(b);
        std::swap(b.copper[0], b.copper[1]);
        completes(b);

        // Apply a rigid transform: no assumption about board origin or axes.
        b = fixture();
        b.copper[0] = rectangle("source", {-.5,10}, -2,8,3,12);
        auto transform = [](Point p) { return Point{.6*p.x-.8*p.y-100, .8*p.x+.6*p.y+75}; };
        for (auto &p : b.outline) p = transform(p);
        for (auto &pad : b.copper) {
            pad.a = transform(pad.a); pad.b = transform(pad.b);
            for (auto &p : pad.polygon) p = transform(p);
        }
        completes(b);

        // A hole is not terminal copper, even when it contains the source.
        b = fixture();
        b.copper[0] = rectangle("source", {16.5,10}, 16.3,9.8,16.7,10.2);
        b.copper[1] = rectangle("target", {14.5,10}, 14,7,19,13);
        b.copper[1].holes = {{{15,8},{18,8},{18,12},{15,12}}};
        auto ring_result = completes(b);
        expect(!connected(b, {}, "source", "target"), "source in hole starts disconnected");
        expect(evaluate(b, ring_result.copper)["WL_mm"].get<double>() > .1,
               "hole cannot be accepted as a zero-length terminal");
        auto nearest = closest_copper_point({16.5,10}, b.copper[1]);
        expect(inside_copper(nearest, b.copper[1]), "hole guidance lands on copper boundary");

        // Changing layers requires real plated copper (a new via here).
        b = fixture(); b.layers = 2; b.copper[1].layers = {1};
        auto multilayer = completes(b);
        expect(std::any_of(multilayer.copper.begin(), multilayer.copper.end(),
                          [](const Shape &s) { return s.kind == "via"; }),
               "XY overlap on the wrong layer cannot finish a connection");

        // Contact clipping must not bypass an obstacle earlier in the edge.
        b = fixture();
        Shape wall = rectangle("wall", {10,10}, 8,0,12,20);
        wall.net = ""; b.keepouts = {wall};
        auto failed = route(b, config("adaptive_strict"));
        expect(evaluate(b, failed.copper)["C_routed"] == 0, "blocked approach stays disconnected");
        expect(check_board(b, failed.copper).empty(), "failed search emits no illegal shortcut");

        // A pad with no legal board-side access must not create a virtual link.
        b = fixture();
        b.copper[1] = rectangle("target", {23,10}, 22,9,24,11);
        auto impossible = route(b, config("adaptive_strict"));
        expect(evaluate(b, impossible.copper)["C_routed"] == 0, "fully exterior pad is not reached");
        std::cout << "terminal region checks passed\n";
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n'; return 1;
    }
}
