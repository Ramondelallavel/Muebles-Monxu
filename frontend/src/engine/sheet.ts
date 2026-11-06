// @ts-nocheck
// Chapa plegada por operaciones (cara base + pestañas a 90°) y desarrollo plano (port de monxu/cad/sheetmetal.py).
export const EDGES = ["x0", "x1", "y0", "y1"];
export const bendAllowance = (t, r, K) => (Math.PI / 2) * (r + K * t);
export const bendDeduction = (t, r, K) => 2 * (r + t) - bendAllowance(t, r, K);

/** Unión exacta de rectángulos alineados con los ejes: contorno exterior (antihorario) y área. */
export function rectUnion(rects) {
  const xs = [...new Set(rects.flatMap((r) => [r[0], r[2]]))].sort((a, b) => a - b);
  const ys = [...new Set(rects.flatMap((r) => [r[1], r[3]]))].sort((a, b) => a - b);
  const nx = xs.length - 1, ny = ys.length - 1;
  const cov = new Uint8Array(nx * ny);
  let area = 0;
  for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) {
    const cx = (xs[i] + xs[i + 1]) / 2, cy = (ys[j] + ys[j + 1]) / 2;
    if (rects.some((r) => cx > r[0] && cx < r[2] && cy > r[1] && cy < r[3])) { cov[i * ny + j] = 1; area += (xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j]); }
  }
  const c = (i, j) => i >= 0 && j >= 0 && i < nx && j < ny && cov[i * ny + j] === 1;
  const edges = new Map();
  const put = (a, b) => edges.set(`${a[0]},${a[1]}`, b);
  for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) {
    if (!c(i, j)) continue;
    const x0 = xs[i], x1 = xs[i + 1], y0 = ys[j], y1 = ys[j + 1];
    if (!c(i, j - 1)) put([x0, y0], [x1, y0]);
    if (!c(i + 1, j)) put([x1, y0], [x1, y1]);
    if (!c(i, j + 1)) put([x1, y1], [x0, y1]);
    if (!c(i - 1, j)) put([x0, y1], [x0, y0]);
  }
  const startKey = edges.keys().next().value;
  const pts = [];
  let k = startKey, guard = 0;
  do {
    const [x, y] = k.split(",").map(Number);
    pts.push([x, y]);
    const nxt = edges.get(k);
    k = `${nxt[0]},${nxt[1]}`;
  } while (k !== startKey && ++guard < 100000);
  // elimina puntos colineales
  const out = [];
  for (let i = 0; i < pts.length; i++) {
    const a = pts[(i - 1 + pts.length) % pts.length], b = pts[i], d = pts[(i + 1) % pts.length];
    if ((a[0] === b[0] && b[0] === d[0]) || (a[1] === b[1] && b[1] === d[1])) continue;
    out.push(b);
  }
  if (edges.size !== pts.length) throw new Error("El desarrollo no es una única región conexa");
  return { outline: out, area };
}

