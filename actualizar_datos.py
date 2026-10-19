"""
Genera stats.json (rachas) y partidos.json (proximos partidos, cruces local/visitante
y verificacion de partidos recientes) con football-data.org (plan gratuito).

Uso (PowerShell):
  $env:FOOTBALL_DATA_TOKEN="TU_TOKEN"
  python actualizar_datos.py
"""
import csv, difflib, io, json, math, os, re, sys, time, unicodedata, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone

COMPETICIONES = ["PL", "PD", "CL"]     # agrega: "SA", "BL1", "FL1", "BSA"...
TEMPORADAS = [2024, 2025, 2026]        # año en que EMPIEZA la temporada
DIAS_PROXIMOS = 7
DIAS_ATRAS = 7
MIN_MUESTRA = 8                        # partidos minimos para mostrar un cruce
NOMBRES = {"PL": "Premier League", "PD": "La Liga", "CL": "Champions League", "SA": "Serie A",
           "BL1": "Bundesliga", "FL1": "Ligue 1", "BSA": "Brasileirão", "DED": "Eredivisie",
           "PPL": "Primeira Liga", "ELC": "Championship"}

# Remates y corners: CSV gratuitos de football-data.co.uk (no incluye Champions League)
CSV_LIGAS = {"PL": "E0", "PD": "SP1", "SA": "I1", "BL1": "D1", "FL1": "F1"}
HISTORIAL_TEMPORADAS = 10   # temporadas de CSV para el cara a cara (H2H)
ALIAS = {"Man City": "Manchester City", "Man United": "Manchester United", "Nott'm Forest": "Nottingham Forest",
         "Spurs": "Tottenham", "Wolves": "Wolverhampton", "Ath Madrid": "Atletico Madrid",
         "Ath Bilbao": "Athletic Club", "Sociedad": "Real Sociedad", "Vallecano": "Rayo Vallecano",
         "Espanol": "Espanyol", "Betis": "Real Betis", "Inter": "Internazionale", "Paris SG": "Paris Saint Germain",
         "St Etienne": "Saint Etienne", "M'gladbach": "Monchengladbach", "Ein Frankfurt": "Eintracht Frankfurt",
         "FC Koln": "Koln", "Bayern Munich": "Bayern Munchen", "Lyon": "Lyonnais", "Brest": "Brestois",
         "Rennes": "Rennais"}
STOP = {"fc", "afc", "cf", "ac", "as", "sc", "ssc", "us", "ud", "cd", "rcd", "rc", "sd", "ca", "club", "de",
        "the", "calcio", "balompie", "futbol", "fsv", "vfb", "vfl", "tsg", "1", "04", "05"}

BASE = "https://api.football-data.org/v4"
TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN")


def llamar(ruta):
    req = urllib.request.Request(BASE + ruta, headers={"X-Auth-Token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            datos = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  ! Error {e.code} en {ruta}")
        datos = None
    time.sleep(6.5)  # plan gratis: 10 llamadas por minuto
    return datos


def fecha(m):
    return datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))


def inicio_temporada(ahora):
    """1 de julio de la temporada en curso (UTC)."""
    y = ahora.year if ahora.month >= 7 else ahora.year - 1
    return datetime(y, 7, 1, tzinfo=timezone.utc)


def fecha_csv(s):
    for f in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime((s or "").strip(), f).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def resumen_goles(est):
    out = {}
    for (tid, comp), e in est.items():
        d = {}
        for k, v in e.items():
            n = len(v["o"])
            if n:
                d[k] = {"pj": n, "o25": tasa(v["o"])[0], "btts": tasa(v["b"])[0],
                        "gf": round(sum(v["gf"]) / n, 1), "gc": round(sum(v["gc"]) / n, 1)}
        out[(comp, tid)] = d
    return out


