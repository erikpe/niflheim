import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

public final class solver2 {
    private interface Hashable {
        long hashCodeValue();
    }

    private interface Equalable {
        boolean equalsValue(Object other);
    }

    private static final class MyMap {
        private long len = 0L;
        private long capacity;
        private Object[] keys;
        private Object[] values;
        private boolean[] occupied;

        private MyMap(long capacity, Object[] keys, Object[] values, boolean[] occupied) {
            this.capacity = capacity;
            this.keys = keys;
            this.values = values;
            this.occupied = occupied;
        }

        static MyMap newMap() {
            return withCapacity(8L);
        }

        static MyMap withCapacity(long minCapacity) {
            long selectedCapacity = 8L;
            while (selectedCapacity < minCapacity) {
                selectedCapacity = selectedCapacity * 2L;
            }
            int arraySize = toIntExact(selectedCapacity);
            return new MyMap(selectedCapacity, new Object[arraySize], new Object[arraySize], new boolean[arraySize]);
        }

        long len() {
            return this.len;
        }

        boolean contains(Object key) {
            return this.findExistingIndex(key) >= 0;
        }

        Object indexGet(Object key) {
            int index = this.findExistingIndex(key);
            if (index < 0) {
                throw new IllegalStateException("Map.index_get: key not found");
            }
            return this.values[index];
        }

        void put(Object key, Object value) {
            this.maybeGrowForInsert();
            if (this.insertOrAssign(key, value)) {
                this.len = this.len + 1L;
            }
        }

        private void maybeGrowForInsert() {
            if (((this.len + 1L) * 10L) < (this.capacity * 7L)) {
                return;
            }
            this.rehash(this.capacity * 2L);
        }

        private void rehash(long newCapacity) {
            int oldCapacity = toIntExact(this.capacity);
            Object[] oldKeys = this.keys;
            Object[] oldValues = this.values;
            boolean[] oldOccupied = this.occupied;

            this.capacity = newCapacity;
            this.keys = new Object[toIntExact(newCapacity)];
            this.values = new Object[toIntExact(newCapacity)];
            this.occupied = new boolean[toIntExact(newCapacity)];
            this.len = 0L;

            for (int i = 0; i < oldCapacity; i++) {
                if (oldOccupied[i]) {
                    if (this.insertOrAssign(oldKeys[i], oldValues[i])) {
                        this.len = this.len + 1L;
                    }
                }
            }
        }

        private int findExistingIndex(Object key) {
            int capacityI32 = toIntExact(this.capacity);
            int index = indexFor(key, this.capacity);
            int probes = 0;

            while (probes < capacityI32) {
                if (!this.occupied[index]) {
                    return -1;
                }
                if (asEqualable(this.keys[index]).equalsValue(key)) {
                    return index;
                }
                index = index + 1;
                if (index >= capacityI32) {
                    index = 0;
                }
                probes = probes + 1;
            }

            return -1;
        }

        private boolean insertOrAssign(Object key, Object value) {
            int capacityI32 = toIntExact(this.capacity);
            int index = indexFor(key, this.capacity);
            int probes = 0;

            while (probes < capacityI32) {
                if (!this.occupied[index]) {
                    this.occupied[index] = true;
                    this.keys[index] = key;
                    this.values[index] = value;
                    return true;
                }
                if (asEqualable(this.keys[index]).equalsValue(key)) {
                    this.values[index] = value;
                    return false;
                }
                index = index + 1;
                if (index >= capacityI32) {
                    index = 0;
                }
                probes = probes + 1;
            }

            throw new IllegalStateException("Map: table full");
        }
    }

    private static final class MyStr implements Hashable, Equalable {
        final String raw;

        MyStr(String raw) {
            this.raw = raw;
        }

        @Override
        public long hashCodeValue() {
            long hash = 0L;
            for (int i = 0; i < this.raw.length(); i++) {
                hash = hash * 31L + this.raw.charAt(i);
            }
            return hash;
        }

        @Override
        public boolean equalsValue(Object other) {
            if (other == null) {
                return false;
            }
            if (!(other instanceof MyStr rightStr)) {
                return false;
            }
            return this.raw.equals(rightStr.raw);
        }
    }

    private static final class CacheElem implements Hashable, Equalable {
        final long start;
        final long end;

        CacheElem(long start, long end) {
            this.start = start;
            this.end = end;
        }

        @Override
        public boolean equals(Object other) {
            return this.equalsValue(other);
        }

        @Override
        public boolean equalsValue(Object other) {
            if (other == null) {
                return false;
            }
            if (!(other instanceof CacheElem rightCache)) {
                return false;
            }
            return this.start == rightCache.start && this.end == rightCache.end;
        }

