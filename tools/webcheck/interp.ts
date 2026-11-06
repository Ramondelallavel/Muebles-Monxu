// Intérprete del navegador sobre frases de prueba (stdin: lista JSON de textos).
import { parse } from "../../frontend/src/engine/assistant";
import * as fs from "node:fs";
const texts = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(texts.map((t) => { const it = parse(t); return { family: it.family, values: it.values, unsupported: it.unsupported, notes: it.notes }; })));
