#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 mouseOffset;
    float maxDisplacement;
    float enableClock;
    float clockDepth;
};

layout(binding = 1) uniform sampler2D source;
layout(binding = 2) uniform sampler2D depthMap;
layout(binding = 3) uniform sampler2D clockSource;

void main() {
    vec2 uv = qt_TexCoord0;
    float depth = texture(depthMap, uv).r;
    
    // Smooth continuous displacement vector
    vec2 p = mouseOffset * maxDisplacement;
    vec2 rawOffset = p * (depth - 0.5);
    
    // Sample depth at target to test for edge occlusion leak
    vec2 tentativeUv = clamp(uv + rawOffset, vec2(0.001), vec2(0.999));
    float targetDepth = texture(depthMap, tentativeUv).r;
    
    // If background pixel tries to pull texture from foreground (targetDepth >> depth),
    // attenuate offset smoothly so background never clones foreground
    float leakDiff = targetDepth - depth;
    float leakWeight = 1.0 - smoothstep(0.04, 0.18, leakDiff);
    
    vec2 finalWallUv = clamp(uv + rawOffset * leakWeight, vec2(0.001), vec2(0.999));
    vec4 wallColor = texture(source, finalWallUv);

    if (enableClock > 0.5) {
        vec2 clockUv = clamp(uv + p * (clockDepth - 0.5), vec2(0.001), vec2(0.999));
        vec4 clockColor = texture(clockSource, clockUv);

        float occlusion = smoothstep(clockDepth - 0.03, clockDepth + 0.03, depth);
        vec3 blended = mix(wallColor.rgb, clockColor.rgb, clockColor.a * (1.0 - occlusion));
        fragColor = vec4(blended, wallColor.a) * qt_Opacity;
    } else {
        fragColor = wallColor * qt_Opacity;
    }
}
