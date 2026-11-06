import { allTemplates } from "../../frontend/src/engine/families";
import { regenerate } from "../../frontend/src/engine/pipeline";
import { checkInterferences } from "../../frontend/src/engine/interference";
import { translation, mmul } from "../../frontend/src/engine/model";
for (const t of allTemplates()) {
  const { model, summary } = regenerate(t.family, t.values);
  const i = summary.interferences;
  console.log(t.id.padEnd(20), "parejas", i.pairs_checked, "interferencias", i.interferences.length, JSON.stringify(i.interferences.slice(0, 3)), summary.timings.interferencias, "s");
}
// caso con interferencia provocada: desplazar una pata 10 mm hacia dentro
const { model } = regenerate("mesa_industrial", { LONGITUD: 1800, CARGA_TOTAL: 300 });
const leg = model.instance("EST.PATA.DI"); leg.T = mmul(translation(15, 0, 0), leg.T); leg._bbox = null;
console.log("PROVOCADA:", JSON.stringify(checkInterferences(model).interferences.slice(0, 4)));
