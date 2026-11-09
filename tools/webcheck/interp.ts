// Intérprete y asistente del navegador sobre frases y conversaciones de prueba (stdin: JSON).
//  · lista de textos → interpretación de cada frase
//  · {"conversations": [{family, start: {values, sources}, turns: [{message, answers}]}]} → respuesta del asistente por turno,
//    aplicando en cada turno sus datos al proyecto simulado (como hace la API).
import { handle, newState, parse } from "../../frontend/src/engine/assistant";
import * as fs from "node:fs";
const inp = JSON.parse(fs.readFileSync(0, "utf8"));
function runConv(conv) {
  let st = newState(conv.family);
  let cur = { values: { ...(conv.start?.values ?? {}) }, sources: { ...(conv.start?.sources ?? {}) } };
  const out = [];
  for (const t of conv.turns) {
    const r = handle(st, t.message ?? "", t.answers ?? null, null, cur);
    st = r.state;
    out.push({ family: r.family, reply: r.reply, to_apply: r.to_apply, ready: r.ready_to_generate,
      questions: r.questions.map((q) => [q.param, q.label]), assumptions: r.assumptions.map((a) => [a.param, a.text]) });
    cur = { values: { ...cur.values, ...r.to_apply }, sources: { ...cur.sources, ...Object.fromEntries(Object.keys(r.to_apply).map((k) => [k, r.sources[k]])) } };
  }
  return out;
}
process.stdout.write(JSON.stringify(Array.isArray(inp)
  ? inp.map((t) => { const it = parse(t); return { family: it.family, values: it.values, unsupported: it.unsupported, notes: it.notes }; })
  : inp.conversations.map(runConv)));
