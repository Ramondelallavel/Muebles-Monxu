// Compone la página del artefacto a partir del build de vite (modo artifact): CSS y JS incrustados.
import fs from "node:fs";
import path from "node:path";
const dist = process.argv[2], out = process.argv[3];
const js = fs.readFileSync(path.join(dist, "app.js"), "utf8").replace(/<\/script/gi, "<\\/script");
const css = fs.readFileSync(path.join(dist, "app.css"), "utf8").replace(/<\/style/gi, "<\\/style");
const page = `<title>Monxu</title>
<meta name="claude:viewport-fit-sides" content="cover">
<meta name="description" content="Configurador de ingeniería paramétrica de mobiliario industrial: diseño, cálculo EN 1993, fabricación y expediente.">
<style>${css}</style>
<div id="root"><p style="padding:24px;font:14px system-ui,sans-serif">Cargando el motor de ingeniería…</p></div>
<script type="module">${js}</script>
`;
fs.writeFileSync(out, page);
console.log(out, (page.length / 1024).toFixed(0) + " kB");
