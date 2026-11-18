#include "megaroute/core.hpp"
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <set>
namespace mr {
static void require(bool ok, const std::string &msg) {
    if (!ok)
        throw std::runtime_error("invalid_input: " + msg);
}
static void fields(const Json &j, std::initializer_list<const char *> allowed) {
    require(j.is_object(), "expected object");
    std::set<std::string> names;
    for (auto x : allowed)
        names.insert(x);
    for (auto it = j.begin(); it != j.end(); ++it)
        require(names.count(it.key()), "unsupported field: " + it.key());
}
static double number(const Json &j) {
    require(j.is_number(), "expected number");
    double v = j.get<double>();
    require(std::isfinite(v) && std::abs(v) <= 1e6, "non-finite or excessive numeric value");
    return v;
}
static Point point(const Json &j) {
    require(j.is_array() && j.size() == 2, "point must be [x,y]");
    return {number(j[0]), number(j[1])};
}
static std::vector<Point> polygon(const Json &j) {
    require(j.is_array(), "polygon must be array");
    std::vector<Point> p;
    for (const auto &v : j)
        p.push_back(point(v));
    require(simple_polygon(p), "polygon must be simple, non-degenerate, without repeated closing point");
    return p;
}
const Net &net(const Board &b, const std::string &id) {
    for (const auto &n : b.nets)
        if (n.id == id)
            return n;
    throw std::runtime_error("invalid_input: unknown net " + id);
}
static std::vector<int> layers(const Json &j, int count) {
    require(j.is_array() && !j.empty(), "empty layers");
    std::set<int> result;
    for (const auto &z : j) {
        require(z.is_number_integer(), "layer must be integer");
        int v = z.get<int>();
        require(v >= 0 && v < count && result.insert(v).second, "invalid/duplicate layer");
    }
    return {result.begin(), result.end()};
}
static Shape shape(const Json &j, const Board &b, bool fixed) {
    fields(j, {"id", "net", "kind", "center", "radius", "points", "a", "b", "width", "layers", "drill", "plated",
               "clearance_override", "copper_group", "holes"});
    Shape s;
    s.id = j.at("id").get<std::string>();
    require(!s.id.empty(), "empty shape id");
    s.kind = j.at("kind").get<std::string>();
    s.net = j.value("net", std::string{});
    s.fixed = fixed;
    if (j.contains("clearance_override")) {
        require(fixed, "route clearance overrides are not supported");
        s.clearance_override = number(j.at("clearance_override"));
        require(s.clearance_override >= 0, "negative clearance override");
    }
    s.copper_group = j.value("copper_group", std::string{});
    require(s.copper_group.empty() || (fixed && s.net.empty()), "copper group requires fixed netless copper");
    if (j.contains("plated")) {
        require(j.at("plated").is_boolean(), "plated must be boolean");
        s.plated = j.at("plated").get<bool>();
    }
    if (!s.net.empty())
        net(b, s.net);
    s.layers = layers(j.at("layers"), b.layers);
    if (s.kind == "circle" || s.kind == "via") {
        s.a = s.b = point(j.at("center"));
        s.radius = number(j.at("radius"));
        require(s.radius > 0, "radius must be positive");
        if (s.kind == "via") {
            s.drill = number(j.at("drill"));
            require(s.drill > 0 && s.drill < 2 * s.radius, "invalid via drill");
            require(s.layers.size() == static_cast<size_t>(b.layers),
                    "unsupported_feature: only through vias supported");
        }
    } else if (s.kind == "segment") {
        s.a = point(j.at("a"));
        s.b = point(j.at("b"));
        s.radius = number(j.at("width")) / 2;
        require(s.radius > 0 && s.layers.size() == 1, "segment requires width>0 and one layer");
    } else if (s.kind == "polygon") {
        s.polygon = polygon(j.at("points"));
        const auto hole_rings = j.value("holes", Json::array());
        require(hole_rings.is_array(), "polygon holes must be array");
        for (const auto &ring : hole_rings) {
            Shape h;
            h.polygon = polygon(ring);
            require(contained_in(h, s.polygon) && boundary_gap(h, s.polygon) > eps,
                    "copper hole must be strictly inside outer ring");
            for (const auto &old : s.holes) {
                Shape other;
                other.polygon = old;
                require(gap(h, other) > eps, "copper holes overlap or touch");
            }
            s.holes.push_back(h.polygon);
        }
        s.a = s.b = point(j.at("center"));
        require(inside_copper(s.a, s), "polygon access center outside copper");
    } else
        throw std::runtime_error("unsupported_feature: shape " + s.kind);
    require(!j.contains("holes") || s.kind == "polygon", "holes require polygon");
    require(!s.plated || s.kind == "circle" || s.kind == "polygon", "plated applies only to pads");
    if (s.kind != "via" && !s.plated)
        require(s.layers.size() == 1,
                "unsupported_feature: multilayer copper requires plated=true");
    return s;
}
Board parse_board(const Json &j) {
    fields(j, {"schema_version", "units", "layers", "outline", "holes", "nets", "pads", "fixed_copper",
               "keepouts", "rules", "metadata"});
    require(j.at("schema_version") == "1.0", "unknown board schema_version");
    require(j.at("units") == "mm", "units must be mm");
    Board b;
    b.document = j;
    require(j.at("layers").is_number_integer(), "layers must be integer");
    b.layers = j.at("layers").get<int>();
    require(b.layers >= 1 && b.layers <= 32, "layer count out of range");
    b.outline = polygon(j.at("outline"));
    for (const auto &v : j.value("holes", Json::array())) {
        auto p = polygon(v);
        Shape h;
        h.polygon = p;
        for (auto x : p)
            require(inside(x, b.outline), "hole outside outline");
        require(boundary_gap(h, b.outline) > eps, "hole touches outline");
        for (const auto &old : b.holes) {
            Shape q;
            q.polygon = old;
            require(gap(h, q) > eps, "overlapping holes");
        }
        b.holes.push_back(p);
    }
    const auto &r = j.at("rules");
    fields(r, {"min_width", "clearance", "edge_clearance", "via_diameter", "via_drill", "min_annular",
               "fixed_boundary_policy"});
    b.min_width = number(r.at("min_width"));
    double clear = number(r.at("clearance"));
    b.min_clearance = clear;
    auto boundary_policy = r.value("fixed_boundary_policy", std::string("contained"));
    require(boundary_policy == "contained" || boundary_policy == "kicad_edges", "invalid fixed boundary policy");
    b.kicad_fixed_edges = boundary_policy == "kicad_edges";
    b.edge_clearance = number(r.at("edge_clearance"));
    b.via_diameter = number(r.at("via_diameter"));
    b.via_drill = number(r.at("via_drill"));
    b.min_annular = number(r.at("min_annular"));
    // KiCad permits a zero global minimum; each net still needs a positive routing width.
    require(b.min_width >= 0 && clear >= 0 && b.edge_clearance >= 0 && b.min_annular >= 0 && b.via_drill > 0 &&
                b.via_diameter > b.via_drill,
            "invalid rules");
    require((b.via_diameter - b.via_drill) / 2 >= b.min_annular - eps,
            "configured via violates annular rule");
    std::set<std::string> ids;
    require(j.at("nets").is_array(), "nets must be array");
    for (const auto &n : j.at("nets")) {
        fields(n, {"id", "width", "clearance"});
        Net x;
        x.id = n.at("id").get<std::string>();
        x.width = n.contains("width") ? number(n["width"]) : b.min_width;
        x.clearance = n.contains("clearance") ? number(n["clearance"]) : clear;
        require(!x.id.empty() && ids.insert(x.id).second, "duplicate/empty net id");
        require(x.width > 0 && x.width >= b.min_width && x.clearance >= 0, "invalid net rules");
        b.nets.push_back(x);
    }
    ids.clear();
    for (auto key : {"pads", "fixed_copper"}) {
        const auto objects = j.value(key, Json::array());
        require(objects.is_array(), "copper collection must be array");
        for (const auto &v : objects) {
            auto s = shape(v, b, true);
            require(ids.insert(s.id).second, "duplicate object id");
            if (std::string(key) == "pads")
                require((s.kind == "circle" || s.kind == "polygon") && !s.net.empty(),
                        "pad requires net and circle/polygon");
            else
                require(s.kind == "segment" || s.kind == "via" || s.kind == "polygon",
                        "fixed_copper supports segment/via/polygon");
            b.copper.push_back(s);
        }
    }
    for (const auto &v : j.value("keepouts", Json::array())) {
        fields(v, {"id", "points", "layers"});
        Shape s;
        s.id = v.at("id").get<std::string>();
        require(!s.id.empty() && ids.insert(s.id).second, "duplicate/empty keepout id");
        s.kind = "polygon";
        s.polygon = polygon(v.at("points"));
        s.layers = layers(v.at("layers"), b.layers);
        b.keepouts.push_back(s);
    }
    return b;
}
Config parse_config(const Json &j) {
    fields(j, {"schema_version", "algorithm", "step_mm", "beta", "d_min_mm", "lambda_v", "time_limit_s",
               "max_expanded_nodes", "max_records", "max_iterations", "penalty_L", "penalty_k", "penalty_mu",
               "history_weight", "history_cell_mm", "stagnation_rounds", "refinement_levels"});
    require(j.at("schema_version") == "1.0", "unknown config schema");
    Config c;
    c.algorithm = j.value("algorithm", c.algorithm);
    require(c.algorithm == "baseline_fixed_strict" || c.algorithm == "adaptive_strict" || c.algorithm == "megaroute",
            "unsupported_algorithm: use megaroute for negotiated rerouting");
    auto set = [&](const char *key, double &value) {
        if (j.contains(key))
            value = number(j[key]);
    };
    set("step_mm", c.step);
    set("beta", c.beta);
    set("d_min_mm", c.d_min);
    set("lambda_v", c.lambda_v);
    set("time_limit_s", c.time_limit);
    set("penalty_L", c.penalty_L);
    set("penalty_k", c.penalty_k);
    set("penalty_mu", c.penalty_mu);
    set("history_weight", c.history_weight);
    set("history_cell_mm", c.history_cell);
    for (auto item : {std::pair<const char *, int *>{"stagnation_rounds", &c.stagnation_rounds},
                      {"refinement_levels", &c.refinement_levels}}) {
        if (!j.contains(item.first)) continue;
        require(j.at(item.first).is_number_integer(), "search control must be integer");
        auto value = j.at(item.first).get<long long>();
        require(value >= (std::string(item.first) == "refinement_levels" ? 0 : 1) &&
                value <= (std::string(item.first) == "refinement_levels" ? 4 : 100), "search control out of range");
        *item.second = static_cast<int>(value);
    }
    if (j.contains("max_iterations")) {
        require(j.at("max_iterations").is_number_integer(), "max_iterations must be integer");
        auto v = j.at("max_iterations").get<long long>();
        require(v >= 1 && v <= 100, "max_iterations must be 1..100");
        c.max_iterations = static_cast<int>(v);
    }
    for (auto item : {std::pair<const char *, size_t *>{"max_expanded_nodes", &c.max_nodes},
                      {"max_records", &c.max_records}})
        if (j.contains(item.first)) {
            require(j[item.first].is_number_integer(), "budget must be integer");
            auto v = j[item.first].get<long long>();
            require(v > 0 && v <= 10000000, "budget out of range");
            *item.second = static_cast<size_t>(v);
        }
    require(c.step > eps && c.d_min >= 0 && c.beta >= 1 && c.lambda_v >= 0 && c.time_limit > 0,
            "invalid config range");
    require(c.penalty_L > 0 && c.penalty_k > 0 && c.penalty_mu > 0, "invalid logistic penalty");
    require(c.history_weight >= 0 && c.history_cell > eps, "invalid congestion parameters");
    if (c.algorithm == "megaroute")
        logistic_penalty(1, c.penalty_L, c.penalty_k, c.penalty_mu);
    return c;
}
Json config_json(const Config &c) {
    return {{"schema_version", "1.0"},
            {"algorithm", c.algorithm},
            {"step_mm", c.step},
            {"beta", c.beta},
            {"d_min_mm", c.d_min},
            {"lambda_v", c.lambda_v},
            {"time_limit_s", c.time_limit},
            {"max_expanded_nodes", c.max_nodes},
            {"max_records", c.max_records},
            {"max_iterations", c.max_iterations},
            {"penalty_L", c.penalty_L},
            {"penalty_k", c.penalty_k},
            {"penalty_mu", c.penalty_mu},
            {"history_weight", c.history_weight},
            {"history_cell_mm", c.history_cell},
            {"stagnation_rounds", c.stagnation_rounds},
            {"refinement_levels", c.refinement_levels}};
}
Json routes_json(const std::vector<Shape> &ss) {
    Json arr = Json::array();
    for (const auto &s : ss) {
        Json j = {{"id", s.id}, {"net", s.net}, {"kind", s.kind}, {"layers", s.layers}};
        if (s.kind == "segment") {
            j["a"] = {s.a.x, s.a.y};
            j["b"] = {s.b.x, s.b.y};
            j["width"] = 2 * s.radius;
        } else {
            j["center"] = {s.a.x, s.a.y};
            j["radius"] = s.radius;
            j["drill"] = s.drill;
        }
        arr.push_back(j);
    }
    return {{"schema_version", "1.0"}, {"copper", arr}};
}
std::vector<Shape> parse_routes(const Json &j, const Board &b) {
    fields(j, {"schema_version", "copper"});
    require(j.at("schema_version") == "1.0", "unknown routes schema");
    require(j.at("copper").is_array(), "copper must be array");
    std::set<std::string> ids;
    for (auto &s : b.copper)
        ids.insert(s.id);
    for (auto &s : b.keepouts)
        ids.insert(s.id);
    std::vector<Shape> out;
    for (const auto &v : j.at("copper")) {
        auto s = shape(v, b, false);
        require(!s.net.empty() && (s.kind == "segment" || s.kind == "via"),
                "routes must contain net-associated segments/vias");
        require(ids.insert(s.id).second, "duplicate route id");
        out.push_back(s);
    }
    return out;
}
Json read_json(const std::string &path) {
    std::ifstream f(path);
    if (!f)
        throw std::runtime_error("cannot open: " + path);
    Json j;
    f >> j;
    return j;
}
void write_json(const std::string &path, const Json &j) {
    std::ofstream f(path);
    if (!f)
        throw std::runtime_error("cannot write: " + path);
    f << j.dump(2) << '\n';
    if (!f)
        throw std::runtime_error("write failed: " + path);
}
Board JsonImporter::load(const std::string &path) {
    if (std::filesystem::path(path).extension() != ".json")
        throw std::runtime_error("unsupported_format: only neutral JSON is implemented");
    return parse_board(read_json(path));
}
Board EasyEdaImporter::load(const std::string &) {
    throw std::runtime_error("unsupported_format: EasyEDA adapter reserved");
}
} // namespace mr
