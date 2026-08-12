'use client';

import { useEffect, useRef } from 'react';
import { Camera, Geometry, Mesh, Program, Renderer } from 'ogl';

/**
 * The animated field behind the chat column.
 *
 * The response mode is a claim about depth — concise skims the surface, detailed
 * runs a reasoning pass through the whole picture — so the backdrop makes that
 * claim literally rather than decoratively. One morph parameter drives every
 * visual: at 0 the motes lie on a single sheet, all the same size, lit the same,
 * drifting quickly sideways; at 1 the same motes are stretched away from the
 * camera, sized and dimmed by distance, turning slowly so the parallax reads.
 *
 * That single parameter is eased in the render loop rather than swapped, so
 * changing mode is a visible transition of the space itself, not a cut between
 * two effects.
 *
 * Adapted from the React Bits "Particles" background (ogl point cloud). The
 * differences that matter: props are read through refs so the WebGL context is
 * built once instead of being torn down on every mode change, the depth cues are
 * driven by a uniform so they can be turned off continuously, and colour comes
 * from the design tokens at runtime instead of being passed in as hex.
 */

type ChatMode = 'concise' | 'detailed';

interface ChatModeBackdropProps {
  mode: ChatMode;
  /** True while a request is in flight — the field quickens and brightens. */
  busy?: boolean;
}

const PARTICLE_COUNT = 340;
const BASE_SIZE = 3.0;

/** Reads a design token so the field cannot drift away from the rest of the UI. */
const readToken = (name: string, fallback: string): string => {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
};

