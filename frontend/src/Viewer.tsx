import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { IS_LOCAL, type ViewerPayload } from "./api";

const cssColor = (name: string, fallback: string) => {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return new THREE.Color(v || fallback);
};

export type ViewName = "iso" | "alzado" | "perfil" | "planta";
interface Props {
  payload: ViewerPayload | null;
  mode: "tecnico" | "comercial";
  explode: number;
  hidden: Set<string>;
  selected: string | null;
  onSelect: (id: string | null) => void;
  measuring: boolean;
  view: { name: ViewName; n: number };
  theme?: string;
}

function decode(b64: string | Float32Array | Uint32Array, T: Float32ArrayConstructor | Uint32ArrayConstructor) {
  if (typeof b64 !== "string") return b64;
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new T(bytes.buffer);
}

interface Item { group: THREE.Group; mesh: THREE.Mesh; base: THREE.Matrix4; explode: THREE.Vector3; color: THREE.Color }

export default function Viewer(p: Props) {
  const host = useRef<HTMLDivElement>(null);
  const ctx = useRef<{
    renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera; controls: OrbitControls;
    root: THREE.Group; items: Map<string, Item>; ground: THREE.Mesh; lights: THREE.Group; measure: THREE.Group;
  } | null>(null);
  const [measurePts, setMeasurePts] = useState<THREE.Vector3[]>([]);
  const [dist, setDist] = useState<number | null>(null);

  // ---------------------------------------------------------------- inicialización
  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 10, 50000);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    const root = new THREE.Group();
    scene.add(root);
    const lights = new THREE.Group();
    lights.add(new THREE.HemisphereLight(0xffffff, 0x8a8f98, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(2500, -3500, 5000);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 2;
    Object.assign(sun.shadow.camera, { left: -3000, right: 3000, top: 3000, bottom: -3000, near: 100, far: 15000 });
    lights.add(sun);
    scene.add(lights);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(20000, 20000), new THREE.ShadowMaterial({ opacity: 0.18 }));
    ground.receiveShadow = true;
    scene.add(ground);
    const measure = new THREE.Group();
    scene.add(measure);
    ctx.current = { renderer, scene, camera, controls, root, items: new Map(), ground, lights, measure };
    const resize = () => {
      const w = el.clientWidth, h = el.clientHeight;
      renderer.setSize(w, h);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();
    let raf = 0;
    const loop = () => { controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(loop); };
    loop();
    return () => { cancelAnimationFrame(raf); ro.disconnect(); renderer.dispose(); el.removeChild(renderer.domElement); };
  }, []);

  // ---------------------------------------------------------------- geometría
  useEffect(() => {
    const c = ctx.current;
    if (!c || !p.payload) return;
    c.root.clear();
    c.items.clear();
    const geoms = new Map<string, { g: THREE.BufferGeometry; e: THREE.EdgesGeometry }>();
    for (const [key, part] of Object.entries(p.payload.parts)) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(decode(part.positions, Float32Array), 3));
      g.setIndex(new THREE.BufferAttribute(decode(part.indices, Uint32Array), 1));
      g.computeVertexNormals();
      geoms.set(key, { g, e: new THREE.EdgesGeometry(g, 28) });
    }
    for (const inst of p.payload.instances) {
      const gg = geoms.get(inst.part)!;
      const color = new THREE.Color(...(inst.color as [number, number, number]));
      const mesh = new THREE.Mesh(gg.g, new THREE.MeshStandardMaterial({ color }));
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.userData.id = inst.id;
      const edges = new THREE.LineSegments(gg.e, new THREE.LineBasicMaterial({ color: 0x1b1f24 }));
      const group = new THREE.Group();
      group.add(mesh, edges);
      group.matrixAutoUpdate = false;
      const base = new THREE.Matrix4().fromArray(inst.matrix);
      group.matrix.copy(base);
      c.root.add(group);
      c.items.set(inst.id, { group, mesh, base, explode: new THREE.Vector3(...inst.explode), color });
    }
    fit("iso");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.payload]);

  // ---------------------------------------------------------------- estado visual
  useEffect(() => {
    const c = ctx.current;
    if (!c) return;
    const tech = p.mode === "tecnico";
    c.scene.background = tech ? cssColor("--viewer", "#f2f4f7") : cssColor("--viewer-real", "#dde3ea");
    const partTech = cssColor("--part-tech", "#d3d9e0"), sel3d = cssColor("--sel-3d", "#3a86ff"), edge = cssColor("--edge", "#1b1f24");
    c.ground.visible = !tech;
    c.renderer.toneMapping = tech ? THREE.NoToneMapping : THREE.ACESFilmicToneMapping;
    for (const [id, it] of c.items) {
      const m = it.mesh.material as THREE.MeshStandardMaterial;
      const sel = id === p.selected;
      m.color.copy(tech ? (sel ? sel3d : partTech) : it.color);
      ((it.group.children[1] as THREE.LineSegments).material as THREE.LineBasicMaterial).color.copy(edge);
      m.metalness = tech ? 0 : 0.35;
      m.roughness = tech ? 1 : 0.42;
      m.emissive = new THREE.Color(sel ? 0x1d4ed8 : 0x000000);
      m.emissiveIntensity = sel ? 0.35 : 0;
      (it.group.children[1] as THREE.LineSegments).visible = tech || sel;
      it.mesh.castShadow = !tech;
      it.mesh.receiveShadow = !tech;
      it.group.visible = !p.hidden.has(id);
      const off = it.explode.clone().multiplyScalar(p.explode);
      it.group.matrix.copy(new THREE.Matrix4().makeTranslation(off.x, off.y, off.z).multiply(it.base));
    }
  }, [p.mode, p.selected, p.hidden, p.explode, p.payload, p.theme]);

  useEffect(() => { if (p.view.n) fit(p.view.name); /* eslint-disable-next-line */ }, [p.view]);
  useEffect(() => { if (!p.measuring) { setMeasurePts([]); setDist(null); ctx.current?.measure.clear(); } }, [p.measuring]);

  function fit(name: ViewName) {
    const c = ctx.current;
    if (!c || !p.payload) return;
    const [lo, hi] = p.payload.bbox;
    const center = new THREE.Vector3((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2);
    const size = Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]);
    const d = size * 2.1;
    const dirs: Record<ViewName, THREE.Vector3> = {
      iso: new THREE.Vector3(0.9, -1.25, 0.85), alzado: new THREE.Vector3(0, -1, 0.0001),
      perfil: new THREE.Vector3(-1, 0, 0.0001), planta: new THREE.Vector3(0.0001, -0.0001, 1),
    };
    const dir = dirs[name].normalize();
    c.camera.position.copy(center.clone().add(dir.multiplyScalar(d)));
    c.camera.up.set(name === "planta" ? 0 : 0, name === "planta" ? 1 : 0, name === "planta" ? 0 : 1);
    c.controls.target.copy(center);
    c.controls.update();
  }

  function pick(ev: React.MouseEvent) {
    const c = ctx.current;
    if (!c) return;
    const r = c.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, c.camera);
    const meshes = [...c.items.values()].filter((i) => i.group.visible).map((i) => i.mesh);
    const hit = ray.intersectObjects(meshes, false)[0];
    if (p.measuring) {
      if (!hit) return;
      const pts = measurePts.length >= 2 ? [hit.point.clone()] : [...measurePts, hit.point.clone()];
      setMeasurePts(pts);
      c.measure.clear();
      for (const q of pts) {
        const s = new THREE.Mesh(new THREE.SphereGeometry(6), new THREE.MeshBasicMaterial({ color: 0xe63946 }));
        s.position.copy(q);
        c.measure.add(s);
      }
      if (pts.length === 2) {
        c.measure.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
          new THREE.LineBasicMaterial({ color: 0xe63946, depthTest: false })));
        setDist(pts[0].distanceTo(pts[1]));
      } else setDist(null);
      return;
    }
    p.onSelect(hit ? (hit.object.userData.id as string) : null);
  }

  return (
    <div className="viewer" ref={host} onDoubleClick={pick} onClick={(e) => p.measuring && pick(e)}>
      {p.mode === "comercial" && <div className="viewer-badge warn">Visualización comercial · no es documentación técnica</div>}
      {p.mode === "tecnico" && <div className="viewer-badge">{IS_LOCAL ? "Modelo técnico · malla generada en el navegador (taladros no representados)" : "Modelo CAD técnico · B-rep OpenCascade teselado"}</div>}
      {p.measuring && (
        <div className="viewer-measure">
          {dist === null ? `Medición: seleccione ${2 - measurePts.length} punto(s)` :
            `Distancia: ${dist.toFixed(1).replace(".", ",")} mm  (ΔX ${Math.abs(measurePts[1].x - measurePts[0].x).toFixed(1)} · ΔY ${Math.abs(measurePts[1].y - measurePts[0].y).toFixed(1)} · ΔZ ${Math.abs(measurePts[1].z - measurePts[0].z).toFixed(1)})`}
        </div>
      )}
      {!p.payload && <div className="viewer-empty">Pulse «GENERAR DISEÑO TÉCNICO» para construir el modelo</div>}
    </div>
  );
}
