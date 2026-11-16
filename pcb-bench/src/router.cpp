#include "megaroute/core.hpp"
#include <algorithm>
#include <array>
#include <map>
#include <numeric>
#include <queue>
#include <set>
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
static bool on_layer(const Shape &s, int z) {
    return std::find(s.layers.begin(), s.layers.end(), z) != s.layers.end();
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
struct Cost {
    double length = 0, drc = 0, via = 0;
};
static double priority_of(const Cost &cost, double h, double alpha, double lambda) {
    return cost.length + h + alpha * cost.drc + lambda * cost.via;
}
static int soft_clearance(const std::vector<Violation> &violations, bool &hard) {
    std::set<std::tuple<std::string, std::string, int>> keys;
    hard = false;
    for (const auto &v : violations) {
        if (v.rule != "clearance" && v.rule != "short") {
            hard = true;
            return 0;
        }
        keys.emplace(v.rule, v.b, v.layer);
    }
    return static_cast<int>(keys.size());
}
struct Node {
    Point p;
    int z, parent;
    Cost cost;
};
using Bucket = std::tuple<long long, long long, int>;
static Bucket bucket(Point p, int z, double cell) {
    return {static_cast<long long>(std::floor(p.x / cell)), static_cast<long long>(std::floor(p.y / cell)),
            z};
}
struct Attempt {
    bool found = false;
    std::string reason = "search_exhausted";
    std::vector<Shape> copper;
    size_t expanded = 0;
    double drc = 0;
};
static Attempt search_pair(const Board &b, const Config &c, const Shape &source, const Shape &target,
                           const Net &n, const std::vector<Shape> &obstacles, double alpha, bool adaptive,
                           bool strict, const std::function<bool()> &expired, Observer observer) {
    Attempt attempt;
    std::vector<Node> nodes;
    std::map<Bucket, std::vector<int>> spatial;
    double cell = std::max(c.d_min, eps * 2);
    using Entry = std::tuple<double, double, size_t, int>;
    std::priority_queue<Entry, std::vector<Entry>, std::greater<Entry>> open;
    size_t order = 0;
    auto score = [&](const Cost &cost, Point p) {
        double h = heuristic(p, target.a) / .0254;
        return std::pair<double, double>{priority_of(cost, h, alpha, c.lambda_v), h};
    };
    auto push = [&](Point p, int z, int parent, Cost cost) {
        int id = static_cast<int>(nodes.size());
        nodes.push_back({p, z, parent, cost});
        spatial[bucket(p, z, cell)].push_back(id);
        auto ranked = score(cost, p);
        open.emplace(ranked.first, ranked.second, order++, id);
    };
    for (int z : source.layers)
        push(source.a, z, -1, {});
    int found = -1;
    if (observer)
        observer({{"event", "search_start"}, {"net", n.id}, {"a", source.id}, {"b", target.id}});
    while (!open.empty()) {
        if (expired()) {
            attempt.reason = "timeout";
            break;
        }
        if (attempt.expanded >= c.max_nodes) {
            attempt.reason = "node_limit";
            break;
        }
        if (nodes.size() >= c.max_records) {
            attempt.reason = "record_limit";
            break;
        }
        auto entry = open.top();
        open.pop();
        int id = std::get<3>(entry);
        Node current = nodes[id];
        auto ranked = score(current.cost, current.p);
        if (std::get<0>(entry) > ranked.first + eps)
            continue;
        ++attempt.expanded;
        if (on_layer(target, current.z) && distance(current.p, target.a) <= eps) {
            found = id;
            break;
        }
        double delta = c.step;
        if (adaptive) {
            Shape point;
            point.a = point.b = current.p;
            double d = edge_distance(current.p, b.outline);
            for (auto &hole : b.holes)
                d = std::min(d, edge_distance(current.p, hole));
            for (auto &o : obstacles)
                if (o.net != n.id && on_layer(o, current.z))
                    d = std::min(d, std::max(0., gap(point, o)));
            for (auto &o : b.keepouts)
                if (on_layer(o, current.z))
                    d = std::min(d, std::max(0., gap(point, o)));
            delta = d <= c.beta * n.width ? n.width : c.beta * n.width;
        }
        int target_layer = on_layer(target, current.z) ? current.z : -1;
        for (auto next : candidates(current.p, current.z, target.a, target_layer, delta, b.layers)) {
            bool goal = on_layer(target, next.layer) && distance(next.p, target.a) <= eps;
            if (goal)
                next.p = target.a;
            Shape s = edge(current.p, current.z, next.p, next.layer, b, n);
            auto violations = check_shape(b, s, obstacles);
            bool hard = false;
            int drc = 0;
            if (strict) {
                if (!violations.empty())
                    continue;
            } else {
                drc = soft_clearance(violations, hard);
                if (hard)
                    continue;
            }
            Cost step = current.cost;
            if (current.z == next.layer)
                step.length += distance(current.p, next.p) / .0254;
            else
                step.via += b.via_diameter / .0254;
            step.drc += drc;
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
                        double dist = distance(next.p, nodes[old].p);
                        if (dist <= eps)
                            exact = old;
                        else if (dist < c.d_min)
                            dense = true;
                    }
                }
            auto next_rank = score(step, next.p);
            if (exact >= 0) {
                if (next_rank.first + eps < score(nodes[exact].cost, nodes[exact].p).first) {
                    nodes[exact].cost = step;
                    nodes[exact].parent = id;
                    open.emplace(next_rank.first, next_rank.second, order++, exact);
                }
                continue;
            }
            if (dense && !goal)
                continue;
            if (nodes.size() >= c.max_records) {
                attempt.reason = "record_limit";
                break;
            }
            push(next.p, next.layer, id, step);
        }
    }
    if (found < 0) {
        if (observer)
            observer({{"event", "search_failed"}, {"net", n.id}, {"reason", attempt.reason}});
        return attempt;
    }
    std::vector<int> path;
    for (int at = found; at >= 0; at = nodes[at].parent)
        path.push_back(at);
    std::reverse(path.begin(), path.end());
    for (size_t i = 1; i < path.size(); ++i) {
        auto &a = nodes[path[i - 1]];
        auto &d = nodes[path[i]];
        Shape s = edge(a.p, a.z, d.p, d.z, b, n);
        if (s.kind == "segment" && distance(s.a, s.b) <= eps)
            continue;
        if (!attempt.copper.empty()) {
            auto &prev = attempt.copper.back();
            if (prev.kind == "segment" && s.kind == "segment" && prev.layers == s.layers &&
                distance(prev.b, s.a) <= eps &&
                std::abs(distance(prev.a, prev.b) + distance(s.a, s.b) - distance(prev.a, s.b)) <= eps) {
                prev.b = s.b;
                continue;
            }
        }
        attempt.copper.push_back(s);
    }
    attempt.found = true;
    attempt.drc = nodes[found].cost.drc;
    attempt.reason = "routed";
    return attempt;
}
struct Snapshot {
    bool exists = false;
    int routed = -1, drc = 0, vc = 0;
    double wl = 0;
    std::vector<Shape> copper;
};
static bool better_legal(const Snapshot &a, const Snapshot &b) {
    if (a.routed != b.routed)
        return a.routed > b.routed;
    if (std::abs(a.wl - b.wl) > eps)
        return a.wl < b.wl;
    return a.vc < b.vc;
}
static bool better_diagnostic(const Snapshot &a, const Snapshot &b) {
    if (a.routed != b.routed)
        return a.routed > b.routed;
    if (a.drc != b.drc)
        return a.drc < b.drc;
    if (std::abs(a.wl - b.wl) > eps)
        return a.wl < b.wl;
    return a.vc < b.vc;
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
    bool negotiated = c.algorithm == "megaroute";
    bool adaptive = negotiated || c.algorithm == "adaptive_strict";
    int limit = negotiated ? c.max_iterations : 1;
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
    std::vector<Shape> working;
    std::set<std::string> active;
    bool restrict = false;
    Snapshot legal, diagnostic;
    size_t serial = 0;
    auto occupied = [&](const std::string &id) {
        return pads.count(id) ||
               std::any_of(b.keepouts.begin(), b.keepouts.end(), [&](auto &k) { return k.id == id; }) ||
               std::any_of(working.begin(), working.end(), [&](auto &s) { return s.id == id; });
    };
    for (int iteration = 1; iteration <= limit; ++iteration) {
        if (expired()) {
            result.reason = "timeout";
            break;
        }
        result.iterations = iteration;
        double alpha = negotiated ? logistic_penalty(iteration, c.penalty_L, c.penalty_k, c.penalty_mu) : 0;
        if (restrict) {
            working.erase(std::remove_if(working.begin(), working.end(),
                                         [&](const Shape &s) { return active.count(s.net); }),
                          working.end());
        }
        bool stop = false;
        for (auto &q : req) {
            if (restrict && !active.count(q.net))
                continue;
            if (expired()) {
                result.reason = "timeout";
                stop = true;
                break;
            }
            if (connected(b, working, q.a, q.b))
                continue;
            auto obstacles = b.copper;
            obstacles.insert(obstacles.end(), working.begin(), working.end());
            auto attempt = search_pair(b, c, pads.at(q.a), pads.at(q.b), net(b, q.net), obstacles, alpha,
                                       adaptive, !negotiated, expired, observer);
            result.expanded += attempt.expanded;
            if (!attempt.found) {
                result.failures.push_back(
                    {{"net", q.net}, {"a", q.a}, {"b", q.b}, {"reason", attempt.reason}});
                if (attempt.reason == "timeout") {
                    result.reason = "timeout";
                    stop = true;
                    break;
                }
                continue;
            }
            result.last_path_drc = attempt.drc;
            for (auto &s : attempt.copper) {
                do {
                    s.id = "route_" + std::to_string(serial++);
                } while (occupied(s.id));
                working.push_back(s);
            }
            if (observer)
                observer({{"event", "route_committed"},
                          {"net", q.net},
                          {"iteration", iteration},
                          {"expanded", attempt.expanded},
                          {"drc_cost", attempt.drc},
                          {"copper", routes_json(attempt.copper)["copper"]}});
        }
        auto round = evaluate(b, working);
        Snapshot shot;
        shot.exists = true;
        shot.routed = round.at("C_routed").get<int>();
        shot.drc = round.at("DRC").get<int>();
        shot.vc = round.at("VC").get<int>();
        shot.wl = round.at("WL_mm").get<double>();
        shot.copper = working;
        if (shot.drc == 0 && (!legal.exists || better_legal(shot, legal)))
            legal = shot;
        if (!diagnostic.exists || better_diagnostic(shot, diagnostic))
            diagnostic = shot;
        bool complete = shot.routed == static_cast<int>(req.size()) && shot.drc == 0;
        if (stop || complete || !negotiated)
            break;
        std::map<std::string, std::string> owners;
        for (const auto &s : working)
            owners[s.id] = s.net;
        std::set<std::string> next;
        for (const auto &missing : round.at("missing_connections"))
            next.insert(missing.at("net").get<std::string>());
        for (const auto &v : round.at("violations")) {
            for (const char *key : {"a", "b"}) {
                auto id = v.at(key).get<std::string>();
                auto owner = owners.find(id);
                if (owner != owners.end())
                    next.insert(owner->second);
            }
        }
        if (next.empty())
            break;
        active.swap(next);
        restrict = true;
    }
    if (negotiated) {
        if (legal.exists)
            result.copper = legal.copper;
        if (diagnostic.exists) {
            result.diagnostic = diagnostic.copper;
            result.has_diagnostic = true;
        }
        if (result.reason == "finished" && result.iterations == limit) {
            auto final_shot = diagnostic.exists ? diagnostic : legal;
            if (!final_shot.exists || final_shot.drc != 0 || final_shot.routed != static_cast<int>(req.size()))
                result.reason = "iteration_limit";
        }
    } else
        result.copper = working;
    return result;
}
} // namespace mr
