from __future__ import annotations

import sys


class Hashable:
    def hash_code(self) -> int:
        raise NotImplementedError()


class Equalable:
    def equals(self, other: object) -> bool:
        raise NotImplementedError()


class MyMap:
    def __init__(self, capacity: int, keys: list[object | None], values: list[object | None], occupied: list[bool]) -> None:
        self._len = 0
        self._capacity = capacity
        self._keys = keys
        self._values = values
        self._occupied = occupied

    @staticmethod
    def new() -> MyMap:
        return MyMap.with_capacity(8)

    @staticmethod
    def with_capacity(min_capacity: int) -> MyMap:
        capacity = 8
        while capacity < min_capacity:
            capacity = capacity * 2
        return MyMap(capacity, [None] * capacity, [None] * capacity, [False] * capacity)

    def len(self) -> int:
        return self._len

    def contains(self, key: object) -> bool:
        return self._find_existing_index(key) >= 0

    def index_get(self, key: object) -> object:
        index = self._find_existing_index(key)
        if index < 0:
            raise RuntimeError("Map.index_get: key not found")
        return self._values[index]

    def put(self, key: object, value: object) -> None:
        self._maybe_grow_for_insert()
        if self._insert_or_assign(key, value):
            self._len = self._len + 1

    def _maybe_grow_for_insert(self) -> None:
        if ((self._len + 1) * 10) < (self._capacity * 7):
            return
        self._rehash(self._capacity * 2)

    def _rehash(self, new_capacity: int) -> None:
        old_capacity = self._capacity
        old_keys = self._keys
        old_values = self._values
        old_occupied = self._occupied

        self._capacity = new_capacity
        self._keys = [None] * new_capacity
        self._values = [None] * new_capacity
        self._occupied = [False] * new_capacity
        self._len = 0

        i = 0
        while i < old_capacity:
            if old_occupied[i]:
                if self._insert_or_assign(old_keys[i], old_values[i]):
                    self._len = self._len + 1
            i = i + 1

    def _find_existing_index(self, key: object) -> int:
        capacity_i64 = self._capacity
        index = index_for(key, self._capacity)
        probes = 0

        while probes < capacity_i64:
            if not self._occupied[index]:
                return -1
            if as_equalable(self._keys[index]).equals(key):
                return index
            index = index + 1
            if index >= capacity_i64:
                index = 0
            probes = probes + 1

        return -1

    def _insert_or_assign(self, key: object, value: object) -> bool:
        capacity_i64 = self._capacity
        index = index_for(key, self._capacity)
        probes = 0

        while probes < capacity_i64:
            if not self._occupied[index]:
                self._occupied[index] = True
                self._keys[index] = key
                self._values[index] = value
                return True
            if as_equalable(self._keys[index]).equals(key):
                self._values[index] = value
                return False
            index = index + 1
            if index >= capacity_i64:
                index = 0
            probes = probes + 1

        raise RuntimeError("Map: table full")


class MyStr(Hashable, Equalable):
    def __init__(self, raw: str) -> None:
        self.raw = raw

    def hash_code(self) -> int:
        hash_value = 14695981039346656037
        for byte in self.raw.encode("utf-8"):
            hash_value = hash_value ^ byte
            hash_value = hash_value * 1099511628211
        return hash_value

    def equals(self, other: object) -> bool:
        if other is None:
            return False
        if not isinstance(other, MyStr):
            return False
        return self.raw == other.raw


class CacheElem(Hashable, Equalable):
    def __init__(self, start: int, end: int) -> None:
        self.start = start
        self.end = end

    def hash_code(self) -> int:
        hash_value = 117
        hash_value = hash_value * 311 + self.start
        hash_value = hash_value * 311 + self.end
        return hash_value

    def equals(self, other: object) -> bool:
        if other is None:
            return False
        if not isinstance(other, CacheElem):
            return False
        return self.start == other.start and self.end == other.end


def find_all_paths_dag(graph: list[list[int]], memoize_cache: MyMap, start: int, end: int) -> int:
    if start == end:
        return 1

    elem = CacheElem(start, end)
    if memoize_cache.contains(elem):
        return int(memoize_cache.index_get(elem))

    paths = 0
    for node in graph[start]:
        paths = paths + find_all_paths_dag(graph, memoize_cache, node, end)

    memoize_cache.put(elem, paths)
    return paths


def main() -> None:
    input_text = read_stdin()
    total = 0
    for i in range(0, 1000):
        total = total + run(input_text)
        print("Iteration ", end="")
        print(i)

    if total == -(1 << 63):
        print(total)


def run(input_text: str) -> int:
    lines = split_lines(input_text)
    keymap = MyMap.new()
    key = 0
    for line_obj1 in lines:
        line = line_obj1
        keymap.put(MyStr(line[:3]), key)
        key = key + 1
    keymap.put(MyStr("out"), key)

    svr_key = int(keymap.index_get(MyStr("svr")))
    dac_key = int(keymap.index_get(MyStr("dac")))
    fft_key = int(keymap.index_get(MyStr("fft")))
    out_key = int(keymap.index_get(MyStr("out")))

    graph: list[list[int]] = [[] for _ in range(len(lines) + 1)]
    for line_obj2 in lines:
        line = line_obj2
        key = int(keymap.index_get(MyStr(line[:3])))
        nodes = split_by_space(line[5:])
        node_arr = [0] * len(nodes)
        i = 0
        for node_obj in nodes:
            node_arr[i] = int(keymap.index_get(MyStr(node_obj)))
            i = i + 1
        graph[key] = node_arr
    graph[out_key] = []

    memoize_cache = MyMap.new()

    fft_dac = (
        find_all_paths_dag(graph, memoize_cache, svr_key, fft_key)
        * find_all_paths_dag(graph, memoize_cache, fft_key, dac_key)
        * find_all_paths_dag(graph, memoize_cache, dac_key, out_key)
    )
    dac_fft = (
        find_all_paths_dag(graph, memoize_cache, svr_key, dac_key)
        * find_all_paths_dag(graph, memoize_cache, dac_key, fft_key)
        * find_all_paths_dag(graph, memoize_cache, fft_key, out_key)
    )
    num_paths = fft_dac + dac_fft

    print("RESULT:", end="")
    print(num_paths)
    return 0


def read_stdin() -> str:
    return sys.stdin.read()


def split_lines(input_text: str) -> list[str]:
    return input_text.splitlines()


def split_by_space(value: str) -> list[str]:
    if value == "":
        return []
    return value.split(" ")


def as_hashable(value: object) -> Hashable:
    if not isinstance(value, Hashable):
        raise RuntimeError("Map: key is not Hashable")
    return value


def as_equalable(value: object) -> Equalable:
    if not isinstance(value, Equalable):
        raise RuntimeError("Map: key is not Equalable")
    return value


def index_for(key: object, capacity: int) -> int:
    return as_hashable(key).hash_code() % capacity


if __name__ == "__main__":
    main()