        @Override
        public int hashCode() {
            long hash = this.hashCodeValue();
            return (int)(hash ^ (hash >>> 32));
        }

        @Override
        public long hashCodeValue() {
            long hash = 117L;
            hash = hash * 311L + this.start;
            hash = hash * 311L + this.end;
            return hash;
        }
    }

    private solver2() {
    }

    private static long findAllPathsDAG(long[][] graph, MyMap memoizeCache, long start, long end) {
        if (start == end) {
            return 1L;
        }

        CacheElem elem = new CacheElem(start, end);
        if (memoizeCache.contains(elem)) {
            return ((Long)memoizeCache.indexGet(elem)).longValue();
        }

        long paths = 0L;
        for (long node : graph[(int)start]) {
            paths = paths + findAllPathsDAG(graph, memoizeCache, node, end);
        }

        memoizeCache.put(elem, Long.valueOf(paths));
        return paths;
    }

    public static void main(String[] args) throws IOException {
        String input = readStdin();
        long sum = 0L;
        for (long i = 0L; i < 1000L; i++) {
            sum = sum + run(input);
            System.out.print("Iteration ");
            System.out.println(i);
        }

        if (sum == Long.MIN_VALUE) {
            System.out.println(sum);
        }
    }

    private static long run(String input) {
        List<String> lines = splitLines(input);
        MyMap keymap = MyMap.newMap();
        long key = 0L;
        String line;
        for (String lineObj1 : lines) {
            line = lineObj1;
            keymap.put(new MyStr(line.substring(0, 3)), Long.valueOf(key));
            key = key + 1L;
        }
        keymap.put(new MyStr("out"), Long.valueOf(key));

        long svrKey = ((Long)keymap.indexGet(new MyStr("svr"))).longValue();
        long dacKey = ((Long)keymap.indexGet(new MyStr("dac"))).longValue();
        long fftKey = ((Long)keymap.indexGet(new MyStr("fft"))).longValue();
        long outKey = ((Long)keymap.indexGet(new MyStr("out"))).longValue();

        long i = 0L;
        long[][] graph = new long[lines.size() + 1][];
        for (String lineObj2 : lines) {
            line = lineObj2;
            key = ((Long)keymap.indexGet(new MyStr(line.substring(0, 3)))).longValue();
            List<String> nodes = splitBySpace(line.substring(5));
            long[] nodeArr = new long[nodes.size()];
            i = 0L;
            for (String nodeObj : nodes) {
                nodeArr[(int)i] = ((Long)keymap.indexGet(new MyStr(nodeObj))).longValue();
                i = i + 1L;
            }
            graph[(int)key] = nodeArr;
        }
        graph[(int)outKey] = new long[0];

        MyMap memoizeCache = MyMap.newMap();

        long fftDac =
            findAllPathsDAG(graph, memoizeCache, svrKey, fftKey) *
            findAllPathsDAG(graph, memoizeCache, fftKey, dacKey) *
            findAllPathsDAG(graph, memoizeCache, dacKey, outKey);
        long dacFft =
            findAllPathsDAG(graph, memoizeCache, svrKey, dacKey) *
            findAllPathsDAG(graph, memoizeCache, dacKey, fftKey) *
            findAllPathsDAG(graph, memoizeCache, fftKey, outKey);
        long numPaths = fftDac + dacFft;

        System.out.print("RESULT:");
        System.out.println(numPaths);

        return 0L;
    }

    private static String readStdin() throws IOException {
        return new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
    }

    private static List<String> splitLines(String input) {
        ArrayList<String> lines = new ArrayList<>();
        input.lines().forEach(lines::add);
        return lines;
    }

    private static List<String> splitBySpace(String value) {
        if (value.isEmpty()) {
            return new ArrayList<>();
        }
        return new ArrayList<>(List.of(value.split(" ")));
    }

    private static Hashable asHashable(Object value) {
        if (!(value instanceof Hashable hashable)) {
            throw new IllegalStateException("Map: key is not Hashable");
        }
        return hashable;
    }

    private static Equalable asEqualable(Object value) {
        if (!(value instanceof Equalable equalable)) {
            throw new IllegalStateException("Map: key is not Equalable");
        }
        return equalable;
    }

    private static int indexFor(Object key, long capacity) {
        long hash = asHashable(key).hashCodeValue();
        long index = Long.remainderUnsigned(hash, capacity);
        return toIntExact(index);
    }

    private static int toIntExact(long value) {
        if (value < Integer.MIN_VALUE || value > Integer.MAX_VALUE) {
            throw new IllegalStateException("integer overflow");
        }
        return (int)value;
    }
}