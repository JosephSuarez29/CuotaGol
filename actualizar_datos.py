"""
Genera stats.json (rachas) y partidos.json (proximos partidos, cruces local/visitante
y verificacion de partidos recientes) con football-data.org (plan gratuito).

Uso (PowerShell):
  $env:FOOTBALL_DATA_TOKEN="TU_TOKEN"
  python actualizar_datos.py
"""
import csv, difflib, io, json, os, re, sys, time, unicodedata, urllib.error, urllib.request
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
CSV_TEMPORADAS = ["2425", "2526", "2627"]
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


def procesar(partidos, ahora, extra=None):
    """partidos: lista de (codigo_liga, partido). Devuelve (stats, partidos_json)."""
    est, forma = {}, {}
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
        if ahora - timedelta(days=DIAS_ATRAS) <= fecha(m) <= ahora:
            f = ficha()
            cumple = {"o25": total > 2.5, "btts": ambos, "u25": total <= 2.5}
            f["marcador"] = f"{gl}-{gv}"
            f["cruces"] = [dict(c, cumplido=cumple[c["mercado"]]) for c in f["cruces"]]
            recientes.append(f)
        for tid, lado, gf, gc in ((h["id"], "home", gl, gv), (a["id"], "away", gv, gl)):
            e = est.setdefault((tid, comp), nuevo())
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
                         "resumen": resumen(est, comp, h["id"], a["id"], extra)})
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
    return stats, pj


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


def descargar_filas(code):
    filas = []
    for t in CSV_TEMPORADAS:
        url = f"https://www.football-data.co.uk/mmz4281/{t}/{code}.csv"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = r.read().decode("utf-8-sig", "replace")
            filas += list(csv.DictReader(io.StringIO(txt)))
        except Exception as e:
            print(f"  ! No se pudo bajar {url}: {e}")
    return filas


def agregar_extra(filas, registro):
    """filas: {liga: [filas CSV]}; registro: {(liga, id): [nombres]}.
    Devuelve ({(liga, id): {"home": {...}, "away": {...}}}, equipos_sin_emparejar)."""
    extra, sin = {}, set()
    for comp, rows in filas.items():
        cands = {tid: n for (c, tid), n in registro.items() if c == comp}
        acum = {}
        for r in rows:
            try:
                v = {k: int(r[k]) for k in ("HS", "AS", "HC", "AC")}
            except (KeyError, ValueError, TypeError):
                continue
            for lado, col, f, c, ef, ec in (("home", "HomeTeam", "HS", "AS", "HC", "AC"),
                                            ("away", "AwayTeam", "AS", "HS", "AC", "HC")):
                a = acum.setdefault((r[col], lado), {"rem": [], "rem_c": [], "esq": [], "esq_c": []})
                a["rem"].append(v[f]); a["rem_c"].append(v[c])
                a["esq"].append(v[ef]); a["esq_c"].append(v[ec])
        cache = {}
        for (eq, lado), a in acum.items():
            if eq not in cache:
                cache[eq] = emparejar(eq, cands)
                if cache[eq] is None:
                    sin.add((comp, eq))
            tid = cache[eq]
            if tid is None:
                continue
            n = len(a["rem"])
            av = lambda l: round(sum(l) / n, 1)
            extra.setdefault((comp, tid), {})[lado] = {
                "rem": av(a["rem"]), "rem_c": av(a["rem_c"]), "esq": av(a["esq"]), "esq_c": av(a["esq_c"]),
                "esq_t": round((sum(a["esq"]) + sum(a["esq_c"])) / n, 1), "n_x": n}
    return extra, sin


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
    filas = {}
    for code in COMPETICIONES:
        if code in CSV_LIGAS:
            print(f"Descargando remates y corners {code}...")
            filas[code] = descargar_filas(CSV_LIGAS[code])
    extra, sin = agregar_extra(filas, registro)
    if sin:
        print("Equipos sin emparejar (sin remates/corners):", sorted(sin))
    stats, pj = procesar(todos, datetime.now(timezone.utc), extra)
    for nombre, obj in (("stats.json", stats), ("partidos.json", pj)):
        with open(nombre, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    print(f"Listo: stats.json y partidos.json ({len(pj['proximos'])} proximos, "
          f"{len(pj['recientes'])} recientes)")


if __name__ == "__main__":
    main()
