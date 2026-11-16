#include "megaroute/core.hpp"
#include <algorithm>
#include <map>
#include <numeric>
#include <set>
#include <tuple>
namespace mr {
std::vector<Violation> check_shape(const Board &b, const Shape &s, const std::vector<Shape> &copper) {
    std::vector<Violation> out;
    auto add = [&](std::string rule, std::string other, int z, double measured, double required, bool fixed) {
        out.push_back({rule, s.id, other, z, measured, required, fixed});
    };
    bool contained = inside(s.a, b.outline) && inside(s.b, b.outline);
    for (auto p : s.polygon)
        contained = contained && inside(p, b.outline);
    double edge = boundary_gap(s, b.outline);
    for (int z : s.layers) {
        if (!contained || edge < b.edge_clearance - eps || edge <= eps)
            add("board_edge", "outline", z, edge, b.edge_clearance, s.fixed);
        if (s.kind == "segment" && 2 * s.radius < b.min_width - eps)
            add("min_width", "", z, 2 * s.radius, b.min_width, s.fixed);
        if (s.kind == "via" && s.radius - s.drill / 2 < b.min_annular - eps)
            add("annular_ring", "", z, s.radius - s.drill / 2, b.min_annular, s.fixed);
        for (size_t i = 0; i < b.holes.size(); ++i) {
            Shape h;
            h.polygon = b.holes[i];
            double d = gap(s, h);
            if (d <= eps || d < b.edge_clearance - eps)
                add("board_hole", "hole_" + std::to_string(i), z, d, b.edge_clearance, s.fixed);
        }
        for (const auto &k : b.keepouts)
            if (std::find(k.layers.begin(), k.layers.end(), z) != k.layers.end()) {
                double d = gap(s, k);
                if (d <= eps)
                    add("keepout", k.id, z, d, 0, s.fixed);
            }
    }
    for (const auto &o : copper) {
        if (o.id == s.id || (!s.net.empty() && s.net == o.net) || !share_layer(s, o))
            continue;
        double d = gap(s, o);
        double c = std::max(s.net.empty() ? 0. : net(b, s.net).clearance,
                            o.net.empty() ? 0. : net(b, o.net).clearance);
        if (d <= eps || d < c - eps)
            for (int z : s.layers)
                if (std::find(o.layers.begin(), o.layers.end(), z) != o.layers.end())
                    add(d <= eps ? "short" : "clearance", o.id, z, d, c, s.fixed && o.fixed);
    }
    return out;
}
std::vector<Violation> check_board(const Board &b, const std::vector<Shape> &added) {
    auto all = b.copper;
    all.insert(all.end(), added.begin(), added.end());
    std::vector<Violation> out;
    std::set<std::tuple<std::string, std::string, std::string, int>> seen;
    for (const auto &s : all)
        for (auto v : check_shape(b, s, all)) {
            auto a = v.a, c = v.b;
            if (c < a)
                std::swap(a, c);
            if (seen.emplace(v.rule, a, c, v.layer).second)
                out.push_back(v);
        }
    return out;
}
struct DSU {
    std::vector<size_t> p;
    explicit DSU(size_t n) : p(n) {
        std::iota(p.begin(), p.end(), 0);
    }
    size_t root(size_t x) {
        while (p[x] != x) {
            p[x] = p[p[x]];
            x = p[x];
        }
        return x;
    }
    void join(size_t a, size_t b) {
        p[root(a)] = root(b);
    }
};
static DSU components(const std::vector<Shape> &all) {
    DSU d(all.size());
    for (size_t i = 0; i < all.size(); ++i)
        for (size_t j = 0; j < i; ++j)
            if (!all[i].net.empty() && all[i].net == all[j].net && share_layer(all[i], all[j]) &&
                gap(all[i], all[j]) <= eps)
                d.join(i, j);
    return d;
}
bool connected(const Board &b, const std::vector<Shape> &added, const std::string &a, const std::string &c) {
    auto all = b.copper;
    all.insert(all.end(), added.begin(), added.end());
    auto d = components(all);
    size_t ia = all.size(), ic = all.size();
    for (size_t i = 0; i < all.size(); ++i) {
        if (all[i].id == a)
            ia = i;
        if (all[i].id == c)
            ic = i;
    }
    return ia < all.size() && ic < all.size() && d.root(ia) == d.root(ic);
}
std::vector<Connection> requirements(const Board &b) {
    auto d = components(b.copper);
    std::set<std::string> pads;
    for (const auto &p : b.document.value("pads", Json::array()))
        pads.insert(p.at("id").get<std::string>());
    struct Edge {
        double length;
        std::string a, b, net;
        size_t i, j;
    };
    std::vector<Edge> edges;
    for (size_t i = 0; i < b.copper.size(); ++i)
        for (size_t j = 0; j < i; ++j) {
            auto &a = b.copper[i];
            auto &c = b.copper[j];
            if (pads.count(a.id) && pads.count(c.id) && a.net == c.net)
                edges.push_back(
                    {distance(a.a, c.a), std::min(a.id, c.id), std::max(a.id, c.id), a.net, i, j});
        }
    std::sort(edges.begin(), edges.end(),
              [](auto &a, auto &b) { return std::tie(a.length, a.a, a.b) < std::tie(b.length, b.a, b.b); });
    std::vector<Connection> out;
    for (auto &e : edges)
        if (d.root(e.i) != d.root(e.j)) {
            d.join(e.i, e.j);
            out.push_back({e.net, e.a, e.b});
        }
    return out;
}
// Length of the union of collinear centerlines. Split crossings have zero measure.
static double wire_length(const std::vector<Shape> &shapes) {
    double total = 0;
    for (size_t i = 0; i < shapes.size(); ++i) {
        auto &s = shapes[i];
        if (s.kind != "segment")
            continue;
        double len = distance(s.a, s.b);
        if (len <= eps)
            continue;
        Point u = (s.b - s.a) * (1 / len);
        std::vector<std::pair<double, double>> covered;
        for (size_t j = 0; j < i; ++j) {
            auto &t = shapes[j];
            if (t.kind != "segment" || t.net != s.net || t.layers != s.layers)
                continue;
            auto proj = [&](Point p) {
                auto v = p - s.a;
                return v.x * u.x + v.y * u.y;
            };
            auto off = [&](Point p) {
                auto v = p - s.a;
                return std::abs(v.x * u.y - v.y * u.x);
            };
            if (off(t.a) > eps || off(t.b) > eps)
                continue;
            double a = proj(t.a), b = proj(t.b);
            if (a > b)
                std::swap(a, b);
            a = std::max(0., a);
            b = std::min(len, b);
            if (a < b)
                covered.push_back({a, b});
        }
        std::sort(covered.begin(), covered.end());
        double overlap = 0, end = 0;
        for (auto interval : covered) {
            overlap += std::max(0., interval.second - std::max(end, interval.first));
            end = std::max(end, interval.second);
        }
        total += len - overlap;
    }
    return total;
}
Json evaluate(const Board &b, const std::vector<Shape> &added) {
    auto all = b.copper;
    all.insert(all.end(), added.begin(), added.end());
    auto d = components(all);
    std::map<std::string, size_t> ids;
    for (size_t i = 0; i < all.size(); ++i)
        ids[all[i].id] = i;
    auto q = requirements(b);
    size_t routed = 0;
    Json missing = Json::array();
    std::map<std::string, bool> nets;
    for (auto &e : q) {
        if (!nets.count(e.net))
            nets[e.net] = true;
        if (d.root(ids.at(e.a)) == d.root(ids.at(e.b)))
            ++routed;
        else {
            nets[e.net] = false;
            missing.push_back({{"net", e.net}, {"a", e.a}, {"b", e.b}});
        }
    }
    auto violations = check_board(b, added);
    Json drc = Json::array();
    size_t fixed = 0;
    for (auto &v : violations) {
        fixed += v.fixed;
        drc.push_back({{"rule", v.rule},
                       {"a", v.a},
                       {"b", v.b},
                       {"layer", v.layer},
                       {"measured_mm", v.measured},
                       {"required_mm", v.required},
                       {"fixed_input", v.fixed}});
    }
    size_t vias = 0;
    for (size_t i = 0; i < added.size(); ++i)
        if (added[i].kind == "via") {
            bool unique = true;
            for (size_t j = 0; j < i; ++j)
                if (added[j].kind == "via" && added[j].net == added[i].net &&
                    added[j].layers == added[i].layers && distance(added[j].a, added[i].a) <= eps &&
                    std::abs(added[j].radius - added[i].radius) <= eps &&
                    std::abs(added[j].drill - added[i].drill) <= eps)
                    unique = false;
            vias += unique;
        }
    double wl = wire_length(added);
    size_t full = 0;
    for (auto &n : nets)
        full += n.second;
    return {{"schema_version", "1.0"},
            {"metrics_scope", "internal_geometry_diagnostics"},
            {"C_total", q.size()},
            {"C_routed", routed},
            {"R", q.empty() ? Json(nullptr) : Json(double(routed) / q.size())},
            {"WL_mm", wl},
            {"VC", vias},
            {"meanWL", routed ? Json(wl / routed) : Json(nullptr)},
            {"meanVC", routed ? Json(double(vias) / routed) : Json(nullptr)},
            {"DRC", violations.size()},
            {"fixed_input_DRC", fixed},
            {"added_DRC", violations.size() - fixed},
            {"fixed_WL_mm", wire_length(b.copper)},
            {"fully_connected_nets", full},
            {"nets_requiring_routing", nets.size()},
            {"missing_connections", missing},
            {"violations", drc},
            {"status", violations.empty()
                           ? (routed == q.size() ? "complete" : "partial")
                           : (routed == q.size() ? "completed_with_violations" : "partial_with_violations")},
            {"epsilon_mm", eps},
            {"supported_rules",
             {"copper_short", "clearance", "min_width", "board_edge", "board_hole", "keepout", "annular_ring",
              "through_via_span", "connectivity"}},
            {"unsupported_features",
             {"blind_buried_vias", "polygon_pad_holes", "net_class_pair_rules",
              "differential_pairs", "length_matching", "manufacturing_drill_clearance", "full_angle_rules",
              "EasyEDA"}}};
}
} // namespace mr
