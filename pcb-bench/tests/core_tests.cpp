#include "megaroute/core.hpp"
#include <algorithm>
#include <iostream>
#include <stdexcept>
using namespace mr;
static void expect(bool value, const char *name) {
    if (!value)
        throw std::runtime_error(name);
}
int main() {
    try {
        expect(std::abs(point_segment({3, 1}, {0, 0}, {2, 0}) - std::sqrt(2.)) < eps,
               "finite segment endpoint distance");
        expect(segment_distance({0, 0}, {2, 2}, {0, 2}, {2, 0}) == 0, "crossing segments");
        expect(!simple_polygon({{0, 0}, {2, 2}, {0, 2}, {2, 0}}), "reject self intersection");
        Shape polygon;
        polygon.polygon = {{0, 0}, {4, 0}, {4, 4}, {0, 4}};
        Shape circle;
        circle.a = circle.b = {2, 2};
        circle.radius = .2;
        expect(gap(circle, polygon) < 0, "contained circle is collision");
        circle.a = circle.b = {5, 2};
        expect(std::abs(gap(circle, polygon) - .8) < eps, "polygon circle distance");
        Shape wire;
        wire.a = {-1, 2};
        wire.b = {5, 2};
        wire.radius = .1;
        expect(gap(wire, polygon) < 0, "whole segment crossing");
        auto c = candidates({0, 0}, 0, {2, 2}, 0, 1, 2);
        auto axis = std::find_if(c.begin(), c.end(), [](auto &x) { return x.operation == "axis"; });
        expect(axis != c.end() && axis->p.x == 0 && axis->p.y == 2, "axis tie uses y");
        auto count = [](auto &list, const std::string &op) {
            return std::count_if(list.begin(), list.end(), [&](auto &x) { return x.operation == op; });
        };
        c = candidates({0, 0}, 0, {2, 3}, 0, 1, 3);
        expect(count(c, "diagonal") == 0, "strict q < delta");
        expect(count(c, "layer") == 2, "all layer candidates");
        c = candidates({0, 0}, 0, {.5, .5}, 0, 1, 2);
        expect(count(c, "end") == 1, "diagonal end");
        c = candidates({0, 0}, 0, {1, 0}, 0, 1, 2);
        expect(count(c, "end") == 0, "strict end distance");
        expect(std::abs(heuristic({0, 0}, {2, 1}) - (1 + std::sqrt(2.))) < eps, "octile heuristic");
        expect(logistic_penalty(0) == 0 && std::abs(logistic_penalty(10) - 100) < eps &&
                   std::abs(logistic_penalty(20) - 200) < eps,
               "logistic endpoints midpoint");
        Board b;
        b.outline = {{0, 0}, {10, 0}, {10, 10}, {0, 10}};
        b.layers = 3;
        b.nets = {{"A", .2, .2}, {"B", .2, .2}};
        Shape via;
        via.id = "via";
        via.net = "A";
        via.kind = "via";
        via.a = via.b = {5, 5};
        via.radius = .3;
        via.drill = .3;
        via.layers = {0, 1, 2};
        Shape obstacle;
        obstacle.id = "middle";
        obstacle.net = "B";
        obstacle.kind = "circle";
        obstacle.a = obstacle.b = {5, 5};
        obstacle.radius = .3;
        obstacle.layers = {1};
        expect(!check_shape(b, via, {obstacle}).empty(), "via middle layer collision");
        obstacle.layers = {0};
        via.layers = {2};
        expect(check_shape(b, via, {obstacle}).empty(), "different layers do not collide");
        bool rejected = false;
        try {
            EasyEdaImporter{}.load("foo.epro");
        } catch (...) {
            rejected = true;
        }
        expect(rejected, "EasyEDA explicit rejection");
        std::cout << "All core checks passed\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
