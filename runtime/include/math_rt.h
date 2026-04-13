#ifndef NIFLHEIM_RUNTIME_MATH_RT_H
#define NIFLHEIM_RUNTIME_MATH_RT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

double rt_math_sin(double value);
double rt_math_cos(double value);
double rt_math_tan(double value);
double rt_math_asin(double value);
double rt_math_acos(double value);
double rt_math_atan(double value);
double rt_math_atan2(double y, double x);
double rt_math_exp(double value);
double rt_math_log(double value);
double rt_math_log10(double value);
double rt_math_pow(double base, double exponent);
double rt_math_sqrt(double value);
double rt_math_cbrt(double value);
double rt_math_floor(double value);
double rt_math_ceil(double value);
double rt_math_round(double value);
double rt_math_trunc(double value);
double rt_math_abs(double value);
double rt_math_min(double left, double right);
double rt_math_max(double left, double right);
double rt_math_hypot(double left, double right);
uint64_t rt_math_is_nan(double value);
uint64_t rt_math_is_infinite(double value);

#ifdef __cplusplus
}
#endif

#endif