// API local del navegador (almacenamiento en memoria): borrado de proyectos y códigos que no se reutilizan.
import { localApi } from "../../frontend/src/local/localApi";
const out: Record<string, unknown> = {};
const mk = async (name: string) => (await localApi.createProject({ name, family: "mesa_industrial" })).code;
const a = await mk("A"), b = await mk("B"), c = await mk("C");
out.created = [a, b, c];
out.deleted = await localApi.deleteProject(b);
out.after = (await localApi.projects()).map((p) => p.code);
out.next = await mk("D");
await localApi.deleteProject(out.next as string);
out.next2 = await mk("E");
try { await localApi.project(b); out.get_deleted = "encontrado"; } catch (e) { out.get_deleted = String((e as Error).message); }
try { await localApi.deleteProject(b); out.delete_again = "borrado"; } catch (e) { out.delete_again = String((e as Error).message); }
console.log(JSON.stringify(out));
