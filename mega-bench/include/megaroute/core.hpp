#pragma once
#include <chrono>
#include <cmath>
#include <functional>
#include <map>
#include <tuple>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>

namespace mr {
using Json = nlohmann::json;
constexpr double eps = 1e-6;
struct Point {
    double x = 0, y = 0;
};
Point operator+(Point a, Point b);
Point operator-(Point a, Point b);
Point operator*(Point a, double t);
double norm(Point a);
double distance(Point a, Point b);
double point_segment(Point p, Point a, Point b);
double segment_distance(Point a, Point b, Point c, Point d);
bool inside(Point p, const std::vector<Point> &poly);
double edge_distance(Point p, const std::vector<Point> &poly);
bool simple_polygon(const std::vector<Point> &poly);

// Circle: a=b=center; capsule: a,b=centerline; polygon: filled simple polygon.
struct Shape {
    std::string id, net, kind;
    Point a, b;
    double radius = 0, drill = 0;
    std::vector<Point> polygon;
    std::vector<int> layers;
    bool fixed = true;
    // One plated pad occupies every listed layer and is a single electrical terminal.
    bool plated = false;
};
double gap(const Shape &a, const Shape &b);
double boundary_gap(const Shape &a, const std::vector<Point> &polygon);
bool contained_in(const Shape &a, const std::vector<Point> &polygon);
bool share_layer(const Shape &a, const Shape &b);
struct Bounds {
    double x0, y0, x1, y1;
};
Bounds bounds(const Shape &s);
// Broad phase only: every returned object must still undergo exact geometry checks.
// The vector object must outlive the index; appends require insert(new_index).
class CopperIndex {
    const std::vector<Shape> &objects_;
    double cell_;
    std::map<std::tuple<long long, long long, int>, std::vector<size_t>> cells_;
    std::map<int, std::vector<size_t>> wide_, layers_;
    std::vector<Bounds> bounds_;
public:
    explicit CopperIndex(const std::vector<Shape> &objects, double cell = 2.);
    void insert(size_t id);
    std::vector<size_t> query(const Shape &shape, double margin = eps) const;
};
// Append-only graph; reconstruct after a rip-up, then union only nearby new copper.
class Connectivity {
    std::vector<Shape> objects_;
    CopperIndex index_;
    std::vector<size_t> parents_;
    std::map<std::string, size_t> ids_;
    size_t root(size_t id);
public:
    explicit Connectivity(const std::vector<Shape> &copper);
    Connectivity(const Connectivity &) = delete;
    Connectivity &operator=(const Connectivity &) = delete;
    void add(const Shape &shape);
    bool connected(const std::string &a, const std::string &b);
    const std::vector<Shape> &copper() const { return objects_; }
    const CopperIndex &index() const { return index_; }
};
struct Net {
    std::string id;
    double width = .2, clearance = .2;
};
// Internal geometry model, not the public benchmark case. KiCad project assets
// and lossless round-trip provenance live in Python's GeometryIRBundle.
struct Board {
    Json document;
    int layers = 2;
    std::vector<Point> outline;
    std::vector<std::vector<Point>> holes;
    std::vector<Shape> copper, keepouts;
    std::vector<Net> nets;
    double edge_clearance = .2, min_width = .2, via_diameter = .6, via_drill = .3, min_annular = .1;
};
struct Config {
    std::string algorithm = "baseline_fixed_strict";
    double step = .0254, beta = 5, d_min = .0254, lambda_v = 1, time_limit = 60;
    double penalty_L = 200, penalty_k = .4, penalty_mu = 10;
    size_t max_nodes = 1000000, max_records = 2000000;
    int max_iterations = 20;
    double history_weight = 1, history_cell = 1;
    int stagnation_rounds = 3, refinement_levels = 2;
};
struct Violation {
    std::string rule, a, b;
    int layer;
    double measured, required;
    bool fixed;
};
struct Connection {
    std::string net, a, b;
};
struct Result {
    std::vector<Shape> copper;
    // Best inspected solution, including DRC violations. Strict searches leave this empty.
    std::vector<Shape> diagnostic;
    bool has_diagnostic = false;
    std::string reason = "finished";
    size_t expanded = 0;
    int iterations = 0;
    double last_path_drc = 0;
    Json failures = Json::array();
};
using Observer = std::function<void(const Json &)>;
Board parse_board(const Json &j);
Config parse_config(const Json &j);
std::vector<Shape> parse_routes(const Json &j, const Board &b);
Json routes_json(const std::vector<Shape> &shapes);
Json config_json(const Config &c);
Json read_json(const std::string &path);
void write_json(const std::string &path, const Json &j);
const Net &net(const Board &b, const std::string &id);
std::vector<Violation> check_shape(const Board &b, const Shape &s, const std::vector<Shape> &copper,
                                 const CopperIndex *index = nullptr);
bool legal_extension(const Board &b, const std::vector<Shape> &added,
                     const std::vector<Shape> &existing, const CopperIndex &index);
std::vector<Violation> check_board(const Board &b, const std::vector<Shape> &added);
// Same-net segments that share one endpoint must keep an interior angle of at least 135 degrees.
bool interior_turn_ok(const Shape &a, const Shape &b);
bool interior_turn_ok(const Shape &a, const Shape &b, const std::vector<Shape> &copper);
std::vector<Connection> requirements(const Board &b);
bool connected(const Board &b, const std::vector<Shape> &added, const std::string &a, const std::string &c);
Json evaluate(const Board &b, const std::vector<Shape> &added,
              const std::vector<Connection> *cached_requirements = nullptr);
struct Candidate {
    Point p;
    int layer;
    std::string operation;
};
std::vector<Candidate> candidates(Point p, int layer, Point target, int target_layer, double delta,
                                  int layers);
double heuristic(Point p, Point target);
double logistic_penalty(int iteration, double L = 200, double k = .4, double mu = 10);
Result route(const Board &b, const Config &c, Observer observer = {});
// Legacy geometry JSON import boundary. Public KiCad conversion is coordinated
// by pcb_bench.KiCadGeometryBridge; no EasyEDA parsing here.
struct IBoardImporter {
    virtual ~IBoardImporter() = default;
    virtual Board load(const std::string &path) = 0;
};
struct JsonImporter final : IBoardImporter {
    Board load(const std::string &path) override;
};
struct EasyEdaImporter final : IBoardImporter {
    Board load(const std::string &) override;
};
} // namespace mr
