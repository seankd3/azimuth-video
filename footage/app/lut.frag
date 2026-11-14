// A shot's print LUT (grade.print_lut) and the look's vignette on the playing video: what the render shows,
// less the halation.
// The LUT is packed 2D: columns are blue * N + red, rows are green. Red and green interpolate in the texture;
// blue interpolates here between two slices, so the lookup is trilinear.
#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float graded;
    float vignette;  // the look's vignette, stops darker in the corners (grade.vignette)
    float untouched; // how far out it stays untouched (grade.VIGNETTE_FLAT)
    float squeeze;   // the oval's width: the lens squeeze, turned with the shot
    float aspect;    // the frame's width over its height
};
layout(binding = 1) uniform sampler2D source;
layout(binding = 2) uniform sampler2D lut;

const float N = 33.0;

vec3 slice(vec2 rg, float b) {
    vec2 uv = vec2((b * N + rg.x * (N - 1.0) + 0.5) / (N * N), (rg.y * (N - 1.0) + 0.5) / N);
    return texture(lut, uv).rgb;
}

void main() {
    vec4 c = texture(source, qt_TexCoord0);
    vec3 code = clamp(c.rgb / max(c.a, 1e-5), 0.0, 1.0);
    float b = code.b * (N - 1.0);
    float b0 = floor(b);
    vec3 printed = mix(slice(code.rg, b0), slice(code.rg, min(b0 + 1.0, N - 1.0)), b - b0);
    // The vignette, as the render applies it: a mask on linear display light (2.4 gamma).
    vec2 p = vec2((qt_TexCoord0.x - 0.5) * aspect / squeeze, qt_TexCoord0.y - 0.5);
    float d = length(p) / length(vec2(0.5 * aspect / squeeze, 0.5));
    float t = clamp((d - untouched) / (1.0 - untouched), 0.0, 1.0);
    printed *= pow(exp2(-vignette * t * t * (3.0 - 2.0 * t)), 1.0 / 2.4);
    fragColor = vec4(mix(code, printed, graded) * c.a, c.a) * qt_Opacity;
}
