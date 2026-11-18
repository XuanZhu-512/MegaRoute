#include "megaroute/core.hpp"
#include <algorithm>
#include <limits>
namespace mr {
Point operator+(Point a, Point b) {
    return {a.x + b.x, a.y + b.y};
}
Point operator-(Point a, Point b) {
    return {a.x - b.x, a.y - b.y};
}
Point operator*(Point a, double t) {
    return {a.x * t, a.y * t};
}
double norm(Point a) {
    return std::hypot(a.x, a.y);
}
double distance(Point a, Point b) {
    return norm(a - b);
}
static double cross(Point a, Point b) {
    return a.x * b.y - a.y * b.x;
}
double point_segment(Point p, Point a, Point b) {
    auto v = b - a;
    double d = v.x * v.x + v.y * v.y;
    if (d == 0)
        return distance(p, a);
    auto u = p - a;
    double t = std::clamp((u.x * v.x + u.y * v.y) / d, 0., 1.);
    return distance(p, a + v * t);
}
double segment_distance(Point a, Point b, Point c, Point d) {
    double x = cross(b - a, c - a), y = cross(b - a, d - a), z = cross(d - c, a - c), w = cross(d - c, b - c);
    if (((x > 0 && y < 0) || (x < 0 && y > 0)) && ((z > 0 && w < 0) || (z < 0 && w > 0)))
        return 0;
    return std::min(
        {point_segment(a, c, d), point_segment(b, c, d), point_segment(c, a, b), point_segment(d, a, b)});
}
double edge_distance(Point p, const std::vector<Point> &poly) {
    double d = std::numeric_limits<double>::infinity();
    for (size_t i = 0; i < poly.size(); ++i)
        d = std::min(d, point_segment(p, poly[i], poly[(i + 1) % poly.size()]));
    return d;
}
bool inside(Point p, const std::vector<Point> &poly) {
    if (edge_distance(p, poly) <= eps)
        return true;
    bool result = false;
    for (size_t i = 0, j = poly.size() - 1; i < poly.size(); j = i++) {
        auto a = poly[i], b = poly[j];
        if ((a.y > p.y) != (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x)
            result = !result;
    }
    return result;
}
bool simple_polygon(const std::vector<Point> &p) {
    // KiCad coordinates resolve 1 nm (1e-6 mm). DRC's eps must not
    // collapse valid edges or reject nearby, nonintersecting ring edges.
    constexpr double topology_eps = 1e-9;
    if (p.size() < 3)
        return false;
    double area = 0;
    for (size_t i = 0; i < p.size(); ++i) {
        auto a = p[i], b = p[(i + 1) % p.size()];
        if (distance(a, b) <= topology_eps)
            return false;
        area += cross(a, b);
        for (size_t j = i + 1; j < p.size(); ++j) {
            if (j == i + 1 || (i == 0 && j == p.size() - 1))
                continue;
            if (segment_distance(a, b, p[j], p[(j + 1) % p.size()]) <= topology_eps)
                return false;
        }
    }
    return std::abs(area) > topology_eps * topology_eps;
}
// Hole interiors are empty; their boundaries remain part of the closed copper set.
bool inside_copper(Point p, const Shape &s) {
    if (!inside(p, s.polygon)) return false;
    for (const auto &hole : s.holes)
        if (inside(p, hole) && edge_distance(p, hole) > eps) return false;
    return true;
}
template <typename F> static void rings(const Shape &s, F visit) {
    visit(s.polygon);
    for (const auto &hole : s.holes) visit(hole);
}
Point closest_copper_point(Point p, const Shape &s) {
    auto project = [](Point p, Point a, Point b) {
        auto v = b - a;
        double len2 = v.x * v.x + v.y * v.y;
        double t = len2 == 0 ? 0 : std::clamp(((p.x-a.x)*v.x + (p.y-a.y)*v.y) / len2, 0., 1.);
        return a + v * t;
    };
    if (s.polygon.empty()) {
        Point q = project(p, s.a, s.b);
        double d = distance(p, q);
        return d <= s.radius ? p : q + (p-q) * (s.radius / d);
    }
    if (inside_copper(p, s)) return p;
    Point best = s.polygon.front();
    double d = std::numeric_limits<double>::infinity();
    rings(s, [&](const auto &ring) {
        for (size_t i = 0; i < ring.size(); ++i) {
            Point q = project(p, ring[i], ring[(i+1) % ring.size()]);
            double candidate = distance(p, q);
            if (candidate < d) { d = candidate; best = q; }
        }
    });
    return best;
}
static double segment_polygon(Point a, Point b, const Shape &s) {
    if (inside_copper(a, s) || inside_copper(b, s)) return 0;
    double d = 1e100;
    rings(s, [&](const auto &ring) {
        for (size_t i = 0; i < ring.size(); ++i)
            d = std::min(d, segment_distance(a, b, ring[i], ring[(i + 1) % ring.size()]));
    });
    return d;
}
double gap(const Shape &a, const Shape &b) {
    if (a.polygon.empty() && b.polygon.empty())
        return segment_distance(a.a, a.b, b.a, b.b) - a.radius - b.radius;
    if (a.polygon.empty()) return segment_polygon(a.a, a.b, b) - a.radius;
    if (b.polygon.empty()) return segment_polygon(b.a, b.b, a) - b.radius;
    if (inside_copper(a.polygon[0], b) || inside_copper(b.polygon[0], a)) return 0;
    double d = 1e100;
    rings(a, [&](const auto &ra) {
        rings(b, [&](const auto &rb) {
            for (size_t i = 0; i < ra.size(); ++i)
                for (size_t j = 0; j < rb.size(); ++j)
                    d = std::min(d, segment_distance(ra[i], ra[(i + 1) % ra.size()],
                                                     rb[j], rb[(j + 1) % rb.size()]));
        });
    });
    return d;
}
double boundary_gap(const Shape &a, const std::vector<Point> &poly) {
    double d = 1e100;
    for (size_t j = 0; j < poly.size(); ++j) {
        auto c = poly[j], e = poly[(j + 1) % poly.size()];
        if (a.polygon.empty())
            d = std::min(d, segment_distance(a.a, a.b, c, e) - a.radius);
        else
            // A board edge entirely inside a copper hole measures to that hole,
            // rather than to the more distant outer ring.
            rings(a, [&](const auto &ring) {
                for (size_t i = 0; i < ring.size(); ++i)
                    d = std::min(d, segment_distance(ring[i], ring[(i + 1) % ring.size()], c, e));
            });
    }
    return d;
}
// Split at every outline intersection, including collinear vertices. Checking only
// endpoints (or one midpoint) misses excursions through a concave board boundary.
static bool segment_inside(Point a, Point b, const std::vector<Point> &poly) {
    if (!inside(a, poly) || !inside(b, poly)) return false;
    Point v = b - a;
    double len2 = v.x * v.x + v.y * v.y;
    if (len2 <= eps * eps) return true;
    std::vector<double> cuts{0, 1};
    for (size_t i = 0; i < poly.size(); ++i) {
        Point c = poly[i], w = poly[(i + 1) % poly.size()] - c;
        double den = cross(v, w);
        if (std::abs(den) > 1e-12 * norm(v) * norm(w)) {
            double t = cross(c - a, w) / den, u = cross(c - a, v) / den;
            if (t >= 0 && t <= 1 && u >= 0 && u <= 1) cuts.push_back(t);
        } else if (point_segment(c, a, b) <= eps) {
            Point d = c - a;
            cuts.push_back(std::clamp((d.x * v.x + d.y * v.y) / len2, 0., 1.));
        }
    }
    std::sort(cuts.begin(), cuts.end());
    for (size_t i = 1; i < cuts.size(); ++i)
        if (!inside(a + v * ((cuts[i - 1] + cuts[i]) / 2), poly)) return false;
    return true;
}
bool contained_in(const Shape &s, const std::vector<Point> &poly) {
    if (s.polygon.empty())
        return segment_inside(s.a, s.b, poly) && boundary_gap(s, poly) >= -eps;
    for (size_t i = 0; i < s.polygon.size(); ++i)
        if (!segment_inside(s.polygon[i], s.polygon[(i + 1) % s.polygon.size()], poly)) return false;
    return true;
}
bool share_layer(const Shape &a, const Shape &b) {
    for (int z : a.layers)
        if (std::find(b.layers.begin(), b.layers.end(), z) != b.layers.end())
            return true;
    return false;
}
} // namespace mr
