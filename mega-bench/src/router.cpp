#include "megaroute/core.hpp"
#include <algorithm>
#include <array>
#include <map>
#include <limits>
#include <numeric>
#include <queue>
#include <set>
#include <tuple>
#include <unordered_set>
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
// 0=E, 1=NE, 2=N, 3=NW, 4=W, 5=SW, 6=S, 7=SE. -1 means the first segment is free.
static int octant(Point a, Point b) {
    double dx = b.x - a.x, dy = b.y - a.y;
    double ax = std::abs(dx), ay = std::abs(dy);
    if (ax <= eps && ay <= eps)
        return -2;
    if (ay <= eps)
        return dx > 0 ? 0 : 4;
    if (ax <= eps)
        return dy > 0 ? 2 : 6;
    if (std::abs(ax - ay) <= eps) {
        if (dx > 0 && dy > 0)
            return 1;
        if (dx < 0 && dy > 0)
            return 3;
        if (dx < 0 && dy < 0)
            return 5;
        return 7;
    }
    return -3;
}
static bool turn_ok(int incoming, int next) {
    if (incoming < 0)
        return true;
    int d = std::abs(incoming - next) % 8;
    if (d > 4)
        d = 8 - d;
    return d <= 1;
}
struct Cost {
    double length = 0, drc = 0, via = 0;
};
static double priority_of(const Cost &cost, double h, double alpha, double lambda) {
    return cost.length + h + alpha * cost.drc + lambda * cost.via;
}
static int soft_clearance(const std::vector<Violation> &violations,
                          const std::unordered_set<std::string> &immutable, bool &hard) {
    std::set<std::tuple<std::string, std::string, int>> keys;
    hard = false;
    for (const auto &v : violations) {
        if ((v.rule != "clearance" && v.rule != "short") || immutable.count(v.b)) {
            hard = true;
            return 0;
        }
        keys.emplace(v.rule, v.b, v.layer);
    }
    return static_cast<int>(keys.size());
}
struct Node {
    Point p;
    int z = 0, heading = -1, parent = -1;
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
    std::set<std::string> blockers;
};
// Fallback candidates are checked before search and reduced to one fixed legal
// terminal per layer. They never become a cloud of additional search roots.
static std::vector<Point> access_candidates(const Board &b, const Shape &source,
                                            const Shape &target, double width) {
    std::vector<Point> points{source.a, closest_copper_point(target.a, source)};
    auto add_ring = [&](const auto &ring) {
        for (size_t i = 0; i < ring.size(); ++i) {
            points.push_back(ring[i]);
            points.push_back((ring[i] + ring[(i+1) % ring.size()]) * .5);
        }
    };
    add_ring(source.polygon);
    for (const auto &hole : source.holes) add_ring(hole);
    Shape outline;
    outline.polygon = b.outline;
    auto board_box = bounds(outline), box = bounds(source);
    double margin = width / 2 + b.edge_clearance;
    box.x0 = std::max(box.x0, board_box.x0 + margin);
    box.x1 = std::min(box.x1, board_box.x1 - margin);
    box.y0 = std::max(box.y0, board_box.y0 + margin);
    box.y1 = std::min(box.y1, board_box.y1 - margin);
    if (box.x0 <= box.x1 && box.y0 <= box.y1) {
        // Bounded deterministic sampling complements geometric features. This is
        // a finite search, not a claim of complete continuous-space coverage.
        int nx = std::min(16., std::ceil((box.x1-box.x0) / width));
        int ny = std::min(16., std::ceil((box.y1-box.y0) / width));
        for (int x = 0; x <= nx; ++x)
            for (int y = 0; y <= ny; ++y)
                points.push_back({box.x0 + (box.x1-box.x0) * x / std::max(1, nx),
                                  box.y0 + (box.y1-box.y0) * y / std::max(1, ny)});
    }
    return points;
}
static Shape point_probe(Point p) {
    Shape probe;
    probe.a = probe.b = p;
    return probe;
}
static Attempt search_pair(const Board &b, const Config &c, const Shape &source, const Shape &target,
                           const Net &n, const std::vector<Shape> &obstacles, const CopperIndex &index,
                           double alpha, bool adaptive, bool strict,
                           const std::function<bool()> &expired, Observer observer) {
    Attempt attempt;
    std::vector<Node> nodes;
    std::map<Bucket, std::vector<int>> spatial;
    double density = c.d_min;
    double cell = std::max(density, eps * 2);
    std::unordered_set<std::string> immutable;
    for (const auto &s : obstacles) if (s.fixed) immutable.insert(s.id);
    // Adapt KiCad terminals to fixed legal points before entering the paper's
    // point-to-point search. The nominal point is preferred; fallback sampling
    // is used only when that point fails geometry/clearance checks.
    auto terminal_points = [&](const Shape &terminal, const Shape &other) {
        std::map<int, Point> result;
        std::vector<Point> fallback;
        bool sampled = false;
        for (int z : terminal.layers) {
            auto legal = [&](Point p) {
                if (gap(point_probe(p), terminal) > eps) return false;
                auto violations = check_shape(b, edge(p, z, p, z, b, n), obstacles, &index);
                if (strict) return violations.empty();
                bool hard = false;
                soft_clearance(violations, immutable, hard);
                return !hard;
            };
            if (legal(terminal.a)) { result[z] = terminal.a; continue; }
            if (!sampled) {
                fallback = access_candidates(b, terminal, other, n.width);
                sampled = true;
            }
            double best = std::numeric_limits<double>::infinity();
            for (auto p : fallback) {
                if (expired()) break;
                double score = heuristic(p, other.a);
                if (score < best && legal(p)) { best = score; result[z] = p; }
            }
        }
        return result;
    };
    const auto sources = terminal_points(source, target);
    const auto targets = terminal_points(target, source);
    if (sources.empty() || targets.empty()) {
        attempt.reason = expired() ? "timeout" : "no_legal_terminal_access";
        if (observer) observer({{"event", "search_failed"}, {"net", n.id}, {"reason", attempt.reason}, {"expanded", 0}});
        return attempt;
    }
    auto target_point = [&](Point p, int z) {
        auto same_layer = targets.find(z);
        if (same_layer != targets.end()) return same_layer->second;
        auto best = targets.begin();
        for (auto it = targets.begin(); it != targets.end(); ++it)
            if (heuristic(p, it->second) < heuristic(p, best->second)) best = it;
        return best->second;
    };
    auto is_goal = [&](Point p, int z) {
        auto it = targets.find(z);
        return it != targets.end() && distance(p, it->second) <= eps;
    };
    using Entry = std::tuple<double, double, size_t, int>;
    std::priority_queue<Entry, std::vector<Entry>, std::greater<Entry>> open;
    size_t order = 0;
    auto score = [&](const Cost &cost, Point p) {
        double h = std::numeric_limits<double>::infinity();
        for (const auto &[z, point] : targets) {
            (void)z;
            h = std::min(h, heuristic(p, point) / .0254);
        }
        return std::pair<double, double>{priority_of(cost, h, alpha, c.lambda_v), h};
    };
    auto push = [&](Point p, int z, int heading, int parent, Cost cost) {
        int id = static_cast<int>(nodes.size());
        nodes.push_back({p, z, heading, parent, cost});
        spatial[bucket(p, z, cell)].push_back(id);
        auto ranked = score(cost, p);
        open.emplace(ranked.first, ranked.second, order++, id);
    };
    for (const auto &[z, point] : sources) {
        if (nodes.size() >= c.max_records) break;
        push(point, z, -1, -1, {});
    }
    int found = -1;
    if (observer)
        observer({{"event", "search_start"}, {"net", n.id}, {"a", source.id}, {"b", target.id},
                  {"strict", strict}, {"source_seed_count", sources.size()}, {"target_access_count", targets.size()}});
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
        if (is_goal(current.p, current.z)) {
            found = id;
            break;
        }
        double delta = c.step;
        if (adaptive) {
            Shape point;
            point.a = point.b = current.p;
            point.layers = {current.z};
            double threshold = c.beta * n.width;
            bool near = edge_distance(current.p, b.outline) <= threshold;
            for (auto &hole : b.holes)
                near = near || edge_distance(current.p, hole) <= threshold;
            if (!near) for (auto id : index.query(point, threshold)) {
                const auto &o = obstacles[id];
                if (o.net != n.id && gap(point, o) <= threshold) { near = true; break; }
            }
            for (auto &o : b.keepouts)
                if (!near && on_layer(o, current.z)) near = gap(point, o) <= threshold;
            delta = near ? n.width : c.beta * n.width;
        }
        int target_layer = targets.count(current.z) ? current.z : -1;
        Point guide = target_point(current.p, current.z);
        for (auto next : candidates(current.p, current.z, guide, target_layer, delta, b.layers)) {
            bool goal = is_goal(next.p, next.layer);
            if (goal) next.p = targets.at(next.layer);
            Shape s = edge(current.p, current.z, next.p, next.layer, b, n);
            // A via is not a planar corner. Eq. 6 / IV-B do not carry heading across layers.
            int heading = -1;
            if (s.kind == "segment") {
                int edge_heading = octant(s.a, s.b);
                if (edge_heading < 0 || !turn_ok(current.heading, edge_heading))
                    continue;
                bool bad_corner = false;
                for (auto old : index.query(s)) {
                    const auto &o = obstacles[old];
                    if (!interior_turn_ok(s, o, obstacles)) {
                        bad_corner = true;
                        break;
                    }
                }
                if (bad_corner)
                    continue;
                heading = edge_heading;
            }
            auto violations = check_shape(b, s, obstacles, &index);
            for (const auto &v : violations)
                if (!immutable.count(v.b)) attempt.blockers.insert(v.b);
            bool hard = false;
            int drc = 0;
            if (strict) {
                if (!violations.empty())
                    continue;
            } else {
                drc = soft_clearance(violations, immutable, hard);
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
                        if (dist <= eps) {
                            // One state per (x,y,z), independent of arrival heading.
                            exact = old;
                        }
                        // Do not prune a step exactly d_min away because of
                        // floating-point roundoff (e.g. repeated 1 mil steps).
                        else if (dist + eps < density)
                            dense = true;
                    }
                }
            auto next_rank = score(step, next.p);
            if (exact >= 0) {
                if (next_rank.first + eps < score(nodes[exact].cost, nodes[exact].p).first) {
                    nodes[exact].cost = step;
                    nodes[exact].parent = id;
                    nodes[exact].heading = heading;
                    open.emplace(next_rank.first, next_rank.second, order++, exact);
                }
                continue;
            }
            // Eq. 4/5 are explicit alignment corrections, not a denser
            // obstacle-aware lattice. Dropping a sub-d_min correction can make
            // the required target coordinates impossible to represent. Exact
            // duplicates are still merged above and all DRC checks still apply.
            bool alignment = next.operation == "axis" || next.operation == "diagonal";
            if (dense && !goal && !alignment)
                continue;
            if (nodes.size() >= c.max_records) {
                attempt.reason = "record_limit";
                break;
            }
            push(next.p, next.layer, heading, id, step);
        }
    }
    if (found < 0) {
        if (observer)
            observer({{"event", "search_failed"}, {"net", n.id}, {"reason", attempt.reason}, {"expanded", attempt.expanded}});
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
    Connectivity contact_check({source, target});
    size_t contact_id = 0;
    for (auto shape : attempt.copper) {
        // Candidate IDs are intentionally empty until the caller assigns them.
        do { shape.id = "contact_" + std::to_string(contact_id++); }
        while (shape.id == source.id || shape.id == target.id);
        contact_check.add(shape);
    }
    if (!contact_check.connected(source.id, target.id)) {
        attempt.reason = "terminal_connectivity";
        return attempt;
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
struct Bundle {
    Connection demand;
    std::vector<Shape> copper;
};
static Snapshot legal_subset(const Board &b, const std::vector<Bundle> &bundles,
                             const std::vector<Connection> &req) {
    std::vector<Shape> kept;
    auto existing = b.copper;
    CopperIndex index(existing);
    for (const auto &q : req)
        for (const auto &bundle : bundles) {
            if (bundle.demand.net != q.net || bundle.demand.a != q.a || bundle.demand.b != q.b)
                continue;
            if (legal_extension(b, bundle.copper, existing, index))
                for (const auto &s : bundle.copper) {
                    kept.push_back(s);
                    existing.push_back(s);
                    index.insert(existing.size() - 1);
                }
        }
    auto metrics = evaluate(b, kept, &req);
    Snapshot shot;
    shot.exists = true;
    shot.routed = metrics.at("C_routed").get<int>();
    shot.drc = metrics.at("DRC").get<int>();
    shot.vc = metrics.at("VC").get<int>();
    shot.wl = metrics.at("WL_mm").get<double>();
    shot.copper = std::move(kept);
    return shot;
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
using DemandKey = std::tuple<std::string, std::string, std::string>;
static DemandKey demand_key(const Connection &q) { return {q.net, q.a, q.b}; }

Result route(const Board &b, const Config &c, Observer observer) {
    Result result;
    auto start = std::chrono::steady_clock::now();
    auto elapsed = [&] { return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count(); };
    auto expired = [&] { return elapsed() >= c.time_limit; };
    if (!check_board(b, {}).empty()) {
        result.reason = "input_drc_violations";
        return result;
    }
    bool negotiated = c.algorithm == "megaroute";
    bool adaptive = negotiated || c.algorithm == "adaptive_strict";
    int limit = negotiated ? c.max_iterations : 1;
    auto req = requirements(b);
    std::map<std::string, Shape> pads;
    for (const auto &s : b.copper) pads[s.id] = s;
    std::map<std::string, double> totals;
    for (const auto &q : req) totals[q.net] += distance(pads.at(q.a).a, pads.at(q.b).a);
    std::stable_sort(req.begin(), req.end(), [&](const auto &a, const auto &d) {
        if (totals[a.net] != totals[d.net]) return totals[a.net] > totals[d.net];
        return demand_key(a) < demand_key(d);
    });
    std::vector<Shape> working;
    std::vector<Bundle> bundles;
    std::set<DemandKey> active;
    bool restrict = false;
    Snapshot legal, diagnostic;
    size_t serial = 0;
    std::set<std::string> used;
    for (const auto &s : b.copper) used.insert(s.id);
    for (const auto &s : b.keepouts) used.insert(s.id);
    auto name_shapes = [&](std::vector<Shape> &shapes) {
        for (auto &s : shapes) {
            do { s.id = "route_" + std::to_string(serial++); } while (!used.insert(s.id).second);
        }
    };
    auto checkpoint = [&] {
        if (observer && legal.exists)
            observer({{"event", "checkpoint"}, {"iteration", result.iterations},
                      {"C_routed", legal.routed}, {"copper", routes_json(legal.copper)["copper"]}});
    };
    for (int iteration = 1; iteration <= limit; ++iteration) {
        if (expired()) { result.reason = "timeout"; break; }
        result.iterations = iteration;
        double alpha = negotiated ? logistic_penalty(iteration, c.penalty_L, c.penalty_k, c.penalty_mu) : 0;
        if (restrict) {
            std::set<std::string> removed;
            for (const auto &bundle : bundles)
                if (active.count(demand_key(bundle.demand)))
                    for (const auto &s : bundle.copper) removed.insert(s.id);
            working.erase(std::remove_if(working.begin(), working.end(),
                          [&](const Shape &s) { return removed.count(s.id); }), working.end());
            bundles.erase(std::remove_if(bundles.begin(), bundles.end(),
                          [&](const Bundle &bundle) { return active.count(demand_key(bundle.demand)); }), bundles.end());
        }
        Connectivity graph(b.copper);
        for (const auto &s : working) graph.add(s);
        std::set<std::string> blocked_by;
        bool stop = false;
        std::vector<Connection> order;
        for (const auto &q : req)
            if (!restrict || active.count(demand_key(q))) order.push_back(q);
        // Keep non-conflicting copper; vary only the priority within the set
        // being rerouted. This changes neither search cost nor DRC constraints.
        // Deterministic rotation avoids recreating the same conflicting layout.
        if (restrict && c.routing_order == "rotate_conflicts" && !order.empty()) {
            size_t offset = static_cast<size_t>(iteration - 1) % order.size();
            std::rotate(order.begin(), order.begin() + offset, order.end());
        }
        for (const auto &q : order) {
            if (expired()) { result.reason = "timeout"; stop = true; break; }
            if (graph.connected(q.a, q.b)) continue;
            auto attempt = search_pair(b, c, pads.at(q.a), pads.at(q.b), net(b, q.net),
                                       graph.copper(), graph.index(), alpha, adaptive,
                                       !negotiated, expired, observer);
            result.expanded += attempt.expanded;
            if (!attempt.found) {
                result.failures.push_back({{"net", q.net}, {"a", q.a}, {"b", q.b}, {"reason", attempt.reason}});
                blocked_by.insert(attempt.blockers.begin(), attempt.blockers.end());
                if (attempt.reason == "timeout") { result.reason = "timeout"; stop = true; break; }
                continue;
            }
            result.last_path_drc = attempt.drc;
            name_shapes(attempt.copper);
            Bundle bundle{q, attempt.copper};
            for (const auto &s : attempt.copper) { working.push_back(s); graph.add(s); }
            bundles.push_back(std::move(bundle));
            if (observer) observer({{"event", "route_committed"}, {"net", q.net}, {"iteration", iteration},
                                    {"expanded", attempt.expanded}, {"drc_cost", attempt.drc},
                                    {"copper", routes_json(attempt.copper)["copper"]}});
        }
        auto round = evaluate(b, working, &req);
        Snapshot shot{true, round.at("C_routed").get<int>(), round.at("DRC").get<int>(),
                      round.at("VC").get<int>(), round.at("WL_mm").get<double>(), working};
        bool legal_improved = false;
        if (shot.drc == 0) {
            if (!legal.exists || better_legal(shot, legal)) { legal = shot; legal_improved = true; }
        } else if (negotiated) {
            auto subset = legal_subset(b, bundles, req);
            if (!legal.exists || better_legal(subset, legal)) { legal = std::move(subset); legal_improved = true; }
        }
        if (legal_improved) checkpoint();
        if (!diagnostic.exists || better_diagnostic(shot, diagnostic)) diagnostic = shot;
        if (observer) observer({{"event", "iteration_complete"}, {"iteration", iteration},
                                {"C_routed", shot.routed}, {"DRC", shot.drc}, {"alpha", alpha},
                                {"legal_routed", legal.routed}, {"elapsed_s", elapsed()}});
        if (stop || (shot.routed == static_cast<int>(req.size()) && shot.drc == 0) || !negotiated) break;
        std::map<std::string, DemandKey> owners;
        for (const auto &bundle : bundles)
            for (const auto &s : bundle.copper) owners.emplace(s.id, demand_key(bundle.demand));
        std::set<DemandKey> next;
        for (const auto &missing : round.at("missing_connections"))
            next.emplace(missing.at("net").get<std::string>(), missing.at("a").get<std::string>(),
                         missing.at("b").get<std::string>());
        for (const auto &v : round.at("violations"))
            for (const char *key : {"a", "b"}) {
                auto it = owners.find(v.at(key).get<std::string>());
                if (it != owners.end()) next.insert(it->second);
            }
        // Failed strict/hard-obstacle searches may be blocked by otherwise legal routes.
        for (const auto &id : blocked_by) {
            auto it = owners.find(id);
            if (it != owners.end()) next.insert(it->second);
        }
        if (next.empty()) break;
        active.swap(next);
        restrict = true;
    }
    if (legal.exists) result.copper = legal.copper;
    if (negotiated && diagnostic.exists) {
        result.diagnostic = diagnostic.copper; result.has_diagnostic = true;
    }
    if (legal.exists && legal.routed == static_cast<int>(req.size())) result.reason = "finished";
    else if (expired()) result.reason = "timeout";
    else if (negotiated && result.reason == "finished") result.reason = "iteration_limit";
    return result;
}
} // namespace mr
