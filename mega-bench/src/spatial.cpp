#include "megaroute/core.hpp"
#include <algorithm>
#include <stdexcept>

namespace mr {
Bounds bounds(const Shape &s) {
    Bounds box{std::min(s.a.x, s.b.x), std::min(s.a.y, s.b.y),
               std::max(s.a.x, s.b.x), std::max(s.a.y, s.b.y)};
    if (!s.polygon.empty()) {
        box = {s.polygon[0].x, s.polygon[0].y, s.polygon[0].x, s.polygon[0].y};
        for (auto p : s.polygon) {
            box.x0 = std::min(box.x0, p.x); box.y0 = std::min(box.y0, p.y);
            box.x1 = std::max(box.x1, p.x); box.y1 = std::max(box.y1, p.y);
        }
    }
    return {box.x0 - s.radius, box.y0 - s.radius, box.x1 + s.radius, box.y1 + s.radius};
}
CopperIndex::CopperIndex(const std::vector<Shape> &objects, double cell)
    : objects_(objects), cell_(cell) {
    if (!std::isfinite(cell) || cell <= eps)
        throw std::runtime_error("invalid spatial cell size");
    for (size_t i = 0; i < objects.size(); ++i) insert(i);
}
void CopperIndex::insert(size_t id) {
    if (id != bounds_.size()) throw std::runtime_error("spatial inserts must be sequential");
    auto box = bounds(objects_.at(id));
    max_clearance_override_ = std::max(max_clearance_override_, objects_[id].clearance_override);
    bounds_.push_back(box);
    auto x0 = static_cast<long long>(std::floor(box.x0 / cell_));
    auto y0 = static_cast<long long>(std::floor(box.y0 / cell_));
    auto x1 = static_cast<long long>(std::floor(box.x1 / cell_));
    auto y1 = static_cast<long long>(std::floor(box.y1 / cell_));
    for (int z : objects_[id].layers) {
        layers_[z].push_back(id);
        if (double(x1 - x0 + 1) * double(y1 - y0 + 1) > 4096) {
            wide_[z].push_back(id);
            continue;
        }
        for (auto x = x0; x <= x1; ++x)
            for (auto y = y0; y <= y1; ++y) cells_[{x, y, z}].push_back(id);
    }
}
std::vector<size_t> CopperIndex::query(const Shape &shape, double margin) const {
    auto box = bounds(shape);
    box.x0 -= margin; box.y0 -= margin; box.x1 += margin; box.y1 += margin;
    auto x0 = static_cast<long long>(std::floor(box.x0 / cell_));
    auto y0 = static_cast<long long>(std::floor(box.y0 / cell_));
    auto x1 = static_cast<long long>(std::floor(box.x1 / cell_));
    auto y1 = static_cast<long long>(std::floor(box.y1 / cell_));
    std::vector<size_t> out;
    auto take = [&](size_t id) {
        auto other = bounds_[id];
        if (box.x0 <= other.x1 && other.x0 <= box.x1 &&
            box.y0 <= other.y1 && other.y0 <= box.y1) out.push_back(id);
    };
    for (int z : shape.layers) {
        if (double(x1 - x0 + 1) * double(y1 - y0 + 1) > 4096) {
            auto it = layers_.find(z);
            if (it != layers_.end()) for (auto id : it->second) take(id);
            continue;
        }
        auto wide = wide_.find(z);
        if (wide != wide_.end()) for (auto id : wide->second) take(id);
        for (auto x = x0; x <= x1; ++x)
            for (auto y = y0; y <= y1; ++y) {
                auto it = cells_.find({x, y, z});
                if (it != cells_.end()) for (auto id : it->second) take(id);
            }
    }
    std::sort(out.begin(), out.end());
    out.erase(std::unique(out.begin(), out.end()), out.end());
    return out;
}
Connectivity::Connectivity(const std::vector<Shape> &copper) : index_(objects_) {
    for (const auto &s : copper) add(s);
}
size_t Connectivity::root(size_t id) {
    while (parents_[id] != id) {
        parents_[id] = parents_[parents_[id]];
        id = parents_[id];
    }
    return id;
}
void Connectivity::add(const Shape &shape) {
    size_t id = objects_.size();
    objects_.push_back(shape);
    const auto &stored = objects_.back();
    parents_.push_back(id);
    ids_[stored.id] = id;
    for (auto other : index_.query(stored))
        if (!stored.net.empty() && stored.net == objects_[other].net &&
            share_layer(stored, objects_[other]) && gap(stored, objects_[other]) <= eps)
            parents_[root(other)] = root(id);
    index_.insert(id);
}
bool Connectivity::connected(const std::string &a, const std::string &b) {
    auto ia = ids_.find(a), ib = ids_.find(b);
    return ia != ids_.end() && ib != ids_.end() && root(ia->second) == root(ib->second);
}
} // namespace mr
