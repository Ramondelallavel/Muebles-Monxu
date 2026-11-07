"""Casos aleatorios realistas (sólo los datos que daría un usuario) para la validación cruzada y los barridos."""
import random

MATS = [("S235JRH", "S235JR", "RAL7035_POLVO"), ("1.4301", "1.4301", "INOX_SATINADO"),
        ("S235JRH", "DC01", "RAL5010_POLVO"), ("EN AW-6082 T6", "EN AW-5754 H22", "ANODIZADO_NATURAL")]


def random_case(rng: random.Random) -> tuple[str, dict]:
    """Familia y valores de un caso aleatorio realista; el resto de parámetros queda por defecto o 'auto'."""
    m = rng.choice(MATS)
    u = rng.random()
    if u >= 0.9:
        fid = "carro_taller"
        H = rng.choice(range(800, 1001, 50))
        v = {"LONGITUD": rng.choice(range(700, 1601, 100)), "ANCHURA": rng.choice(range(450, 801, 50)), "ALTURA": H,
             "ALTURA_ASA": H + rng.choice([100, 150, 200]), "CARGA_TOTAL": rng.choice([None, 50, 100, 200]),
             "NUMERO_BALDAS": rng.choice([0, 1]), "CARGA_BALDA": rng.choice([None, 50, 100]),
             "CARGA_HORIZONTAL": rng.choice([50, 100, 150]),
             "ASA_EMPUJE": rng.choice(["un_extremo", "dos_extremos", "ninguna"]), "PETO_TRASERO": rng.choice([0, 0, 50, 100])}
    elif u >= 0.82:
        fid = "carro_estanteria"
        H = rng.choice(range(1000, 1801, 100))
        n = rng.randint(2, 5)
        v = {"ANCHURA": rng.choice(range(600, 1601, 100)), "PROFUNDIDAD": rng.choice(range(400, 801, 50)), "ALTURA": H,
             "NUMERO_NIVELES": n, "ALTURA_PRIMER_NIVEL": rng.choice([250, 300, 350]),
             "CARGA_POR_NIVEL": rng.choice([None, 20, 40, 80]), "ASA_EMPUJE": rng.choice(["un_extremo", "dos_extremos", "ninguna"]),
             "ALTURA_ASA": rng.choice([900, 1000, 1100]), "CARGA_HORIZONTAL": rng.choice([40, 60, 100])}
    elif u >= 0.7:
        fid = "puesto_trabajo"
        H = rng.choice(range(800, 1001, 50))
        top = rng.choice(range(max(1500, H + 600), 2201, 100))     # deja sitio al estante sobre la encimera
        v = {"LONGITUD": rng.choice(range(1000, 2401, 100)), "ANCHURA": rng.choice(range(600, 901, 50)), "ALTURA": H,
             "ALTURA_TOTAL": top, "ESTANTE_SUPERIOR": rng.choice([0, 1]), "ALTURA_ESTANTE": rng.choice(range(H + 400, top - 149, 50)),
             "PROFUNDIDAD_ESTANTE": rng.choice(range(200, 401, 50)), "PANEL_HERRAMIENTAS": rng.choice([0, 1]),
             "CARGA_TOTAL": rng.choice([None, 100, 200, 400]), "CARGA_ESTANTE": rng.choice([None, 20, 50, 80]),
             "NUMERO_BALDAS": rng.choice([0, 1]), "CARGA_BALDA": rng.choice([None, 50, 100]),
             "CARGA_HORIZONTAL": rng.choice([100, 200, 300]), "ANCLAJE": rng.choice(["ninguno", "al_suelo"]),
             "PETO_TRASERO": rng.choice([0, 0, 60]), "REPOSAPIES": rng.choice([0, 1])}
    elif u < 0.08:
        fid = "mesa_soldadura"
        v = {"LONGITUD": rng.choice(range(800, 3001, 100)), "ANCHURA": rng.choice(range(600, 1501, 100)),
             "ALTURA": rng.choice(range(750, 951, 50)), "CARGA_TOTAL": rng.choice([None, 300, 600, 1200]),
             "CARGA_PUNTUAL": rng.choice([None, 100, 300]), "SISTEMA_TALADROS": rng.choice(["D16_P50", "D28_P100", "ninguno"]),
             "ESPESOR_PLACA": rng.choice(["auto", "auto", 12.0, 15.0, 20.0]), "VUELO": rng.choice([40, 60, 100]),
             "NUMERO_BALDAS": rng.choice([0, 1]), "CARGA_BALDA": rng.choice([None, 100]),
             "CARGA_HORIZONTAL": rng.choice([200, 300, 500]), "ANCLAJE": rng.choice(["ninguno", "al_suelo"])}
    elif u < 0.4:
        fid = "mesa_industrial"
        v = {"LONGITUD": rng.choice(range(800, 3001, 100)), "ANCHURA": rng.choice(range(500, 1201, 50)),
             "ALTURA": rng.choice(range(700, 1101, 50)), "CARGA_TOTAL": rng.choice([None, 100, 200, 300, 400, 600, 800]),
             "NUMERO_BALDAS": rng.choice([0, 1]), "CARGA_BALDA": rng.choice([None, 0, 50, 100, 200]),
             "CARGA_PUNTUAL": rng.choice([None, None, 50, 100]),
             "USO": rng.choice(["montaje", "trabajo_pesado", "inspeccion"]), "CARGA_HORIZONTAL": rng.choice([100, 200, 300]),
             "ANCLAJE": rng.choice(["ninguno", "al_suelo"]), "PETO_TRASERO": rng.choice([0, 0, 0, 40, 100]),
             "REPOSAPIES": rng.choice([0, 0, 1]), "ALTURA_REPOSAPIES": rng.choice([200, 250, 300])}
    elif u >= 0.52 and u < 0.58:
        fid = "tarima"
        L, W = rng.choice(range(600, 3001, 100)), rng.choice(range(500, 1801, 100))
        q = rng.choice([None, 1.5, 2.0, 3.0, 5.0])          # kN/m²
        v = {"LONGITUD": L, "ANCHURA": W, "ALTURA": rng.choice(range(150, 501, 50)),
             "CARGA_TOTAL": None if q is None else round(q * L * W * 1e-6 / 9.81e-3),
             "CARGA_PUNTUAL": rng.choice([153, 153, 250, 100]), "ANCLAJE": rng.choice(["ninguno", "al_suelo"]),
             "CARGA_HORIZONTAL": rng.choice([100, 150, 300])}
    elif u >= 0.58:
        fid = "estanteria_bateria"
        v = {"NUMERO_MODULOS": rng.randint(2, 5), "ANCHURA": rng.choice(range(600, 1601, 100)),
             "PROFUNDIDAD": rng.choice(range(300, 901, 50)), "ALTURA": rng.choice(range(1200, 2801, 100)),
             "NUMERO_NIVELES": rng.randint(2, 6), "CARGA_POR_NIVEL": rng.choice([None, 50, 100, 150, 250]),
             "ANCLAJE": rng.choice(["al_suelo", "ninguno"]), "CARGA_HORIZONTAL": rng.choice([100, 200, 300]),
             "PERFIL_TRAVESANO": rng.choice(["auto", "auto", "RHS 50x30x2"])}
    else:
        fid = "estanteria"
        v = {"ANCHURA": rng.choice(range(800, 3001, 100)), "PROFUNDIDAD": rng.choice(range(300, 1001, 50)),
             "ALTURA": rng.choice(range(1200, 3001, 100)), "NUMERO_NIVELES": rng.randint(2, 7),
             "CARGA_POR_NIVEL": rng.choice([None, 50, 100, 150, 250, 400]), "ANCLAJE": rng.choice(["al_suelo", "ninguno"])}
    if fid in ("mesa_soldadura", "tarima") and m[0] != "S235JRH":
        m = MATS[0]                       # placa de acero soldada: estructura de acero al carbono
    v.update({"MATERIAL_ESTRUCTURAL": m[0], "MATERIAL_CHAPA": m[1], "ACABADO": m[2]})
    if fid == "tarima":
        v.pop("MATERIAL_CHAPA")           # sin chapa plegada
    return fid, v


def random_cases(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for k in range(n):
        fid, v = random_case(rng)
        out.append({"id": f"R{k:03d}", "family": fid, "values": v})
    return out