export function makeSpec({ Lx, Ly, t, r, K, flanges = [], notch = [0, 0], holes = [] }) {
  const R = r + t, BA = bendAllowance(t, r, K), BD = bendDeduction(t, r, K);
  const fl = (e) => flanges.find((f) => f.edge === e);
  const base = [fl("x0") ? R : 0, fl("x1") ? Lx - R : Lx, fl("y0") ? R : 0, fl("y1") ? Ly - R : Ly];
  const [nx, ny] = notch;
  const extent = (e) => {
    if (e === "x0" || e === "x1") return [Math.max(ny, fl("y0") ? R : 0), Ly - Math.max(ny, fl("y1") ? R : 0)];
    return [Math.max(nx, fl("x0") ? R : 0), Lx - Math.max(nx, fl("x1") ? R : 0)];
  };
  /** Región plana de la base como rectángulos (base menos escotaduras de esquina). */
  const baseRects = () => {
    const [bx0, bx1, by0, by1] = base;
    if (!(nx > 0 && ny > 0)) return [[bx0, by0, bx1, by1]];
    const out = [[Math.max(bx0, nx), by0, Math.min(bx1, Lx - nx), by1],
      [bx0, Math.max(by0, ny), bx1, Math.min(by1, Ly - ny)]];
    return out.filter((q) => q[2] > q[0] && q[3] > q[1]);
  };
  const spec = {
    Lx, Ly, t, r, K, flanges, notch, holes, R, BA, BD, flatBoundsBase: base, flangeExtent: extent, baseRects,
    rectUnionOutline: () => rectUnion(baseRects()).outline,
    signature: JSON.stringify([Lx, Ly, t, r, K, notch, flanges.map((f) => [f.edge, f.height, f.direction, f.holes]), holes]),
    bendLengths: () => flanges.map((f) => { const [s0, s1] = extent(f.edge); return s1 - s0; }),
    flat() {
      const [bx0, bx1, by0, by1] = base;
      const rects = [...baseRects()], bends = [], fh = [];
      for (const f of flanges) {
        const [s0, s1] = extent(f.edge), F = f.height - R, dir = f.direction === "up" ? "ARRIBA" : "ABAJO";
        let b;
        if (f.edge === "x0") { rects.push([bx0 - BA - F, s0, bx0, s1]); const xb = bx0 - BA / 2; b = { p0: [xb, s0], p1: [xb, s1] };
          for (const [s, h, d] of f.holes) fh.push({ kind: "round", x: bx0 - BA - (h - R), y: s, d }); }
        else if (f.edge === "x1") { rects.push([bx1, s0, bx1 + BA + F, s1]); const xb = bx1 + BA / 2; b = { p0: [xb, s0], p1: [xb, s1] };
          for (const [s, h, d] of f.holes) fh.push({ kind: "round", x: bx1 + BA + (h - R), y: s, d }); }
        else if (f.edge === "y0") { rects.push([s0, by0 - BA - F, s1, by0]); const yb = by0 - BA / 2; b = { p0: [s0, yb], p1: [s1, yb] };
          for (const [s, h, d] of f.holes) fh.push({ kind: "round", x: s, y: by0 - BA - (h - R), d }); }
        else { rects.push([s0, by1, s1, by1 + BA + F]); const yb = by1 + BA / 2; b = { p0: [s0, yb], p1: [s1, yb] };
          for (const [s, h, d] of f.holes) fh.push({ kind: "round", x: s, y: by1 + BA + (h - R), d }); }
        bends.push({ ...b, edge: f.edge, direction: dir, angle: 90, radius: r, length: s1 - s0 });
      }
      for (const h of holes) fh.push(h[0] === "round" ? { kind: "round", x: h[1], y: h[2], d: h[3] } : { kind: "rect", x: h[1], y: h[2], w: h[3], h: h[4] });
      const u = rectUnion(rects);
      const xs = u.outline.map((p) => p[0]), ys = u.outline.map((p) => p[1]);
      const bounds = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
      const holesArea = fh.reduce((s, h) => s + (h.kind === "round" ? (Math.PI * h.d * h.d) / 4 : h.w * h.h), 0);
      let per = 0;
      for (let i = 0; i < u.outline.length; i++) { const a = u.outline[i], b2 = u.outline[(i + 1) % u.outline.length]; per += Math.hypot(b2[0] - a[0], b2[1] - a[1]); }
      const cut = per + fh.reduce((s, h) => s + (h.kind === "round" ? Math.PI * h.d : 2 * (h.w + h.h)), 0);
      return { outline: u.outline, holes: fh, bends, t, bounds, width: bounds[2] - bounds[0], height: bounds[3] - bounds[1],
        grossArea: u.area, netArea: u.area - holesArea, cutLength: cut,
        normalized() {
          const [x0, y0] = bounds;
          return { ...this, outline: this.outline.map(([x, y]) => [x - x0, y - y0]),
            holes: this.holes.map((h) => ({ ...h, x: h.x - x0, y: h.y - y0 })),
            bends: this.bends.map((b3) => ({ ...b3, p0: [b3.p0[0] - x0, b3.p0[1] - y0], p1: [b3.p1[0] - x0, b3.p1[1] - y0] })),
            bounds: [0, 0, this.width, this.height] };
        } };
    },
  };
  return spec;
}