const hexToRgb = (hex: string): [number, number, number] => {
  let value = hex.replace(/^#/, '');
  if (value.length === 3) {
    value = value
      .split('')
      .map((c) => c + c)
      .join('');
  }
  const int = parseInt(value.slice(0, 6), 16);
  if (Number.isNaN(int)) return [1, 1, 1];
  return [((int >> 16) & 255) / 255, ((int >> 8) & 255) / 255, (int & 255) / 255];
};

const vertexShader = /* glsl */ `
  attribute vec3 position;
  attribute vec4 random;

  uniform mat4 modelMatrix;
  uniform mat4 viewMatrix;
  uniform mat4 projectionMatrix;
  uniform float uTime;
  uniform float uSpread;
  uniform float uDepth;
  uniform float uSizeRand;
  uniform float uBaseSize;
  uniform float uDpr;

  varying float vFade;
  varying float vSeed;

  void main() {
    vSeed = random.y;

    vec3 pos = position * uSpread;
    // The line that separates the two modes: concise collapses the cloud onto a
    // sheet, detailed stretches it along the view axis.
    pos.z *= mix(0.25, 9.0, uDepth);

    vec4 mPos = modelMatrix * vec4(pos, 1.0);
    float amp = mix(0.30, 1.50, uDepth);
    mPos.x += sin(uTime * random.z + 6.2831 * random.w) * amp;
    mPos.y += sin(uTime * random.y + 6.2831 * random.x) * amp;
    // Nothing moves toward or away from the camera on a flat sheet.
    mPos.z += sin(uTime * random.w + 6.2831 * random.y) * amp * uDepth;

    vec4 mvPos = viewMatrix * mPos;
    float dist = max(length(mvPos.xyz), 0.001);

    // Distance attenuation is the depth cue. At uDepth 0 the term collapses to
    // 1.0 and every mote reads identically, which is what "surface" means here.
    // The floor is deliberately well above zero: the far half of the volume
    // should recede, not disappear, or the deep mode ends up dimmer overall
    // than the flat one it is supposed to out-weigh.
    float atten = mix(1.0, clamp(16.0 / dist, 0.42, 2.6), uDepth);
    vFade = atten;

    float jitter = 1.0 + uSizeRand * (random.x - 0.5) * 1.3;
    gl_PointSize = uBaseSize * uDpr * jitter * atten;
    gl_Position = projectionMatrix * mvPos;
  }
`;

const fragmentShader = /* glsl */ `
  precision highp float;

  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform float uMix;
  uniform float uAlpha;

  varying float vFade;
  varying float vSeed;

  void main() {
    vec2 uv = gl_PointCoord - 0.5;
    float d = length(uv);

    // A hard disc a few pixels wide reads as dirt on the screen; a core plus a
    // wide falloff reads as light.
    float core = smoothstep(0.5, 0.06, d);
    float halo = smoothstep(0.5, 0.0, d) * 0.45;

    vec3 col = mix(uColorA, uColorB, uMix);
    float brightness = 0.55 + 0.45 * vSeed;
    float alpha = (core + halo) * uAlpha * brightness * clamp(vFade, 0.30, 1.8);

    gl_FragColor = vec4(col * brightness, alpha);
  }
`;

export default function ChatModeBackdrop({ mode, busy = false }: ChatModeBackdropProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const targetRef = useRef(mode === 'detailed' ? 1 : 0);
  const busyRef = useRef(busy);
  // Set only on the reduced-motion path, where there is no loop to pick the new
  // target up on its own.
  const redrawRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    targetRef.current = mode === 'detailed' ? 1 : 0;
    redrawRef.current?.();
  }, [mode]);

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let renderer: Renderer;
    try {
      renderer = new Renderer({
        dpr: Math.min(window.devicePixelRatio || 1, 2),
        alpha: true,
        depth: false,
        antialias: false,
      });
    } catch {
      // No WebGL — the gradient layer alone still distinguishes the modes.
      return;
    }

    const gl = renderer.gl;
    const dpr = renderer.dpr;
    gl.clearColor(0, 0, 0, 0);

    const canvas = gl.canvas as HTMLCanvasElement;
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.display = 'block';
    container.appendChild(canvas);

    const camera = new Camera(gl, { fov: 20, near: 0.1, far: 200 });
    camera.position.set(0, 0, 20);

    let aspect = 1;
    const resize = () => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      if (!width || !height) return;
      renderer.setSize(width, height);
      aspect = width / height;
      camera.perspective({ aspect });
    };
    // The redraw is a no-op while the loop is running; it matters only on the
    // reduced-motion path, where nothing else would repaint after a resize.
    const observer = new ResizeObserver(() => {
      resize();
      redrawRef.current?.();
    });
    observer.observe(container);
    resize();

    const positions = new Float32Array(PARTICLE_COUNT * 3);
    const randoms = new Float32Array(PARTICLE_COUNT * 4);
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      // Rejection-sample the unit ball, then cube-root the radius: sampling the
      // cube instead would pile the motes into the corners of the volume.
      let x: number;
      let y: number;
      let z: number;
      let lengthSq: number;
      do {
        x = Math.random() * 2 - 1;
        y = Math.random() * 2 - 1;
        z = Math.random() * 2 - 1;
        lengthSq = x * x + y * y + z * z;
      } while (lengthSq > 1 || lengthSq === 0);
      const radius = Math.cbrt(Math.random());
      positions.set([x * radius, y * radius, z * radius], i * 3);
      randoms.set([Math.random(), Math.random(), Math.random(), Math.random()], i * 4);
    }

    const geometry = new Geometry(gl, {
      position: { size: 3, data: positions },
      random: { size: 4, data: randoms },
    });

    const program = new Program(gl, {
      vertex: vertexShader,
      fragment: fragmentShader,
      uniforms: {
        uTime: { value: 0 },
        uSpread: { value: 6.5 },
        uDepth: { value: targetRef.current },
        uSizeRand: { value: targetRef.current },
        uBaseSize: { value: BASE_SIZE },
        uDpr: { value: dpr },
        uColorA: { value: hexToRgb(readToken('--mode-concise', '#f43f5e')) },
        uColorB: { value: hexToRgb(readToken('--mode-detailed', '#7f96ff')) },
        uMix: { value: targetRef.current },
        uAlpha: { value: 0.48 },
      },
      transparent: true,
      depthTest: false,
      depthWrite: false,
    });
    // Additive: two overlapping motes brighten each other instead of punching a
    // dark hole, which is what source-over does over a near-black page.
    program.setBlendFunc(gl.SRC_ALPHA, gl.ONE);

    const mesh = new Mesh(gl, { mode: gl.POINTS, geometry, program });

    let morph = targetRef.current;
    let pulse = busyRef.current ? 1 : 0;
    let elapsed = 0;

    const draw = () => {
      program.uniforms.uTime.value = elapsed * 0.001;
      program.uniforms.uDepth.value = morph;
      program.uniforms.uSizeRand.value = morph;
      program.uniforms.uMix.value = morph;
      program.uniforms.uSpread.value = 6.5 + morph * 11.5;
      // Detailed carries its own step up. Spreading the same motes through a
      // volume spends most of them on the far planes, so matching concise's
      // alpha leaves the deep mode reading as the quieter of the two — the
      // opposite of what it means.
      program.uniforms.uAlpha.value = 0.48 + morph * 0.26 + pulse * 0.26;

      // Pulling the camera in while widening the lens is what makes the volume
      // open up; at morph 0 the near-telephoto view flattens what is left.
      camera.position.z = 28 - morph * 13;
      camera.fov = 12 + morph * 17;
      camera.perspective({ aspect });

      // Only the deep field turns. Rotation is a parallax cue, and there is no
      // parallax to show when every mote sits on one plane.
      mesh.rotation.x = Math.sin(elapsed * 0.00008) * 0.18 * morph;
      mesh.rotation.y = Math.cos(elapsed * 0.00011) * 0.22 * morph;

      renderer.render({ scene: mesh, camera });
    };

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let frame = 0;

    if (reduceMotion) {
      // One still frame per mode. The depth is still legible; the motion is what
      // the user asked not to have.
      redrawRef.current = () => {
        morph = targetRef.current;
        pulse = 0;
        elapsed = 0;
        draw();
      };
      redrawRef.current();
    } else {
      let last = performance.now();
      const tick = (now: number) => {
        frame = requestAnimationFrame(tick);
        // Clamped so a backgrounded tab does not resume with one enormous step.
        const dt = Math.min(now - last, 64);
        last = now;

        // Exponential approach rather than a fixed increment, so the ease looks
        // the same on a 60Hz and a 120Hz display.
        morph += (targetRef.current - morph) * (1 - Math.exp(-dt / 260));
        pulse += ((busyRef.current ? 1 : 0) - pulse) * (1 - Math.exp(-dt / 400));

        // Concise skims quickly across its sheet; detailed moves slowly through
        // its volume. Waiting on an answer speeds both up a little.
        elapsed += dt * ((1 - morph) * 0.055 + morph * 0.016 + pulse * 0.02);

        mesh.rotation.z += dt * 0.00004 * (0.35 + morph);
        draw();
      };
      frame = requestAnimationFrame(tick);
    }

    return () => {
      redrawRef.current = null;
      if (frame) cancelAnimationFrame(frame);
      observer.disconnect();
      canvas.remove();
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    };
  }, []);

  return (
    <div aria-hidden className="absolute inset-0 z-0 overflow-hidden pointer-events-none">
      <div className="chat-backdrop-well" data-mode={mode} />
      <div ref={containerRef} className="chat-backdrop-field absolute inset-0" />
    </div>
  );
}
