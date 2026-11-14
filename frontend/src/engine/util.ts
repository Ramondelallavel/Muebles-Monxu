// @ts-nocheck
// Utilidades numéricas con la misma semántica que Python (round con redondeo a par, formato :g).

/** round(x, n) de Python: redondeo correcto del valor binario exacto, empates a par. */
export function pyRound(x: number, n = 0): number {
  if (!Number.isFinite(x)) return x;
  const sgn = x < 0 ? -1 : 1;
  const ax = Math.abs(x);
  const m = Math.pow(10, n);
  const y = ax * m;
  let r = Math.round(y);
  const frac = y - Math.floor(y);
  if (Math.abs(frac - 0.5) < 1e-9) {
    // posible empate: decidir con la expansión decimal exacta del valor binario
    const s = ax.toFixed(Math.min(100, n + 25));
    const tail = s.slice(s.indexOf(".") + 1 + n);
    if (/^50*$/.test(tail)) r = Math.floor(y) % 2 === 0 ? Math.floor(y) : Math.floor(y) + 1;
    else r = tail[0] >= "5" ? Math.floor(y) + 1 : Math.floor(y);
  }
  return (sgn * r) / m;
}

/** Formato :g de Python (6 cifras significativas, sin ceros finales). */
export function g(x: number): string {
  if (x === null || x === undefined) return String(x);
  if (Number.isInteger(x) && Math.abs(x) < 1e6) return String(x);
  return String(Number(x.toPrecision(6)));
}

/** Formato :.Nf de Python. */
export const f = (x: number, n = 0) => {
  const r = pyRound(x, n);
  return n === 0 ? String(Math.round(r) === 0 ? 0 : Math.round(r)) : r.toFixed(n);
};

export const range = (n: number) => Array.from({ length: n }, (_, i) => i);
export const sum = (a: number[]) => a.reduce((s, v) => s + v, 0);
export const pad2 = (n: number) => String(n).padStart(2, "0");
