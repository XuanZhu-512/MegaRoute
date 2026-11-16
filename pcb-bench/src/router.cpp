#include "megaroute/core.hpp"
#include <algorithm>
#include <array>
#include <map>
#include <numeric>
#include <queue>
#include <tuple>
namespace mr {
double heuristic(Point p, Point t) {
    double a = std::abs(t.x - p.x), b = std::abs(t.y - p.y);
    return std::max(a, b) + (std::sqrt(2.) - 1) * std::min(a, b);
}
double logistic_penalty(int i, double L, double k, double mu) {
    if (i < 0 || L <= 0 || k <= 0 || mu <= 0)
        throw std::runtime_error("invalid logistic arguments");
    auto f = [&](double x) { return 1 / (1 + std::exp(-k * (x - mu))); };
    double den = f(2 * mu) - f(0);
    if (den <= 0)
        throw std::runtime_error("degenerate logistic denominator");
    return L * (f(i) - f(0)) / den;
}
std::vector<Candidate> candidates(Point p, int z, Point t, int tz, double delta, int layers) {
    std::vector<Candidate> out;
    for (auto v :
         std::array<Point, 8>{{{1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}, {0, -1}, {1, -1}}})
        out.push_back({p + v * delta, z, "obstacle_aware"});
    double dx = t.x - p.x, dy = t.y - p.y, a = std::abs(dx), b = std::abs(dy), q = std::abs(a - b);
    if (a > eps && b > eps)
        out.push_back({a < b ? Point{t.x, p.y} : Point{p.x, t.y}, z, "axis"});
    if (q > eps && q < delta)
        out.push_back(
            {a < b ? Point{p.x, p.y + std::copysign(q, dy)} : Point{p.x + std::copysign(q, dx), p.y}, z,
             "diagonal"});
    for (int next = 0; next < layers; ++next)
        if (next != z)
            out.push_back({p, next, "layer"});
    if (z == tz && distance(p, t) < delta && (a <= eps || b <= eps || std::abs(a - b) <= eps))
        out.push_back({t, z, "end"});
    return out;
}
static Shape edge(Point a, int z, Point b, int next, const Board &board, const Net &n) {
    Shape s;
    // Valid input IDs cannot be empty, so a candidate never aliases fixed copper.
    s.id = "";
    s.net = n.id;
    s.a = a;
    s.b = b;
    s.fixed = false;
    if (z == next) {
        s.kind = "segment";
        s.radius = n.width / 2;
        s.layers = {z};
    } else {
        s.kind = "via";
        s.b = s.a;
        s.radius = board.via_diameter / 2;
        s.drill = board.via_drill;
        s.layers.resize(board.layers);
        std::iota(s.layers.begin(), s.layers.end(), 0);
    }
    return s;
}
struct Node {
    Point p;
    int z, parent;
    double g;
};
using Bucket = std::tuple<long long, long long, int>;
static Bucket bucket(Point p, int z, double cell) {
    return {static_cast<long long>(std::floor(p.x / cell)), static_cast<long long>(std::floor(p.y / cell)),
            z};
}
Result route(const Board &b, const Config &c, Observer observer) {
    Result result;
    auto start = std::chrono::steady_clock::now();
    auto expired = [&] {
        return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() >=
               c.time_limit;
    };
    if (!check_board(b, {}).empty()) {
        result.reason = "input_drc_violations";
        return result;
    }
    auto req = requirements(b);
    std::map<std::string, Shape> pads;
    for (auto &s : b.copper)
        pads[s.id] = s;
    std::map<std::string, double> totals;
    for (auto &q : req)
        totals[q.net] += distance(pads.at(q.a).a, pads.at(q.b).a);
    std::stable_sort(req.begin(), req.end(), [&](auto &a, auto &d) {
        if (totals[a.net] != totals[d.net])
            return totals[a.net] > totals[d.net];
        return std::tie(a.net, a.a, a.b) < std::tie(d.net, d.a, d.b);
    });
    size_t serial = 0;
    for (auto &q : req) {
        if (expired()) {
            result.reason = "timeout";
            break;
        }
        if (connected(b, result.copper, q.a, q.b))
            continue;
        const auto &n = net(b, q.net);
        auto source = pads.at(q.a), target = pads.at(q.b);
        auto obstacles = b.copper;
        obstacles.insert(obstacles.end(), result.copper.begin(), result.copper.end());
        std::vector<Node> nodes;
        std::map<Bucket, std::vector<int>> spatial;
        double cell = std::max(c.d_min, eps * 2);
        using Entry = std::tuple<double, double, size_t, int>;
        std::priority_queue<Entry, std::vector<Entry>, std::greater<Entry>> open;
        size_t order = 0;
        auto push = [&](Point p, int z, int parent, double g) {
            int id = static_cast<int>(nodes.size());
            nodes.push_back({p, z, parent, g});
            spatial[bucket(p, z, cell)].push_back(id);
            double h = heuristic(p, target.a) / .0254;
            open.emplace(g + h, h, order++, id);
        };
        push(source.a, source.layers[0], -1, 0);
        int found = -1;
        size_t expanded = 0;
        std::string reason = "search_exhausted";
        if (observer)
            observer({{"event", "search_start"}, {"net", q.net}, {"a", q.a}, {"b", q.b}});
        while (!open.empty()) {
            if (expired()) {
                reason = "timeout";
                break;
            }
            if (expanded >= c.max_nodes) {
                reason = "node_limit";
                break;
            }
            if (nodes.size() >= c.max_records) {
                reason = "record_limit";
                break;
            }
            auto entry = open.top();
            open.pop();
            int id = std::get<3>(entry);
            Node current = nodes[id];
            double h = heuristic(current.p, target.a) / .0254;
            if (std::get<0>(entry) > current.g + h + eps)
                continue;
            ++expanded;
            if (current.z == target.layers[0] && distance(current.p, target.a) <= eps) {
                found = id;
                break;
            }
            double delta = c.step;
            if (c.algorithm == "adaptive_strict") {
                Shape point;
                point.a = point.b = current.p;
                double d = edge_distance(current.p, b.outline);
                for (auto &hole : b.holes)
                    d = std::min(d, edge_distance(current.p, hole));
                for (auto &o : obstacles)
                    if (o.net != n.id &&
                        std::find(o.layers.begin(), o.layers.end(), current.z) != o.layers.end())
                        d = std::min(d, std::max(0., gap(point, o)));
                for (auto &o : b.keepouts)
                    if (std::find(o.layers.begin(), o.layers.end(), current.z) != o.layers.end())
                        d = std::min(d, std::max(0., gap(point, o)));
                delta = d <= c.beta * n.width ? n.width : c.beta * n.width;
            }
            for (auto next : candidates(current.p, current.z, target.a, target.layers[0], delta, b.layers)) {
                bool goal = next.layer == target.layers[0] && distance(next.p, target.a) <= eps;
                if (goal)
                    next.p = target.a;
                Shape s = edge(current.p, current.z, next.p, next.layer, b, n);
                if (!check_shape(b, s, obstacles).empty())
                    continue;
                double g = current.g + (current.z == next.layer ? distance(current.p, next.p)
                                                                : c.lambda_v * b.via_diameter) /
                                           .0254;
                auto key = bucket(next.p, next.layer, cell);
                auto [bx, by, bz] = key;
                int exact = -1;
                bool dense = false;
                for (int x = -1; x <= 1; ++x)
                    for (int y = -1; y <= 1; ++y) {
                        auto it = spatial.find({bx + x, by + y, bz});
                        if (it == spatial.end())
                            continue;
                        for (int old : it->second) {
                            double d = distance(next.p, nodes[old].p);
                            if (d <= eps)
                                exact = old;
                            else if (d < c.d_min)
                                dense = true;
                        }
                    }
                if (exact >= 0) {
                    if (g + eps < nodes[exact].g) {
                        nodes[exact].g = g;
                        nodes[exact].parent = id;
                        double nh = heuristic(nodes[exact].p, target.a) / .0254;
                        open.emplace(g + nh, nh, order++, exact);
                    }
                    continue;
                }
                if (dense && !goal)
                    continue;
                if (nodes.size() >= c.max_records) {
                    reason = "record_limit";
                    break;
                }
                push(next.p, next.layer, id, g);
            }
        }
        result.expanded += expanded;
        if (found < 0) {
            result.failures.push_back({{"net", q.net}, {"a", q.a}, {"b", q.b}, {"reason", reason}});
            if (observer)
                observer({{"event", "search_failed"}, {"net", q.net}, {"reason", reason}});
            if (reason == "timeout") {
                result.reason = reason;
                break;
            }
            continue;
        }
        std::vector<int> path;
        for (int at = found; at >= 0; at = nodes[at].parent)
            path.push_back(at);
        std::reverse(path.begin(), path.end());
        std::vector<Shape> generated;
        for (size_t i = 1; i < path.size(); ++i) {
            auto &a = nodes[path[i - 1]];
            auto &d = nodes[path[i]];
            Shape s = edge(a.p, a.z, d.p, d.z, b, n);
            if (s.kind == "segment" && distance(s.a, s.b) <= eps)
                continue;
            if (!generated.empty()) {
                auto &prev = generated.back();
                if (prev.kind == "segment" && s.kind == "segment" && prev.layers == s.layers &&
                    distance(prev.b, s.a) <= eps &&
                    std::abs(distance(prev.a, prev.b) + distance(s.a, s.b) - distance(prev.a, s.b)) <= eps) {
                    prev.b = s.b;
                    continue;
                }
            }
            generated.push_back(s);
        }
        for (auto &s : generated) {
            do {
                s.id = "route_" + std::to_string(serial++);
            } while (pads.count(s.id) || std::any_of(b.keepouts.begin(), b.keepouts.end(),
                                                     [&](auto &k) { return k.id == s.id; }));
            result.copper.push_back(s);
        }
        if (observer)
            observer({{"event", "route_committed"},
                      {"net", q.net},
                      {"expanded", expanded},
                      {"copper", routes_json(generated)["copper"]}});
    }
    return result;
}
} // namespace mr
