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
    if (p.size() < 3)
        return false;
    double area = 0;
    for (size_t i = 0; i < p.size(); ++i) {
        auto a = p[i], b = p[(i + 1) % p.size()];
        if (distance(a, b) <= eps)
            return false;
        area += cross(a, b);
        for (size_t j = i + 1; j < p.size(); ++j) {
            if (j == i + 1 || (i == 0 && j == p.size() - 1))
                continue;
            if (segment_distance(a, b, p[j], p[(j + 1) % p.size()]) <= eps)
                return false;
        }
    }
    return std::abs(area) > eps * eps;
}
static double segment_polygon(Point a, Point b, const std::vector<Point> &p) {
    if (inside(a, p) || inside(b, p))
        return 0;
    double d = 1e100;
    for (size_t i = 0; i < p.size(); ++i)
        d = std::min(d, segment_distance(a, b, p[i], p[(i + 1) % p.size()]));
    return d;
}
double gap(const Shape &a, const Shape &b) {
    if (a.polygon.empty() && b.polygon.empty())
        return segment_distance(a.a, a.b, b.a, b.b) - a.radius - b.radius;
    if (a.polygon.empty())
        return segment_polygon(a.a, a.b, b.polygon) - a.radius;
    if (b.polygon.empty())
        return segment_polygon(b.a, b.b, a.polygon) - b.radius;
    if (inside(a.polygon[0], b.polygon) || inside(b.polygon[0], a.polygon))
        return 0;
    double d = 1e100;
    for (size_t i = 0; i < a.polygon.size(); ++i)
        for (size_t j = 0; j < b.polygon.size(); ++j)
            d = std::min(d, segment_distance(a.polygon[i], a.polygon[(i + 1) % a.polygon.size()],
                                             b.polygon[j], b.polygon[(j + 1) % b.polygon.size()]));
    return d;
}
double boundary_gap(const Shape &a, const std::vector<Point> &poly) {
    double d = 1e100;
    for (size_t j = 0; j < poly.size(); ++j) {
        auto c = poly[j], e = poly[(j + 1) % poly.size()];
        if (a.polygon.empty())
            d = std::min(d, segment_distance(a.a, a.b, c, e) - a.radius);
        else
            for (size_t i = 0; i < a.polygon.size(); ++i)
                d = std::min(d, segment_distance(a.polygon[i], a.polygon[(i + 1) % a.polygon.size()], c, e));
    }
    return d;
}
bool share_layer(const Shape &a, const Shape &b) {
    for (int z : a.layers)
        if (std::find(b.layers.begin(), b.layers.end(), z) != b.layers.end())
            return true;
    return false;
}
} // namespace mr
