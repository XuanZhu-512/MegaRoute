#include "megaroute/core.hpp"
#include <iostream>
#include <stdexcept>
using namespace mr;
static void expect(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}
static Shape circle(std::string id, std::string net_id, Point center, double radius = .1) {
    Shape s;
    s.id = id; s.net = net_id; s.kind = "circle";
    s.a = s.b = center; s.radius = radius; s.layers = {0};
    return s;
}
static Board board() {
    Board b;
    b.layers = 1; b.outline = {{0, 0}, {20, 0}, {20, 20}, {0, 20}};
    b.nets = {{"A", .2, .254}, {"B", .2, .2}};
    b.min_clearance = .025;
    return b;
}
int main() {
    try {
        auto b = board();
        auto a = circle("a", "A", {5, 5});
        auto o = circle("o", "B", {5.3, 5}); // .1 gap
        std::vector<Shape> others{o};
        expect(!check_shape(b, a, others).empty(), "inherited net rule enforced");
        a.clearance_override = .05;
        expect(check_shape(b, a, others).empty(), "one override replaces both net-class rules");
        others[0].clearance_override = .15;
        expect(!check_shape(b, a, others).empty(), "maximum of two local overrides");
        others[0].clearance_override = -1;
        b.min_clearance = .12;
        expect(!check_shape(b, a, others).empty(), "board minimum clamps local override");
        b.min_clearance = .025; a.clearance_override = 0;
        expect(!check_shape(b, a, others).empty(), "zero override falls back to net rule");
        a.clearance_override = .05; a.a = a.b = others[0].a;
        expect(!check_shape(b, a, others).empty(), "override never permits short");

        a = circle("a", "A", {5, 5});
        others[0] = circle("obstacle", "", {7, 5});
        others[0].clearance_override = 2;
        CopperIndex index(others);
        expect(check_shape(b, a, others, &index).size() == check_shape(b, a, others).size(),
               "index includes large obstacle override");
        expect(!check_shape(b, a, others, &index).empty(), "netless obstacle override enforced");
        others.push_back(circle("appended", "", {12, 5}));
        others.back().clearance_override = 8;
        index.insert(1);
        expect(index.max_clearance_override() == 8, "append updates clearance search radius");
        a.clearance_override = 9;
        expect(check_shape(b, a, others, &index).size() == check_shape(b, a, others).size(),
               "index includes querying object's override");

        b = board(); b.edge_clearance = 0;
        Shape pad;
        pad.id = "edge-pad"; pad.kind = "polygon"; pad.layers = {0};
        pad.a = pad.b = {0, 5};
        pad.polygon = {{-1, 4}, {1, 4}, {1, 6}, {-1, 6}};
        expect(!check_shape(b, pad, {}).empty(), "legacy fixed copper remains contained");
        b.kicad_fixed_edges = true;
        expect(check_shape(b, pad, {}).empty(), "zero KiCad edge distance permits fixed polygon overhang");
        b.edge_clearance = .1;
        expect(!check_shape(b, pad, {}).empty(), "positive edge distance still enforced");
        b.edge_clearance = 0; pad.fixed = false;
        expect(!check_shape(b, pad, {}).empty(), "new copper must stay inside outline");
        b.holes = {{{8, 8}, {12, 8}, {12, 12}, {8, 12}}};
        auto mount = circle("mount", "", {10, 10}, .5);
        b.edge_clearance = .2;
        expect(check_shape(b, mount, {}).empty(), "fixed copper in cutout uses boundary distance");
        mount.fixed = false;
        expect(!check_shape(b, mount, {}).empty(), "new copper cannot enter cutout");
        mount.fixed = true; mount.a = mount.b = {8.6, 10};
        expect(!check_shape(b, mount, {}).empty(), "fixed cutout edge clearance enforced");
        b.edge_clearance = 0;
        mount.fixed = false; mount.a = mount.b = {8, 10};
        expect(!check_shape(b, mount, {}).empty(), "new copper cannot cross cutout at zero clearance");

        b = board();
        Shape stroke;
        stroke.id = "text:0"; stroke.kind = "segment"; stroke.layers = {0};
        stroke.a = {5, 5}; stroke.b = {6, 5}; stroke.radius = .03;
        stroke.copper_group = "text";
        auto second = stroke; second.id = "text:1";
        expect(check_shape(b, stroke, {second}).empty(), "glyph strokes are not traces or mutual shorts");
        second.copper_group = "different-text";
        expect(!check_shape(b, stroke, {second}).empty(), "different text remains an obstacle");
        auto trace = stroke; trace.id = "trace"; trace.net = "A"; trace.fixed = false;
        trace.copper_group.clear(); trace.radius = .1;
        expect(!check_shape(b, trace, {stroke}).empty(), "new trace collides with copper text");
        std::vector<Shape> glyph;
        const std::vector<Point> ring = {{8, 8}, {12, 8}, {12, 12}, {8, 12}};
        for (size_t i = 0; i < ring.size(); ++i) {
            auto piece = stroke; piece.id = "O:" + std::to_string(i);
            piece.a = ring[i]; piece.b = ring[(i + 1) % ring.size()]; glyph.push_back(piece);
        }
        trace.a = {9, 10}; trace.b = {11, 10};
        expect(check_shape(b, trace, glyph).empty(), "glyph interior remains free for routing");

        auto document = Json::parse(R"({"schema_version":"1.0","units":"mm","layers":1,
          "outline":[[0,0],[20,0],[20,20],[0,20]],"nets":[{"id":"A","width":0.2}],
          "pads":[{"id":"p","net":"A","kind":"circle","center":[5,5],"radius":0.5,
                   "layers":[0],"clearance_override":0}],
          "rules":{"min_width":0.2,"clearance":0.025,"edge_clearance":0,"via_diameter":0.6,
                   "via_drill":0.3,"min_annular":0.1}})");
        auto parsed = parse_board(document);
        expect(!parsed.kicad_fixed_edges && parsed.min_clearance == .025 &&
               parsed.copper[0].clearance_override == 0, "optional fields round-trip through parser");
        document["rules"]["fixed_boundary_policy"] = "kicad_edges";
        expect(parse_board(document).kicad_fixed_edges, "import policy parsed explicitly");
        auto rejects = [](const Json &doc) {
            try { parse_board(doc); return false; } catch (const std::exception &) { return true; }
        };
        document["pads"][0]["clearance_override"] = -1;
        expect(rejects(document), "negative explicit override rejected");
        document["pads"][0]["clearance_override"] = 0;
        document["rules"]["fixed_boundary_policy"] = "ignore";
        expect(rejects(document), "unknown boundary policy rejected");
        std::cout << "rule semantics passed\n";
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n'; return 1;
    }
}
