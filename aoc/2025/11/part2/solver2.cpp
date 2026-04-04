#include <cstdint>
#include <iostream>
#include <iterator>
#include <limits>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>


struct CacheElem {
    std::int64_t start;
    std::int64_t end;

    bool operator==(const CacheElem& other) const {
        return start == other.start && end == other.end;
    }
};


struct CacheElemHash {
    std::size_t operator()(const CacheElem& value) const {
        std::uint64_t hash_value = 117u;
        hash_value = hash_value * 311u + static_cast<std::uint64_t>(value.start);
        hash_value = hash_value * 311u + static_cast<std::uint64_t>(value.end);
        return static_cast<std::size_t>(hash_value);
    }
};


static std::int64_t find_all_paths_dag(
    const std::vector<std::vector<std::int64_t>>& graph,
    std::unordered_map<CacheElem, std::int64_t, CacheElemHash>& memoize_cache,
    std::int64_t start,
    std::int64_t end
) {
    if (start == end) {
        return 1;
    }

    CacheElem elem{start, end};
    auto memoized = memoize_cache.find(elem);
    if (memoized != memoize_cache.end()) {
        return memoized->second;
    }

    std::int64_t paths = 0;
    for (std::int64_t node : graph[static_cast<std::size_t>(start)]) {
        paths = paths + find_all_paths_dag(graph, memoize_cache, node, end);
    }

    memoize_cache[elem] = paths;
    return paths;
}


static std::string read_stdin() {
    return std::string(std::istreambuf_iterator<char>(std::cin), std::istreambuf_iterator<char>());
}


static std::vector<std::string> split_lines(const std::string& input_text) {
    std::vector<std::string> lines;
    std::string current;

    for (char ch : input_text) {
        if (ch == '\n') {
            if (!current.empty() && current.back() == '\r') {
                current.pop_back();
            }
            lines.push_back(current);
            current.clear();
            continue;
        }
        current.push_back(ch);
    }

    if (!current.empty()) {
        if (!current.empty() && current.back() == '\r') {
            current.pop_back();
        }
        lines.push_back(current);
    }

    return lines;
}


static std::vector<std::string> split_by_space(const std::string& value) {
    if (value.empty()) {
        return {};
    }

    std::vector<std::string> parts;
    std::size_t start = 0;
    while (true) {
        std::size_t next = value.find(' ', start);
        if (next == std::string::npos) {
            parts.push_back(value.substr(start));
            break;
        }
        parts.push_back(value.substr(start, next - start));
        start = next + 1;
    }
    return parts;
}


static std::int64_t run(const std::string& input_text) {
    std::vector<std::string> lines = split_lines(input_text);
    std::unordered_map<std::string, std::int64_t> keymap;
    std::int64_t key = 0;

    for (const std::string& line_obj1 : lines) {
        const std::string& line = line_obj1;
        keymap[line.substr(0, 3)] = key;
        key = key + 1;
    }
    keymap["out"] = key;

    std::int64_t svr_key = keymap["svr"];
    std::int64_t dac_key = keymap["dac"];
    std::int64_t fft_key = keymap["fft"];
    std::int64_t out_key = keymap["out"];

    std::vector<std::vector<std::int64_t>> graph(lines.size() + 1);
    for (const std::string& line_obj2 : lines) {
        const std::string& line = line_obj2;
        key = keymap[line.substr(0, 3)];
        std::vector<std::string> nodes = split_by_space(line.substr(5));
        std::vector<std::int64_t> node_arr(nodes.size());
        std::int64_t i = 0;
        for (const std::string& node_obj : nodes) {
            node_arr[static_cast<std::size_t>(i)] = keymap[node_obj];
            i = i + 1;
        }
        graph[static_cast<std::size_t>(key)] = std::move(node_arr);
    }
    graph[static_cast<std::size_t>(out_key)] = {};

    std::unordered_map<CacheElem, std::int64_t, CacheElemHash> memoize_cache;

    std::int64_t fft_dac =
        find_all_paths_dag(graph, memoize_cache, svr_key, fft_key) *
        find_all_paths_dag(graph, memoize_cache, fft_key, dac_key) *
        find_all_paths_dag(graph, memoize_cache, dac_key, out_key);
    std::int64_t dac_fft =
        find_all_paths_dag(graph, memoize_cache, svr_key, dac_key) *
        find_all_paths_dag(graph, memoize_cache, dac_key, fft_key) *
        find_all_paths_dag(graph, memoize_cache, fft_key, out_key);
    std::int64_t num_paths = fft_dac + dac_fft;

    std::cout << "RESULT:" << num_paths << '\n';
    return 0;
}


int main() {
    std::string input_text = read_stdin();
    std::int64_t sum = 0;
    for (std::int64_t i = 0; i < 1000; i++) {
        sum = sum + run(input_text);
        std::cout << "Iteration " << i << '\n';
    }

    if (sum == std::numeric_limits<std::int64_t>::min()) {
        std::cout << sum << '\n';
    }
    return 0;
}