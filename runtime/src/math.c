#include "math_rt.h"

#include <math.h>


static uint64_t rt_math_bool_result(int predicate) {
    return predicate ? 1u : 0u;
}

static double rt_math_java_like_minmax_zero(double left, double right, int pick_max) {
    if (signbit(left) == signbit(right)) {
        return left;
    }
    if (pick_max) {
        return signbit(left) ? right : left;
    }
    return signbit(left) ? left : right;
}

double rt_math_sin(double value) {
    return sin(value);
}

double rt_math_cos(double value) {
    return cos(value);
}

double rt_math_tan(double value) {
    return tan(value);
}

double rt_math_asin(double value) {
    return asin(value);
}

double rt_math_acos(double value) {
    return acos(value);
}

double rt_math_atan(double value) {
    return atan(value);
}

double rt_math_atan2(double y, double x) {
    return atan2(y, x);
}

double rt_math_exp(double value) {
    return exp(value);
}

double rt_math_log(double value) {
    return log(value);
}

double rt_math_log10(double value) {
    return log10(value);
}

double rt_math_pow(double base, double exponent) {
    return pow(base, exponent);
}

double rt_math_sqrt(double value) {
    return sqrt(value);
}

double rt_math_cbrt(double value) {
    return cbrt(value);
}

double rt_math_floor(double value) {
    return floor(value);
}

double rt_math_ceil(double value) {
    return ceil(value);
}

double rt_math_round(double value) {
    return round(value);
}

double rt_math_trunc(double value) {
    return trunc(value);
}

double rt_math_abs(double value) {
    return fabs(value);
}

double rt_math_min(double left, double right) {
    if (isnan(left) || isnan(right)) {
        return NAN;
    }
    if (left == 0.0 && right == 0.0) {
        return rt_math_java_like_minmax_zero(left, right, 0);
    }
    return left < right ? left : right;
}

double rt_math_max(double left, double right) {
    if (isnan(left) || isnan(right)) {
        return NAN;
    }
    if (left == 0.0 && right == 0.0) {
        return rt_math_java_like_minmax_zero(left, right, 1);
    }
    return left > right ? left : right;
}

double rt_math_hypot(double left, double right) {
    return hypot(left, right);
}

uint64_t rt_math_is_nan(double value) {
    return rt_math_bool_result(isnan(value));
}

uint64_t rt_math_is_infinite(double value) {
    return rt_math_bool_result(isinf(value));
}