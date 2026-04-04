# TODO

Personal reminder list for important future work.

## Structural Sugar

1. Support interface-typed indexing sugar for `value[index]` when the interface declares a compatible `index_get(K) -> R` method.
2. Support interface-typed index assignment sugar for `value[index] = rhs` when the interface declares a compatible `index_set(K, V) -> unit` method.
3. Support interface-typed slice sugar for `value[begin:end]` and `value[begin:end] = rhs` when the interface declares compatible `slice_get` and `slice_set` methods.
4. Support interface-typed `for ... in` when the interface declares compatible `iter_len() -> u64` and `iter_get(i64) -> T` methods.
5. Add golden coverage for the positive interface-typed cases above once the implementation exists.

## Notes

- The structural sugar design already intends these behaviors; the current gaps are implementation-side.
- Arrays and concrete class receivers already work for the corresponding sugar paths.