#include "runtime.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>


static void fail(const char* message) {
    fprintf(stderr, "test_math_runtime: %s\n", message);
    exit(1);
}

static void assert_true(int condition, const char* message) {
    if (!condition) {
        fail(message);
    }
}

static void assert_close(double actual, double expected, double tolerance, const char* message) {
    double diff = fabs(actual - expected);
    if (diff > tolerance) {
        fprintf(
            stderr,
            "test_math_runtime: %s (actual=%0.17g expected=%0.17g diff=%0.17g tolerance=%0.17g)\n",
            message,
            actual,
            expected,
            diff,
            tolerance
        );
        exit(1);
    }
}

static void test_unary_wrappers_match_libm(void) {
    assert_close(rt_math_sin(0.5), sin(0.5), 1e-15, "sin should match libm");
    assert_close(rt_math_cos(-1.25), cos(-1.25), 1e-15, "cos should match libm");
    assert_close(rt_math_tan(0.25), tan(0.25), 1e-15, "tan should match libm");
    assert_close(rt_math_asin(0.5), asin(0.5), 1e-15, "asin should match libm");
    assert_close(rt_math_acos(0.5), acos(0.5), 1e-15, "acos should match libm");
    assert_close(rt_math_atan(-2.0), atan(-2.0), 1e-15, "atan should match libm");
    assert_close(rt_math_exp(1.0), exp(1.0), 1e-15, "exp should match libm");
    assert_close(rt_math_log(3.0), log(3.0), 1e-15, "log should match libm");
    assert_close(rt_math_log10(1000.0), log10(1000.0), 1e-15, "log10 should match libm");
    assert_close(rt_math_sqrt(81.0), sqrt(81.0), 1e-15, "sqrt should match libm");
    assert_close(rt_math_cbrt(-27.0), cbrt(-27.0), 1e-15, "cbrt should match libm");
    assert_close(rt_math_floor(-1.25), floor(-1.25), 0.0, "floor should match libm");
    assert_close(rt_math_ceil(-1.25), ceil(-1.25), 0.0, "ceil should match libm");
    assert_close(rt_math_round(-1.5), round(-1.5), 0.0, "round should match libm");
    assert_close(rt_math_trunc(-1.75), trunc(-1.75), 0.0, "trunc should match libm");
    assert_close(rt_math_abs(-123.5), fabs(-123.5), 0.0, "abs should match libm");
}

static void test_binary_wrappers_match_libm(void) {
    assert_close(rt_math_atan2(1.0, -1.0), atan2(1.0, -1.0), 1e-15, "atan2 should match libm");
    assert_close(rt_math_pow(2.0, 10.0), pow(2.0, 10.0), 0.0, "pow should match libm");
    assert_close(rt_math_hypot(3.0, 4.0), hypot(3.0, 4.0), 0.0, "hypot should match libm");
}

static void test_predicates_wrap_libm_classification(void) {
    double nan_value = 0.0 / 0.0;
    double pos_inf = 1.0 / 0.0;

    assert_true(rt_math_is_nan(nan_value) == 1u, "is_nan should detect NaN");
    assert_true(rt_math_is_nan(1.0) == 0u, "is_nan should reject finite values");
    assert_true(rt_math_is_infinite(pos_inf) == 1u, "is_infinite should detect infinity");
    assert_true(rt_math_is_infinite(nan_value) == 0u, "is_infinite should reject NaN");
}

static void test_min_max_follow_java_like_nan_and_signed_zero_rules(void) {
    double nan_value = 0.0 / 0.0;
    double neg_zero = -0.0;
    double pos_zero = 0.0;

    assert_true(isnan(rt_math_min(nan_value, 1.0)), "min should propagate NaN");
    assert_true(isnan(rt_math_max(1.0, nan_value)), "max should propagate NaN");
    assert_true(signbit(rt_math_min(neg_zero, pos_zero)) != 0, "min should preserve -0.0");
    assert_true(signbit(rt_math_max(neg_zero, pos_zero)) == 0, "max should preserve +0.0");
    assert_close(rt_math_min(3.0, -4.0), -4.0, 0.0, "min should choose smaller value");
    assert_close(rt_math_max(3.0, -4.0), 3.0, 0.0, "max should choose larger value");
}

int main(void) {
    rt_init();

    test_unary_wrappers_match_libm();
    test_binary_wrappers_match_libm();
    test_predicates_wrap_libm_classification();
    test_min_max_follow_java_like_nan_and_signed_zero_rules();

    rt_shutdown();
    puts("test_math_runtime: ok");
    return 0;
}