def poisson(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def modelo(est, lg, comp, hid, aid, k=10):
    """Probabilidades estimadas con un modelo de Poisson sobre goles de la liga.
    Cada tasa se suaviza hacia el promedio de la liga (k partidos de peso)."""
    h, a, l = est.get((hid, comp)), est.get((aid, comp)), lg.get(comp)
    if not h or not a or not l or l[2] < 30:
        return None
    lh, la = l[0] / l[2], l[1] / l[2]
    sh = lambda lista, base: (sum(lista) + k * base) / (len(lista) + k)
    lam_h = sh(h["home"]["gf"], lh) * sh(a["away"]["gc"], lh) / lh
    lam_a = sh(a["away"]["gf"], la) * sh(h["home"]["gc"], la) / la
    ph = [poisson(i, lam_h) for i in range(11)]
    pa = [poisson(i, lam_a) for i in range(11)]
    suma = lambda f: sum(ph[i] * pa[j] for i in range(11) for j in range(11) if f(i, j))
    pct = lambda x: round(100 * x)
    p1, p2 = pct(suma(lambda i, j: i > j)), pct(suma(lambda i, j: i < j))
    return {"lam_l": round(lam_h, 2), "lam_v": round(lam_a, 2), "p1": p1, "px": 100 - p1 - p2, "p2": p2,
            "o15": pct(suma(lambda i, j: i + j >= 2)), "o25": pct(suma(lambda i, j: i + j >= 3)),
            "o35": pct(suma(lambda i, j: i + j >= 4)),
            "btts": pct((1 - math.exp(-lam_h)) * (1 - math.exp(-lam_a))),
            "pc0_l": pct(math.exp(-lam_a)), "pc0_v": pct(math.exp(-lam_h))}


def bloque_h2h(ms, hid):
    """ms: [(fecha, id_local_de_ese_partido, goles_local, goles_visita)]; hid = local del partido por jugar."""
    b = {k: 0 for k in ("vl", "e", "vv", "gl", "gv", "o15", "o25", "o35", "btts", "pc0_l", "pc0_v")}
    b["n"] = len(ms)
    for _, ht, hg, ag in ms:
        gl, gv = (hg, ag) if ht == hid else (ag, hg)
        b["vl"] += gl > gv; b["e"] += gl == gv; b["vv"] += gl < gv
        b["gl"] += gl; b["gv"] += gv
        t = gl + gv
        b["o15"] += t >= 2; b["o25"] += t >= 3; b["o35"] += t >= 4
        b["btts"] += gl > 0 and gv > 0
        b["pc0_l"] += gv == 0; b["pc0_v"] += gl == 0
    return b


def resumen_h2h(lista, hid):
    if not lista:
        return None
    return {"todos": bloque_h2h(lista[:20], hid), "ult5": bloque_h2h(lista[:5], hid)}


def tasa(lista):
    n = len(lista)
    return (round(100 * sum(lista) / n), n) if n else (0, 0)


def racha(lista):
    n = 0
    for ok in reversed(lista):
        if not ok:
            break
        n += 1
    return n


def nuevo():
    return {k: {"o": [], "b": [], "gf": [], "gc": []} for k in ("all", "home", "away")}


def cruces(est, comp, hid, aid):
    h, a = est.get((hid, comp)), est.get((aid, comp))
    if not h or not a:
        return []
    out = []
    for clave, titulo, key, inv in (("o25", "Más de 2.5 goles", "o", False),
                                    ("btts", "Ambos anotan", "b", False),
                                    ("u25", "Menos de 2.5 goles", "o", True)):
        ph, nh = tasa(h["home"][key])
        pa, na = tasa(a["away"][key])
        if inv:
            ph, pa = 100 - ph, 100 - pa
        if min(nh, na) < MIN_MUESTRA:
            continue
        m = min(ph, pa)
        nivel = "fuerte" if m >= 70 else "moderado" if m >= 60 else None
        if nivel:
            out.append({"mercado": clave, "titulo": titulo, "nivel": nivel,
                        "local_pct": ph, "local_n": nh, "visita_pct": pa, "visita_n": na})
    return out


def resumen(est, comp, hid, aid, extra=None):
    """Base fija para TODOS los partidos: local en casa vs visitante fuera."""
    h, a = est.get((hid, comp)), est.get((aid, comp))
    if not h or not a:
        return None
    ex = extra or {}

    def lado(e, x):
        n = len(e["o"])
        prom = lambda l: round(sum(l) / n, 1) if n else 0
        d = {"n": n, "o25": tasa(e["o"])[0], "btts": tasa(e["b"])[0],
             "gf": prom(e["gf"]), "gc": prom(e["gc"])}
        if x:
            d.update(x)
        return d
    return {"local": lado(h["home"], ex.get((comp, hid), {}).get("home")),
            "visita": lado(a["away"], ex.get((comp, aid), {}).get("away"))}


def procesar(partidos, ahora, extra=None, reuniones=None):
    """partidos: lista de (codigo_liga, partido). Devuelve (stats, partidos_json)."""
    est, est_act, forma, lg = {}, {}, {}, {}
    inicio = inicio_temporada(ahora)
    proximos, recientes, pendientes = [], [], []
    for comp, m in sorted(partidos, key=lambda x: fecha(x[1])):
        h, a = m["homeTeam"], m["awayTeam"]
        if not h.get("id") or not a.get("id"):
            continue
        nom = lambda t: t.get("shortName") or t["name"]
        ficha = lambda: {"id": m["id"], "liga": comp, "fecha": m["utcDate"],
                         "local": nom(h), "visitante": nom(a),
                         "forma_local": forma.get(h["id"], [])[-5:],
                         "forma_visita": forma.get(a["id"], [])[-5:],
                         "cruces": cruces(est, comp, h["id"], a["id"]),
                         "resumen": resumen(est, comp, h["id"], a["id"], extra)}
        if m["status"] in ("SCHEDULED", "TIMED"):
            if ahora <= fecha(m) <= ahora + timedelta(days=DIAS_PROXIMOS):
                pendientes.append((comp, m))
            continue
        if m["status"] != "FINISHED":
            continue
        gl, gv = m["score"]["fullTime"]["home"], m["score"]["fullTime"]["away"]
        if gl is None or gv is None:
            continue
        total, ambos = gl + gv, gl > 0 and gv > 0
        acc = lg.setdefault(comp, [0, 0, 0])
        acc[0] += gl; acc[1] += gv; acc[2] += 1
        if ahora - timedelta(days=DIAS_ATRAS) <= fecha(m) <= ahora:
            f = ficha()
            cumple = {"o25": total > 2.5, "btts": ambos, "u25": total <= 2.5}
            f["marcador"] = f"{gl}-{gv}"
            f["cruces"] = [dict(c, cumplido=cumple[c["mercado"]]) for c in f["cruces"]]
            recientes.append(f)
        for tid, lado, gf, gc in ((h["id"], "home", gl, gv), (a["id"], "away", gv, gl)):
            for dic in ((est, est_act) if fecha(m) >= inicio else (est,)):
                e = dic.setdefault((tid, comp), nuevo())
                for k in ("all", lado):
                    e[k]["o"].append(total > 2.5)
                    e[k]["b"].append(ambos)
                    e[k]["gf"].append(gf)
                    e[k]["gc"].append(gc)
            forma.setdefault(tid, []).append("G" if gf > gc else "E" if gf == gc else "P")
    for comp, m in pendientes:   # con el estado final
        h, a = m["homeTeam"], m["awayTeam"]
        nom = lambda t: t.get("shortName") or t["name"]
        proximos.append({"id": m["id"], "liga": comp, "fecha": m["utcDate"],
                         "local": nom(h), "visitante": nom(a),
                         "forma_local": forma.get(h["id"], [])[-5:],
                         "forma_visita": forma.get(a["id"], [])[-5:],
                         "cruces": cruces(est, comp, h["id"], a["id"]),
                         "resumen": resumen(est, comp, h["id"], a["id"], extra),
                         "modelo": modelo(est, lg, comp, h["id"], a["id"]),
                         "h2h": resumen_h2h((reuniones or {}).get((comp, frozenset((h["id"], a["id"])))), h["id"])})
    nombres = {}
    for comp, m in partidos:
        for t in (m["homeTeam"], m["awayTeam"]):
            if t.get("id"):
                nombres[(t["id"], comp)] = t["name"]
    stats = {}
    for (tid, comp), e in est.items():
        o, b = e["all"]["o"], e["all"]["b"]
        stats.setdefault(comp, []).append({
            "equipo": nombres.get((tid, comp), str(tid)), "partidos": len(o),
            "pct_over25": tasa(o)[0], "pct_btts": tasa(b)[0],
            "racha_over25": racha(o), "racha_btts": racha(b)})
    for comp in stats:
        stats[comp].sort(key=lambda x: x["racha_over25"], reverse=True)
    proximos.sort(key=lambda x: x["fecha"])
    recientes.sort(key=lambda x: x["fecha"], reverse=True)
    pj = {"generado": ahora.isoformat(timespec="minutes"),
          "ligas": {c: NOMBRES.get(c, c) for c in COMPETICIONES},
          "proximos": proximos, "recientes": recientes}
    goles = {"hist": resumen_goles(est), "act": resumen_goles(est_act)}
    return stats, pj, goles


def toks(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return frozenset(w for w in re.sub(r"[^a-z0-9 ]", " ", s).split() if w not in STOP)


def emparejar(nombre, cands):
    """cands: {id: [nombres]}. Devuelve el id del equipo que mejor coincide, o None."""
    t = toks(ALIAS.get(nombre, nombre))
    mejor, elegido = 0, None
    for tid, nombres in cands.items():
        for n in nombres:
            u = toks(n)
            if not t or not u:
                continue
            if t == u:
                sc = 1.0
            elif t <= u or u <= t:
                sc = 0.9
            else:
                sc = difflib.SequenceMatcher(None, " ".join(sorted(t)), " ".join(sorted(u))).ratio()
            if sc > mejor:
                mejor, elegido = sc, tid
    return elegido if mejor >= 0.75 else None


def descargar_filas(code, temporadas):
    filas = []
    for t in temporadas:
        url = f"https://www.football-data.co.uk/mmz4281/{t}/{code}.csv"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = r.read().decode("utf-8-sig", "replace")
            filas += list(csv.DictReader(io.StringIO(txt)))
        except Exception as e:
            print(f"  ! No se pudo bajar {url}: {e}")
    return filas


def agregar_extra(filas, registro, inicio=None):
    """filas: {liga: [filas CSV]}; registro: {(liga, id): [nombres]}; inicio: solo partidos desde esa fecha.
    Devuelve ({(liga, id): {"all"|"home"|"away": {...}}}, equipos_sin_emparejar)."""
    METRICAS = {"rem": ("HS", "AS"), "pta": ("HST", "AST"), "esq": ("HC", "AC"),
                "fal": ("HF", "AF"), "tar": ("HY", "AY")}
    extra, sin = {}, set()
    for comp, rows in filas.items():
        cands = {tid: n for (c, tid), n in registro.items() if c == comp}
        acum = {}
        for r in rows:
            if inicio:
                f = fecha_csv(r.get("Date"))
                if f is None or f < inicio:
                    continue
            for lado, col in (("home", "HomeTeam"), ("away", "AwayTeam")):
                for sc in (lado, "all"):
                    a = acum.setdefault((r.get(col), sc), {k: ([], []) for k in METRICAS})
                    for k, (ch, ca) in METRICAS.items():
                        try:
                            vh, va = int(r[ch]), int(r[ca])
                        except (KeyError, ValueError, TypeError):
                            continue
                        pf, pc = (vh, va) if lado == "home" else (va, vh)
                        a[k][0].append(pf)
                        a[k][1].append(pc)
        cache = {}
        for (eq, lado), a in acum.items():
            if not eq:
                continue
            if eq not in cache:
                cache[eq] = emparejar(eq, cands)
                if cache[eq] is None:
                    sin.add((comp, eq))
            tid = cache[eq]
            if tid is None:
                continue
            d = {}
            for k, (f, c) in a.items():
                if f:
                    d[k] = round(sum(f) / len(f), 1)
                    d[k + "_c"] = round(sum(c) / len(c), 1)
            if "esq" in d:
                f, c = a["esq"]
                d["esq_t"] = round((sum(f) + sum(c)) / len(f), 1)
            if a["rem"][0]:
                d["n_x"] = len(a["rem"][0])
            if d:
                extra.setdefault((comp, tid), {})[lado] = d
    return extra, sin


def construir_reuniones(filas, registro):
    """{(liga, frozenset({id1, id2})): [(fecha, id_local, goles_local, goles_visita)]} mas reciente primero."""
    out = {}
    for comp, rows in filas.items():
        cands = {tid: n for (c, tid), n in registro.items() if c == comp}
        cache = {}
        eq = lambda nom: cache.setdefault(nom, emparejar(nom, cands))
        for r in rows:
            f = fecha_csv(r.get("Date"))
            try:
                hg, ag = int(r["FTHG"]), int(r["FTAG"])
            except (KeyError, ValueError, TypeError):
                continue
            if f is None or not r.get("HomeTeam") or not r.get("AwayTeam"):
                continue
            th, ta = eq(r["HomeTeam"]), eq(r["AwayTeam"])
            if th is None or ta is None or th == ta:
                continue
            out.setdefault((comp, frozenset((th, ta))), []).append((f, th, hg, ag))
    for v in out.values():
        v.sort(key=lambda x: x[0], reverse=True)
    return out


def construir_tablas(goles, extras, todos, ahora):
    """Tablas por liga para la pagina Ligas: periodo x ambito (all/home/away)."""
    cortos = {}
    for comp, m in todos:
        for t in (m["homeTeam"], m["awayTeam"]):
            if t.get("id"):
                cortos.setdefault((comp, t["id"]), t.get("shortName") or t["name"])
    tablas = {}
    for per in ("hist", "act"):
        for (comp, tid), sc in goles[per].items():
            fila = tablas.setdefault(comp, {}).setdefault(tid, {"equipo": cortos.get((comp, tid), str(tid))})
            ex = extras[per].get((comp, tid), {})
            fila[per] = {k: dict(v, **ex.get(k, {})) for k, v in sc.items()}
    return {"generado": ahora.isoformat(timespec="minutes"),
            "ligas": {c: NOMBRES.get(c, c) for c in COMPETICIONES},
            "tablas": {c: sorted(d.values(), key=lambda r: r["equipo"]) for c, d in tablas.items()}}


def main():
    if not TOKEN:
        sys.exit("Falta el token. Define la variable FOOTBALL_DATA_TOKEN.")
    todos = []
    for code in COMPETICIONES:
        for temp in TEMPORADAS:
            print(f"Descargando {code} {temp}...")
            d = llamar(f"/competitions/{code}/matches?season={temp}")
            if d:
                todos += [(code, m) for m in d["matches"]]
    registro = {}
    for comp, m in todos:
        for t in (m["homeTeam"], m["awayTeam"]):
            if t.get("id"):
                registro.setdefault((comp, t["id"]), set()).update({t["name"], t.get("shortName") or t["name"]})
    registro = {k: sorted(v) for k, v in registro.items()}
    ahora = datetime.now(timezone.utc)
    y0 = inicio_temporada(ahora).year
    temps = [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(y0 - HISTORIAL_TEMPORADAS + 1, y0 + 1)]
    filas = {}
    for code in COMPETICIONES:
        if code in CSV_LIGAS:
            print(f"Descargando remates, corners e historial {code}...")
            filas[code] = descargar_filas(CSV_LIGAS[code], temps)
    extra, _ = agregar_extra(filas, registro, datetime(y0 - 2, 7, 1, tzinfo=timezone.utc))
    extra_act, sin = agregar_extra(filas, registro, inicio_temporada(ahora))
    if sin:
        print("Equipos sin emparejar (sin remates/corners):", sorted(sin))
    reuniones = construir_reuniones(filas, registro)
    stats, pj, goles = procesar(todos, ahora, extra, reuniones)
    tablas = construir_tablas(goles, {"hist": extra, "act": extra_act}, todos, ahora)
    for nombre, obj in (("stats.json", stats), ("partidos.json", pj), ("tablas.json", tablas)):
        with open(nombre, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    print(f"Listo: stats.json, partidos.json y tablas.json ({len(pj['proximos'])} proximos, "
          f"{len(pj['recientes'])} recientes)")


if __name__ == "__main__":
    main()
