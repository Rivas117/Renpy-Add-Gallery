# =====================================================================
#  UNIVERSAL REN'PY MOD  -  1.0.0-rc12  (todo en un solo archivo)
# ---------------------------------------------------------------------
#  INSTALACION: copia este archivo en la carpeta game/ del juego.
#  Antes, borra de game/ cualquier umod_todo_en_uno.rpy y .rpyc anterior
#  (y cualquier universal_mod*.rpy / .rpyc suelto).
#
#  USO: F8 abre y cierra la galeria. Tres apartados:
#    Imagenes  - las ilustraciones, en el orden de la historia
#    Videos    - los videos, con linea de tiempo (pausa, saltar)
#    Escenas   - los momentos de la historia con su dialogo. Al elegir
#                uno, puedes VER como transcurre o JUGAR desde ahi.
#  En el visor y en el cartel, las flechas del teclado pasan a la
#  anterior / siguiente. Filtro por personaje: "+N" muestra todos.
#  La version aparece abajo a la derecha de la galeria.
# =====================================================================


# ##################################################################### #
#   universal_mod.rpy
# ##################################################################### #

# =====================================================================
#  UNIVERSAL REN'PY MOD (UMOD)  -  FASE 1 / Proof of Concept
# ---------------------------------------------------------------------
#  Que hace esta fase:
#    - Se carga sola, sin tocar ningun archivo del juego.
#    - Detecta version de Ren'Py y de Python.
#    - Inyecta su propia UI sin editar screens.rpy.
#    - Lista labels, imagenes declaradas, archivos y variables del store.
#    - Sondea que APIs existen en este motor (semilla del Compat Layer).
#    - Guarda cache e informe JSON en la carpeta de saves.
#
#  INSTALACION: copiar este archivo dentro de la carpeta "game/".
#  ABRIR / CERRAR:  ALT + U      (configurable en TOGGLE_KEYS)
#
#  Motor objetivo: Ren'Py 6.99.12+ / 7.x / 8.x  (Screen Language 2).
#  Ren'Py 6 antiguo necesitara una variante: previsto en la Fase 8.
#
#  REGLA DE ORO: el mod nunca debe romper el juego. Todo acceso a APIs
#  internas va envuelto en try/except y degrada en silencio.
# =====================================================================


# ---------------------------------------------------------------------
# 0) BOOTSTRAP - modulo de runtime FUERA del store de Ren'Py
# ---------------------------------------------------------------------
# Motivo: lo que vive en el store se serializa en los savegames y lo
# vigila el rollback. Si guardaramos ahi el indice del juego (y, en
# fases futuras, referencias a nodos del AST) engordariamos los saves o
# romperiamos el pickle. Un modulo normal en sys.modules es invisible
# tanto para el save como para el rollback.
# ---------------------------------------------------------------------
init -1100 python:

    import sys as _umod_sys
    import types as _umod_types

    if "umod_rt" not in _umod_sys.modules:
        _umod_sys.modules["umod_rt"] = _umod_types.ModuleType("umod_rt")

    # Reinicio en cada init: asi un Shift+R no deja un indice obsoleto.
    _umod_rt = _umod_sys.modules["umod_rt"]
    _umod_rt.ready = False
    _umod_rt.scanning = False
    _umod_rt.errors = []
    _umod_rt.info = {}
    _umod_rt.labels = {"all": [], "game": [], "internal": []}
    _umod_rt.images = []
    _umod_rt.files = {"images": [], "video": [], "audio": [], "script": [],
                      "total": 0, "other": 0}
    _umod_rt.vars = []
    _umod_rt.baseline = set()
    _umod_rt.last_export = None
    _umod_rt.last_cache = None
    _umod_rt.selftest = None
    del _umod_rt


# ---------------------------------------------------------------------
# 1) NUCLEO - capa de compatibilidad + inspeccion
#    Namespace propio "umod" para no colisionar con el juego.
# ---------------------------------------------------------------------
init -1000 python in umod:

    import sys, os, re, json, time, types
    import umod_rt as RT

    # ---------- 1.0 El "renpy" correcto ---------------------------
    # Encontrado al probar en Ren'Py 8.5.2: hay DOS objetos "renpy".
    #  - "import renpy" da el PAQUETE: tiene version, config, store, game,
    #    ast... pero NO la API (show_screen, get_all_labels, list_files...).
    #  - El "renpy" que usan los juegos es renpy.exports, al que el motor
    #    copia ademas los atributos del paquete al arrancar.
    # Todos los modulos comparten este namespace, asi que esta unica
    # asignacion decide que "renpy" ven los ocho.
    class _RenpyFacade(object):
        """Solo si exports no tuviera los atributos del paquete: busca
        primero en exports y despues en el paquete; escribe en exports."""
        def __init__(self, api, pkg):
            object.__setattr__(self, "_api", api)
            object.__setattr__(self, "_pkg", pkg)

        def __getattr__(self, name):
            api = object.__getattribute__(self, "_api")
            try:
                return getattr(api, name)
            except AttributeError:
                return getattr(object.__getattribute__(self, "_pkg"), name)

        def __setattr__(self, name, value):
            setattr(object.__getattribute__(self, "_api"), name, value)

    def _resolve_renpy():
        pkg = sys.modules.get("renpy")
        api = None
        try:
            api = getattr(pkg.store, "renpy", None)       # el de los juegos
        except Exception:
            api = None
        if api is None or not callable(getattr(api, "show_screen", None)):
            api = getattr(pkg, "exports", None)
        if api is None or not callable(getattr(api, "show_screen", None)):
            return pkg                                    # ultimo recurso
        if all(hasattr(api, n) for n in ("config", "game", "store", "version_tuple")):
            return api
        return _RenpyFacade(api, pkg)

    renpy = _resolve_renpy()
    RENPY_API = ("exports" if callable(getattr(renpy, "show_screen", None)) else "paquete (sin API)")

    # ===================== CONFIGURACION =========================
    VERSION     = "1.0.0-rc12"
    TOGGLE_KEYS = ["alt_K_u"]   # Alt+M lo usa URM; evitamos el choque.
    PAGE_SIZE   = 120
    REPR_LIMIT  = 160
    # =============================================================

    # Modulos opcionales: cada fase enciende su bandera al cargarse.
    # El nucleo funciona solo aunque no este ninguno.
    GALLERY = False
    SCRIPT  = False
    GRAPH   = False
    TRACKER = False
    RECONSTRUCT = False
    EMULATOR = False
    ADAPTERS = False

    # ---------- 1.1 Compatibilidad Python 2 / Python 3 -----------
    PY2 = (sys.version_info[0] == 2)

    if PY2:
        string_types = (str, unicode)            # noqa  (solo se evalua en Py2)

        def iteritems(d):
            return d.iteritems()

        def to_text(x):
            try:
                return unicode(x)                # noqa
            except Exception:
                try:
                    return str(x)
                except Exception:
                    return "<?>"
    else:
        string_types = (str,)

        def iteritems(d):
            return iter(d.items())

        def to_text(x):
            try:
                return str(x)
            except Exception:
                return "<?>"

    # ---------- 1.2 Errores: se registran, nunca se propagan -----
    def log_error(where, exc):
        """Registra el error en memoria y, en el momento, en
        <saves>/umod_errors.log: aunque un panel no llegue a abrirse, el
        archivo cuenta por que."""
        try:
            line = "[%s] %s: %s" % (time.strftime("%H:%M:%S"), where, exc)
            RT.errors.append(line)
            if len(RT.errors) > 300:
                del RT.errors[:150]
            _log_line(line)
        except Exception:
            pass

    _LOG = {"n": 0, "header": False, "written": set()}

    def _log_line(line):
        if _LOG["n"] >= 300:
            return
        try:
            p = _savedir_path("umod_errors.log")
        except Exception:
            p = None
        if not p:
            return
        try:
            f = open(p, "a")
            try:
                if not _LOG["header"]:
                    f.write("--- %s  UMOD %s  Ren'Py %s  API %s\n" % (
                        time.strftime("%Y-%m-%d %H:%M:%S"), VERSION, RENPY_STR, RENPY_API))
                    _LOG["header"] = True
                txt = to_text(line)
                if PY2:
                    txt = txt.encode("utf-8", "replace")
                f.write(txt)
                f.write("\n")
            finally:
                f.close()
            _LOG["n"] += 1
            _LOG["written"].add(line)
        except Exception:
            pass

    def safe(fn, default=None, where="?"):
        try:
            return fn()
        except Exception as e:
            log_error(where, e)
            return default

    # ---------- 1.3 Deteccion de version -------------------------
    def _digits(s):
        try:
            nums = re.findall(r"\d+", to_text(s))
            return tuple(int(n) for n in nums[:3]) if nums else None
        except Exception:
            return None

    def detect_renpy_version():
        vt = getattr(renpy, "version_tuple", None)
        if isinstance(vt, tuple) and len(vt) >= 2:
            try:
                return tuple(int(x) for x in vt[:3])
            except Exception:
                pass
        for attr in ("version_only", "version_string"):
            s = getattr(renpy, attr, None)
            if isinstance(s, string_types):
                p = _digits(s)
                if p:
                    return p
        v = getattr(renpy, "version", None)
        try:
            s = v() if callable(v) else v
            p = _digits(s)
            if p:
                return p
        except Exception:
            pass
        return (0, 0, 0)

    RENPY = detect_renpy_version()
    RENPY_STR = ".".join(str(x) for x in RENPY)

    def at_least(major, minor=0, patch=0):
        return RENPY >= (major, minor, patch)

    if RENPY[0] >= 8:
        GENERATION = "8 (Python 3)"
    elif RENPY[0] == 7:
        GENERATION = "7 (Python 2)"
    elif RENPY[0] == 6:
        GENERATION = "6 (Python 2, legacy)"
    else:
        GENERATION = "desconocida"

    HAS_SVIV = at_least(6, 99, 12)      # ScreenVariableInputValue

    HEADER = "%s   -   Ren'Py %s   -   Python %d.%d" % (
        VERSION, RENPY_STR, sys.version_info[0], sys.version_info[1])

    # ---------- 1.4 Escalado propio (sin depender de gui.*) ------
    _SCALE = None

    def scale_factor():
        global _SCALE
        if _SCALE is None:
            try:
                h = float(getattr(renpy.config, "screen_height", 0) or 1080)
            except Exception:
                h = 1080.0
            _SCALE = max(0.55, min(1.6, h / 1080.0))
        return _SCALE

    def S(n):
        try:
            return int(round(n * scale_factor()))
        except Exception:
            return int(n)

    def esc(s):
        """Escapa texto para el displayable Text: evita [ y { accidentales."""
        return to_text(s).replace("{", "{{").replace("[", "[[")

    # ---------- 1.5 Identidad del juego --------------------------
    def game_id():
        return "%s|%s" % (to_text(getattr(renpy.config, "name", "") or ""),
                          to_text(getattr(renpy.config, "version", "") or ""))

    _FP = None

    def script_fp():
        """Huella del guion compilado. Cambia si cambia cualquier script,
        aunque el juego no suba config.version (parches sin versionar).
        1) renpy.game.script.digest: md5 que el motor acumula al cargar
           cada .rpyc  (INTERNO, existe desde Ren'Py 6.x)
        2) fallback: numero de statements + lista de archivos de guion."""
        global _FP
        if _FP is not None:
            return _FP
        parts = [game_id()]
        try:
            dg = renpy.game.script.digest
            parts.append(to_text(dg.hexdigest()))
        except Exception:
            try:
                parts.append(to_text(len(renpy.game.script.all_stmts)))
            except Exception:
                pass
            try:
                sc = [to_text(f) for f in renpy.list_files()
                      if to_text(f).lower().endswith((".rpy", ".rpyc"))]
                sc.sort()
                parts.append("|".join(sc))
            except Exception:
                pass
        import hashlib
        try:
            raw = "#".join(parts)
            if not PY2:
                raw = raw.encode("utf-8", "replace")
            _FP = hashlib.md5(raw).hexdigest()
        except Exception:
            _FP = game_id()
        return _FP

    # ---------- 1.6 Sondas de API --------------------------------
    # (P) = publica y documentada    (I) = interna, puede romperse
    API_CHECKS = [
        ("(P) renpy.get_all_labels",   lambda: callable(renpy.get_all_labels)),
        ("(P) renpy.has_label",        lambda: callable(renpy.has_label)),
        ("(P) renpy.list_images",      lambda: callable(renpy.list_images)),
        ("(P) renpy.list_files",       lambda: callable(renpy.list_files)),
        ("(P) renpy.loadable",         lambda: callable(renpy.loadable)),
        ("(P) renpy.get_screen",       lambda: callable(renpy.get_screen)),
        ("(P) renpy.list_saved_games", lambda: callable(getattr(renpy, "list_saved_games", None))),
        ("(P) renpy.copy_save",        lambda: callable(getattr(renpy, "copy_save", None))),
        ("(P) renpy.invoke_in_thread", lambda: callable(getattr(renpy, "invoke_in_thread", None))),
        ("(P) renpy.get_return_stack", lambda: callable(getattr(renpy, "get_return_stack", None))),
        ("(P) config.overlay_screens", lambda: hasattr(renpy.config, "overlay_screens")),
        ("(P) config.label_callback",  lambda: hasattr(renpy.config, "label_callback")),
        ("(I) config.underlay",        lambda: hasattr(renpy.config, "underlay")),
        ("(I) renpy.Keymap",           lambda: callable(getattr(renpy, "Keymap", None))),
        ("(I) renpy.session",          lambda: hasattr(renpy, "session")),
        ("(I) renpy.game.script",      lambda: renpy.game.script is not None),
        ("(I) script.namemap",         lambda: bool(getattr(renpy.game.script, "namemap", None))),
        ("(I) script.all_stmts",       lambda: bool(getattr(renpy.game.script, "all_stmts", None))),
        ("(I) script.lookup",          lambda: callable(getattr(renpy.game.script, "lookup", None))),
        ("(I) renpy.ast.Menu",         lambda: hasattr(renpy.ast, "Menu")),
        ("(I) renpy.ast.Jump",         lambda: hasattr(renpy.ast, "Jump")),
        ("(I) renpy.ast.Call",         lambda: hasattr(renpy.ast, "Call")),
        ("(I) renpy.ast.If",           lambda: hasattr(renpy.ast, "If")),
    ]

    def probe_apis():
        out = []
        for name, fn in API_CHECKS:
            try:
                out.append((name, bool(fn())))
            except Exception:
                out.append((name, False))
        return out

    def ast_available():
        try:
            return bool(getattr(renpy.game.script, "namemap", None)) and hasattr(renpy, "ast")
        except Exception:
            return False

    # ---------- 1.7 Labels ---------------------------------------
    def scan_labels():
        out = {"all": [], "game": [], "internal": []}
        raw = safe(lambda: sorted(renpy.get_all_labels()), [], "scan_labels")
        for lb in raw:
            t = to_text(lb)
            out["all"].append(t)
            if t.startswith("_"):
                out["internal"].append(t)
            else:
                out["game"].append(t)
        return out

    def label_details(name):
        """Preview de la Fase 3: localizar el label dentro del AST.
        script.lookup es API INTERNA -> siempre protegida."""
        d = {"name": to_text(name), "file": "?", "line": "?",
             "exists": "?", "node": "?"}
        try:
            d["exists"] = to_text(bool(renpy.has_label(name)))
        except Exception as e:
            log_error("has_label", e)
        try:
            node = renpy.game.script.lookup(name)
            d["file"] = to_text(getattr(node, "filename", "?"))
            d["line"] = to_text(getattr(node, "linenumber", "?"))
            d["node"] = type(node).__name__
        except Exception as e:
            log_error("label_details", e)
        return d

    def label_detail_lines(name):
        d = label_details(name)
        return [
            ("Archivo",   d["file"]),
            ("Linea",     d["line"]),
            ("Nodo AST",  d["node"]),
            ("has_label", d["exists"]),
        ]

    # ---------- 1.8 Imagenes declaradas --------------------------
    def scan_images():
        raw = safe(lambda: renpy.list_images(), [], "scan_images")
        out = []
        for it in raw:
            if isinstance(it, tuple):
                out.append(" ".join(to_text(x) for x in it))
            else:
                out.append(to_text(it))
        out.sort()
        return out

    def image_tags():
        """Agrupa por tag. Base de la clasificacion automatica (Fase 2)."""
        tags = {}
        for full in RT.images:
            tag = full.split(" ")[0]
            tags[tag] = tags.get(tag, 0) + 1
        return sorted(iteritems(tags), key=lambda kv: (-kv[1], kv[0]))

    # ---------- 1.9 Archivos (disco + archivos .rpa) -------------
    EXT_IMG = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tga")
    EXT_VID = (".webm", ".mp4", ".ogv", ".avi", ".mkv", ".mpg")
    EXT_AUD = (".ogg", ".mp3", ".wav", ".opus", ".flac", ".m4a")
    EXT_SCR = (".rpy", ".rpyc", ".rpym", ".rpymc")

    def scan_files():
        res = {"images": [], "video": [], "audio": [], "script": [],
               "total": 0, "other": 0}
        raw = safe(lambda: renpy.list_files(), [], "scan_files")
        for f in raw:
            fl = to_text(f)
            low = fl.lower()
            res["total"] += 1
            if low.endswith(EXT_IMG):
                res["images"].append(fl)
            elif low.endswith(EXT_VID):
                res["video"].append(fl)
            elif low.endswith(EXT_AUD):
                res["audio"].append(fl)
            elif low.endswith(EXT_SCR):
                res["script"].append(fl)
            else:
                res["other"] += 1
        for k in ("images", "video", "audio", "script"):
            res[k].sort()
        return res

    # ---------- 1.10 Variables del store -------------------------
    NEVER_VARS = set([
        "config", "renpy", "store", "persistent", "gui", "build", "umod",
        "preferences", "achievement", "layeredimage", "audio", "director",
        "iap", "updater", "nvl_list", "adv", "nvl", "mouse_visible",
        "default_mouse", "suppress_overlay", "style", "theme", "layout",
        "os", "sys", "math", "random", "time", "json", "re",
    ])

    def _is_state_value(v):
        if isinstance(v, types.ModuleType):
            return False
        if isinstance(v, type):
            return False
        if callable(v):        # funciones, Character(), Actions, ...
            return False
        return True

    def snapshot_names():
        return safe(lambda: set(vars(renpy.store).keys()), set(), "snapshot_names")

    def scan_vars():
        out = []
        d = safe(lambda: dict(vars(renpy.store)), {}, "scan_vars")
        base = RT.baseline or set()
        for k in sorted(d.keys()):
            if k.startswith("_") or k in NEVER_VARS:
                continue
            v = d[k]
            if not _is_state_value(v):
                continue
            try:
                tn = type(v).__name__
            except Exception:
                tn = "?"
            try:
                rp = repr(v)
                if len(rp) > REPR_LIMIT:
                    rp = rp[:REPR_LIMIT] + " ..."
            except Exception:
                rp = "<no legible>"
            out.append({"name": k, "type": tn, "value": to_text(rp),
                        "new": (k not in base)})
        return out

    def refresh_vars():
        RT.vars = scan_vars()
        return len(RT.vars)

    # ---------- 1.11 Informe -------------------------------------
    def build_info():
        i = {}
        i["umod"]        = VERSION
        i["renpy"]       = RENPY_STR
        i["renpy_raw"]   = to_text(getattr(renpy, "version_string", "") or
                                   getattr(renpy, "version_only", "") or "?")
        i["generation"]  = GENERATION
        i["python"]      = "%d.%d.%d" % tuple(sys.version_info[:3])
        i["api"]         = RENPY_API
        i["game_name"]   = to_text(getattr(renpy.config, "name", "") or "?")
        i["game_ver"]    = to_text(getattr(renpy.config, "version", "") or "?")
        i["resolution"]  = "%s x %s" % (getattr(renpy.config, "screen_width", "?"),
                                        getattr(renpy.config, "screen_height", "?"))
        i["developer"]   = to_text(bool(getattr(renpy.config, "developer", False)))
        i["ast_ok"]      = to_text(ast_available())
        i["labels_all"]  = to_text(len(RT.labels.get("all", [])))
        i["labels_game"] = to_text(len(RT.labels.get("game", [])))
        i["images"]      = to_text(len(RT.images))
        i["image_tags"]  = to_text(len(image_tags()))
        i["files_total"] = to_text(RT.files.get("total", 0))
        i["files_img"]   = to_text(len(RT.files.get("images", [])))
        i["files_vid"]   = to_text(len(RT.files.get("video", [])))
        i["files_aud"]   = to_text(len(RT.files.get("audio", [])))
        i["files_scr"]   = to_text(len(RT.files.get("script", [])))
        i["vars"]        = to_text(len(RT.vars))
        i["gamedir"]     = to_text(getattr(renpy.config, "gamedir", "?"))
        i["savedir"]     = to_text(getattr(renpy.config, "savedir", "?"))
        return i

    INFO_ORDER = [
        ("umod",        "Version del mod"),
        ("renpy",       "Ren'Py detectado"),
        ("renpy_raw",   "Cadena de version"),
        ("generation",  "Generacion"),
        ("python",      "Python"),
        ("api",         "API de Ren'Py"),
        ("scan_seg",    "Tiempo de escaneo (s)"),
        ("game_name",   "Juego"),
        ("game_ver",    "Version del juego"),
        ("resolution",  "Resolucion"),
        ("developer",   "Modo desarrollador"),
        ("ast_ok",      "AST accesible"),
        ("labels_all",  "Labels totales"),
        ("labels_game", "Labels del juego"),
        ("images",      "Imagenes declaradas"),
        ("image_tags",  "Tags de imagen"),
        ("vars",        "Variables detectadas"),
        ("files_total", "Archivos totales"),
        ("files_img",   "   imagenes"),
        ("files_vid",   "   video"),
        ("files_aud",   "   audio"),
        ("files_scr",   "   scripts"),
        ("gamedir",     "Carpeta game"),
        ("savedir",     "Carpeta saves"),
    ]

    def info_rows():
        return [(lbl, to_text(RT.info.get(key, "?"))) for key, lbl in INFO_ORDER]

    def tag_rows():
        return ["%s   (%d)" % (t, n) for t, n in image_tags()]

    # ---------- 1.12 Escaneo perezoso ----------------------------
    def scan_all(force=False, vars_too=True):
        """Se ejecuta al abrir el panel por primera vez, no al arrancar.
        En juegos enormes puede tardar; la Fase 10 lo hara incremental."""
        if RT.scanning:
            return False
        if RT.ready and not force:
            return False
        RT.scanning = True
        t0 = time.time()
        try:
            RT.labels = scan_labels()
            RT.images = scan_images()
            RT.files  = scan_files()
            RT.vars   = scan_vars() if vars_too else []
            RT.info   = build_info()
            RT.info["scan_seg"] = to_text(round(time.time() - t0, 3))
            RT.ready = True
            save_cache()
        except Exception as e:
            log_error("scan_all", e)
        finally:
            RT.scanning = False
        return True

    # ---------- 1.13 Cache e informe -----------------------------
    # Escribimos SIEMPRE en savedir (siempre escribible) y nunca en
    # gamedir, que puede ser de solo lectura (Program Files, Android...).
    def _savedir_path(filename):
        sd = getattr(renpy.config, "savedir", None)
        return os.path.join(sd, filename) if sd else None

    # Fase 10: escritura rapida, atomica y troceable.
    #  - json.dump() sobre un archivo usa SIEMPRE el codificador de Python
    #    puro (es ~7 veces mas lento); json.dumps() usa el de C.
    #  - Se escribe a "<archivo>.tmp" y despues se renombra: si el juego se
    #    cierra a mitad, la cache anterior queda intacta.
    #  - Las caches grandes se generan por trozos (cada entrada de los
    #    diccionarios y listas grandes por separado) para poder ceder el
    #    control entre trozos sin congelar la pantalla.
    YIELD_S = 0.008

    def _replace_file(src, dst):
        try:
            os.replace(src, dst)                 # Python 3
        except AttributeError:
            if os.path.exists(dst):              # Python 2 en Windows
                os.remove(dst)
            os.rename(src, dst)

    def json_chunks(payload):
        if not isinstance(payload, dict):
            yield json.dumps(payload)
            return
        yield "{"
        first = True
        for k in payload:
            yield ("" if first else ",") + json.dumps(to_text(k)) + ":"
            first = False
            v = payload[k]
            if isinstance(v, dict) and len(v) > 200:
                yield "{"
                f2 = True
                for kk in v:
                    yield ("" if f2 else ",") + json.dumps(to_text(kk)) + ":" + json.dumps(v[kk])
                    f2 = False
                yield "}"
            elif isinstance(v, list) and len(v) > 200:
                yield "["
                f2 = True
                for x in v:
                    yield ("" if f2 else ",") + json.dumps(x)
                    f2 = False
                yield "]"
            else:
                yield json.dumps(v)
        yield "}"

    def write_json_gen(path, payload, out=None):
        """Generador: escribe payload troceado y cede cada YIELD_S segundos.
        Al terminar deja la ruta en out[0] (o None si fallo)."""
        if out is None:
            out = [None]
        if not path:
            return
        tmp = path + ".tmp"
        try:
            f = open(tmp, "w")
            try:
                buf = []
                size = 0
                nexty = time.time() + YIELD_S
                for piece in json_chunks(payload):
                    buf.append(piece)
                    size += len(piece)
                    if size > 262144:
                        f.write("".join(buf))
                        buf, size = [], 0
                    if time.time() >= nexty:
                        yield
                        nexty = time.time() + YIELD_S
                f.write("".join(buf))
            finally:
                f.close()
            _replace_file(tmp, path)
            out[0] = path
        except Exception as e:
            log_error("write_json", e)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _write_json(path, payload, pretty=False):
        """De una vez. pretty=True para archivos pensados para personas
        (informes, reglas, adaptadores); las caches van compactas."""
        if not path:
            return None
        if pretty:
            tmp = path + ".tmp"
            try:
                f = open(tmp, "w")
                try:
                    f.write(json.dumps(payload, indent=1, sort_keys=True))
                finally:
                    f.close()
                _replace_file(tmp, path)
                return path
            except Exception as e:
                log_error("write_json", e)
                return None
        out = [None]
        run_sync(write_json_gen(path, payload, out))
        return out[0]

    def save_cache():
        RT.last_cache = _write_json(_savedir_path("umod_cache.json"), {
            "format":  1,
            "umod":    VERSION,
            "game_id": game_id(),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "info":    RT.info,
            "labels":  RT.labels.get("game", [])[:8000],
            "images":  RT.images[:8000],
        })
        return RT.last_cache

    def load_cache():
        p = _savedir_path("umod_cache.json")
        if not p or not os.path.exists(p):
            return None
        try:
            f = open(p, "r")
            try:
                data = json.load(f)
            finally:
                f.close()
        except Exception as e:
            log_error("load_cache", e)
            return None
        if data.get("game_id") != game_id():
            return None          # otro juego u otra version: invalidar
        return data

    def export_report():
        RT.last_export = _write_json(_savedir_path("umod_report.json"), pretty=True, payload={
            "info":   RT.info,
            "apis":   dict(probe_apis()),
            "errors": RT.errors,
            "labels": RT.labels.get("game", [])[:500],
            "images": RT.images[:500],
            "tags":   [list(t) for t in image_tags()[:200]],
        })
        return RT.last_export

    def cache_line():
        return "Cache: %s" % (RT.last_cache or "(sin escribir)")

    def export_line():
        return "Informe: %s" % (RT.last_export or "(sin exportar)")

    def errors_line():
        return "Errores capturados: %d" % len(RT.errors)

    # ---------- 1.14 Datos para la UI ----------------------------
    TABS = [
        ("info",   "Inspector"),
        ("labels", "Labels"),
        ("images", "Imagenes"),
        ("tags",   "Tags"),
        ("media",  "Archivos"),
        ("vars",   "Variables"),
        ("compat", "Compatibilidad"),
        ("tools",  "Herramientas"),
    ]

    LIST_TABS = ("labels", "images", "tags", "media", "vars")

    def rows(tab, query):
        q = to_text(query or "").strip().lower()
        src = []
        if tab == "labels":
            src = RT.labels.get("game", [])
        elif tab == "images":
            src = RT.images
        elif tab == "tags":
            src = tag_rows()
        elif tab == "media":
            f = RT.files
            src = f.get("images", []) + f.get("video", []) + f.get("audio", [])
        elif tab == "vars":
            src = ["%s = %s     <%s>%s" % (v["name"], v["value"], v["type"],
                                           "   *" if v["new"] else "")
                   for v in RT.vars]
        if not q:
            return src
        return [s for s in src if q in s.lower()]

    def page_slice(items, page):
        try:
            start = max(0, int(page)) * PAGE_SIZE
        except Exception:
            start = 0
        return items[start:start + PAGE_SIZE]

    def page_count(items):
        n = len(items)
        return 1 if n == 0 else (n + PAGE_SIZE - 1) // PAGE_SIZE

    def counter_line(items, page):
        return "%d resultados   -   pagina %d / %d" % (
            len(items), int(page) + 1, page_count(items))

    # ---------- 1.15 Apertura / cierre ---------------------------
    SCREEN = "umod_main"

    def is_open():
        try:
            return bool(renpy.get_screen(SCREEN))
        except Exception:
            return False

    def open_panel():
        try:
            scan_all()
            refresh_vars()                 # el store solo se lee desde la pantalla
            RT.info = build_info()
            renpy.show_screen(SCREEN)
            renpy.restart_interaction()
        except Exception as e:
            log_error("open_panel", e)

    def close_panel():
        try:
            renpy.hide_screen(SCREEN)
            renpy.restart_interaction()
        except Exception as e:
            log_error("close_panel", e)

    def toggle_panel():
        if is_open():
            close_panel()
        else:
            open_panel()

    UMOD_SCREENS = ["umod_main", "umod_gallery", "umod_script", "umod_graph",
                    "umod_tracker", "umod_reconstruct", "umod_emulator",
                    "umod_adapters"]

    def _on_load():
        # Si algun panel del mod quedase guardado en un save (por ejemplo
        # la copia de seguridad de la Fase 6), lo cerramos al cargar.
        for s in UMOD_SCREENS:
            try:
                renpy.hide_screen(s)
            except Exception:
                pass


# =====================================================================
# 1b) COMPATIBILITY LAYER  (Fase 8)
# ---------------------------------------------------------------------
#  Unico lugar del mod que sabe en que se diferencian las versiones de
#  Ren'Py. Tres piezas:
#    a) RESOLUTORES: funciones que eligen la API correcta en cada motor
#       (register_key, add_callback, revertable_class, open_game_file).
#       Todos los modulos las usan en vez de resolverlo por su cuenta.
#    b) CAPACIDADES: cada una declara sus APIs principales, una
#       alternativa si la hay y el impacto si falta. Se evaluan en el
#       juego real -> OK / ALTERNATIVA / NO DISPONIBLE.
#    c) AUTODIAGNOSTICO: pruebas funcionales seguras (no modifican la
#       partida) y un informe exportable: umod_compat.json.
#  Mismo prioridad (-1000) que el nucleo y despues en el archivo: se
#  ejecuta antes de cualquier registro (-999 en adelante).
# =====================================================================
init -1000 python in umod:

    # ---------- 1b.1 Resolutores ------------------------------------
    KEY_MODE = {}          # accion -> "underlay" | "overlay"
    OVERLAY_KEYS = []      # (accion, funcion) que la overlay debe atender
    CB_MODE = {}           # funcion -> como quedo registrada

    def keymap_class():
        """renpy.Keymap (moderno) o renpy.display.behavior.Keymap."""
        KM = getattr(renpy, "Keymap", None)
        if KM is None:
            try:
                KM = renpy.display.behavior.Keymap
            except Exception:
                KM = None
        return KM

    def adv_keys(keys):
        """Los atajos Alt+... de las herramientas avanzadas solo se activan si
        el usuario lo pide (Inspector > Herramientas). Por defecto la unica
        tecla del mod es F8 (galeria)."""
        try:
            on = bool(getattr(renpy.store.persistent, "umod_adv_keys", False))
        except Exception:
            on = False
        return list(keys) if on else []

    AUTOSTART = []          # funciones *_ensure que se lanzan solas al arrancar
    _AUTO = [False]

    def autostart_once():
        """Primera interaccion del juego (splash o menu principal): lanza en
        segundo plano la preparacion de galeria, guion y grafo, para que
        todo este listo cuando el jugador pulse F8."""
        if _AUTO[0]:
            return
        _AUTO[0] = True
        try:
            if getattr(renpy.store.persistent, "umod_autostart", True) is False:
                return
        except Exception:
            pass
        for fn in list(AUTOSTART):
            try:
                fn()
            except Exception as e:
                log_error("autostart %s" % getattr(fn, "__name__", "?"), e)

    def register_key(action, keys, fn):
        """Tecla global. Preferencia: config.underlay con un Keymap (lo que
        hace el propio motor en 00keymap.rpy; funciona incluso en el menu
        principal). Alternativa: la overlay screen del mod. Sin teclas, solo
        se declara el nombre (las pantallas lo usan con 'key')."""
        if not keys:
            try:
                renpy.config.keymap.setdefault(action, [])
            except Exception as e:
                log_error("register_key.keymap", e)
            KEY_MODE[action] = "sin tecla"
            return "sin tecla"
        try:
            km = renpy.config.keymap
            cur = km.get(action, [])
            if not isinstance(cur, list):
                cur = list(cur)
            for b in keys:
                if b not in cur:
                    cur.append(b)
            km[action] = cur
        except Exception as e:
            log_error("register_key.keymap", e)
        KM = keymap_class()
        if KM is not None:
            try:
                renpy.config.underlay.append(KM(**{action: fn}))
                KEY_MODE[action] = "underlay"
                return "underlay"
            except Exception as e:
                log_error("register_key.underlay", e)
        OVERLAY_KEYS.append((action, fn))
        KEY_MODE[action] = "overlay"
        return "overlay"

    def add_callback(list_name, single_name, fn, tag=""):
        """Registra fn en la lista moderna de config si existe; si no, la
        encadena a la funcion unica antigua sin perder la del juego."""
        try:
            lst = getattr(renpy.config, list_name, None) if list_name else None
            if isinstance(lst, list):
                if fn not in lst:
                    lst.append(fn)
                CB_MODE[tag or list_name] = list_name
                return list_name
            if single_name:
                prev = getattr(renpy.config, single_name, None)
                if getattr(prev, "_umod_fn", None) is fn:
                    return single_name

                def _chained(*a, **k):
                    if prev is not None:
                        prev(*a, **k)
                    return fn(*a, **k)
                _chained._umod_fn = fn
                setattr(renpy.config, single_name, _chained)
                mode = single_name + (" (encadenado)" if prev is not None else "")
                CB_MODE[tag or single_name] = mode
                return mode
        except Exception as e:
            log_error("add_callback.%s" % (list_name or single_name), e)
        CB_MODE[tag or list_name or single_name] = "no disponible"
        return None

    def add_overlay_screen(name):
        try:
            if name not in renpy.config.overlay_screens:
                renpy.config.overlay_screens.append(name)
            return True
        except Exception as e:
            log_error("add_overlay_screen", e)
            return False

    def revertable_class(name):
        """RevertableList/Dict/Set: renpy.revertable (8.x) o renpy.python (6/7)."""
        for modname in ("revertable", "python"):
            m = getattr(renpy, modname, None)
            c = getattr(m, name, None) if m is not None else None
            if c is not None:
                return c
        return None

    def open_game_file(path):
        """Abre un archivo del juego (suelto o dentro de un .rpa)."""
        f = getattr(renpy, "file", None)
        if f is not None:
            return f(path)
        return renpy.loader.load(path)

    # ---------- 1b.1b Trabajo en segundo plano (Fase 10) ------------
    #  Los analisis pesados son generadores que ceden el control y
    #  devuelven su progreso (0..1). El planificador los ejecuta:
    #    "hilo"     renpy.invoke_in_thread (7.x/8.x escritorio): a velocidad
    #               completa sin congelar la pantalla. Es seguro porque los
    #               analisis solo LEEN el guion y los archivos y publican su
    #               resultado de una vez al final.
    #    "tramos"   unos milisegundos por fotograma desde un callback
    #               periodico: funciona en cualquier version, tambien en web.
    #    "sincrono" todo de una vez (pruebas; o si el usuario lo fuerza).
    #
    #  rc7: UNA cola y UN trabajador. Antes se lanzaban varios analisis a la
    #  vez y, como los hilos de Python comparten el procesador (GIL), el
    #  juego entero iba mas lento. Ahora:
    #   - los trabajos se hacen de uno en uno, en orden de cola;
    #   - lo que el jugador esta mirando pasa delante (job_bump);
    #   - en modo hilo, el trabajador descansa entre tramos para que el
    #     juego tenga siempre la mayor parte del procesador;
    #   - la pantalla solo se refresca si hay un panel del mod abierto.
    JOBS = {}
    QUEUE = []                  # nombres, en orden de ejecucion
    TIMINGS = {}
    JOB_BUDGET_MS = 12.0        # tramos: trabajo por llamada del callback periodico
    THREAD_NAP = 0.006          # hilo: descanso tras cada tramo (~8 ms de trabajo)
    _JOB_REFRESH = [0.0]
    _WORKER = {"alive": False}

    #  rc8: DOS VELOCIDADES.
    #   - Jugando (galeria cerrada): REPOSO. El mod trabaja a ratos muy
    #     cortos (2 ms) y descansa mucho (100 ms): ~2 % de un nucleo, el
    #     juego no lo nota. Asi va dejando cosas preparadas sin molestar.
    #   - Galeria abierta (F8): A FONDO. Tramos largos y casi sin descanso,
    #     y SOLO en lo que necesita el apartado que se esta mirando (FOCUS);
    #     lo demas espera a que eso termine.
    POWER_IDLE = {"slice": 0.002, "nap": 0.100, "budget_ms": 1.5}
    POWER_FULL = {"slice": 0.010, "nap": 0.001, "budget_ms": 14.0}
    POWER = {"full": None, "since": 0.0}
    FOCUS = []                  # trabajos que pide el apartado visible, en orden
    TICK_HOOKS = []             # comprobaciones baratas en cada tick (hilo principal)

    def power_set(full):
        global YIELD_S, THREAD_NAP, JOB_BUDGET_MS
        full = bool(full)
        if POWER["full"] is full:
            return
        P = POWER_FULL if full else POWER_IDLE
        YIELD_S = P["slice"]
        THREAD_NAP = P["nap"]
        JOB_BUDGET_MS = P["budget_ms"]
        POWER["full"] = full
        POWER["since"] = time.time()

    def set_focus(names):
        """La galeria dice que trabajos necesita lo que se esta mirando."""
        names = [n for n in names if n]
        if names != FOCUS:
            FOCUS[:] = names
        apply_focus()

    def apply_focus():
        if not FOCUS or len(QUEUE) < 2:
            return
        rank = dict((n, i) for i, n in enumerate(FOCUS))
        big = len(FOCUS)
        new = sorted(QUEUE, key=lambda n: rank.get(n, big))   # estable
        if new != QUEUE:
            QUEUE[:] = new

    power_set(False)            # se arranca en reposo

    def run_sync(gen):
        for _p in gen:
            pass

    def job_mode():
        pref = None
        try:
            pref = getattr(renpy.store.persistent, "umod_bg_mode", None)
        except Exception:
            pref = None
        if pref in ("tramos", "sincrono"):
            return pref
        web = bool(getattr(renpy, "emscripten", False))
        if not web and callable(getattr(renpy, "invoke_in_thread", None)):
            return "hilo"
        return "tramos"

    def job_running(name):
        """En cola o ejecutandose."""
        j = JOBS.get(name)
        return bool(j and j["status"] == "corriendo")

    def _job_progress(j, p):
        try:
            j["p"] = max(0.0, min(1.0, float(p)))
        except Exception:
            pass

    def _job_done(j, status, err=None):
        j["status"] = status
        j["err"] = err
        j["t1"] = time.time()
        j["p"] = 1.0
        TIMINGS[j["name"]] = round(j["t1"] - j.get("ts", j["t0"]), 2)
        try:
            QUEUE.remove(j["name"])
        except ValueError:
            pass

    def _job_gen(j):
        if j["gen"] is None:
            j["ts"] = time.time()
            j["gen"] = j["factory"]()
        return j["gen"]

    def _job_blocked(j):
        for dep in j.get("after") or ():
            d = JOBS.get(dep)
            if d is not None and d["status"] == "corriendo":
                return True
        return False

    def _job_next():
        """El primer trabajo de la cola que pueda avanzar (los que esperan
        a otro, p. ej. el orden de la historia al grafo, se saltan)."""
        for name in list(QUEUE):
            j = JOBS.get(name)
            if j and j["status"] == "corriendo" and not _job_blocked(j):
                return j
        return None

    def _job_drain(j, gen, nap=0.0):
        try:
            for p in gen:
                _job_progress(j, p)
                if nap:
                    time.sleep(nap)
            _job_done(j, "hecho")
        except Exception as e:
            log_error("trabajo %s" % j["name"], e)
            _job_done(j, "error", to_text(e))

    def _job_step(j):
        """Avanza un tramo (2 ms en reposo, 10 ms a fondo). False si ha terminado."""
        try:
            _job_progress(j, next(_job_gen(j)))
            return True
        except StopIteration:
            _job_done(j, "hecho")
        except Exception as e:
            log_error("trabajo %s" % j["name"], e)
            _job_done(j, "error", to_text(e))
        return False

    def _worker():
        # Un tramo cada vez del PRIMER trabajo de la cola: si el jugador
        # pide algo (miniaturas, escenas), pasa delante al instante y el
        # trabajo largo que se estaba haciendo sigue despues donde se quedo.
        try:
            while True:
                j = _job_next()
                if j is None:
                    break
                if _job_step(j):
                    time.sleep(THREAD_NAP)
        finally:
            _WORKER["alive"] = False

    def _ensure_worker():
        if _WORKER["alive"]:
            return True
        _WORKER["alive"] = True
        try:
            renpy.invoke_in_thread(_worker)
            return True
        except Exception as e:
            _WORKER["alive"] = False
            log_error("invoke_in_thread", e)
            return False

    def job_start(name, factory, label="", front=False, after=()):
        j = JOBS.get(name)
        if j and j["status"] == "corriendo":
            if front:
                job_bump(name)
            return j
        mode = job_mode()
        j = {"name": name, "label": label or name, "status": "corriendo", "p": 0.0,
             "t0": time.time(), "t1": None, "mode": mode, "err": None,
             "gen": None, "factory": factory, "after": tuple(after or ())}
        JOBS[name] = j
        if mode == "sincrono":
            try:
                _job_drain(j, _job_gen(j))
            except Exception as e:
                log_error("trabajo %s" % name, e)
                _job_done(j, "error", to_text(e))
            return j
        if front:
            QUEUE.insert(0, name)
        else:
            QUEUE.append(name)
        if mode == "hilo" and not _ensure_worker():
            for jj in JOBS.values():
                if jj["status"] == "corriendo":
                    jj["mode"] = "tramos"
        return j

    def job_bump(name):
        """Lo que el jugador esta esperando pasa delante en la cola. El
        trabajo que se estaba haciendo queda en pausa y sigue despues."""
        try:
            QUEUE.remove(name)
        except ValueError:
            return
        QUEUE.insert(0, name)

    def mod_visible():
        for sname in UMOD_SCREENS:
            try:
                if renpy.get_screen(sname):
                    return True
            except Exception:
                pass
        return False

    def jobs_tick():
        """Callback periodico: en modo tramos avanza el primer trabajo de la
        cola; en todos los modos refresca los paneles del mod (si hay alguno
        abierto) unas 3 veces por segundo y al terminar un trabajo."""
        now = time.time()
        vis = mod_visible()
        power_set(vis)
        if vis:
            apply_focus()
        finished = False
        for j in JOBS.values():
            if j["status"] != "corriendo" and not j.get("seen"):
                j["seen"] = True
                finished = True
        j = _job_next()
        running = j is not None
        if j is not None and j["mode"] == "hilo" and not _WORKER["alive"]:
            _ensure_worker()                      # el hilo acabo justo al llegar otro trabajo
        if j is not None and j["mode"] == "tramos":
            t_end = now + JOB_BUDGET_MS / 1000.0
            try:
                gen = _job_gen(j)
                while time.time() < t_end:
                    _job_progress(j, next(gen))
            except StopIteration:
                _job_done(j, "hecho")
                j["seen"] = True
                finished = True
            except Exception as e:
                log_error("trabajo %s" % j["name"], e)
                _job_done(j, "error", to_text(e))
                j["seen"] = True
                finished = True
        for hk in TICK_HOOKS:
            try:
                hk()
            except Exception as e:
                log_error("tick", e)
        if (finished or (running and now - _JOB_REFRESH[0] > 0.2)) and vis:
            _JOB_REFRESH[0] = now
            try:
                renpy.restart_interaction()
            except Exception:
                pass

    def adv_visible():
        """Algun panel avanzado abierto (no la galeria)."""
        for sname in UMOD_SCREENS:
            if sname == "umod_gallery":
                continue
            try:
                if renpy.get_screen(sname):
                    return True
            except Exception:
                pass
        return False

    def jobs_active():
        return [j for j in JOBS.values() if j["status"] == "corriendo"]

    def job_line(j):
        el = time.time() - j["t0"]
        return "UMOD  -  %s  %d%%  (%.0f s, %s)" % (j["label"], int(j["p"] * 100), el, j["mode"])

    # ---------- 1b.1c Proteccion de pantallas (Fase 10) -------------
    #  Si una funcion que alimenta una pantalla del mod falla, Ren'Py
    #  mostraria su pantalla de error y el jugador perderia el hilo de la
    #  partida. guard() convierte el fallo en un aviso dentro del panel.
    ERR_ROWS = [("warn", "Error interno del mod al preparar esta vista. Detalle en Inspector > Herramientas.")]
    ERR_ROWS3 = [("t", "#ff9b8a", ERR_ROWS[0][1])]
    ERR_PAIRS = [("Error", "interno del mod al preparar esta vista (ver Inspector > Herramientas)")]

    def guard(fn, default, *args, **kw):
        try:
            return fn(*args, **kw)
        except Exception as e:
            log_error("vista %s" % getattr(fn, "__name__", "?"), e)
            return default

    def errors_flush(*args):
        """Al salir: deja los errores en la carpeta de saves para poder
        enviarlos (umod_errors.log)."""
        pending = [e for e in RT.errors if e not in _LOG["written"]]
        for e in pending:
            _log_line(e)

    # ---------- 1b.2 Nivel de soporte por version -------------------
    def support_level():
        v = RENPY
        if v == (0, 0, 0):
            return ("desconocida", "#e7c58a",
                    "No se pudo leer la version: se confia solo en las sondas.")
        if v < (6, 99, 0):
            return ("no soportado", "#ff9b8a",
                    "Anterior a 6.99: las pantallas del mod pueden no compilar.")
        if v < (7, 0, 0):
            return ("parcial", "#e7c58a",
                    "6.99.x: sin label_callbacks ni Transform(fit); busqueda solo desde 6.99.12.")
        if v < (7, 4, 0):
            return ("bueno", "#9fe0b0",
                    "7.0-7.3: todo salvo miniaturas escaladas de imagenes compuestas.")
        if v < (8, 0, 0):
            return ("completo", "#7ee0a5", "7.4+ sobre Python 2.7.")
        return ("completo", "#7ee0a5", "8.x sobre Python 3.")

    # ---------- 1b.3 Capacidades ------------------------------------
    def _a(obj, name):
        return lambda: getattr(obj(), name, None) is not None

    def _c(obj, name):
        return lambda: callable(getattr(obj(), name, None))

    _R = lambda: renpy
    _CFG = lambda: renpy.config
    _SC = lambda: renpy.game.script
    _ST = lambda: renpy.store

    def _ast_classes():
        A = getattr(renpy, "ast", None)
        return A is not None and all(hasattr(A, n) for n in
                                     ("Label", "Menu", "If", "Jump", "Call", "Python", "Say"))

    def _pysrc_ok():
        A = getattr(renpy, "ast", None)
        st = getattr(renpy.game.script, "all_stmts", None) or []
        n = 0
        for node in st:
            n += 1
            if n > 50000:
                break
            if A is not None and isinstance(node, A.Python):
                src = getattr(getattr(node, "code", None), "source", None)
                return isinstance(src, string_types)
        return False

    _SAVEDIR_OK = [None]

    def _savedir_ok():
        if _SAVEDIR_OK[0] is None:
            p = _savedir_path("umod_writetest.tmp")
            ok = False
            try:
                f = open(p, "w")
                f.write("ok")
                f.close()
                os.remove(p)
                ok = True
            except Exception:
                ok = False
            _SAVEDIR_OK[0] = ok
        return _SAVEDIR_OK[0]

    def _rev_ok():
        return all(revertable_class(n) is not None
                   for n in ("RevertableList", "RevertableDict", "RevertableSet"))

    # Cada capacidad: id, nombre, modulos afectados,
    #   pri: [(api, sonda, P|I)]  -> todas deben pasar para OK
    #   alt: [(api, sonda, P|I)]  -> si pri falla y alguna pasa: ALTERNATIVA
    #   alt_txt, impacto si no hay nada
    CAPS = [
        {"id": "api", "name": "API de Ren'Py (renpy.exports)", "mods": "todos",
         "pri": [("renpy.show_screen", _c(_R, "show_screen"), "P"),
                 ("renpy.restart_interaction", _c(_R, "restart_interaction"), "P"),
                 ("renpy.notify", _c(_R, "notify"), "P")],
         "alt": [], "alt_txt": "",
         "impact": "ningun panel del mod puede mostrarse"},
        {"id": "key", "name": "Tecla global", "mods": "todos",
         "pri": [("config.underlay", _a(_CFG, "underlay"), "I"),
                 ("Keymap", lambda: keymap_class() is not None, "I")],
         "alt": [("config.overlay_screens", _a(_CFG, "overlay_screens"), "P")],
         "alt_txt": "tecla atendida por la overlay screen del mod",
         "impact": "no se puede abrir el mod con el teclado"},
        {"id": "overlay", "name": "Overlay screens", "mods": "1, 7",
         "pri": [("config.overlay_screens", _a(_CFG, "overlay_screens"), "P")],
         "alt": [], "alt_txt": "",
         "impact": "sin barra de estado del emulador"},
        {"id": "labels", "name": "Lista de labels", "mods": "1",
         "pri": [("renpy.get_all_labels", _c(_R, "get_all_labels"), "P"),
                 ("renpy.has_label", _c(_R, "has_label"), "P")],
         "alt": [], "alt_txt": "", "impact": "sin lista de labels"},
        {"id": "images", "name": "Imagenes declaradas", "mods": "1, 2",
         "pri": [("renpy.list_images", _c(_R, "list_images"), "P")],
         "alt": [], "alt_txt": "", "impact": "galeria solo con archivos sueltos"},
        {"id": "imgfile", "name": "Archivo de cada imagen", "mods": "2",
         "pri": [("renpy.get_registered_image", _c(_R, "get_registered_image"), "P")],
         "alt": [("renpy.display.image.images", lambda: isinstance(renpy.display.image.images, dict), "I")],
         "alt_txt": "tabla interna de imagenes del motor",
         "impact": "imagenes declaradas sin archivo ni dimensiones"},
        {"id": "files", "name": "Archivos del juego y .rpa", "mods": "1, 2",
         "pri": [("renpy.list_files", _c(_R, "list_files"), "P"),
                 ("renpy.file", _c(_R, "file"), "P")],
         "alt": [("renpy.loader.load", lambda: callable(renpy.loader.load), "I")],
         "alt_txt": "lectura con renpy.loader",
         "impact": "galeria sin dimensiones ni miniaturas fiables"},
        {"id": "input", "name": "Busqueda en paneles", "mods": "todos",
         "pri": [("ScreenVariableInputValue (6.99.12+)", _a(_ST, "ScreenVariableInputValue"), "P")],
         "alt": [], "alt_txt": "", "impact": "los paneles funcionan sin filtro de texto"},
        {"id": "fit", "name": "Miniaturas de imagenes compuestas", "mods": "2",
         "pri": [("Transform(fit=...) (7.4+)", lambda: at_least(7, 4), "P")],
         "alt": [], "alt_txt": "",
         "impact": "layeredimage/ATL se muestran sin escalar"},
        {"id": "ast", "name": "Lectura del guion (AST)", "mods": "3, 4, 6, 7",
         "pri": [("script.all_stmts", _a(_SC, "all_stmts"), "I"),
                 ("script.namemap", _a(_SC, "namemap"), "I"),
                 ("script.lookup", _c(_SC, "lookup"), "I"),
                 ("renpy.ast (Label, Menu, If, Jump, Call, Python, Say)", _ast_classes, "I")],
         "alt": [], "alt_txt": "",
         "impact": "sin analizador, grafo ni emulador; la reconstruccion solo usa lo observado"},
        {"id": "pysrc", "name": "Codigo fuente de bloques Python", "mods": "3, 7",
         "pri": [("PyCode.source", _pysrc_ok, "I")],
         "alt": [], "alt_txt": "",
         "impact": "no se extraen variables ni efectos de los bloques $ / python"},
        {"id": "digest", "name": "Huella del guion", "mods": "3, 4",
         "pri": [("script.digest", _a(_SC, "digest"), "I")],
         "alt": [("lista de archivos de guion", _c(_R, "list_files"), "P")],
         "alt_txt": "huella aproximada (n de statements + archivos)",
         "impact": "las caches no detectan actualizaciones del juego"},
        {"id": "labelcb", "name": "Gancho de labels", "mods": "5, 7",
         "pri": [("config.label_callbacks", lambda: isinstance(getattr(renpy.config, "label_callbacks", None), list), "P")],
         "alt": [("config.label_callback (encadenado)", lambda: hasattr(renpy.config, "label_callback"), "P")],
         "alt_txt": "encadenado al callback del juego",
         "impact": "sin tracker ni emulador"},
        {"id": "retstack", "name": "Pila de llamadas", "mods": "5",
         "pri": [("renpy.get_return_stack", _c(_R, "get_return_stack"), "P")],
         "alt": [], "alt_txt": "",
         "impact": "tras call/return pueden registrarse transiciones falsas"},
        {"id": "rollback", "name": "Deteccion de rollback", "mods": "5, 7",
         "pri": [("renpy.in_rollback", _c(_R, "in_rollback"), "P")],
         "alt": [], "alt_txt": "",
         "impact": "un rollback podria atribuirse a un label"},
        {"id": "nesting", "name": "Nivel de contexto", "mods": "5, 6, 7",
         "pri": [("renpy.context_nesting_level", _c(_R, "context_nesting_level"), "P")],
         "alt": [], "alt_txt": "",
         "impact": "saltar desde el menu del juego puede fallar"},
        {"id": "menuhook", "name": "Interceptar menus", "mods": "5, 7",
         "pri": [("renpy.exports.menu", lambda: callable(renpy.exports.menu), "I")],
         "alt": [], "alt_txt": "",
         "impact": "sin registro de elecciones ni respuestas automaticas"},
        {"id": "save", "name": "Copias de seguridad", "mods": "6, 7",
         "pri": [("renpy.save", _c(_R, "save"), "P"),
                 ("renpy.load", _c(_R, "load"), "P"),
                 ("renpy.can_load", _c(_R, "can_load"), "P")],
         "alt": [], "alt_txt": "",
         "impact": "sin copia no se aplica ni se emula nada (por seguridad)"},
        {"id": "jumpctx", "name": "Saltar fuera de un contexto", "mods": "6, 7",
         "pri": [("renpy.jump_out_of_context", _c(_R, "jump_out_of_context"), "P")],
         "alt": [], "alt_txt": "",
         "impact": "no se puede saltar desde el menu principal ni el del juego"},
        {"id": "revert", "name": "Contenedores con rollback", "mods": "6",
         "pri": [("RevertableList/Dict/Set", _rev_ok, "I")],
         "alt": [], "alt_txt": "",
         "impact": "listas y sets nuevos no participan del rollback"},
        {"id": "skip", "name": "Avance rapido", "mods": "7",
         "pri": [("config.skipping", lambda: hasattr(renpy.config, "skipping"), "I"),
                 ("preferences.skip_unseen", lambda: hasattr(renpy.game.preferences, "skip_unseen"), "P")],
         "alt": [], "alt_txt": "", "impact": "el emulador no puede avanzar solo"},
        {"id": "periodic", "name": "Vigilante periodico", "mods": "7",
         "pri": [("config.periodic_callbacks", lambda: isinstance(getattr(renpy.config, "periodic_callbacks", None), list), "P")],
         "alt": [("config.periodic_callback (encadenado)", lambda: hasattr(renpy.config, "periodic_callback"), "P")],
         "alt_txt": "encadenado al callback periodico del juego",
         "impact": "la emulacion no detecta atascos"},
        {"id": "callbacks", "name": "Callbacks de interaccion y carga", "mods": "2, 5, 7",
         "pri": [("config.interact_callbacks", lambda: isinstance(getattr(renpy.config, "interact_callbacks", None), list), "P"),
                 ("config.after_load_callbacks", lambda: isinstance(getattr(renpy.config, "after_load_callbacks", None), list), "P")],
         "alt": [], "alt_txt": "",
         "impact": "sin registro de imagenes vistas ni limpieza al cargar"},
        {"id": "quit", "name": "Guardado al salir", "mods": "5",
         "pri": [("config.quit_callbacks", lambda: isinstance(getattr(renpy.config, "quit_callbacks", None), list), "P")],
         "alt": [("guardado periodico (40 eventos / 60 s)", lambda: True, "P")],
         "alt_txt": "se pierde como mucho el ultimo minuto de grabacion",
         "impact": ""},
        {"id": "savedir", "name": "Carpeta de saves escribible", "mods": "todos",
         "pri": [("escritura en config.savedir", _savedir_ok, "P")],
         "alt": [], "alt_txt": "",
         "impact": "sin caches, grabaciones ni informes"},
    ]

    def _probe(fn):
        try:
            return bool(fn())
        except Exception:
            return False

    def compat_eval():
        out = []
        for cap in CAPS:
            pri = [(d, _probe(f), k) for d, f, k in cap["pri"]]
            alt = [(d, _probe(f), k) for d, f, k in cap["alt"]]
            if all(ok for _d, ok, _k in pri):
                status = "OK"
            elif any(ok for _d, ok, _k in alt):
                status = "ALTERNATIVA"
            else:
                status = "NO DISPONIBLE"
            out.append({"id": cap["id"], "name": cap["name"], "mods": cap["mods"],
                        "status": status, "pri": pri, "alt": alt,
                        "alt_txt": cap["alt_txt"], "impact": cap["impact"]})
        return out

    def compat_counts(res):
        c = {"OK": 0, "ALTERNATIVA": 0, "NO DISPONIBLE": 0}
        for r in res:
            c[r["status"]] += 1
        return c

    def module_flags():
        names = [("GALLERY", "2 Galeria"), ("SCRIPT", "3 Analizador"), ("GRAPH", "4 Grafo"),
                 ("TRACKER", "5 Tracker"), ("RECONSTRUCT", "6 Reconstruccion"),
                 ("EMULATOR", "7 Emulador"), ("ADAPTERS", "9 Adaptadores")]
        g = globals()
        return [(lbl, bool(g.get(flag, False))) for flag, lbl in names]

    # ---------- 1b.4 Autodiagnostico (seguro) -----------------------
    def _st(name, fn):
        t0 = time.time()
        try:
            status, detail = fn()
        except Exception as e:
            status, detail = "fallo", "%s: %s" % (type(e).__name__, e)
        return (status, name, to_text(detail), round((time.time() - t0) * 1000.0, 1))

    def _t_savedir():
        _SAVEDIR_OK[0] = None
        return ("ok", "lectura/escritura correcta") if _savedir_ok() else ("fallo", "no se puede escribir")

    def _t_ast():
        sc = renpy.game.script
        st = getattr(sc, "all_stmts", None) or []
        nm = getattr(sc, "namemap", None) or {}
        if not st:
            return ("fallo", "all_stmts vacio o inexistente")
        kinds = {}
        for n in st[:200000]:
            k = type(n).__name__
            kinds[k] = kinds.get(k, 0) + 1
        top = ", ".join("%s %d" % kv for kv in sorted(kinds.items(), key=lambda t: -t[1])[:6])
        return ("ok", "%d nodos, %d nombres. %s" % (len(st), len(nm), top))

    def _t_formats():
        A = renpy.ast
        st = getattr(renpy.game.script, "all_stmts", None) or []
        seen = {"Menu": None, "If": None, "Label": None}
        for n in st:
            if seen["Menu"] is None and isinstance(n, A.Menu):
                it = (getattr(n, "items", None) or [None])[0]
                seen["Menu"] = isinstance(it, tuple) and len(it) >= 3
            elif seen["If"] is None and isinstance(n, A.If):
                e = (getattr(n, "entries", None) or [None])[0]
                seen["If"] = isinstance(e, tuple) and len(e) >= 2
            elif seen["Label"] is None and isinstance(n, A.Label):
                seen["Label"] = hasattr(n, "block")
            if all(v is not None for v in seen.values()):
                break
        bad = [k for k, v in seen.items() if v is False]
        miss = [k for k, v in seen.items() if v is None]
        if bad:
            return ("fallo", "formato inesperado en: " + ", ".join(bad))
        if miss:
            return ("aviso", "no hay nodos para comprobar: " + ", ".join(miss))
        return ("ok", "Menu.items (caption, condicion, bloque), If.entries y Label.block como se esperaba")

    def _t_pysrc():
        return ("ok", "PyCode.source disponible") if _pysrc_ok() else ("aviso", "no se encontro fuente en los bloques Python")

    def _t_condition():
        if not SCRIPT:
            return ("omitido", "Fase 3 no instalada")
        cs = parse_condition("10 <= alice_points and not met_alice")
        txt = [cond_text(c) for c in cs]
        good = txt == ["alice_points >= 10", "NO (met_alice es cierto False)"]
        return ("ok" if good else "fallo", "; ".join(txt))

    def _t_snapshot():
        if not TRACKER:
            return ("omitido", "Fase 5 no instalada")
        t0 = time.time()
        s = tr_snapshot()
        ms = (time.time() - t0) * 1000.0
        return ("ok" if ms < 80 else "aviso", "%d variables en %.1f ms" % (len(s), ms))

    def _t_hooks():
        if not TRACKER:
            return ("omitido", "Fase 5 no instalada")
        lab = RT.tr_label_mode
        ok = lab.startswith("config.label_callback")
        return ("ok" if ok and RT.tr_menu_hooked else "aviso",
                "labels: %s; menus: %s" % (lab, "instalado" if RT.tr_menu_hooked else "no"))

    def _t_graph():
        if not GRAPH:
            return ("omitido", "Fase 4 no instalada")
        if not RT.g_ready:
            if not ng_load_cache():
                ng_build()
        if not RT.g_ready:
            return ("fallo", RT.g_msg)
        st = ng_stats()
        n = len(RT.g_nodes)
        return ("ok", "%d labels, %d aristas, %d calculadas, %d huerfanos" % (
            n, len(RT.g_edges), st.get("dyn", 0), n - len(RT.g_reach)))

    def _t_plan():
        if not (RECONSTRUCT and GRAPH and RT.g_ready):
            return ("omitido", "necesita Fases 4 y 6")
        cands = [lb for lb in RT.g_reach if lb != RT.g_origin]
        if not cands:
            return ("aviso", "no hay labels alcanzables desde el origen")
        cands.sort(key=lambda lb: -len(RT.g_nodes[lb]["in"]))
        tgt = cands[0]
        t0 = time.time()
        P = rc_plan(tgt, None, "guards", "actual")
        ms = (time.time() - t0) * 1000.0
        return ("ok", "plan para '%s' en %.0f ms: %d cambios, confianza %s (no se aplica)" % (
            tgt, ms, len(P["assigns"]), P["conf"]))

    SELFTESTS = [
        ("Carpeta de saves", _t_savedir),
        ("AST del guion", _t_ast),
        ("Formatos de nodos", _t_formats),
        ("Fuente de bloques Python", _t_pysrc),
        ("Analisis de condiciones", _t_condition),
        ("Snapshot del store", _t_snapshot),
        ("Ganchos de labels y menus", _t_hooks),
        ("Construccion del grafo", _t_graph),
        ("Plan de reconstruccion (simulado)", _t_plan),
    ]

    def compat_selftest():
        if not RT.ready:
            scan_all()
        RT.selftest = [_st(n, f) for n, f in SELFTESTS]
        renpy.restart_interaction()
        return RT.selftest

    # ---------- 1b.5 Vista y exportacion ----------------------------
    STATUS_COLOR = {"OK": "#7ee0a5", "ALTERNATIVA": "#e7c58a", "NO DISPONIBLE": "#ff9b8a",
                    "ok": "#7ee0a5", "aviso": "#e7c58a", "fallo": "#ff9b8a", "omitido": "#7f8ca1"}

    def compat_rows():
        rows = []
        lvl, col, why = support_level()
        rows.append(("h", "#8fe0ff", "Ren'Py %s  -  Python %d.%d  -  soporte: %s" % (
            RENPY_STR, sys.version_info[0], sys.version_info[1], lvl.upper())))
        rows.append(("t", col, why))
        mods = ", ".join("%s %s" % (l, "si" if on else "no") for l, on in module_flags())
        rows.append(("t", "#7f8ca1", "Modulos: " + mods))
        if KEY_MODE:
            rows.append(("t", "#7f8ca1", "Teclas: " + ", ".join(
                "%s=%s" % kv for kv in sorted(KEY_MODE.items()))))

        st = getattr(RT, "selftest", None)
        rows.append(("h", "#8fe0ff", "AUTODIAGNOSTICO"))
        if not st:
            rows.append(("t", "#7f8ca1", "Pulsa 'Autodiagnostico' para ejecutar pruebas funcionales seguras (no modifican tu partida)."))
        else:
            for status, name, detail, ms in st:
                rows.append(("t", STATUS_COLOR.get(status, "#dfe7f2"),
                             "%-8s %s  (%s ms)" % (status.upper(), name, ms)))
                rows.append(("i", "#9aa8bd", detail))

        res = compat_eval()
        c = compat_counts(res)
        rows.append(("h", "#8fe0ff", "CAPACIDADES  -  %d OK, %d con alternativa, %d no disponibles" % (
            c["OK"], c["ALTERNATIVA"], c["NO DISPONIBLE"])))
        for r in res:
            rows.append(("t", STATUS_COLOR[r["status"]], "%-14s %s   [fases %s]" % (
                r["status"], r["name"], r["mods"])))
            for d, ok, k in r["pri"]:
                if not ok:
                    rows.append(("i", "#9aa8bd", "falta (%s) %s" % (k, d)))
            if r["status"] == "ALTERNATIVA":
                rows.append(("i", "#e7c58a", "usa: " + r["alt_txt"]))
            elif r["status"] == "NO DISPONIBLE" and r["impact"]:
                rows.append(("i", "#ff9b8a", "impacto: " + r["impact"]))
        rows.append(("t", "#6f7a8d", "(P) API publica y documentada   -   (I) interna: puede cambiar entre versiones"))
        return rows

    def compat_export():
        res = compat_eval()
        lvl, _col, why = support_level()
        payload = {
            "format": 1,
            "umod": VERSION,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "renpy": RENPY_STR,
            "renpy_raw": RT.info.get("renpy_raw") if RT.info else to_text(getattr(renpy, "version_string", "")),
            "python": "%d.%d.%d" % tuple(sys.version_info[:3]),
            "api": RENPY_API,
            "support": {"level": lvl, "why": why},
            "game": {"name": to_text(getattr(renpy.config, "name", "")),
                     "version": to_text(getattr(renpy.config, "version", "")),
                     "fp": script_fp()},
            "modules": dict(module_flags()),
            "keys": KEY_MODE,
            "callbacks": CB_MODE,
            "capabilities": [{"id": r["id"], "status": r["status"],
                              "missing": [d for d, ok, _k in r["pri"] if not ok]} for r in res],
            "selftest": [list(x) for x in (getattr(RT, "selftest", None) or [])],
            "background": job_mode(),
            "timings_s": dict(TIMINGS, scan=RT.info.get("scan_seg") if RT.info else None,
                              snapshot_ms=round(getattr(RT, "tr_ms", 0.0) or 0.0, 1),
                              snapshot_max_ms=round(getattr(RT, "tr_ms_max", 0.0) or 0.0, 1),
                              snapshot_mode=getattr(RT, "tr_snap_mode", None)),
            "sizes": {"labels": len(RT.labels.get("all", [])) if RT.labels else 0,
                      "images": len(RT.images), "files": RT.files.get("total", 0) if RT.files else 0,
                      "vars": len(RT.vars)},
            "info": RT.info,
            "errors": RT.errors[-100:],
        }
        p = _write_json(_savedir_path("umod_compat.json"), payload, pretty=True)
        RT.last_export = p
        try:
            renpy.notify("Informe de compatibilidad: umod_compat.json")
        except Exception:
            pass
        return p


# ---------------------------------------------------------------------
# 2) REGISTRO - tecla global + overlay, SIN tocar screens.rpy
#    (todo a traves de la Compatibility Layer)
# ---------------------------------------------------------------------
init -999 python:
    umod.register_key("umod_toggle", umod.adv_keys(umod.TOGGLE_KEYS), umod.toggle_panel)
    umod.add_callback("interact_callbacks", None, umod.autostart_once, "nucleo.autostart")
    umod.add_overlay_screen("umod_overlay")
    umod.add_overlay_screen("umod_jobs_overlay")
    umod.add_callback("after_load_callbacks", None, umod._on_load, "nucleo.after_load")
    umod.add_callback("periodic_callbacks", "periodic_callback", umod.jobs_tick, "nucleo.trabajos")
    umod.add_callback("quit_callbacks", None, umod.errors_flush, "nucleo.errores")
    if persistent.umod_bg_mode is None:
        persistent.umod_bg_mode = ""


# ---------------------------------------------------------------------
# 3) BASELINE al final del init.
#    Lo que aparezca despues (default, asignaciones del script) se
#    marcara con "*" como estado de partida.
# ---------------------------------------------------------------------
init 999 python:
    try:
        umod.RT.baseline = umod.snapshot_names()
    except Exception:
        pass


# =====================================================================
# 4) INTERFAZ
#    Colores y tamanos propios: NO dependemos de gui.* porque en juegos
#    de Ren'Py 6 esas variables no existen.
# =====================================================================

# Progreso de los analisis en segundo plano (Fase 10). Por encima de los
# paneles del mod, pero sin capturar el raton ni el teclado.
screen umod_jobs_overlay():
    zorder 1300
    $ _umod_jobs = umod.guard(umod.jobs_active, []) if umod.guard(umod.adv_visible, False) else []
    if _umod_jobs:
        frame:
            background Solid("#0b0e14e6")
            xalign 1.0
            yalign 1.0
            xoffset -umod.S(12)
            yoffset -umod.S(12)
            padding (umod.S(12), umod.S(6))
            vbox:
                spacing umod.S(3)
                for _umod_j in _umod_jobs:
                    text umod.esc(umod.job_line(_umod_j)) size umod.S(13) color "#8fe0ff"
                    bar:
                        value _umod_j["p"]
                        range 1.0
                        xsize umod.S(360)
                        ysize umod.S(6)
                        left_bar Solid("#4aa8d8")
                        right_bar Solid("#1d2734")


screen umod_overlay():
    zorder 1000
    # Solo las teclas que no se pudieron registrar en config.underlay
    # (motores sin Keymap): la Compatibility Layer las deja aqui.
    for _umod_k, _umod_f in umod.OVERLAY_KEYS:
        key _umod_k action Function(_umod_f)


screen umod_main():

    modal True
    zorder 1100
    tag umod_panel

    default tab = "info"
    default q = ""
    default page = 0
    default sel = None

    key "K_ESCAPE" action Hide("umod_main")
    key "umod_toggle" action Hide("umod_main")

    $ islist = tab in umod.LIST_TABS
    $ items = umod.guard(umod.rows, [], tab, q) if islist else []
    $ shown = umod.page_slice(items, page) if islist else []
    $ npages = umod.page_count(items)
    $ qval = ScreenVariableInputValue("q", default=False) if umod.HAS_SVIV else None

    add Solid("#000000cc")

    frame:
        background Solid("#12141af2")
        xalign 0.5
        yalign 0.5
        xsize umod.S(1480)
        ysize umod.S(880)
        padding (umod.S(18), umod.S(14))

        vbox:
            spacing umod.S(10)

            # -------------------- Cabecera --------------------
            fixed:
                xfill True
                ysize umod.S(40)

                hbox:
                    xalign 0.0
                    yalign 0.5
                    spacing umod.S(16)
                    text "UNIVERSAL REN'PY MOD" size umod.S(23) color "#7fd4ff"
                    text umod.HEADER size umod.S(14) color "#78839a" yalign 0.5

                textbutton "Cerrar  (Esc)":
                    xalign 1.0
                    yalign 0.5
                    action Hide("umod_main")
                    text_size umod.S(15)
                    text_color "#ffd9d9"
                    background Solid("#43222a")
                    hover_background Solid("#6a3340")
                    padding (umod.S(14), umod.S(6))

            # -------------------- Pestanas --------------------
            hbox:
                spacing umod.S(4)
                box_wrap True
                for tid, tlabel in umod.TABS:
                    textbutton tlabel:
                        action [SetScreenVariable("tab", tid),
                                SetScreenVariable("page", 0),
                                SetScreenVariable("sel", None)]
                        text_size umod.S(16)
                        text_color ("#ffffff" if tab == tid else "#98a3b5")
                        background (Solid("#2b3446") if tab == tid else Solid("#191d26"))
                        hover_background Solid("#333e54")
                        padding (umod.S(14), umod.S(7))

            # -------------------- Barra de filtro --------------------
            fixed:
                xfill True
                ysize umod.S(36)

                if islist:
                    hbox:
                        yalign 0.5
                        spacing umod.S(10)

                        text "Filtro:" size umod.S(15) color "#98a3b5" yalign 0.5

                        if qval:
                            button:
                                action qval.Toggle()
                                background Solid("#0c0f14")
                                hover_background Solid("#161c26")
                                xsize umod.S(400)
                                ysize umod.S(32)
                                padding (umod.S(9), umod.S(5))
                                input:
                                    value qval
                                    length 48
                                    size umod.S(15)
                                    color "#e8eef7"
                        else:
                            text "(busqueda no disponible en este motor)":
                                size umod.S(13)
                                color "#5c6678"
                                yalign 0.5

                        textbutton "limpiar":
                            action [SetScreenVariable("q", ""),
                                    SetScreenVariable("page", 0)]
                            text_size umod.S(13)
                            background Solid("#232a36")
                            padding (umod.S(10), umod.S(6))

                        text umod.counter_line(items, page):
                            size umod.S(14)
                            color "#98a3b5"
                            yalign 0.5

                        textbutton "<":
                            action SetScreenVariable("page", max(0, page - 1))
                            text_size umod.S(15)
                            background Solid("#232a36")
                            padding (umod.S(15), umod.S(6))

                        textbutton ">":
                            action SetScreenVariable("page", min(npages - 1, page + 1))
                            text_size umod.S(15)
                            background Solid("#232a36")
                            padding (umod.S(15), umod.S(6))

            # -------------------- Contenido --------------------
            frame:
                background Solid("#0c0f14")
                xsize umod.S(1444)
                ysize umod.S(704)
                padding (umod.S(12), umod.S(10))

                # ---- Inspector ----
                if tab == "info":
                    viewport:
                        xsize umod.S(1418)
                        ysize umod.S(682)
                        scrollbars "vertical"
                        mousewheel True
                        draggable True
                        vbox:
                            spacing umod.S(4)
                            for irow in umod.guard(umod.info_rows, umod.ERR_PAIRS):
                                hbox:
                                    spacing umod.S(10)
                                    text umod.esc(irow[0]):
                                        size umod.S(15)
                                        color "#7f8ca1"
                                        xsize umod.S(300)
                                    text umod.esc(irow[1]):
                                        size umod.S(15)
                                        color "#dfe7f2"

                # ---- Compatibilidad (Fase 8) ----
                elif tab == "compat":
                    vbox:
                        spacing umod.S(8)
                        hbox:
                            spacing umod.S(8)
                            textbutton "Autodiagnostico":
                                action Function(umod.compat_selftest)
                                text_size umod.S(15)
                                background Solid("#1d3428")
                                hover_background Solid("#2b4d3a")
                                padding (umod.S(14), umod.S(7))
                            textbutton "Exportar informe de compatibilidad":
                                action Function(umod.compat_export)
                                text_size umod.S(15)
                                background Solid("#1d2734")
                                hover_background Solid("#2b3a4e")
                                padding (umod.S(14), umod.S(7))
                            text umod.esc(umod.export_line()) size umod.S(12) color "#7f8ca1" yalign 0.5
                        viewport:
                            xsize umod.S(1418)
                            ysize umod.S(628)
                            scrollbars "vertical"
                            mousewheel True
                            draggable True
                            vbox:
                                spacing umod.S(3)
                                for crow in umod.guard(umod.compat_rows, umod.ERR_ROWS3):
                                    if crow[0] == "h":
                                        null height umod.S(6)
                                    text umod.esc(crow[2]):
                                        size (umod.S(15) if crow[0] == "h" else umod.S(13))
                                        color crow[1]
                                        xoffset (umod.S(24) if crow[0] == "i" else 0)
                                        xsize umod.S(1380)

                # ---- Herramientas ----
                elif tab == "tools":
                    vbox:
                        spacing umod.S(9)

                        if umod.GALLERY:
                            hbox:
                                spacing umod.S(8)
                                textbutton "Abrir Galeria  (Alt+G)":
                                    action Function(umod.gallery_open)
                                    text_size umod.S(16)
                                    background Solid("#1d3428")
                                    hover_background Solid("#2b4d3a")
                                    padding (umod.S(16), umod.S(9))
                                textbutton ("Mostrando TODO" if umod.show_all() else "Solo desbloqueado"):
                                    action Function(umod.toggle_show_all)
                                    text_size umod.S(14)
                                    background Solid("#232a36")
                                    padding (umod.S(14), umod.S(9))
                                textbutton "Borrar registro de vistas":
                                    action Function(umod.clear_seen)
                                    text_size umod.S(14)
                                    background Solid("#232a36")
                                    padding (umod.S(14), umod.S(9))

                        if umod.SCRIPT:
                            textbutton "Abrir Analizador de guion  (Alt+S)":
                                action Function(umod.script_open)
                                text_size umod.S(16)
                                background Solid("#26243a")
                                hover_background Solid("#383455")
                                padding (umod.S(16), umod.S(9))

                        if umod.GRAPH:
                            textbutton "Abrir Navegador narrativo  (Alt+N)":
                                action Function(umod.graph_open)
                                text_size umod.S(16)
                                background Solid("#2e2a1c")
                                hover_background Solid("#4a4329")
                                padding (umod.S(16), umod.S(9))

                        if umod.TRACKER:
                            textbutton "Abrir State Tracker  (Alt+T)":
                                action Function(umod.tracker_open)
                                text_size umod.S(16)
                                background Solid("#1c2a2e")
                                hover_background Solid("#29434a")
                                padding (umod.S(16), umod.S(9))

                        if umod.RECONSTRUCT:
                            textbutton "Abrir Reconstruccion de estado  (Alt+R)":
                                action Function(umod.reconstruct_open)
                                text_size umod.S(16)
                                background Solid("#2a1c2e")
                                hover_background Solid("#43294a")
                                padding (umod.S(16), umod.S(9))

                        if umod.EMULATOR:
                            textbutton "Abrir Emulador de recorrido  (Alt+E)":
                                action Function(umod.emulator_open)
                                text_size umod.S(16)
                                background Solid("#2e231c")
                                hover_background Solid("#4a3829")
                                padding (umod.S(16), umod.S(9))

                        if umod.ADAPTERS:
                            textbutton "Abrir Adaptadores  (Alt+A)":
                                action Function(umod.adapters_open)
                                text_size umod.S(16)
                                background Solid("#1c2e26")
                                hover_background Solid("#294a3c")
                                padding (umod.S(16), umod.S(9))

                        textbutton ("Atajos avanzados (Alt+U, Alt+T...): SI" if persistent.umod_adv_keys else "Atajos avanzados (Alt+U, Alt+T...): NO   (la galeria siempre es F8)"):
                            action ToggleField(persistent, "umod_adv_keys")
                            text_size umod.S(14)
                            background Solid("#191d26")
                            hover_background Solid("#2b3a4e")
                            padding (umod.S(14), umod.S(7))
                        text "El cambio de atajos se aplica al reiniciar el juego." size umod.S(12) color "#7f8ca1"

                        hbox:
                            spacing umod.S(6)
                            text "Analisis pesados:" size umod.S(14) color "#98a3b5" yalign 0.5
                            for _bm, _bl in (("", "automatico"), ("tramos", "por tramos"), ("sincrono", "de una vez")):
                                textbutton _bl:
                                    action SetField(persistent, "umod_bg_mode", _bm)
                                    text_size umod.S(13)
                                    text_color ("#ffffff" if (persistent.umod_bg_mode or "") == _bm else "#98a3b5")
                                    background (Solid("#2b3446") if (persistent.umod_bg_mode or "") == _bm else Solid("#191d26"))
                                    padding (umod.S(10), umod.S(5))
                            text umod.esc("en uso: %s" % umod.job_mode()) size umod.S(12) color "#7f8ca1" yalign 0.5

                        textbutton "Re-escanear el juego":
                            action Function(umod.scan_all, True)
                            text_size umod.S(16)
                            background Solid("#1d2734")
                            hover_background Solid("#2b3a4e")
                            padding (umod.S(16), umod.S(9))

                        textbutton "Refrescar variables":
                            action Function(umod.refresh_vars)
                            text_size umod.S(16)
                            background Solid("#1d2734")
                            hover_background Solid("#2b3a4e")
                            padding (umod.S(16), umod.S(9))

                        textbutton "Exportar informe JSON":
                            action Function(umod.export_report)
                            text_size umod.S(16)
                            background Solid("#1d2734")
                            hover_background Solid("#2b3a4e")
                            padding (umod.S(16), umod.S(9))

                        null height umod.S(8)
                        text umod.cache_line() size umod.S(13) color "#7f8ca1"
                        text umod.export_line() size umod.S(13) color "#7f8ca1"
                        text umod.errors_line() size umod.S(13) color "#7f8ca1"
                        null height umod.S(6)

                        viewport:
                            xsize umod.S(1418)
                            ysize umod.S(380)
                            scrollbars "vertical"
                            mousewheel True
                            vbox:
                                for erow in umod.RT.errors[-80:]:
                                    text umod.esc(erow) size umod.S(12) color "#c98d8d"

                # ---- Listados ----
                else:
                    hbox:
                        spacing umod.S(12)

                        viewport:
                            xsize (umod.S(986) if tab == "labels" else umod.S(1418))
                            ysize umod.S(682)
                            scrollbars "vertical"
                            mousewheel True
                            draggable True
                            vbox:
                                spacing umod.S(1)
                                for it in shown:
                                    if tab == "labels":
                                        textbutton umod.esc(it):
                                            action SetScreenVariable("sel", it)
                                            text_size umod.S(14)
                                            text_color ("#8fe0ff" if sel == it else "#dfe7f2")
                                            background None
                                            hover_background Solid("#1b2431")
                                            padding (umod.S(6), umod.S(2))
                                            xfill True
                                    else:
                                        text umod.esc(it):
                                            size umod.S(14)
                                            color "#dfe7f2"

                        # Detalle de label: preview de la Fase 3
                        if tab == "labels":
                            frame:
                                background Solid("#141924")
                                xsize umod.S(420)
                                ysize umod.S(682)
                                padding (umod.S(12), umod.S(10))
                                vbox:
                                    spacing umod.S(6)
                                    if sel:
                                        text umod.esc(sel) size umod.S(17) color "#8fe0ff"
                                        null height umod.S(6)
                                        for drow in umod.guard(umod.label_detail_lines, umod.ERR_PAIRS, sel):
                                            text umod.esc("%s: %s" % (drow[0], drow[1])):
                                                size umod.S(13)
                                                color "#dfe7f2"
                                        null height umod.S(14)
                                        text "En las fases 3 y 4 este panel mostrara jumps, calls, menus, condiciones y variables asociadas al label.":
                                            size umod.S(12)
                                            color "#66707f"
                                    else:
                                        text "Selecciona un label para ver de que archivo y linea del script procede.":
                                            size umod.S(13)
                                            color "#66707f"


# ##################################################################### #
#   universal_mod_gallery.rpy
# ##################################################################### #

# =====================================================================
#  UNIVERSAL REN'PY MOD (UMOD)  -  FASE 2 / Gallery Engine
# ---------------------------------------------------------------------
#  Requiere universal_mod.rpy (Fase 1) en la misma carpeta.
#
#  Que hace esta fase:
#    - Inventario de recursos visuales de DOS fuentes:
#        a) imagenes declaradas  -> renpy.list_images()
#        b) archivos en disco/.rpa -> renpy.list_files()
#      y los deduplica resolviendo la imagen declarada a su archivo.
#    - Lee dimensiones leyendo SOLO la cabecera del archivo (PNG, JPG,
#      GIF, BMP, WEBP). Nunca descomprime la imagen entera.
#    - Clasifica automaticamente en CG / Fondos / Personajes /
#      Animaciones / Video / Interfaz / Otros, combinando senales de
#      ruta (peso alto), de nombre (peso bajo) y de dimensiones.
#    - Galeria con rejilla, thumbnails escalados, busqueda, filtros,
#      favoritos, visor a pantalla completa y reproduccion de video.
#    - Cachea el indice en la carpeta de saves: el segundo arranque
#      es instantaneo.
#
#  ABRIR:  ALT + G     (o desde Herramientas en el panel principal)
#
#  IMPORTANTE: la clasificacion es HEURISTICA. Acierta mucho en juegos
#  con carpetas ordenadas y falla en juegos con nombres opacos. Por eso
#  el visor permite reclasificar a mano, y esa correccion se guarda en
#  persistent: es la semilla del sistema de adaptadores de la Fase 9.
# =====================================================================


# ---------------------------------------------------------------------
# 0) Estado de runtime de la galeria (fuera del store, como el nucleo)
# ---------------------------------------------------------------------
init -1090 python:
    import sys as _umod_sys_g
    try:
        _umod_g = _umod_sys_g.modules["umod_rt"]
        _umod_g.gal_ready = False
        _umod_g.gal_scanning = False
        _umod_g.gal_assets = []      # lista de dicts (registros de recurso)
        _umod_g.gal_counts = {}      # categoria -> nº de recursos
        _umod_g.gal_msg = "Sin analizar"
        _umod_g.gal_seconds = 0.0
        _umod_g.gal_dims_read = 0
        _umod_g.gal_chars = {}       # personaje -> {name, n, p (retrato)}
        _umod_g.gal_char_src = {}    # personajes declarados (init)
        _umod_g.gal_index = {}       # clave de recurso -> recurso
        _umod_g.gal_view = {}
        _umod_g.gal_where = None     # imagen -> momento de la historia
        _umod_g.scenes = None        # escenas con dialogo (None = buscando)
        _umod_g.scn_cache = {}
        _umod_g.gal_by_base = {}
        _umod_g.rp = None            # repeticion de escena en curso
        del _umod_g
    except Exception:
        pass


# ---------------------------------------------------------------------
# 1) Persistent: vistos, favoritos y reclasificaciones manuales
# ---------------------------------------------------------------------
init -989 python:
    if persistent.umod_seen is None:
        persistent.umod_seen = set()
    if persistent.umod_favs is None:
        persistent.umod_favs = set()
    if persistent.umod_cat is None:
        persistent.umod_cat = {}
    if persistent.umod_show_all is None:
        persistent.umod_show_all = True


# ---------------------------------------------------------------------
# 2) Motor de galeria. Vive en el mismo namespace "umod" que el nucleo,
#    asi reutiliza S(), esc(), to_text(), log_error(), safe()...
# ---------------------------------------------------------------------
init -990 python in umod:

    import struct

    GALLERY = True                  # el nucleo consulta esta bandera

    GAL_KEYS      = ["K_F8"]        # la unica tecla visible para el usuario
    GAL_PAGE      = 40              # recursos por pagina
    GAL_COLS      = 5
    THUMB_W       = 268
    THUMB_H       = 150
    DIM_LIMIT     = 20000           # tope de cabeceras por escaneo (en segundo plano)
    JPEG_SCAN     = 65536           # bytes maximos a escanear en un JPEG

    # ---------- 2.1 Acceso a objetos del store por defecto ----------
    def _P():
        return renpy.store.persistent

    _im = renpy.display.im

    def _Transform(*a, **kw):
        return renpy.store.Transform(*a, **kw)

    def screen_size():
        try:
            return (int(renpy.config.screen_width), int(renpy.config.screen_height))
        except Exception:
            return (1920, 1080)

    # ---------- 2.2 Lectura de dimensiones por cabecera -------------
    # open_game_file (Compatibility Layer) funciona igual para archivos
    # sueltos y para archivos dentro de un .rpa.
    def _head(path, n):
        f = None
        try:
            f = open_game_file(path)
            return bytearray(f.read(n))
        except Exception:
            return None
        finally:
            if f is not None:
                try:
                    f.close()
                except Exception:
                    pass

    def _png_size(b):
        if len(b) >= 24 and b[:8] == bytearray(b"\x89PNG\r\n\x1a\n"):
            try:
                return struct.unpack(">II", bytes(b[16:24]))
            except Exception:
                return None
        return None

    def _gif_size(b):
        if len(b) >= 10 and b[:3] == bytearray(b"GIF"):
            try:
                return struct.unpack("<HH", bytes(b[6:10]))
            except Exception:
                return None
        return None

    def _bmp_size(b):
        if len(b) >= 26 and b[:2] == bytearray(b"BM"):
            try:
                w, h = struct.unpack("<ii", bytes(b[18:26]))
                return (abs(w), abs(h))
            except Exception:
                return None
        return None

    def _webp_size(b):
        if len(b) < 30:
            return None
        if b[:4] != bytearray(b"RIFF") or b[8:12] != bytearray(b"WEBP"):
            return None
        fmt = bytes(b[12:16])
        try:
            if fmt == b"VP8X":
                w = (b[24] | (b[25] << 8) | (b[26] << 16)) + 1
                h = (b[27] | (b[28] << 8) | (b[29] << 16)) + 1
                return (w, h)
            if fmt == b"VP8L":
                bits = b[21] | (b[22] << 8) | (b[23] << 16) | (b[24] << 24)
                return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
            if fmt == b"VP8 ":
                i = bytes(b).find(b"\x9d\x01\x2a")
                if i > 0 and len(b) >= i + 7:
                    w = (b[i + 3] | (b[i + 4] << 8)) & 0x3FFF
                    h = (b[i + 5] | (b[i + 6] << 8)) & 0x3FFF
                    return (w, h)
        except Exception:
            return None
        return None

    _JPEG_SOF = (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)

    def _jpeg_size(path):
        d = _head(path, JPEG_SCAN)
        if not d or len(d) < 4 or d[0] != 0xFF or d[1] != 0xD8:
            return None
        i, n = 2, len(d)
        while i + 9 < n:
            if d[i] != 0xFF:
                i += 1
                continue
            m = d[i + 1]
            if m == 0xFF:
                i += 1
                continue
            if m == 0x01 or (0xD0 <= m <= 0xD9):
                i += 2
                continue
            seglen = (d[i + 2] << 8) | d[i + 3]
            if m in _JPEG_SOF:
                return (((d[i + 7] << 8) | d[i + 8]),
                        ((d[i + 5] << 8) | d[i + 6]))
            if seglen <= 0:
                break
            i += 2 + seglen
        return None

    def image_dims(path):
        """Devuelve (w, h) o None. Solo lee cabecera: es barato."""
        low = to_text(path).lower()
        try:
            if low.endswith(".jpg") or low.endswith(".jpeg"):
                return _jpeg_size(path)
            b = _head(path, 64)
            if not b:
                return None
            for fn in (_png_size, _webp_size, _gif_size, _bmp_size):
                r = fn(b)
                if r and r[0] > 0 and r[1] > 0:
                    return r
        except Exception as e:
            log_error("image_dims", e)
        return None

    # ---------- 2.3 Clasificacion heuristica ------------------------
    CAT_ORDER = ["cg", "sprite", "bg", "anim", "video", "ui", "other"]
    CAT_LABEL = {
        "cg":     "CG / Escenas",
        "sprite": "Personajes",
        "bg":     "Fondos",
        "anim":   "Animaciones",
        "video":  "Video",
        "ui":     "Interfaz",
        "other":  "Otros",
    }

    CAT_TOKENS = {
        "video":  set(["movie", "movies", "video", "videos", "cutscene",
                       "cutscenes", "webm", "mp4"]),
        "ui":     set(["gui", "ui", "interface", "button", "buttons", "icon",
                       "icons", "menu", "menus", "hud", "overlay", "overlays",
                       "frame", "frames", "logo", "logos", "cursor", "cursors",
                       "bar", "bars", "font", "fonts", "textbox", "nvl",
                       "window", "notify", "slider", "check", "scrollbar",
                       "phone", "ui2", "hoverbutton", "idle", "hover"]),
        "cg":     set(["cg", "cgs", "ev", "evs", "event", "events", "evt",
                       "scene", "scenes", "gallery", "hcg", "hscene", "hs",
                       "special", "illustration", "illustrations", "art",
                       "art_cg", "still", "stills", "sex", "lewd"]),
        "bg":     set(["bg", "bgs", "background", "backgrounds", "location",
                       "locations", "room", "rooms", "place", "places", "env",
                       "environment", "environments", "map", "maps", "street",
                       "outside", "inside"]),
        "sprite": set(["sprite", "sprites", "char", "chars", "character",
                       "characters", "people", "girl", "girls", "boy", "boys",
                       "body", "bodies", "face", "faces", "expression",
                       "expressions", "pose", "poses", "portrait", "portraits",
                       "outfit", "outfits", "clothes", "hair", "eyes", "mouth",
                       "brow", "brows", "arms", "legs"]),
        "anim":   set(["anim", "anims", "animation", "animations", "fx",
                       "effect", "effects", "particle", "particles", "sprite_sheet"]),
    }

    # Prioridad al empatar puntuaciones
    CAT_PRIORITY = ["video", "ui", "cg", "sprite", "bg", "anim"]

    _SPLIT = re.compile(r"[\\/._\-\s]+")

    def _split_path(path):
        p = to_text(path).replace("\\", "/")
        parts = [x for x in p.split("/") if x]
        if not parts:
            return (set(), set())
        dir_tokens = set()
        for seg in parts[:-1]:
            for t in _SPLIT.split(seg.lower()):
                if t:
                    dir_tokens.add(t)
        name_tokens = set(t for t in _SPLIT.split(parts[-1].lower()) if t)
        return (dir_tokens, name_tokens)

    def classify(path, name, w, h, attr_count=0):
        """Devuelve (categoria, confianza 0..1, motivo)."""
        low = to_text(path or name).lower()

        # 1) Extension de video: senal absoluta
        if low.endswith(EXT_VID):
            return ("video", 1.0, "extension de video")

        dir_t, name_t = _split_path(path or name)
        scores = {}
        for cat, toks in iteritems(CAT_TOKENS):
            s = 3 * len(dir_t & toks) + 1 * len(name_t & toks)
            if s:
                scores[cat] = s

        best, best_score = None, 0
        for cat in CAT_PRIORITY:
            s = scores.get(cat, 0)
            if s > best_score:
                best, best_score = cat, s

        if best and best_score >= 3:
            return (best, min(1.0, 0.5 + 0.1 * best_score), "ruta")

        # 2) Sin senal fuerte de ruta: usamos dimensiones
        sw, sh = screen_size()
        if w and h and sw and sh:
            ratio = float(w) / float(h)
            sratio = float(sw) / float(sh)
            if max(w, h) < 320:
                return ("ui", 0.55, "tamano pequeno")
            if w >= 0.7 * sw and abs(ratio - sratio) < 0.10:
                # ocupa la pantalla: CG o fondo. Sin mas datos, CG.
                return (best or "cg", 0.5, "resolucion de pantalla completa")
            if h >= 0.7 * sh and ratio < 0.8:
                return ("sprite", 0.6, "vertical y alto")

        # 3) Muchas variantes del mismo tag = set de sprite
        if attr_count >= 6:
            return ("sprite", 0.45, "muchas variantes del tag")

        if best:
            return (best, 0.35, "ruta debil")
        return ("other", 0.2, "sin senales")

    # ---------- 2.4 Resolucion imagen declarada -> archivo ----------
    def resolve_image_file(name):
        d = None
        try:
            g = getattr(renpy, "get_registered_image", None)
            if g:
                d = g(name)
        except Exception:
            d = None
        if d is None:
            try:
                d = renpy.display.image.images.get(tuple(name.split()), None)
            except Exception:
                d = None
        # filename/name: imagenes; _play/play: Movie(play="...") (videos)
        for attr in ("filename", "name", "_play", "play"):
            try:
                fn = getattr(d, attr, None)
                if isinstance(fn, (list, tuple)) and fn:
                    fn = fn[0]
                if isinstance(fn, string_types) and "." in fn:
                    return fn
            except Exception:
                pass
        # ImageReference y compuestos: no resolvemos, se usara el nombre
        return None

    # ---------- 2.4b Personajes -------------------------------------
    #  Pistas, de mas a menos fiable:
    #   1. Character("Alice", image="alice") declarados por el juego
    #   2. el adaptador del juego (seccion "characters")
    #   3. etiquetas de sprite con muchas variantes (alice happy, alice sad...)
    #   4. palabras del nombre de archivo y de sus carpetas
    #      (cg/alice_beach_02.png, images/alice/...)
    _WORD = re.compile(r"[^\W\d_]+", re.U)
    CHAR_SKIP = set(["you", "me", "narrator", "narrador", "narradora", "unknown", "voice",
                     "voz", "thought", "thoughts", "pensamiento", "system", "sistema",
                     "nvl", "centered", "extend", "adv", "tv", "radio", "phone",
                     "telefono", "note", "nota", "side", "all", "everyone", "todos"])
    CHAR_CATS = ("cg", "sprite", "anim", "video", "other")   # sin fondos ni interfaz

    def _words(s):
        try:
            return [w.lower() for w in _WORD.findall(to_text(s))]
        except Exception:
            return []

    def _strip_tags(s):
        return re.sub(r"\{[^}]*\}", "", to_text(s)).strip()

    # rc10: por que a veces NO aparecian personajes (diagnostico):
    #   1. Solo se leian los personajes del store principal, al final del
    #      init, y solo si la clase se llamaba "...Character...": se perdian
    #      los de 'default' (se crean al empezar la partida), los de
    #      espacios con nombre ('define chars.alice = Character(...)') y las
    #      clases propias del juego (class Person(ADVCharacter)).
    #   2. Los que tienen nombre variable ("[mom_name]") se descartaban.
    #   3. Los que hablan con nombre escrito ('"Alice" "Hola"') o cuya
    #      variable no se encuentra no contaban.
    #   4. Una imagen solo se asignaba si su NOMBRE contenia el del personaje
    #      (cg_alice_03): con nombres tipo ep2_045.webp no habia forma.
    #      Ahora tambien cuenta QUIEN HABLA mientras la imagen esta en
    #      pantalla, y las abreviaturas (jess_ -> Jessica).
    #   5. La fila de filtros solo ensenaba los personajes que cabian en
    #      una linea: el resto estaba, pero no se veia. Ahora hay "+N mas".
    PRO_VARS = set(["mc", "pc", "p", "player", "me", "you", "hero", "i", "y", "m", "protagonist", "prota"])
    SPEAKER_MIN = 3          # lineas para considerar personaje a quien habla

    def _store_items():
        """(variable, valor) de todos los stores: 'store' y los espacios
        con nombre ('store.chars' -> 'chars.alice')."""
        out = []
        dicts = None
        try:
            dicts = getattr(renpy.python, "store_dicts", None)
        except Exception:
            dicts = None
        if dicts:
            for sname, d in list(dicts.items()):
                try:
                    if not isinstance(sname, string_types):
                        continue
                    if sname == "store":
                        pre = ""
                    elif sname.startswith("store.") and not sname.startswith("store._") \
                            and not sname.startswith("store.umod") and not sname.startswith("store.renpy"):
                        pre = sname[6:] + "."
                    else:
                        continue
                    for var, v in list(d.items()):
                        out.append((pre + var if isinstance(var, string_types) else var, v))
                except Exception:
                    continue
            return out
        try:
            return list(vars(renpy.store).items())
        except Exception:
            return []

    def _is_character(v):
        try:
            adv = getattr(renpy.store, "ADVCharacter", None)
            if adv is not None and isinstance(adv, type) and isinstance(v, adv):
                return True
        except Exception:
            pass
        try:
            if "Character" in type(v).__name__:
                return True
            # clases propias con la forma de un personaje de Ren'Py
            # (Persistent y similares devuelven None para cualquier atributo)
            return isinstance(getattr(v, "who_args", None), dict) and \
                isinstance(getattr(v, "what_args", None), dict) and hasattr(v, "name")
        except Exception:
            return False

    _BRACKET = re.compile(r"\[([A-Za-z_][\w.]*)\]")

    # rc11: el protagonista con nombre calculado salia como
    # "persistent.player_name": el juego lo declara con
    # Character("persistent.player_name", dynamic=True) (el nombre es una
    # expresion que Ren'Py evalua en cada linea) o habla con una variable de
    # texto ('persistent.player_name "Hola"'). Ahora se evalua la expresion
    # (solo nombres simples, sin llamar a nada) y, si aun no tiene valor, se
    # llama "Protagonista". Los personajes sin nombre (narrador, textos en
    # mitad de la pantalla) no son personajes.
    _PRO_RE = re.compile(r"player|protag|hero|jugador|your|(^|[._])(mc|pc)($|[._])")
    _NAME_EXPR = re.compile(r"^[A-Za-z_][\w.]*$")

    def _eval_name(expr):
        """Valor actual de una expresion simple (persistent.player_name)."""
        expr = to_text(expr or "").strip()
        if not _NAME_EXPR.match(expr):
            return None
        try:
            v = renpy.store
            for part in expr.split("."):
                v = getattr(v, part)
            return v
        except Exception:
            return None

    def _looks_pro(*texts):
        t = " ".join(to_text(x or "") for x in texts).lower()
        return bool(_PRO_RE.search(t))

    def _char_display_name(v, var):
        """(nombre visible o None si no es un personaje, dinamico, protagonista)."""
        raw = getattr(v, "name", None)
        leaf = to_text(var).split(".")[-1]
        lleaf = leaf.lower()
        if raw is None or (isinstance(raw, string_types) and not raw.strip()):
            return None, False, False                  # narrador, texto centrado...
        if getattr(v, "dynamic", False):
            expr = to_text(raw) if isinstance(raw, string_types) else ""
            pro = lleaf in PRO_VARS or _looks_pro(expr, leaf)
            val = _eval_name(expr) if expr else None
            nm = _strip_tags(val) if isinstance(val, string_types) else ""
            if not _words(nm):
                nm = "Protagonista" if pro else _pretty(leaf)
            return nm, True, pro
        if not isinstance(raw, string_types):
            return None, False, False
        nm = to_text(raw)
        if "[" in nm:
            exprs = _BRACKET.findall(nm)
            pro = lleaf in PRO_VARS or _looks_pro(" ".join(exprs), leaf)

            def sub(m):
                val = _eval_name(m.group(1))
                return to_text(val) if isinstance(val, string_types) else ""
            nm2 = _strip_tags(_BRACKET.sub(sub, nm))
            if not _words(nm2):
                nm2 = "Protagonista" if pro else _pretty(leaf)
            return nm2, True, pro
        return _strip_tags(nm), False, lleaf in PRO_VARS

    def collect_char_sources(late=False):
        """Personajes declarados con Character(). Se lee al final del init
        y otra vez al abrir la galeria (para los creados con 'default' y
        los nombres que dependen de variables). Solo en el hilo principal.
        Devuelve True si ha cambiado algo."""
        old = getattr(RT, "gal_char_src", None) or {}
        out = {}
        for cid, c in old.items():
            out[cid] = dict(c)
            for k in ("keys", "tags", "vars"):
                out[cid][k] = list(c.get(k, ()))
        skip = set(getattr(RT, "gal_char_skip", None) or ())
        for var, v in _store_items():
            try:
                if not isinstance(var, string_types) or var.startswith("_") or "._" in var:
                    continue
                if not _is_character(v):
                    continue
                leaf = var.split(".")[-1].lower()
                disp, dyn, pro = _char_display_name(v, var)
                ws = _words(disp) if disp else []
                if not ws or leaf in ("narrator", "centered", "extend", "nvl", "adv", "vcentered") or \
                        "".join(ws) in CHAR_SKIP or ws[0] in CHAR_SKIP:
                    skip.add(var)                     # habla, pero no es un personaje
                    continue
                cid = ("v_" + leaf) if dyn else "".join(ws)
                if pro:
                    # un solo protagonista aunque el juego tenga varias variables
                    for ocid, oc in out.items():
                        if oc.get("pro") and ocid != cid and ocid.startswith("v_"):
                            cid = ocid
                            break
                e = out.setdefault(cid, {"name": disp, "keys": [], "tags": [], "vars": [], "pro": pro})
                if dyn:
                    e["name"] = disp
                    e["expr"] = to_text(getattr(v, "name", "")) if getattr(v, "dynamic", False) else ""
                e["pro"] = bool(e.get("pro") or pro)
                for k in ([] if dyn else ["".join(ws), ws[0]]) + ([] if pro else [leaf]):
                    if len(k) >= 3 and k not in CHAR_SKIP and k not in e["keys"]:
                        e["keys"].append(k)
                for t in (getattr(v, "image_tag", None), var):
                    if isinstance(t, string_types) and t and t not in e["tags"]:
                        e["tags"].append(t)
                if var not in e["vars"]:
                    e["vars"].append(var)
            except Exception:
                continue
        changed = sorted((k, tuple(v["vars"]), v["name"]) for k, v in out.items()) != \
                  sorted((k, tuple(v.get("vars", ())), v["name"]) for k, v in old.items())
        RT.gal_char_src = out
        RT.gal_char_skip = skip
        _VAR2CID.clear()
        return changed

    _VAR2CID = {}

    def var2cid():
        """{variable o etiqueta: id de personaje}."""
        if not _VAR2CID:
            for cid, c in (getattr(RT, "gal_char_src", None) or {}).items():
                for t in c.get("tags", ()):
                    _VAR2CID.setdefault(t, cid)
                for t in c.get("vars", ()):
                    _VAR2CID[t] = cid
            # 'chars.jess' tambien responde a 'jess' (si no hay otra)
            for cid, c in (getattr(RT, "gal_char_src", None) or {}).items():
                for t in c.get("vars", ()):
                    if "." in t:
                        _VAR2CID.setdefault(t.split(".")[-1], cid)
        return _VAR2CID

    _QUOTED = re.compile(r"""^\s*[urUR]?["'](.+)["']\s*$""")

    def speaker_cid(who):
        """Personaje de un 'who' del guion: variable conocida, nombre
        escrito entre comillas, o la propia variable como ultimo recurso."""
        if not who:
            return None
        who = to_text(who)
        m = var2cid()
        if who in m:
            return m[who]
        if who in (getattr(RT, "gal_char_skip", None) or ()):
            return None
        q = _QUOTED.match(who)
        if q:
            nm = _strip_tags(q.group(1))
            ws = _words(nm)
            if not ws or ws[0] in CHAR_SKIP or "[" in nm:
                return None
            return "".join(ws)
        leaf = who.split(".")[-1].lower()
        if leaf in CHAR_SKIP or leaf in ("narrator", "centered", "extend", "nvl", "adv") or not _WORD.search(leaf):
            return None
        return "v_" + leaf

    def speaker_name(who):
        who = to_text(who)
        q = _QUOTED.match(who)
        if q:
            return _strip_tags(q.group(1))
        if _looks_pro(who):
            return "Protagonista"
        return _pretty(who.split(".")[-1])

    def add_speakers(spk):
        """Quien habla en el guion (con al menos SPEAKER_MIN lineas) es un
        personaje aunque no tenga imagenes ni se haya podido leer."""
        src = getattr(RT, "gal_char_src", None) or {}
        added = False
        for who, n in sorted(spk.items(), key=lambda kv: -kv[1]):
            if n < SPEAKER_MIN:
                continue
            cid = speaker_cid(who)
            if not cid:
                continue
            e = src.get(cid)
            quoted = bool(_QUOTED.match(to_text(who)))
            pro = (not quoted) and (_looks_pro(who) or to_text(who).split(".")[-1].lower() in PRO_VARS)
            if e is None and pro:
                # 'persistent.player_name "..."': es el protagonista que ya conocemos
                for ocid, oc in src.items():
                    if oc.get("pro"):
                        e, cid = oc, ocid
                        break
            if e is None:
                nm = speaker_name(who)
                ws = _words(nm)
                if not ws:
                    continue
                e = src[cid] = {"name": nm, "keys": [], "tags": [], "vars": [], "pro": pro}
                if not pro:
                    for k in ("".join(ws), ws[0]):
                        if len(k) >= 3 and k not in CHAR_SKIP and k not in e["keys"]:
                            e["keys"].append(k)
                if not quoted:
                    e["expr"] = to_text(who)       # se intentara leer su valor (hilo principal)
                added = True
            if not _QUOTED.match(to_text(who)) and who not in e["vars"]:
                e["vars"].append(who)
                added = True
            e["lines"] = max(e.get("lines", 0), n)
        RT.gal_char_src = src
        if added:
            _VAR2CID.clear()
        return added

    def _char_sources(assets):
        src = {}
        for cid, c in (getattr(RT, "gal_char_src", None) or {}).items():
            src[cid] = {"name": c["name"], "keys": list(c["keys"]), "tags": list(c["tags"]),
                        "pro": c.get("pro", False)}
        # adaptador: puede anadir personajes o palabras clave
        try:
            if ADAPTERS:
                for aid, c in ((AD().get("characters") or {}).items()):
                    name = _strip_tags(c.get("name") or aid)
                    ws = _words(name)
                    cid = "".join(ws) or aid.lower()
                    e = src.setdefault(cid, {"name": name, "keys": [], "tags": []})
                    for k in [cid] + ws[:1] + [_strip_tags(x).lower() for x in (c.get("match") or [])]:
                        if len(k) >= 3 and k not in e["keys"]:
                            e["keys"].append(k)
                    for t in [aid] + list(c.get("tags") or []):
                        if t not in e["tags"]:
                            e["tags"].append(t)
        except Exception as e:
            log_error("chars.adapter", e)
        # sprites con muchas variantes y sin Character
        known = set()
        for c in src.values():
            known.update(c["keys"])
            known.update(t.lower() for t in c["tags"])
        per_tag = {}
        for a in assets:
            if a.get("s") == "declarada" and a.get("c") == "sprite":
                per_tag[a["t"]] = per_tag.get(a["t"], 0) + 1
        for t, n in per_tag.items():
            tl = to_text(t).lower()
            if n < 4 or tl in known or tl in CHAR_SKIP or len(tl) < 2:
                continue
            cid = "".join(_words(t)) or tl
            if cid in src:
                continue
            src[cid] = {"name": to_text(t).replace("_", " ").title(),
                        "keys": [tl] if len(tl) >= 3 else [], "tags": [t]}
        return src

    def _frequent_speakers():
        """Quien habla en casi todas las escenas (normalmente el
        protagonista): no sirve para decir 'esta imagen es de X'."""
        sc = getattr(RT, "scenes", None) or []
        if len(sc) < 8:
            return set()
        cnt = {}
        for e in sc:
            for w in set(e.get("wv") or ()):
                cid = speaker_cid(w)
                if cid:
                    cnt[cid] = cnt.get(cid, 0) + 1
        return set(c for c, n in cnt.items() if n > 0.6 * len(sc))

    def gal_assign_chars(assets):
        """Marca cada recurso con sus personajes (a["ch"]) y elige un retrato
        por personaje. Se ejecuta en segundo plano tras clasificar."""
        src = _char_sources(assets)
        keymap, tagmap = {}, {}
        for cid, c in src.items():
            for k in c["keys"]:
                keymap.setdefault(k, []).append(cid)
            for t in c["tags"]:
                tagmap.setdefault(t, []).append(cid)
        longkeys = [k for k in keymap if len(k) >= 4]
        W = getattr(RT, "gal_where", None) or {}
        CO = W.get("co") or {}
        heavy = _frequent_speakers()
        mine = {}
        for a in assets:
            a.pop("ch", None)
            if a.get("c") not in CHAR_CATS:
                continue
            found = set(tagmap.get(a.get("t"), ()))
            for w in _words(a.get("f", "")) + _words(a.get("d", "")):
                hit = keymap.get(w)
                if hit:
                    found.update(hit)
                elif len(w) >= 4:
                    # abreviaturas: jess_ -> jessica; plurales: sarahs -> sarah
                    for k in longkeys:
                        if k.startswith(w) or (w.startswith(k) and len(w) - len(k) <= 1):
                            found.update(keymap[k])
            # quien habla mientras la imagen esta en pantalla
            if a.get("c") in ("cg", "anim", "video", "other"):
                co = None
                if a.get("d"):
                    co = CO.get(a["d"])
                if not co and a.get("f"):
                    co = CO.get(_base_noext(a["f"]))
                if co:
                    cand = []
                    for who, n in co.items():
                        cid = speaker_cid(who)
                        if not cid or cid not in src or src[cid].get("pro") or cid in heavy:
                            continue
                        cand.append((n, cid))
                    tot = sum(n for n, _c in cand)
                    for n, cid in sorted(cand, reverse=True)[:2]:
                        if n >= 2 and n >= 0.3 * tot:
                            found.add(cid)
            if found:
                a["ch"] = sorted(found)
                for cid in found:
                    mine.setdefault(cid, []).append(a)
        chars = {}
        for cid, lst in mine.items():
            tags = set(src[cid]["tags"])

            def score(a):
                sp = a.get("c") == "sprite"
                tall = a.get("w") and a.get("h") and a["h"] >= a["w"]
                return (0 if sp else 1, 0 if a.get("t") in tags else 1, 0 if tall else 1,
                        len(_words(a.get("d") or a.get("n", ""))), a.get("n", ""))
            best = min(lst, key=score)
            chars[cid] = {"name": src[cid]["name"], "n": len(lst), "p": best["k"]}
        RT.gal_chars = chars
        return chars

    def gal_build_index():
        RT.gal_index = dict((a["k"], a) for a in RT.gal_assets)
        bb = {}
        for a in RT.gal_assets:
            if a.get("f"):
                bb.setdefault(_base_noext(a["f"]), a)
        RT.gal_by_base = bb
        RT.gal_view = {}
        RT.scn_cache = {}

    # ---------- 2.4c Momento de la historia de cada imagen ----------
    #  Un recorrido del guion (en segundo plano) apunta, para cada imagen,
    #  en que label y sentencia aparece y DONDE EMPIEZA ESA ESCENA (el ultimo
    #  'scene' anterior). "Jugar desde aqui" reconstruye el estado de ese
    #  label (Fase 6) y salta al comienzo de la escena.
    _QSTR = re.compile(r"[\"']([^\"'\n]{1,200})[\"']")
    PLAY_CATS = ("cg", "anim", "video", "other")
    MEDIA_EXT = EXT_IMG + EXT_VID

    def _base_noext(path):
        b = to_text(path).replace("\\", "/").split("/")[-1].lower()
        return b.rsplit(".", 1)[0] if "." in b else b

    def _label_body(lab):
        blk = getattr(lab, "block", None)
        if blk:
            return blk
        body = []
        n = getattr(lab, "next", None)                # sintaxis antigua
        while n is not None and len(body) < 5000 and not _isa(n, C_Label):
            body.append(n)
            n = getattr(n, "next", None)
        return body

    def _node_children(n):
        out = []
        try:
            if _isa(n, C_If):
                for entry in (getattr(n, "entries", None) or []):
                    out.append(entry[1])
            elif _isa(n, C_Menu):
                for it in (getattr(n, "items", None) or []):
                    if len(it) > 2 and it[2]:
                        out.append(it[2])
            else:
                blk = getattr(n, "block", None)
                if isinstance(blk, list):
                    out.append(blk)
        except Exception:
            pass
        return out

    def _strings_of(node):
        txt = ""
        if _isa(node, C_Python):
            txt = _py_source(node)
        elif _isa(node, C_User):
            txt = to_text(getattr(node, "line", "") or "")
        elif _isa(node, C_Scene) or _isa(node, C_Show):
            spec = getattr(node, "imspec", None) or ()
            if len(spec) > 1 and spec[1]:
                txt = to_text(spec[1])                # show expression "x.png"
        return _QSTR.findall(txt) if txt else []

    def gal_where_gen():
        RT.gal_where = None
        try:
            ok = bool(SCRIPT) and sa_available()
        except Exception:
            ok = False
        if not ok:
            RT.gal_where = {"names": {}, "files": {}}
            return
        cached = _disk_load("umod_where.json", 3)
        if cached is not None:
            W = {}
            for part in ("names", "files"):
                W[part] = dict((k, [tuple(_tup(x) for x in r) for r in v])
                               for k, v in (cached.get(part) or {}).items())
            W["spk"] = cached.get("spk") or {}
            W["co"] = cached.get("co") or {}
            RT.gal_where = W
            chars_ensure()
            return
        names, files = {}, {}
        spk, co = {}, {}           # quien habla (lineas) y quien habla con cada imagen en pantalla
        CO_WIN = 10                # lineas de dialogo que se cuentan tras mostrar una imagen
        stmts = _all_stmts()
        labels = []
        for x in stmts:
            nm = getattr(x, "name", None)
            if _isa(x, C_Label) and isinstance(nm, string_types) and not nm.startswith("_") \
                    and _is_game_file(getattr(x, "filename", "")):
                labels.append(x)
        total = max(1, len(labels))
        yield 0.0
        nexty = time.time() + YIELD_S

        def add(table, key, ref):
            # Una referencia por label (la primera aparicion dentro de el), y
            # hasta 12 labels distintos: el orden de la historia usa la mas
            # temprana; "Jugar desde aqui" la primera alcanzable.
            lst = table.setdefault(key, [])
            if len(lst) < 12:
                for r in lst:
                    if r[0] == ref[0]:
                        return
                lst.append(ref)

        for li, lab in enumerate(labels):
            if time.time() >= nexty:
                yield float(li) / total
                nexty = time.time() + YIELD_S
            state = {"start": lab.name}
            ordn = 0
            recent = []            # [clave, lineas que quedan]
            stack = [(_label_body(lab), 0)]
            while stack:
                block, i = stack.pop()
                if not block or i >= len(block) or len(stack) > 40:
                    continue
                node = block[i]
                stack.append((block, i + 1))
                ordn += 1
                try:
                    if _isa(node, C_Scene):
                        state["start"] = getattr(node, "name", None) or state["start"]
                    ref = (lab.name, getattr(node, "name", None), state["start"], ordn)
                    if _isa(node, C_Say):
                        who = getattr(node, "who", None)
                        if who:
                            who = to_text(who)
                            spk[who] = spk.get(who, 0) + 1
                            for r in recent:
                                if r[1] > 0:
                                    d = co.setdefault(r[0], {})
                                    d[who] = d.get(who, 0) + 1
                        for r in recent:
                            r[1] -= 1
                        if recent and recent[0][1] <= 0:
                            recent = [r for r in recent if r[1] > 0]
                    shown = []
                    if _isa(node, C_Scene):
                        recent = []
                    if _isa(node, C_Scene) or _isa(node, C_Show):
                        spec = getattr(node, "imspec", None) or ()
                        if spec and spec[0]:
                            k = " ".join(to_text(x) for x in spec[0])
                            add(names, k, ref)
                            shown.append(k)
                    for sv in _strings_of(node):
                        sv = sv.strip()
                        if sv.lower().endswith(MEDIA_EXT):
                            add(files, _base_noext(sv), ref)
                            shown.append(_base_noext(sv))
                        elif sv and len(sv) < 80:
                            add(names, sv, ref)        # renpy.show("cg1")
                            if _isa(node, C_Python) and "show" in _py_source(node):
                                shown.append(sv)
                    for k in shown:
                        recent.append([k, CO_WIN])
                    if len(recent) > 4:
                        recent = recent[-4:]
                except Exception:
                    pass
                for child in reversed(_node_children(node)):
                    stack.append((child, 0))
        # solo los 4 que mas hablan con cada imagen
        for k in list(co.keys()):
            d = co[k]
            if len(d) > 4:
                co[k] = dict(sorted(d.items(), key=lambda kv: -kv[1])[:4])
        RT.gal_where = {"names": names, "files": files, "spk": spk, "co": co}
        for _x in write_json_gen(_savedir_path("umod_where.json"),
                                 {"format": 3, "fp": script_fp(), "names": names, "files": files,
                                  "spk": spk, "co": co}):
            yield 0.99
        chars_ensure()

    # ---------- 2.4c2 Personajes (rc10) -----------------------------
    #  Cuando ya se sabe quien habla en el guion (indice de momentos) y que
    #  imagenes hay (galeria), se completan los personajes y se vuelven a
    #  asignar a las imagenes y escenas. Barato: unos ms en segundo plano.
    CHARS = {"ver": 0}

    def chars_gen():
        W = getattr(RT, "gal_where", None) or {}
        add_speakers(W.get("spk") or {})
        yield 0.3
        scenes_map_who()
        yield 0.5
        if RT.gal_ready and RT.gal_assets:
            try:
                gal_assign_chars(RT.gal_assets)
            except Exception as e:
                log_error("chars.assign", e)
        CHARS["ver"] += 1
        RT.gal_view = {}
        RT.scn_cache = {}

    def chars_ensure():
        if job_running("chars"):
            return
        job_start("chars", chars_gen, "Buscando personajes", after=("gal", "where", "scenes"))

    _RES = {"ver": -1}

    def resolve_char_names():
        """Hilo principal: nombres que dependen de variables del juego
        (persistent.player_name...). Barato; se hace al cambiar los personajes."""
        if _RES["ver"] == CHARS["ver"]:
            return
        _RES["ver"] = CHARS["ver"]
        for cid, c in list((getattr(RT, "gal_char_src", None) or {}).items()):
            expr = c.get("expr")
            if not expr:
                continue
            val = _eval_name(expr)
            if isinstance(val, string_types):
                nm = _strip_tags(val)
                if _words(nm) and nm != c.get("name"):
                    c["name"] = nm
                    _CHIPS.clear()
                    _CELLS.clear()
            elif _is_character(val):
                try:
                    nm = _strip_tags(to_text(val))
                except Exception:
                    nm = ""
                if _words(nm) and "[" not in nm and nm != c.get("name"):
                    c["name"] = nm
                    _CHIPS.clear()
                    _CELLS.clear()

    TICK_HOOKS.append(lambda: resolve_char_names())

    def chars_refresh():
        """Hilo principal (al abrir la galeria): vuelve a leer los
        personajes del juego; si hay nuevos, se reasignan en segundo plano."""
        if collect_char_sources(late=True):
            chars_ensure()

    def gal_where_ensure():
        if getattr(RT, "gal_where", None) is not None or job_running("where"):
            return
        job_start("where", gal_where_gen, "Buscando las escenas en la historia")

    def _where_refs(a):
        W = getattr(RT, "gal_where", None)
        if not W or a is None:
            return None
        refs = None
        if a.get("d"):
            refs = W["names"].get(a["d"])
        if not refs and a.get("f"):
            refs = W["files"].get(_base_noext(a["f"])) or W["names"].get(_base_noext(a["f"]))
        return refs or None

    def gal_where(a):
        """{"label", "start"} o None. Solo para escenas, animaciones y videos."""
        if a is None or category_of(a) not in PLAY_CATS:
            return None
        refs = _where_refs(a)
        if not refs:
            return None
        reach = None
        try:
            if GRAPH and RT.g_ready:
                reach = RT.g_reach
        except Exception:
            reach = None
        best = refs[0]
        pos = STORY["pos"]
        if pos:
            # la primera vez que aparece en la historia
            cand = [r for r in refs if (not reach or r[0] in reach) and r[0] in pos] or \
                   [r for r in refs if r[0] in pos]
            if cand:
                best = min(cand, key=lambda r: (pos[r[0]], r[3] if len(r) > 3 else 0))
        elif reach:
            for r in refs:
                if r[0] in reach:
                    best = r
                    break
        return {"label": best[0], "node": best[1], "start": best[2]}

    def gal_can_play(a):
        try:
            return bool(RECONSTRUCT) and gal_where(a) is not None
        except Exception:
            return False

    def gal_play_where(a):
        w = gal_where(a)
        if not w:
            return ""
        name = ""
        try:
            if ADAPTERS:
                name = ad_label_suffix(w["label"]).replace("   - ", "")
        except Exception:
            name = ""
        return name or w["label"]

    def gal_play_from(a):
        """Ir a ese momento de la historia y seguir jugando desde ahi."""
        w = gal_where(a)
        if not w:
            renpy.notify("No se encontro esta imagen en la historia.")
            return
        P = dict(rc_plan(w["label"], None, "guards", "auto"))
        P["node"] = w["start"] if w["start"] != w["label"] else None
        P["notice"] = " ".join(asset_end_notes(a))
        try:
            renpy.hide_screen(GAL_SCREEN)
        except Exception:
            pass
        rc_execute(P)

    # ---------- 2.4d Escenas de la historia (con dialogo) -------------
    #  Una "escena" es un tramo del guion con dialogo: un label entero o,
    #  si el label es largo, cada parte que empieza con un 'scene'.
    #   - Ver escena: repeticion de Ren'Py (call_replay) con el estado de
    #     la historia reconstruido; al terminar vuelves a la galeria.
    #   - Jugar desde aqui: reconstruye el estado y salta a ese punto de la
    #     partida para seguir jugando.
    SCN_MIN_SAY = 3

    def _scan_segment(nodes, acc, depth=0):
        if depth > 30:
            return
        for n in nodes:
            try:
                if _isa(n, C_Say):
                    acc["n"] += 1
                    who = getattr(n, "who", None)
                    if who:
                        acc["who"][who] = acc["who"].get(who, 0) + 1
                    if not acc["first"]:
                        acc["first"] = _strip_tags(getattr(n, "what", "") or "")[:110]
                elif _isa(n, C_Menu):
                    acc.setdefault("menus", []).append(to_text(getattr(n, "linenumber", "")))
                elif _isa(n, C_Scene) or _isa(n, C_Show):
                    spec = getattr(n, "imspec", None) or ()
                    if spec and spec[0] and len(acc["imgs"]) < 8:
                        acc["imgs"].append(" ".join(to_text(x) for x in spec[0]))
                for sv in _strings_of(n):
                    sv = sv.strip()
                    if sv.lower().endswith(MEDIA_EXT) and len(acc["imgs"]) < 8:
                        acc["imgs"].append(sv)
            except Exception:
                pass
            for child in _node_children(n):
                _scan_segment(child, acc, depth + 1)

    def _pretty(label):
        t = re.sub(r"[_]+", " ", to_text(label)).strip()
        return (t[:1].upper() + t[1:]) if t else to_text(label)

    def _group_name(fn):
        f = to_text(fn or "").replace("\\", "/").split("/")[-1]
        f = re.sub(r"\.rpym?c?$", "", f)
        return _pretty(f)

    def _tup(x):
        """Los nombres de sentencia son tuplas; JSON los devuelve como listas."""
        return tuple(x) if isinstance(x, list) else x

    def _disk_load(fname, fmt):
        p = _savedir_path(fname)
        if not p or not os.path.exists(p):
            return None
        try:
            f = open(p, "r")
            try:
                data = json.load(f)
            finally:
                f.close()
        except Exception as e:
            log_error("cache %s" % fname, e)
            return None
        if data.get("format") != fmt or data.get("fp") != script_fp():
            return None
        return data

    def scenes_gen():
        RT.scenes = None
        try:
            ok = bool(SCRIPT) and sa_available()
        except Exception:
            ok = False
        if not ok:
            RT.scenes = []
            return
        cached = _disk_load("umod_scenes.json", 4)
        if cached is not None:
            sc = cached.get("scenes") or []
            for e in sc:
                e["node"] = _tup(e.get("node"))
            scenes_map_who(sc)
            RT.scenes = sc
            RT.scn_cache = {}
            return
        labels = []
        for x in _all_stmts():
            nm = getattr(x, "name", None)
            if _isa(x, C_Label) and isinstance(nm, string_types) and not nm.startswith("_") \
                    and _is_game_file(getattr(x, "filename", "")):
                labels.append(x)
        yield 0.0
        total = max(1, len(labels))
        nexty = time.time() + YIELD_S
        out = []
        for li, lab in enumerate(labels):
            if time.time() >= nexty:
                yield float(li) / total
                nexty = time.time() + YIELD_S
            body = _label_body(lab)
            # partes: se corta en cada 'scene' del nivel superior
            parts, cur_start, cur = [], None, []
            for n in body:
                if _isa(n, C_Scene) and cur:
                    parts.append((cur_start, cur))
                    cur_start, cur = getattr(n, "name", None), []
                cur.append(n)
            if cur:
                parts.append((cur_start, cur))
            segs = []
            for start, nodes in parts:
                acc = {"n": 0, "who": {}, "first": "", "imgs": [], "menus": []}
                _scan_segment(nodes, acc)
                if segs and acc["n"] < SCN_MIN_SAY:
                    # parte corta: se une a la anterior
                    prev = segs[-1][1]
                    prev["n"] += acc["n"]
                    prev["menus"].extend(acc["menus"])
                    for k, v in acc["who"].items():
                        prev["who"][k] = prev["who"].get(k, 0) + v
                    prev["imgs"].extend(acc["imgs"][:8 - len(prev["imgs"])])
                    continue
                segs.append((start, acc))
            segs = [sg for sg in segs if sg[1]["n"] >= SCN_MIN_SAY]
            if not segs:
                continue
            fn = to_text(getattr(lab, "filename", ""))
            base = _pretty(lab.name)
            for k, (start, acc) in enumerate(segs):
                who = sorted(acc["who"].items(), key=lambda kv: -kv[1])
                out.append({
                    "id": "%s#%d" % (lab.name, k),
                    "label": lab.name,
                    "node": None if k == 0 and start is None else start,
                    "title": base if len(segs) == 1 else "%s  (%d/%d)" % (base, k + 1, len(segs)),
                    "group": _group_name(fn),
                    "n": acc["n"],
                    "wv": [to_text(w) for w, _c in who[:8]],
                    "who": [],
                    "menus": acc["menus"][:30],
                    "imgs": acc["imgs"],
                    "first": acc["first"],
                    "file": fn,
                    "line": getattr(lab, "linenumber", 0) or 0,
                    "k": k,
                })
        scenes_map_who(out)
        RT.scenes = out
        RT.scn_cache = {}
        for _x in write_json_gen(_savedir_path("umod_scenes.json"),
                                 {"format": 4, "fp": script_fp(), "scenes": out}):
            yield 0.99

    def scenes_map_who(sc=None):
        """'who' de cada escena (ids de personaje) a partir de las variables
        que hablan en ella. Se rehace cuando se conocen mas personajes."""
        if sc is None:
            sc = getattr(RT, "scenes", None) or []
        src = getattr(RT, "gal_char_src", None) or {}
        for e in sc:
            cids = []
            for w in e.get("wv") or ():
                cid = speaker_cid(w)
                if cid and cid in src and cid not in cids:
                    cids.append(cid)
            e["who"] = cids[:6]
        _FOLD["key"] = None

    # ---------- 2.4d2 Decisiones en una sola escena (rc10) ------------
    #  Muchas novelas escriben cada opcion de un menu en su propio label
    #  (escena5_choice1, escena5_choice2...) que despues se juntan en el
    #  mismo punto. Antes salia una escena por opcion: la misma escena
    #  repetida 2 o 3 veces. Ahora:
    #   - las opciones de un mismo menu que vuelven a juntarse enseguida
    #     (cada una salta al mismo label, o vuelve con 'return' si se
    #     llamo con 'call') se pliegan dentro de la escena que tiene el
    #     menu: UNA escena con "N caminos";
    #   - al verla o jugarla, el menu aparece y eliges tu: la repeticion
    #     sigue por la opcion elegida y termina donde se juntan;
    #   - las rutas largas (que no se juntan) y los finales NO se pliegan:
    #     siguen siendo escenas propias.
    _FOLD = {"key": None, "view": None, "of": {}}

    def _fold_plan():
        """{label de rama: (label con el menu, linea del menu, texto opcion)}"""
        try:
            if not (GRAPH and RT.g_ready):
                return {}
        except Exception:
            return {}
        N, E, origin = RT.g_nodes, RT.g_edges, RT.g_origin
        ends = set(story_endings())
        cand = {}                      # (P, linea) -> [(L, opcion, M)]
        for L, node in N.items():
            ins = [E[i] for i in node.get("in", ()) if not E[i].get("obs")]
            if not ins or L == origin or L in ends:
                continue
            P, line, cap, ok = None, None, "", True
            for e in ins:
                d = e.get("d") or []
                if e.get("a") is None or not d:
                    ok = False
                    break
                if P is None:
                    P, line, cap = e["a"], to_text(d[-1].get("line")), to_text(d[-1].get("cap", ""))
                elif e["a"] != P or to_text(d[-1].get("line")) != line:
                    ok = False
                    break
            if not ok or P is None or P == L or N[L].get("dyn"):
                continue
            outs = set(b for b in _fwd(L, N, E, origin) if b != P)
            called = any(e.get("t") == "call" for e in ins)
            if len(outs) == 1:
                M = list(outs)[0]
            elif not outs and called:
                M = None                   # vuelve al menu con 'return'
            else:
                continue                   # ruta larga o varias salidas: escena propia
            cand.setdefault((P, line), []).append((L, cap, M))
        plan = {}
        for (P, line), lst in cand.items():
            merges = set(m for _l, _c, m in lst)
            if len(merges) != 1:
                continue
            M = list(merges)[0]
            if len(lst) < 2 and not (M is not None and M in _fwd(P, N, E, origin)):
                continue                   # una sola opcion con label propio que no se junta con P
            for L, cap, _m in lst:
                plan[L] = (P, line, cap)
        return plan

    def scenes_all():
        """Escenas tal como se ensenan: con las decisiones plegadas."""
        sc = getattr(RT, "scenes", None) or []
        key = (id(sc), len(sc), len(getattr(RT, "g_edges", None) or ()), STORY["ver"], CHARS["ver"])
        if _FOLD["key"] == key and _FOLD["view"] is not None:
            return _FOLD["view"]
        try:
            plan = _fold_plan()
        except Exception as ex:
            log_error("fold", ex)
            plan = {}
        if not plan:
            _FOLD.update(key=key, view=list(sc), of={})
            return _FOLD["view"]
        by_label = {}
        for e in sc:
            by_label.setdefault(e["label"], []).append(e)
        # cada rama se pliega en la escena del label con el menu que contiene ese menu
        groups = {}                         # id escena anfitriona -> [(opcion, L)]
        host_of = {}
        synth = {}
        for L, (P, line, cap) in plan.items():
            host = None
            for e in by_label.get(P, ()):
                if line in (e.get("menus") or ()):
                    host = e
                    break
            if host is None and by_label.get(P):
                host = by_label[P][-1]       # el menu quedo en una parte corta unida
            if host is None:
                # el label con el menu casi no tiene dialogo: escena nueva que empieza en el
                hid = P + "#m"
                host = synth.get(hid)
                if host is None:
                    first = (by_label.get(L) or [{}])[0]
                    host = synth[hid] = {"id": hid, "label": P, "node": None, "title": _pretty(P),
                                         "group": first.get("group", ""), "n": 0, "who": [], "wv": [],
                                         "imgs": [], "first": first.get("first", ""), "menus": [line],
                                         "file": first.get("file", ""), "line": first.get("line", 0), "k": 0}
            groups.setdefault(host["id"], []).append((cap, L))
            host_of[host["id"]] = host
        folded = set(plan.keys())
        view = []
        done = set()

        def merged(h):
            m = dict(h)
            br = groups[h["id"]]
            m["branches"] = [c or _pretty(l) for c, l in br]
            m["span"] = [h["label"]] + [l for _c, l in br]
            who, imgs, n = list(h.get("who") or []), list(h.get("imgs") or []), h.get("n", 0)
            for _c, l in br:
                for e in by_label.get(l, ()):
                    n += e.get("n", 0)
                    for c in e.get("who") or ():
                        if c not in who:
                            who.append(c)
                    for im in e.get("imgs") or ():
                        if im not in imgs and len(imgs) < 12:
                            imgs.append(im)
                    if not m.get("first"):
                        m["first"] = e.get("first", "")
            m["n"], m["who"], m["imgs"] = n, who[:6], imgs
            return m

        for e in sc:
            if e["label"] in folded:
                # la escena anfitriona sintetica va donde estaba la primera rama
                for hid, h in synth.items():
                    if hid not in done and e["label"] in [l for _c, l in groups[hid]]:
                        view.append(merged(h))
                        done.add(hid)
                continue
            if e["id"] in groups:
                view.append(merged(e))
                done.add(e["id"])
            else:
                view.append(e)
        _FOLD.update(key=key, view=view, of=dict((l, p[0]) for l, p in plan.items()))
        return view

    def scenes_ensure(front=False):
        if getattr(RT, "scenes", None) is not None:
            return
        if job_running("scenes"):
            if front:
                job_bump("scenes")
            return
        job_start("scenes", scenes_gen, "Buscando las escenas de la historia", front=front)

    # ---------- 2.4e Orden de la historia (rc8) ----------------------
    #  PROBLEMA (rc7 y antes):
    #   - Las imagenes se ordenaban por categoria y despues por nombre
    #     ALFABETICO: "cg10" antes que "cg2", "ep10_" antes que "ep2_", y
    #     todas las animaciones detras de todas las ilustraciones.
    #   - Las escenas, por la distancia MAS CORTA desde el inicio: una ruta
    #     larga (10 labels) y una corta (2) que se juntan despues dejaban el
    #     capitulo siguiente en mitad de la ruta larga; y los labels a los
    #     que solo se llega desde pantallas (mapas, telefonos) iban al final.
    #  AHORA: un recorrido de la historia de principio a fin.
    #   - Se recorre el mapa de la historia desde el inicio en profundidad
    #     y se toma el orden "post-orden inverso": cada label sale DESPUES
    #     de todo lo que lleva a el (un capitulo, despues de TODAS las rutas
    #     que desembocan en el) y cada ruta sale entera, sin mezclarse con
    #     las demas. Entre opciones de un menu, en el orden del menu.
    #   - Tambien cuentan los saltos que el tracker vio al jugar de verdad
    #     (navegacion por pantallas incluida).
    #   - Un label al que no llega ningun salto (se entra desde una
    #     pantalla) va justo despues del label escrito antes que el en su
    #     archivo: los guiones se escriben en orden.
    #   - Cada imagen va donde aparece POR PRIMERA VEZ (label + posicion
    #     dentro del label). Las que el guion no muestra por su nombre se
    #     colocan junto a la imagen de nombre mas parecido (cg_ep3_05 junto
    #     a cg_ep3_04); si no se parece a ninguna, al final.
    STORY = {"pos": None, "ver": 0, "key": None, "scr": {}, "scr_calls": set()}
    import math

    def _lnum(x):
        try:
            return int(x)
        except Exception:
            return 0

    def _nat(x):
        try:
            return natkey(x)
        except Exception:
            return to_text(x).lower()

    # --- navegacion por pantallas (mapas, telefonos, menus de dia) ---
    #  Muchos juegos no saltan con 'jump' sino con botones: 'call screen
    #  mapa' y en la pantalla textbutton "Parque" action Jump("parque").
    #  Se leen las pantallas del juego (su arbol SL2, en memoria) para saber
    #  a que labels lleva cada una, y los labels que las muestran.
    _SCR_JUMP = re.compile(r"""\b(?:Jump|Call)\(\s*u?["']([^"']+)["']""")
    _SCR_PYJUMP = re.compile(r"""renpy\.(?:jump|call)\(\s*u?["']([^"']+)["']""")
    _SCR_CALLONLY = re.compile(r"""\bCall\(\s*u?["']([^"']+)["']|renpy\.call\(\s*u?["']([^"']+)["']""")
    _SCR_SHOW = re.compile(r"""\b(?:Show|ShowMenu|ShowScreen|ToggleScreen|ShowTransient)\(\s*u?["']([\w.]+)["']""")
    _LBL_SCREEN = re.compile(r"""^\s*(?:call|show)\s+screen\s+([\w.]+)""")
    _PY_SCREEN = re.compile(r"""renpy\.(?:call_screen|show_screen)\(\s*u?["']([\w.]+)["']""")
    SCR_SKIP = ("main_menu", "game_menu", "navigation", "save", "load", "preferences", "about",
                "help", "quick_menu", "confirm", "history", "file_slots", "say", "choice", "nvl")

    def _sl_strings(node, out, uses, depth=0):
        """Recorre un nodo de pantalla SL2 y junta las expresiones (texto)."""
        if node is None or depth > 60:
            return
        for k, v in (getattr(node, "keyword", None) or ()):
            if isinstance(v, string_types):
                out.append(v)
        for v in (getattr(node, "positional", None) or ()):
            if isinstance(v, string_types):
                out.append(v)
        code = getattr(node, "code", None)
        src = getattr(code, "source", None)
        if isinstance(src, string_types):
            out.append(src)
        tgt = getattr(node, "target", None)
        if isinstance(tgt, string_types):
            uses.append(tgt)
        for c in (getattr(node, "children", None) or ()):
            _sl_strings(c, out, uses, depth + 1)
        for ent in (getattr(node, "entries", None) or ()):
            try:
                _sl_strings(ent[1], out, uses, depth + 1)
            except Exception:
                pass
        blk = getattr(node, "block", None)
        if blk is not None and not isinstance(blk, list):
            _sl_strings(blk, out, uses, depth + 1)

    def screen_jumps():
        """{pantalla: [labels a los que lleva, en el orden de sus botones]}."""
        out = {}
        try:
            scr = renpy.display.screen
            by_name = getattr(scr, "screens_by_name", None)
            if not by_name:
                by_name = {}
                for (nm, _v), so in (getattr(scr, "screens", None) or {}).items():
                    by_name.setdefault(nm, {})[_v] = so
        except Exception:
            return out
        direct, links = {}, {}
        for nm, variants in list(by_name.items()):
            if not isinstance(nm, string_types) or nm.startswith("_") or nm.startswith("umod") or nm in SCR_SKIP:
                continue
            texts, uses = [], []
            for so in list((variants or {}).values()):
                ast = getattr(so, "ast", None)
                if ast is not None:
                    try:
                        _sl_strings(ast, texts, uses)
                    except Exception:
                        pass
            tg = []
            for t in texts:
                for m1, m2 in _SCR_CALLONLY.findall(t):
                    STORY["scr_calls"].add(m1 or m2)
                for m in _SCR_JUMP.findall(t) + _SCR_PYJUMP.findall(t):
                    if m not in tg:
                        tg.append(m)
                for m in _SCR_SHOW.findall(t):
                    uses.append(m)
            direct[nm] = tg
            links[nm] = [u for u in uses if u != nm]
        for nm in direct:                      # incluye las pantallas que usa o abre
            seen, stack, res = set([nm]), [nm], []
            while stack:
                x = stack.pop(0)
                for t in direct.get(x, ()):
                    if t not in res:
                        res.append(t)
                for u in links.get(x, ()):
                    if u not in seen and u in direct and len(seen) < 40:
                        seen.add(u)
                        stack.append(u)
            if res:
                out[nm] = res
        return out

    def _label_screens(N):
        """{label: [pantallas que muestra]} recorriendo el guion una vez."""
        res = {}
        if not (SCRIPT and sa_available()):
            return res
        lines = {}
        for n, node in N.items():
            lines.setdefault(node.get("file", ""), []).append((_lnum(node.get("line")), n))
        for v in lines.values():
            v.sort()
        import bisect
        for st in _all_stmts():
            names = None
            try:
                if _isa(st, C_User):
                    m = _LBL_SCREEN.match(to_text(getattr(st, "line", "") or ""))
                    names = [m.group(1)] if m else None
                elif _isa(st, C_Python):
                    src = _py_source(st)
                    if "screen" in src:
                        names = _PY_SCREEN.findall(src) or None
            except Exception:
                names = None
            if not names:
                continue
            fl = lines.get(to_text(getattr(st, "filename", "")))
            if not fl:
                continue
            i = bisect.bisect_right(fl, (_lnum(getattr(st, "linenumber", 0)), u"\uffff")) - 1
            if i < 0:
                continue
            lst = res.setdefault(fl[i][1], [])
            for x in names:
                if x not in lst:
                    lst.append(x)
        return res

    def story_order_gen():
        try:
            if not (GRAPH and RT.g_ready):
                return
        except Exception:
            return
        N, E = RT.g_nodes, RT.g_edges
        origin = RT.g_origin
        nobs = sum(1 for e in E if e.get("obs"))
        key = [len(N), len(E) - nobs, nobs, to_text(origin), 3]
        cached = _disk_load("umod_order.json", 2)
        if cached is not None and cached.get("key") == key:
            STORY["scr"] = cached.get("scr") or {}
            STORY["scr_calls"] = set(cached.get("scr_calls") or ())
            STORY["pos"] = cached.get("pos") or {}
            STORY["key"] = key
            STORY["ver"] += 1
            warm_thumbs()
            return
        yield 0.02
        nexty = time.time() + YIELD_S
        names = list(N.keys())
        fk = dict((n, (_nat(N[n].get("file", "")), _lnum(N[n].get("line")))) for n in names)
        forder = sorted(names, key=lambda n: fk[n])
        fidx = dict((n, i) for i, n in enumerate(forder))
        yield 0.08
        # 1) navegacion por pantallas
        scr_edges = {}
        try:
            sj = screen_jumps()
            if sj:
                for lab, scrs in _label_screens(N).items():
                    tg = []
                    for sc in scrs:
                        for t in sj.get(sc, ()):
                            if t in N and t != lab and t not in tg:
                                tg.append(t)
                    if tg:
                        scr_edges[lab] = tg
        except Exception as e:
            log_error("orden.pantallas", e)
        STORY["screen_edges"] = sum(len(v) for v in scr_edges.values())
        STORY["scr"] = scr_edges
        yield 0.15
        # 2) sucesores en orden de preferencia: codigo (en su orden),
        #    botones de pantallas, saltos vistos al jugar. Las vueltas al
        #    inicio ('jump start' tras un final malo) no cuentan.
        succ, has_in = {}, set()
        for k, n in enumerate(names):
            if (k & 511) == 0 and time.time() >= nexty:
                yield 0.15 + 0.15 * k / max(1, len(names))
                nexty = time.time() + YIELD_S
            real, obs, seen = [], [], set()
            for ei in N[n].get("out", ()):
                try:
                    e = E[ei]
                except Exception:
                    continue
                b = e.get("b")
                if e.get("dyn") or b is None or b == n or b not in N or b in seen or b == origin:
                    continue
                seen.add(b)
                (obs if e.get("obs") else real).append(b)
            for b in scr_edges.get(n, ()):
                if b not in seen and b != origin:
                    seen.add(b)
                    real.append(b)
            succ[n] = real + obs
            has_in.update(succ[n])
        # 3) labels sin ningun salto de entrada: van justo detras del
        #    label escrito antes que ellos en su archivo
        prev = None
        virt = {}
        for n in forder:
            if prev is not None and n not in has_in and n != origin \
                    and N[prev].get("file") == N[n].get("file"):
                succ[prev].insert(0, n)
                virt.setdefault(prev, []).append(n)
            prev = n
        yield 0.35
        # 4) grupos que se repiten (un mapa con eventos que vuelven a el,
        #    los dias de un modo libre): componentes fuertemente conexas
        #    (Tarjan, iterativo). Dentro de cada grupo: el primero al que se
        #    llega y despues el orden en que estan escritos.
        index, low, onst, comp_of = {}, {}, set(), {}
        comps = []
        stack, counter = [], [0]
        for root in forder:
            if root in index:
                continue
            work = [(root, 0)]
            steps = 0
            while work:
                steps += 1
                if (steps & 1023) == 0 and time.time() >= nexty:
                    yield 0.35 + 0.2 * len(index) / max(1, len(names))
                    nexty = time.time() + YIELD_S
                v, i = work[-1]
                if i == 0:
                    index[v] = low[v] = counter[0]
                    counter[0] += 1
                    stack.append(v)
                    onst.add(v)
                ch = succ.get(v, ())
                if i < len(ch):
                    work[-1] = (v, i + 1)
                    w = ch[i]
                    if w not in index:
                        work.append((w, 0))
                    elif w in onst:
                        low[v] = min(low[v], index[w])
                    continue
                work.pop()
                if work:
                    u = work[-1][0]
                    low[u] = min(low[u], low[v])
                if low[v] == index[v]:
                    c = []
                    while True:
                        w = stack.pop()
                        onst.discard(w)
                        comp_of[w] = len(comps)
                        c.append(w)
                        if w == v:
                            break
                    comps.append(c)
            if time.time() >= nexty:
                yield 0.35 + 0.2 * len(index) / max(1, len(names))
                nexty = time.time() + YIELD_S
        csucc = []
        for ci, c in enumerate(comps):
            c.sort(key=lambda n: fidx[n])
            out, seen = [], set([ci])
            for n in c:                         # primero lo escrito justo detras
                for b in virt.get(n, ()):
                    cb = comp_of[b]
                    if cb not in seen:
                        seen.add(cb)
                        out.append(cb)
            rest = []
            for n in c:
                for b in succ.get(n, ()):
                    cb = comp_of[b]
                    if cb not in seen:
                        seen.add(cb)
                        rest.append((fidx[b], cb))
            if len(c) > 1:
                # salidas de un bucle (mapa, dias): en el codigo de un bucle
                # el orden no es cronologico; se usa el orden de escritura
                rest.sort()
            out.extend(cb for _f, cb in rest)
            csucc.append(out)
        yield 0.6
        # 5) recorrido de la historia: post-orden inverso sobre los grupos
        #    (cada ruta entera; lo que se junta, despues de todo lo que
        #    lleva a ello). Del menos al mas preferido, para que el mas
        #    preferido quede justo detras.
        visited = set()
        entry = {}

        def dfs(rootc, via):
            post = []
            visited.add(rootc)
            entry.setdefault(rootc, via)
            st2 = [[rootc, len(csucc[rootc])]]
            while st2:
                top = st2[-1]
                i = top[1] - 1
                if i >= 0:
                    top[1] = i
                    c = csucc[top[0]][i]
                    if c not in visited:
                        visited.add(c)
                        st2.append([c, len(csucc[c])])
                else:
                    st2.pop()
                    post.append(top[0])
            post.reverse()
            return post

        def members(ci):
            c = comps[ci]
            if origin in c:
                return [origin] + [n for n in c if n != origin]
            return c

        pos = {}
        k = 0
        if origin in N:
            for ci in dfs(comp_of[origin], origin):
                for n in members(ci):
                    pos[n] = float(k)
                    k += 1
        yield 0.75
        # 6) lo que queda suelto: en el hueco detras del label anterior
        #    (en orden de archivo)
        last = -1.0
        for j, n in enumerate(forder):
            if (j & 511) == 0 and time.time() >= nexty:
                yield 0.75 + 0.2 * j / max(1, len(forder))
                nexty = time.time() + YIELD_S
            if n in pos:
                last = pos[n]
                continue
            ci = comp_of[n]
            if ci in visited:
                continue
            seq = []
            for cj in dfs(ci, n):
                seq.extend(members(cj))
            seq = [m for m in seq if m not in pos]
            end = math.floor(last) + 1.0
            for t, m in enumerate(seq):
                pos[m] = last + (end - last) * (t + 1) / (len(seq) + 2.0)
            if seq:
                last = pos[seq[-1]]
        STORY["pos"] = pos
        STORY["key"] = key
        STORY["ver"] += 1
        for _x in write_json_gen(_savedir_path("umod_order.json"),
                                 {"format": 2, "fp": script_fp(), "key": key, "pos": pos,
                                  "scr": scr_edges, "scr_calls": sorted(STORY["scr_calls"])}):
            yield 0.99
        warm_thumbs()

    # ---------- 2.4f Finales (rc9) ----------------------------------
    #  Un FINAL es un label en el que la historia se acaba: termina con
    #  'return' (o se queda sin guion) sin que nadie lo haya llamado con
    #  'call' (entonces 'return' vuelve al menu principal), o vuelve al
    #  inicio con 'jump start' (fin de partida), o se llama end/ending/
    #  final/credits/epilogue. Con eso, al elegir una escena se sabe:
    #   - si es la escena final de un camino;
    #   - si quedan muy pocas escenas para terminar;
    #   - a cuales de los finales del juego se puede llegar desde ahi.
    #  Si desde la escena hay saltos calculados (jump expression), no se
    #  puede asegurar a donde lleva y no se dice nada sobre los finales.
    _END_HINT = re.compile(r"(?:^|_)(?:end|ending|endings|final|finale|credits|epilog|epilogue|fin|gameover|game_over)(?:_|$|\d)")
    ENDS = {"key": None, "ends": [], "info": {}}
    NEAR_END = 2            # "estas muy cerca del final": quedan 2 escenas o menos

    def _fwd(n, N, E, origin):
        out = []
        for ei in N[n].get("out", ()):
            try:
                e = E[ei]
            except Exception:
                continue
            b = e.get("b")
            if b is not None and b in N and b != origin and not e.get("dyn"):
                out.append(b)
        for b in STORY["scr"].get(n, ()):
            if b in N and b != origin:
                out.append(b)
        return out

    def story_endings():
        """Lista de labels que son finales (en orden de la historia)."""
        try:
            if not (GRAPH and RT.g_ready):
                return []
        except Exception:
            return []
        N, E, origin = RT.g_nodes, RT.g_edges, RT.g_origin
        key = (len(N), len(E), STORY["ver"], len(STORY["scr"]))
        if ENDS["key"] == key:
            return ENDS["ends"]
        called = set(STORY["scr_calls"])
        dyn_call = False
        for e in E:
            if e.get("t") == "call":
                if e.get("dyn"):
                    dyn_call = True
                elif e.get("b"):
                    called.add(e["b"])
        reach = set()
        if origin in N:
            reach.add(origin)
            todo = [origin]
            while todo:
                x = todo.pop()
                for b in _fwd(x, N, E, origin):
                    if b not in reach:
                        reach.add(b)
                        todo.append(b)
        ends = []
        for n in N:
            if n == origin or n in called:
                continue
            hint = bool(_END_HINT.search(n.lower()))
            terminal = not _fwd(n, N, E, origin) and not N[n].get("dyn")
            if terminal and (n in reach or hint) and (not dyn_call or hint):
                ends.append(n)
        pos = STORY["pos"] or {}
        ends.sort(key=lambda n: (pos.get(n, float("inf")), n))
        ENDS["key"] = key
        ENDS["ends"] = ends
        ENDS["info"] = {}
        return ends

    def end_name(n):
        try:
            if ADAPTERS:
                nm = ad_scene(n).get("name")
                if nm:
                    return to_text(nm)
        except Exception:
            pass
        return _pretty(n)

    def scene_ending_info(e):
        """{"final": bool, "left": escenas que quedan, "ends": [finales a
        los que se llega], "all": numero de finales, "sure": bool}"""
        ends = story_endings()
        if not ends:
            return None
        lab = e.get("label")
        k = e.get("k", 0)
        ck = (lab, k)
        hit = ENDS["info"].get(ck)
        if hit is not None:
            return hit
        N, E, origin = RT.g_nodes, RT.g_edges, RT.g_origin
        if lab not in N:
            return None
        R = set([lab])
        todo = [lab]
        sure = not N[lab].get("dyn")
        while todo:
            x = todo.pop()
            for b in _fwd(x, N, E, origin):
                if b not in R:
                    R.add(b)
                    todo.append(b)
                    if N[b].get("dyn"):
                        sure = False
        endset = set(ends)
        reached = [n for n in ends if n in R]
        left = 0
        for s2 in scenes_all():
            if s2["label"] == lab:
                if s2.get("k", 0) > k:
                    left += 1
            elif s2["label"] in R:
                left += 1
        info = {"final": lab in endset and left == 0, "left": left, "ends": reached,
                "all": len(ends), "sure": sure}
        if len(ENDS["info"]) > 500:
            ENDS["info"].clear()
        ENDS["info"][ck] = info
        return info

    def asset_end_notes(a):
        """Los mismos avisos para 'Jugar desde este momento' del visor."""
        try:
            w = gal_where(a)
            if not w:
                return []
            k = 0
            for s2 in (getattr(RT, "scenes", None) or ()):
                if s2["label"] == w["label"] and s2.get("node") is not None and s2.get("node") == w.get("start"):
                    k = s2.get("k", 0)
                    break
            return scene_end_notes({"label": w["label"], "k": k})
        except Exception as ex:
            log_error("asset_end_notes", ex)
            return []

    def scene_end_notes(e):
        """Avisos sencillos para el cartel (lista de frases)."""
        try:
            info = scene_ending_info(e)
        except Exception as ex:
            log_error("scene_end_notes", ex)
            return []
        if not info or not info["sure"]:
            return []
        out = []
        if info["final"]:
            out.append(u"Esta es la escena final de su camino: cuando termine, el juego se acaba.")
        elif info["ends"] and info["left"] <= NEAR_END:
            out.append(u"Est\u00e1s muy cerca del final: despu\u00e9s de esta escena %s y el juego termina." %
                       (u"queda solo 1 escena" if info["left"] == 1 else u"quedan solo %d escenas" % info["left"]))
        if info["all"] >= 2 and info["ends"] and len(info["ends"]) < info["all"]:
            names = [end_name(n) for n in info["ends"][:3]]
            if len(info["ends"]) == 1:
                out.append(u"Este camino lleva a un final concreto: '%s' (el juego tiene %d finales)." %
                           (names[0], info["all"]))
            else:
                out.append(u"Desde aqu\u00ed solo se puede llegar a %d de los %d finales: %s%s." %
                           (len(info["ends"]), info["all"], u", ".join(names),
                            u"..." if len(info["ends"]) > 3 else u""))
        return out

    def story_ensure(front=False):
        """Orden de la historia: espera al mapa de la historia (grafo)."""
        try:
            if not GRAPH:
                return
        except Exception:
            return
        if job_running("order"):
            return
        if STORY["pos"] is not None and RT.g_ready:
            nobs = sum(1 for e in RT.g_edges if e.get("obs"))
            if STORY["key"] == [len(RT.g_nodes), len(RT.g_edges) - nobs, nobs, to_text(RT.g_origin), 3]:
                return
        try:
            ng_ensure()
        except Exception:
            pass
        job_start("order", story_order_gen, "Ordenando segun la historia", front=front, after=("ng",))

    def story_ready():
        return STORY["pos"] is not None

    def story_busy():
        """Texto corto mientras se calcula el orden de la historia."""
        if STORY["pos"] is not None and getattr(RT, "gal_where", None) is not None:
            return False
        return job_running("order") or job_running("ng") or job_running("where")

    def _common_prefix(x, y):
        n = min(len(x), len(y))
        i = 0
        while i < n and x[i] == y[i]:
            i += 1
        return i

    _NORM_RE = re.compile(r"[\s_\-/\\.]+")

    def _norm_name(a):
        """'images/CG_ep3-05.png' y 'cg ep3 05' -> 'cg ep3 05'."""
        n = to_text(a.get("n") or a.get("f") or "").lower()
        for ext in MEDIA_EXT:
            if n.endswith(ext):
                n = n[:-len(ext)]
                break
        return _NORM_RE.sub(" ", n).strip()

    def story_sort_assets(items):
        """Imagenes/videos en el orden en que aparecen en la historia."""
        names = [(_norm_name(a), a) for a in items]
        byname = sorted(names, key=lambda t: _nat(t[0]))
        pos = STORY["pos"]
        if not pos or getattr(RT, "gal_where", None) is None:
            return [a for _n, a in byname]
        keys = {}
        for nm, a in byname:
            refs = _where_refs(a)
            best = None
            for r in (refs or ()):
                p = pos.get(r[0])
                if p is None:
                    continue
                k = (p, r[3] if len(r) > 3 else 0)
                if best is None or k < best:
                    best = k
            if best is not None:
                keys[id(a)] = (best[0], best[1], 0)
        # sin referencia: junto a la de nombre mas parecido
        located = [i for i, (nm, a) in enumerate(byname) if id(a) in keys]
        if located:
            li = 0
            prev_loc = None
            for i, (nm, a) in enumerate(byname):
                if id(a) in keys:
                    prev_loc = i
                    continue
                while li < len(located) and located[li] < i:
                    li += 1
                nxt = located[li] if li < len(located) else None
                best, blen = None, 2
                for j in (prev_loc, nxt):
                    if j is None:
                        continue
                    cp = _common_prefix(nm, byname[j][0])
                    if cp > blen:
                        best, blen = j, cp
                if best is not None:
                    bk = keys[id(byname[best][1])]
                    keys[id(a)] = (bk[0], bk[1], 1 if best < i else -1)
        INF = float("inf")
        order = dict((id(a), k) for k, (nm, a) in enumerate(byname))
        out = [a for nm, a in byname]
        out.sort(key=lambda a: (keys.get(id(a), (INF, 0, 2)), order[id(a)]))
        return out

    def warm_thumbs():
        """En reposo: deja hechas las miniaturas de las primeras paginas,
        para que la galeria se abra al instante."""
        try:
            if not RT.gal_ready:
                return
            L = gal_layout()
            items = gal_items2("img", None, "")
            for a in items[:2 * L["per"]]:
                thumb_request(a, soon=False, urgent=False)
            for e in (scenes_list() or [])[:L["sper"]]:
                ta = scene_thumb(e)
                if ta is not None:
                    thumb_request(ta, soon=False, urgent=False)
        except Exception as e:
            log_error("warm_thumbs", e)

    def gal_focus(tab, picking=False):
        """Lo que necesita el apartado que se esta mirando, en orden."""
        # Si en la pagina que se mira faltan miniaturas, van justo despues
        # de lo imprescindible para ver la lista: se ven en segundos aunque
        # el orden de la historia aun se este calculando.
        hot = thumbs_vis_pending()
        if tab == "scn":
            need = ["scenes", "gal"] + (["thumbs"] if hot else []) + ["ng", "order", "where", "chars", "thumbs"]
        else:
            need = ["gal"] + (["thumbs"] if hot else []) + ["ng", "order", "where", "chars", "thumbs"]
        seen = set()
        need = [n for n in need if not (n in seen or seen.add(n))]
        if picking:
            need = ["sa", "ng"] + [n for n in need if n not in ("sa", "ng")]
        set_focus(need)

    def scenes_list(who=None, q=""):
        sc = scenes_all()
        pos = STORY["pos"]
        key = ("list", who, to_text(q or ""), id(sc), len(sc), STORY["ver"], _nfav(), CHARS["ver"])
        hit = RT.scn_cache.get(key)
        if hit is not None:
            return hit
        s = to_text(q or "").strip().lower()
        out = []
        for e in sc:
            if who and who not in e["who"]:
                continue
            if s and s not in e["title"].lower() and s not in e["first"].lower() \
                    and s not in e["group"].lower():
                continue
            out.append(e)
        big = float("inf")
        if pos:
            out.sort(key=lambda e: (pos.get(e["label"], big), e["k"], _nat(e["file"]), e["line"]))
        else:
            out.sort(key=lambda e: (_nat(e["file"]), e["line"], e["k"]))
        RT.scn_cache[key] = out
        return out

    def scene_title(e):
        if ADAPTERS:
            try:
                n = ad_scene(e["label"]).get("name")
                if n:
                    return to_text(n) if e["k"] == 0 else "%s  (%d)" % (n, e["k"] + 1)
            except Exception:
                pass
        return e["title"]

    def scene_sub(e):
        names = [gal_char_name(c) for c in e.get("who", [])[:3]]
        parts = []
        if names:
            parts.append(u", ".join(names))
        parts.append(scene_meta(e))
        return u"   ".join(parts)

    def scene_names(e):
        return u", ".join(gal_char_name(c) for c in (e.get("who") or [])[:4])

    def lines_text(n):
        return u"1 l\u00ednea" if n == 1 else u"%d l\u00edneas" % n

    def scene_meta(e):
        t = lines_text(e.get("n", 0))
        if e.get("branches"):
            t += u", %d caminos" % len(e["branches"])
        return t

    def quote(e):
        return u"\u201c" + esc(e.get("first", "")) + u"\u201d"

    def warn_line(t):
        return u"\u26a0  " + esc(t)

    def check_label(on, label):
        return (u"\u2713   " if on else u"      ") + label

    def count_text(kind, n):
        one, many = {"scn": (u"escena", u"escenas"), "vid": (u"v\u00eddeo", u"v\u00eddeos")}.get(
            kind, (u"imagen", u"im\u00e1genes"))
        return u"%d %s" % (n, one if n == 1 else many)

    def scene_branch_note(e):
        br = e.get("branches") or []
        if not br:
            return u""
        caps = u", ".join(u"'%s'" % _strip_tags(c)[:40] for c in br[:4])
        return u"Esta escena tiene una decisi\u00f3n con %d caminos (%s%s): al verla o jugarla, eliges t\u00fa." % (
            len(br), caps, u"..." if len(br) > 4 else u"")

    def scene_thumb(e):
        """La ilustracion mas representativa de la escena (un CG si lo hay)."""
        best = None
        for nm in e.get("imgs", ()):
            a = (RT.gal_index or {}).get("i:" + nm) or (RT.gal_by_base or {}).get(_base_noext(nm))
            if a is None:
                continue
            c = category_of(a)
            if c in ("cg", "anim", "video"):
                return a
            if best is None and c in ("bg", "other"):
                best = a
        return best

    def scene_exact(e):
        try:
            return bool(TRACKER) and tr_entry_state(e["label"]) is not None
        except Exception:
            return False

    def scene_who_chips(q=""):
        cnt = {}
        for e in scenes_all():
            for c in e.get("who", ()):
                cnt[c] = cnt.get(c, 0) + 1
        return [(c, gal_char_name(c), n) for c, n in sorted(cnt.items(), key=_chip_order)]

    def _is_pro(cid):
        c = (getattr(RT, "gal_char_src", None) or {}).get(cid) or {}
        return bool(c.get("pro"))

    def _chip_order(kv):
        """Mas apariciones primero; el protagonista (sale en casi todo) al final."""
        return (_is_pro(kv[0]), -kv[1], gal_char_name(kv[0]).lower())

    def _replay_scope(label):
        """Variables de la historia para la repeticion (Ren'Py admite
        nombres con punto: player.affection)."""
        scope = {}
        try:
            P = rc_plan(label, None, "guards", "auto")
            for a in P.get("assigns", ()):
                v = a["v"]
                if v.startswith("persistent.") or "[" in v:
                    continue
                val = a["val"]
                tn = type(val).__name__
                if tn in ("_ObjPatch", "_NoRestore"):
                    if tn == "_ObjPatch":
                        for k2, v2 in val.attrs.items():
                            scope["%s.%s" % (v, k2)] = v2
                    continue
                scope[v] = val
        except Exception as ex:
            log_error("replay.scope", ex)
        return scope

    def scene_watch(e):
        """Ver la escena con su dialogo; al terminar se vuelve a la galeria."""
        target = e["node"] if (e.get("node") is not None and rc_node_exists_g(e["node"])) else e["label"]
        RT.rp = {"label": e["label"], "depth": None, "span": set(e.get("span") or [e["label"]])}
        try:
            renpy.call_replay(target, _replay_scope(e["label"]))
        except Exception as ex:
            if type(ex).__name__ in ("EndReplay",):
                pass
            else:
                log_error("scene_watch", ex)
                renpy.notify("No se pudo reproducir esta escena.")
        finally:
            RT.rp = None
        try:
            renpy.restart_interaction()
        except Exception:
            pass

    def rc_node_exists_g(name):
        try:
            return renpy.game.script.lookup(name) is not None
        except Exception:
            return False

    def _in_replay():
        try:
            return bool(getattr(renpy.store, "_in_replay", None))
        except Exception:
            return False

    def rp_on_label(name, abnormal=False):
        """La escena termina cuando la historia pasa a otro label (las
        novelas suelen enlazar labels con 'jump', y la repeticion de
        Ren'Py solo termina sola con 'return')."""
        R = RT.rp
        if not R or not _in_replay():
            return
        try:
            d = len(renpy.get_return_stack())
        except Exception:
            d = 0
        if R["depth"] is None:
            if name == R["label"]:
                R["depth"] = d
                return
            R["depth"] = d
        if d > R["depth"]:
            return                     # 'call' a una subrutina: sigue la escena
        if name not in R.get("span", (R["label"],)):
            renpy.end_replay()         # las ramas de la decision son parte de la escena

    def rp_tick():
        R = RT.rp
        if R and R["depth"] is None and _in_replay():
            try:
                R["depth"] = len(renpy.get_return_stack())
            except Exception:
                R["depth"] = 0

    def gal_play_scene(e):
        """Entrar en la historia en esta escena y seguir jugando."""
        P = dict(rc_plan(e["label"], None, "guards", "auto"))
        P["node"] = e.get("node")
        P["notice"] = " ".join(scene_end_notes(e))
        try:
            renpy.hide_screen(GAL_SCREEN)
        except Exception:
            pass
        rc_execute(P)

    # ---------- 2.5 Escaneo del inventario --------------------------
    def gal_scan_gen(force=False):
        """Generador (ver sa_scan_gen). Lo caro es leer cabeceras de imagen:
        cede el control cada 40 lecturas."""
        if RT.gal_scanning:
            return
        if RT.gal_ready and not force:
            return
        RT.gal_scanning = True
        RT.gal_msg = "Analizando..."
        t0 = time.time()
        dims_read = 0
        assets = []
        used_files = set()
        try:
            if not RT.ready:
                scan_all()

            total = max(1, len(RT.images) + len(RT.files.get("images", [])) + len(RT.files.get("video", [])))
            done = 0

            # a) Imagenes declaradas
            tag_counts = {}
            for full in RT.images:
                tag_counts[full.split(" ")[0]] = tag_counts.get(full.split(" ")[0], 0) + 1

            nexty = time.time() + YIELD_S
            for full in RT.images:
                done += 1
                if time.time() >= nexty:
                    yield 0.95 * done / total
                    nexty = time.time() + YIELD_S
                tag = full.split(" ")[0]
                fn = resolve_image_file(full)
                w = h = 0
                if fn:
                    used_files.add(fn)
                    if dims_read < DIM_LIMIT:
                        dm = image_dims(fn)
                        dims_read += 1
                        if dm:
                            w, h = dm
                cat, conf, why = classify(fn or full, full, w, h,
                                          tag_counts.get(tag, 0))
                assets.append({
                    "k": "i:" + full, "n": full, "d": full, "f": fn or "",
                    "c": cat, "t": tag, "w": w, "h": h,
                    "s": "declarada", "why": why, "cf": conf,
                })

            # b) Archivos no cubiertos por una imagen declarada
            media = (RT.files.get("images", []) + RT.files.get("video", []))
            for fn in media:
                done += 1
                if time.time() >= nexty:
                    yield 0.95 * done / total
                    nexty = time.time() + YIELD_S
                if fn in used_files:
                    continue
                low = fn.lower()
                w = h = 0
                if not low.endswith(EXT_VID) and dims_read < DIM_LIMIT:
                    dm = image_dims(fn)
                    dims_read += 1
                    if dm:
                        w, h = dm
                base = fn.replace("\\", "/").split("/")[-1]
                cat, conf, why = classify(fn, base, w, h, 0)
                assets.append({
                    "k": "f:" + fn, "n": base, "d": "", "f": fn,
                    "c": cat, "t": base.split(".")[0], "w": w, "h": h,
                    "s": "archivo", "why": why, "cf": conf,
                })

            assets.sort(key=lambda a: (CAT_ORDER.index(a["c"]) if a["c"] in CAT_ORDER else 9,
                                       a["n"].lower()))
            yield 0.94
            try:
                gal_assign_chars(assets)
            except Exception as e:
                log_error("gal_assign_chars", e)
                RT.gal_chars = {}
            RT.gal_assets = assets
            gal_build_index()
            RT.gal_counts = gal_count_by_cat(assets)
            RT.gal_dims_read = dims_read
            RT.gal_seconds = round(time.time() - t0, 2)
            RT.gal_ready = True
            RT.gal_msg = "%d recursos en %.2f s (%d cabeceras leidas)" % (
                len(assets), RT.gal_seconds, dims_read)
            yield 0.96
            _out = [None]
            for _x in gal_save_cache_gen(_out):
                yield 0.98
            RT.last_cache = _out[0]
        except Exception as e:
            log_error("gal_scan", e)
            RT.gal_msg = "Error durante el analisis: %s" % e
        finally:
            RT.gal_scanning = False

    def gal_scan(force=False):
        """De una sola vez (pruebas, boton 'Reanalizar' en modo sincrono)."""
        run_sync(gal_scan_gen(force))
        return True

    def gal_prepare_gen(force=False):
        """Todo en segundo plano: inventario del juego, cache si sirve y, si
        no, analisis completo. Nada de esto ocurre en el hilo de la pantalla."""
        if not RT.ready:
            scan_all(vars_too=False)       # el store se lee solo desde la pantalla
            yield 0.02
        if not force and not RT.gal_ready:
            if gal_load_cache():
                return
            yield 0.05
        for p in gal_scan_gen(force):
            yield 0.05 + 0.95 * p

    def gal_ensure(force=False):
        if job_running("gal"):
            return
        if RT.gal_ready and not force:
            return
        job_start("gal", lambda: gal_prepare_gen(force), "Preparando la galeria")

    def gal_count_by_cat(assets):
        c = {}
        for a in assets:
            cat = category_of(a)
            c[cat] = c.get(cat, 0) + 1
        return c

    # ---------- 2.6 Cache en disco ----------------------------------
    def gal_save_cache():
        out = [None]
        run_sync(gal_save_cache_gen(out))
        RT.last_cache = out[0]
        return out[0]

    def gal_save_cache_gen(out=None):
        return write_json_gen(_savedir_path("umod_gallery.json"), _gal_payload(), out)

    def _gal_payload():
        return ({
            "format":  2,
            "game_id": game_id(),
            "chars":   RT.gal_chars,
            "count":   len(RT.gal_assets),
            "files":   RT.files.get("total", 0),
            "assets":  RT.gal_assets,
        })

    def gal_load_cache():
        p = _savedir_path("umod_gallery.json")
        if not p or not os.path.exists(p):
            return False
        try:
            f = open(p, "r")
            try:
                data = json.load(f)
            finally:
                f.close()
        except Exception as e:
            log_error("gal_load_cache", e)
            return False
        if data.get("format") != 2 or data.get("game_id") != game_id():
            return False       # cache de una version anterior (sin personajes)
        if data.get("files") != RT.files.get("total", 0):
            return False       # cambio el numero de archivos: reanalizar
        try:
            RT.gal_assets = data.get("assets", [])
            RT.gal_chars = data.get("chars", {}) or {}
            gal_build_index()
            RT.gal_counts = gal_count_by_cat(RT.gal_assets)
            RT.gal_ready = True
            RT.gal_msg = "%d recursos (desde cache)" % len(RT.gal_assets)
            return True
        except Exception as e:
            log_error("gal_load_cache2", e)
            return False

    # ---------- 2.7 Estado por recurso ------------------------------
    def category_of(a):
        """Categoria efectiva. Precedencia: tu correccion manual >
        adaptador del juego (Fase 9) > heuristica."""
        try:
            ov = _P().umod_cat or {}
            if a["k"] in ov:
                return ov[a["k"]]
        except Exception:
            pass
        if ADAPTERS:
            try:
                c = ad_category(a)
                if c:
                    return c
            except Exception:
                pass
        return a.get("c", "other")

    def gal_name(a):
        """Nombre visible: el que da el adaptador, si lo hay."""
        if ADAPTERS:
            try:
                n = ad_asset_name(a)
                if n:
                    return n
            except Exception:
                pass
        return a.get("n", "")

    def set_category(a, cat):
        try:
            ov = dict(_P().umod_cat or {})
            ov[a["k"]] = cat
            _P().umod_cat = ov
            RT.gal_counts = gal_count_by_cat(RT.gal_assets)
        except Exception as e:
            log_error("set_category", e)

    def is_fav(a):
        try:
            return a["k"] in (_P().umod_favs or set())
        except Exception:
            return False

    def toggle_fav(a):
        try:
            s = set(_P().umod_favs or set())
            if a["k"] in s:
                s.discard(a["k"])
            else:
                s.add(a["k"])
            _P().umod_favs = s
        except Exception as e:
            log_error("toggle_fav", e)

    def is_seen(a):
        try:
            seen = _P().umod_seen or set()
            if a.get("d") and a["d"] in seen:
                return True
            if a.get("t") and a["t"] in seen:
                return True
        except Exception:
            pass
        return False

    def is_locked(a):
        if show_all():
            return False
        # Los archivos sueltos no tienen seguimiento posible: no se bloquean.
        if a.get("s") == "archivo":
            return False
        return not is_seen(a)

    def show_all():
        try:
            return bool(_P().umod_show_all)
        except Exception:
            return True

    def toggle_show_all():
        try:
            _P().umod_show_all = not bool(_P().umod_show_all)
        except Exception as e:
            log_error("toggle_show_all", e)

    def seen_count():
        try:
            return len(_P().umod_seen or set())
        except Exception:
            return 0

    def clear_seen():
        try:
            _P().umod_seen = set()
        except Exception as e:
            log_error("clear_seen", e)

    # ---------- 2.8 Registro de lo que el jugador ve -----------------
    # Se llama antes de cada interaccion. Solo consulta tags visibles:
    # es una operacion barata.
    def seen_tick():
        try:
            P = _P()
            seen = P.umod_seen
            if seen is None:
                seen = set()
            added = False
            layers = getattr(renpy.config, "layers", None) or ["master"]
            for L in layers:
                try:
                    tags = renpy.get_showing_tags(L)
                except Exception:
                    continue
                for t in tags:
                    if t not in seen:
                        seen.add(t)
                        added = True
                    try:
                        at = renpy.get_attributes(t, L)
                    except Exception:
                        at = None
                    if at:
                        full = t + " " + " ".join(to_text(x) for x in at)
                        if full not in seen:
                            seen.add(full)
                            added = True
            if added:
                P.umod_seen = seen
        except Exception:
            pass

    # ---------- 2.9 Filtrado y paginacion ---------------------------
    def gal_filter(cat, query, only_favs, only_seen):
        q = to_text(query or "").strip().lower()
        out = []
        hide = False
        try:
            hide = bool(ADAPTERS and RT.ad_active)
        except Exception:
            hide = False
        for a in RT.gal_assets:
            if hide and ad_hidden(a):
                continue
            if cat != "all" and category_of(a) != cat:
                continue
            if only_favs and not is_fav(a):
                continue
            if only_seen and not is_seen(a):
                continue
            if q and q not in a["n"].lower() and q not in a.get("f", "").lower() \
                    and q not in gal_name(a).lower():
                continue
            out.append(a)
        return out

    def gal_pages(items):
        n = len(items)
        return 1 if n == 0 else (n + GAL_PAGE - 1) // GAL_PAGE

    def gal_page(items, page):
        try:
            start = max(0, int(page)) * GAL_PAGE
        except Exception:
            start = 0
        return items[start:start + GAL_PAGE]

    def gal_pad(cells, cols):
        """vpgrid exige rellenar la ultima fila."""
        out = list(cells)
        rest = (-len(out)) % cols
        for _i in range(rest):
            out.append(None)
        return out

    # ---------- 2.10 Vista de usuario (rediseno rc4) -----------------
    #  Pestanas grandes arriba (Personajes, Escenas, Todo, Favoritos).
    #  Personajes muestra tarjetas con retrato; al elegir uno se ven solo
    #  sus imagenes. Busqueda bajo demanda y opciones raras en el engranaje.
    SIDE_CATS = [("cg", "Escenas"), ("bg", "Fondos"), ("sprite", "Personajes"),
                 ("anim", "Animaciones"), ("video", "Videos"), ("other", "Otros"),
                 ("ui", "Interfaz")]
    SCENE_CATS = ("cg", "anim", "video")

    # rc11: aspecto de "sala de proyeccion": fondo ciruela muy oscuro, las
    # tarjetas como fotos enmarcadas y una sola luz de color, el ambar del
    # proyector, para lo que se elige y para "Jugar". Esquinas redondeadas
    # dibujadas por el propio mod (RB), sin archivos de imagen.
    THEME = {
        "bg":        "#15121b",   # fondo de la galeria
        "well":      "#1c1825",   # huecos: contenedor de pestanas, fondo de miniaturas
        "card":      "#231e2e",   # tarjetas
        "hover":     "#2e273c",   # tarjeta o boton bajo el raton / con foco
        "sel":       "#3b3150",   # filtro elegido
        "panel":     "#211c2b",   # carteles y menus
        "line":      "#ffffff1a",
        "text":      "#f2ecf8",
        "muted":     "#aaa1bd",
        "dim":       "#867d99",
        "accent":    "#f2b55e",   # ambar
        "accent_hi": "#ffca80",
        "on_accent": "#25190a",
        "warn":      "#ff9b80",
        "scrim":     "#0a080ed8",
        "viewer":    "#0b090f",
    }
    G_BG     = THEME["bg"]
    G_BAR    = THEME["bg"]
    G_CARD   = THEME["card"]
    G_HOVER  = THEME["hover"]
    G_SEL    = THEME["sel"]
    G_ACCENT = THEME["accent"]
    G_TEXT   = THEME["text"]
    G_MUTED  = THEME["muted"]
    G_STAR   = THEME["accent"]
    G_WARN   = THEME["warn"]

    # ---------- formas redondeadas generadas (sin archivos) ----------
    #  Un PNG pequeno (2r+4 px de lado) con el rectangulo redondeado
    #  suavizado, hecho con zlib, y un Frame que estira el centro: sirve para
    #  cualquier tamano de boton o tarjeta. Si algo falla, color liso.
    import zlib as _zlib
    _RB = {}

    def _rgba(c):
        c = to_text(c).lstrip("#")
        if len(c) == 3:
            c = "".join(x * 2 for x in c)
        if len(c) == 6:
            c += "ff"
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4, 6))

    def _png_rgba(w, h, rows):
        raw = bytearray()
        for row in rows:
            raw.append(0)
            raw.extend(row)
        def chunk(t, data):
            return struct.pack(">I", len(data)) + t + data + \
                struct.pack(">I", _zlib.crc32(t + data) & 0xffffffff)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
                chunk(b"IDAT", _zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))

    def _cover(px, py, x0, y0, x1, y1, r):
        """Cuanto del pixel (px, py) cae dentro del rectangulo redondeado."""
        qx = min(max(px, x0 + r), x1 - r)
        qy = min(max(py, y0 + r), y1 - r)
        d = math.sqrt((px - qx) ** 2 + (py - qy) ** 2)
        if r <= 0:
            inside = x0 <= px <= x1 and y0 <= py <= y1
            return 1.0 if inside else 0.0
        return max(0.0, min(1.0, r - d + 0.5))

    def round_png(r, color, ring=0):
        n = 2 * r + 4
        cr, cg, cb, ca = _rgba(color)
        rows = []
        for y in range(n):
            row = bytearray()
            for x in range(n):
                px, py = x + 0.5, y + 0.5
                a = _cover(px, py, 0, 0, n, n, r)
                if ring:
                    a -= _cover(px, py, ring, ring, n - ring, n - ring, max(0, r - ring))
                a = max(0.0, min(1.0, a))
                row.extend((cr, cg, cb, int(round(ca * a))))
            rows.append(row)
        return _png_rgba(n, n, rows)

    def RB(color, r=12, ring=0):
        """Fondo redondeado del color dado (radio y borde en px a 1080p)."""
        R = max(2, S(r))
        W = max(1, S(ring)) if ring else 0
        key = (color, R, W)
        d = _RB.get(key)
        if d is None:
            try:
                data = round_png(R, color, W)
                img = _im.Data(data, "umod_rb_%s_%d_%d.png" % (to_text(color).lstrip("#"), R, W))
                d = renpy.store.Frame(img, R + 1, R + 1)
            except Exception as e:
                log_error("RB", e)
                d = renpy.store.Solid(color) if not ring else renpy.store.Null()
            _RB[key] = d
        return d

    def ui_font_bold():
        if _FONT_B[0] is None:
            f = "DejaVuSans-Bold.ttf"
            try:
                if not renpy.loadable(f):
                    f = ui_font()
            except Exception:
                f = ui_font()
            _FONT_B[0] = f
        return _FONT_B[0]

    _FONT_B = [None]

    def chip_label(name, n, sel=False):
        """'Linda  324' con el numero mas discreto."""
        col = THEME["on_accent"] if sel else THEME["dim"]
        return "%s  {size=-3}{color=%s}%d{/color}{/size}" % (esc(name), col, n)

    def fmt_time(t):
        try:
            t = max(0, int(t or 0))
        except Exception:
            t = 0
        return "%d:%02d" % (t // 60, t % 60)

    def noop():
        return None

    # Simbolos y textos con tilde de la galeria: como u"..." con escapes
    # (seguros tambien en Python 2). Todos estan en DejaVuSans.
    ICONS = {
        "x": u"\u2715", "gear": u"\u2699", "prev": u"\u2039", "next": u"\u203a",
        "play": u"\u25b6", "pause": u"II", "star": u"\u2605", "star_off": u"\u2606",
        "restart": u"\u21ba", "back": u"\u2039  Volver",
        "play_from": u"\u25b6   Jugar desde este momento",
        "play_here": u"\u25b6   Jugar desde aqu\u00ed",
        "watch": u"Ver c\u00f3mo transcurre",
        "title": u"Galer\u00eda",
    }

    def _gpref(name, default=False):
        try:
            v = getattr(renpy.store.persistent, name, None)
        except Exception:
            v = None
        return default if v is None else bool(v)

    def gal_show_ui():
        return _gpref("umod_gal_show_ui", False)

    def gal_only_seen():
        return _gpref("umod_gal_only_seen", False)

    def gal_toggle_pref(name):
        try:
            setattr(renpy.store.persistent, name, not _gpref(name, False))
        except Exception as e:
            log_error("gal_toggle_pref", e)
        RT.gal_view = {}

    _FONT = [None]

    def ui_font():
        """DejaVuSans viene con Ren'Py: los simbolos se ven aunque el juego
        use una fuente decorativa sin esos glifos."""
        if _FONT[0] is None:
            f = "DejaVuSans.ttf"
            try:
                if not renpy.loadable(f):
                    f = renpy.store.style.default.font
            except Exception:
                pass
            _FONT[0] = f
        return _FONT[0]

    def _fit(target, avail, gap, lo, hi):
        n = int((avail + gap) // (target + gap))
        n = max(lo, min(hi, n))
        return n, int((avail - gap * (n - 1)) / n)

    def gal_layout():
        """Medidas para la resolucion actual: rejilla de imagenes y de
        tarjetas de personaje."""
        sw, sh = screen_size()
        pad, gap = S(28), S(16)
        top, sub, bottom = S(84), S(58), S(64)
        main_w = sw - pad * 2
        grid_h = sh - top - sub - bottom - pad
        cols, cell_w = _fit(S(300), main_w, gap, 2, 8)
        ratio = max(0.5, min(0.8, float(sh) / max(1, sw)))
        base_h = int(cell_w * ratio)
        name_h = S(36)
        sname_h = S(70)
        # las filas llenan el alto disponible: sin una franja vacia abajo
        # (las miniaturas se recortan para llenar, asi que admiten un poco
        # mas o menos de alto)
        rows, thumb_h = _rows_fit(grid_h, base_h, name_h, gap)
        srows, sthumb_h = _rows_fit(grid_h, base_h, sname_h, gap)
        ccols, card_w = _fit(S(210), main_w, gap, 2, 10)
        card_name_h = S(58)
        card_h = int(card_w * 1.3)
        crows = int((grid_h + gap) // (card_h + card_name_h + gap))
        if crows < 1:
            card_h = max(S(60), grid_h - card_name_h)
            crows = 1
        inset = S(7)
        fs_h = S(64)
        return {"inset": inset, "in_w": cell_w - 2 * inset, "th_in": thumb_h - inset,
                "sthumb_h": sthumb_h, "sth_in": sthumb_h - inset,
                "fs_h": fs_h, "fs_w": int(fs_h * 16 / 9.0),
                "dlg_w": min(sw - 2 * pad, S(1020)), "dlg_th_w": S(360), "dlg_th_h": S(202),
                "sw": sw, "sh": sh, "pad": pad, "gap": gap, "top": top, "sub": sub,
                "bottom": bottom, "main_w": main_w, "grid_h": grid_h,
                "cols": cols, "cell_w": cell_w, "thumb_h": thumb_h, "name_h": name_h,
                "rows": rows, "per": cols * rows,
                "ccols": ccols, "card_w": card_w, "card_h": card_h,
                "card_name_h": card_name_h, "crows": crows, "cper": ccols * crows,
                "sname_h": sname_h, "srows": srows, "sper": cols * srows}

    def _rows_fit(avail, base_h, extra, gap, lo=0.82, hi=1.25):
        """(filas, alto de miniatura) para llenar 'avail' sin deformar demasiado."""
        n = max(1, int((avail + gap) // (base_h + extra + gap)))
        if (avail + gap) / float(n + 1) - gap - extra >= base_h * lo:
            n += 1
        h = (avail + gap) / float(n) - gap - extra
        return n, int(max(S(60), min(h, base_h * hi)))

    def _nfav():
        try:
            return len(renpy.store.persistent.umod_favs or ())
        except Exception:
            return 0

    def gal_chars_list(q=""):
        """[(id, nombre, n, recurso_retrato)] con mas imagenes primero."""
        s = to_text(q or "").strip().lower()
        out = []
        for cid, c in (getattr(RT, "gal_chars", None) or {}).items():
            if s and s not in to_text(c.get("name", "")).lower():
                continue
            out.append((cid, to_text(c.get("name") or cid), int(c.get("n", 0)),
                        (RT.gal_index or {}).get(c.get("p"))))
        out.sort(key=lambda t: (-t[2], t[1].lower()))
        return out

    def gal_char_name(cid):
        """Nombre visible: el del inventario de imagenes o, si el personaje
        habla pero no tiene imagenes propias, el que declara el juego."""
        c = (getattr(RT, "gal_chars", None) or {}).get(cid) or \
            (getattr(RT, "gal_char_src", None) or {}).get(cid) or {}
        if not c.get("name") and to_text(cid).startswith("v_"):
            return _pretty(cid[2:])
        return to_text(c.get("name") or cid)

    IMG_CATS = ("cg", "other", "anim")

    def gal_tabs():
        """Los cuatro apartados: Imagenes, Videos, Escenas (con dialogo) y
        Jugar (entrar en la historia). Videos solo si el juego tiene."""
        out = [("img", u"Im\u00e1genes")]
        if any(is_video(a) for a in (RT.gal_assets or ())):
            out.append(("vid", u"V\u00eddeos"))
        sc = getattr(RT, "scenes", None)
        if sc is None or sc:
            out.append(("scn", "Escenas"))
        return out

    def gal_extra():
        return _gpref("umod_gal_extra", False)

    def gal_items2(tab, who, q):
        """Imagenes o videos de la pestana, filtrados por personaje o ★."""
        if not RT.gal_ready or tab not in ("img", "vid"):
            return []
        show_ui, only, extra = gal_show_ui(), gal_only_seen(), gal_extra()
        try:
            ncat = len(renpy.store.persistent.umod_cat or {})
        except Exception:
            ncat = 0
        key = ("3", tab, who, to_text(q or ""), show_ui, only, extra, len(RT.gal_assets), _nfav(), ncat,
               bool(ADAPTERS and getattr(RT, "ad_active", None)), STORY["ver"],
               getattr(RT, "gal_where", None) is not None)
        cache = getattr(RT, "gal_view", None)
        if cache is None:
            cache = RT.gal_view = {}
        if key in cache:
            return cache[key]
        items = gal_filter("all", q, who == u"\u2605", only)
        if tab == "vid":
            items = [a for a in items if is_video(a)]
        else:
            cats = IMG_CATS + (("bg", "sprite") if extra else ()) + (("ui",) if show_ui else ())
            items = [a for a in items if not is_video(a) and category_of(a) in cats]
        if who and who != u"\u2605":
            items = [a for a in items if who in (a.get("ch") or ())]
        rank = _story_rank()
        items.sort(key=lambda a: rank.get(a["k"], 1 << 30))
        if len(cache) > 40:
            cache.clear()
        cache[key] = items
        return items

    _RANK = {"key": None, "rank": {}}

    def _story_rank():
        """Puesto de cada imagen en el orden de la historia (se calcula una
        vez para todas; los filtros solo conservan ese orden)."""
        key = (STORY["ver"], getattr(RT, "gal_where", None) is not None, len(RT.gal_assets or ()),
               id(RT.gal_assets))
        if _RANK["key"] != key:
            _RANK["rank"] = dict((a["k"], i) for i, a in enumerate(story_sort_assets(RT.gal_assets or [])))
            _RANK["key"] = key
        return _RANK["rank"]

    _CHIPS = {}

    def gal_who_chips(tab, q=""):
        """Filtro por personaje: [(id, nombre, n)]. ★ = favoritas."""
        key = (tab, to_text(q or ""), len(RT.gal_assets or ()), len(getattr(RT, "scenes", None) or ()), CHARS["ver"], STORY["ver"],
               _nfav(), gal_extra(), gal_show_ui(), gal_only_seen())
        hit = _CHIPS.get(key)
        if hit is not None:
            return hit
        out = _who_chips(tab, q)
        if len(_CHIPS) > 20:
            _CHIPS.clear()
        _CHIPS[key] = out
        return out

    def _who_chips(tab, q=""):
        if tab in ("scn", "play"):
            return scene_who_chips(q)
        base = gal_items2(tab, None, q)
        cnt = {}
        for a in base:
            for c in a.get("ch") or ():
                cnt[c] = cnt.get(c, 0) + 1
        out = [(c, gal_char_name(c), n) for c, n in sorted(cnt.items(), key=_chip_order)]
        nf = len(gal_items2(tab, u"\u2605", q))
        if nf:
            out.insert(0, (u"\u2605", u"\u2605 Favoritas", nf))
        return out

    def chips_fit(chips, width, sel=None):
        """Los que caben en una linea (el resto, en "+N mas"). El que esta
        elegido se ensena siempre."""
        out, used = [], S(110)
        for c in chips:
            w = S(34) + S(10) * (len(to_text(c[1])) + len(str(c[2])) + 2)
            if used + w > width:
                break
            out.append(c)
            used += w + S(6)
        if sel is not None and not any(c[0] == sel for c in out):
            for c in chips:
                if c[0] == sel:
                    if out:
                        out[-1] = c
                    else:
                        out.append(c)
                    break
        return out

    TAB_HINT = {
        "img": u"Haz clic en una imagen para verla en grande. Dentro, las flechas pasan a la siguiente.",
        "vid": u"Haz clic en un v\u00eddeo para verlo, con su l\u00ednea de tiempo. Las flechas pasan al siguiente.",
        "scn": u"Elige una escena para verla con su di\u00e1logo o empezar a jugar desde ah\u00ed.",
    }

    def gal_version():
        return "v" + VERSION

    def gal_default_tab():
        return "img"

    def gal_view_items(tab, char, sub, q):
        """Imagenes de la vista actual (cacheado: la pantalla se redibuja a
        menudo y la lista puede tener miles de elementos)."""
        if not RT.gal_ready:
            return []
        if tab == "chars" and not char:
            return []
        show_ui, only = gal_show_ui(), gal_only_seen()
        try:
            ncat = len(renpy.store.persistent.umod_cat or {})
        except Exception:
            ncat = 0
        key = (tab, char, sub, to_text(q or ""), show_ui, only, len(RT.gal_assets),
               _nfav(), ncat, bool(ADAPTERS and getattr(RT, "ad_active", None)))
        cache = getattr(RT, "gal_view", None)
        if cache is None:
            cache = RT.gal_view = {}
        if key in cache:
            return cache[key]
        items = gal_filter("all", q, tab == "fav", only)
        if tab == "chars":
            items = [a for a in items if char in (a.get("ch") or ())]
            if sub == "scenes":
                items = [a for a in items if category_of(a) in SCENE_CATS]
            elif sub == "sprites":
                items = [a for a in items if category_of(a) == "sprite"]
        elif tab == "scenes":
            items = [a for a in items if category_of(a) in SCENE_CATS]
        elif not show_ui:
            items = [a for a in items if category_of(a) != "ui"]
        if len(cache) > 30:
            cache.clear()
        cache[key] = items
        return items

    def gal_char_subs(char, q=""):
        """Filtros dentro de un personaje; solo si hay de los dos tipos."""
        allx = gal_view_items("chars", char, "all", q)
        ns = len([a for a in allx if category_of(a) in SCENE_CATS])
        np = len([a for a in allx if category_of(a) == "sprite"])
        if not ns or not np:
            return []
        return [("all", "Todo", len(allx)), ("scenes", "Escenas", ns), ("sprites", "Retratos", np)]

    def gal_crumbs(tab, char, sub):
        """Donde estas, en palabras: "Personajes  >  Alice  >  Escenas"."""
        names = {"chars": "Personajes", "scenes": "Escenas", "all": "Todo", "fav": "Favoritos"}
        out = [names.get(tab, tab)]
        if tab == "chars" and char:
            out.append(gal_char_name(char))
            if sub == "scenes":
                out.append("Escenas")
            elif sub == "sprites":
                out.append("Retratos")
        return u"  \u203a  ".join(out)

    def gal_hint(cards_mode, viewing):
        if viewing:
            return u"Flechas: pasar.  Clic: ocultar botones.  Esc: volver."
        if cards_mode:
            return "Elige un personaje para ver sus imagenes"
        return u"Clic en una imagen para verla en grande. Rueda del rat\u00f3n: pasar p\u00e1gina."

    def gal_progress():
        """None si la galeria esta lista; si no, (fraccion o None, texto)."""
        j = JOBS.get("gal")
        if j and j["status"] == "corriendo":
            return (j["p"], "Preparando la galeria...")
        if not RT.gal_ready:
            if j and j["status"] == "error":
                return (None, "No se pudo preparar la galeria. Detalle en umod_errors.log")
            return (0.0, "Preparando la galeria...")
        return None

    def gal_short(text, width):
        t = to_text(text)
        n = max(6, int(width // max(1, S(9))))
        return t if len(t) <= n else t[:n - 1] + "..."

    def gal_pages_n(items, per):
        n = len(items)
        return 1 if n == 0 else (n + per - 1) // per

    def gal_slice(items, page, per):
        p = max(0, min(int(page), gal_pages_n(items, per) - 1))
        return items[p * per:(p + 1) * per], p

    def gal_count_text(n, noun_one, noun_many):
        return "%d %s" % (n, noun_one if n == 1 else noun_many)

    def gal_page_text(page, npages):
        return u"P\u00e1gina %d de %d" % (page + 1, npages)

    def is_video(a):
        return category_of(a) == "video" or (a.get("f", "") or "").lower().endswith(EXT_VID)

    # ---------- 2.10b Miniaturas en disco (rc7) -----------------------
    #  Antes cada miniatura descomprimia la imagen original completa
    #  (20-60 ms cada una): una pagina tardaba un segundo o mas. Ahora el
    #  trabajador genera una copia pequena (lado mayor 384 px) la primera
    #  vez que se ve, la guarda en <saves>/umod_thumbs/ y las siguientes
    #  veces carga al instante. Solo se generan las que se miran (y la
    #  pagina siguiente). Si algo falla 5 veces seguidas, se vuelve al
    #  metodo anterior sin romper nada.
    import hashlib as _hl
    import io as _io
    THUMB_MAX = 384
    TH = {"dir": None, "have": None, "disp": {}, "req": [], "reqset": set(),
          "fail": 0, "ver": 0, "off": False, "made": 0, "vis": set(), "nextvis": set()}
    try:
        if getattr(renpy, "emscripten", False):
            TH["off"] = True                      # version web: sin disco propio
    except Exception:
        pass

    def _pg():
        try:
            import pygame_sdl2 as pg
        except Exception:
            import pygame as pg
        return pg

    def _th_dir():
        if TH["dir"] is None:
            d = _savedir_path("umod_thumbs")
            try:
                if d and not os.path.isdir(d):
                    os.makedirs(d)
            except Exception as e:
                log_error("miniaturas.dir", e)
                d = ""
            TH["dir"] = d or ""
        return TH["dir"]

    def _th_have():
        if TH["have"] is None:
            d = _th_dir()
            have = {}
            try:
                for x in (os.listdir(d) if d else ()):
                    if x.endswith(".jpg") or x.endswith(".png"):
                        have[x[:-4]] = x
            except Exception:
                pass
            TH["have"] = have
        return TH["have"]

    def _th_key(a):
        raw = "%s|%s|%s|%s" % (a.get("k"), a.get("f"), a.get("w"), a.get("h"))
        if not PY2:
            raw = raw.encode("utf-8", "replace")
        return _hl.md5(raw).hexdigest()[:24]

    def _th_eligible(a):
        f = (a.get("f") or "").lower()
        return bool(f) and f.endswith(EXT_IMG) and bool(a.get("w")) and bool(a.get("h"))

    def _th_disp(key):
        d = TH["disp"].get(key)
        if d is not None:
            return d
        fname = _th_have().get(key)
        if not fname:
            return None
        try:
            f = open(os.path.join(_th_dir(), fname), "rb")
            try:
                data = f.read()
            finally:
                f.close()
            d = _im.Data(data, fname)
        except Exception as e:
            log_error("miniatura.carga", e)
            return None
        if len(TH["disp"]) > 800:
            TH["disp"].clear()
        TH["disp"][key] = d
        return d

    def thumb_request(a, soon=True, urgent=True):
        if TH["off"] or not _th_eligible(a):
            return
        key = _th_key(a)
        if key in _th_have():
            return
        if key in TH["reqset"]:
            if soon:                             # ya pedida (p. ej. de fondo): pasa delante
                for i, (k, _a) in enumerate(TH["req"]):
                    if k == key:
                        if i:
                            TH["req"].insert(0, TH["req"].pop(i))
                        break
            return
        TH["reqset"].add(key)
        if soon:
            TH["req"].insert(0, (key, a))
        else:
            TH["req"].append((key, a))
        thumbs_kick(urgent)

    def thumbs_kick(urgent=False):
        if TH["req"] and not job_running("thumbs"):
            job_start("thumbs", thumbs_gen, "Preparando miniaturas", front=urgent)

    TICK_HOOKS.append(lambda: thumbs_kick(False))     # nunca se queda una peticion colgada
    TICK_HOOKS.append(lambda: _pred_tick())

    def thumb_pending(a):
        return (not TH["off"]) and _th_eligible(a) and _th_key(a) not in _th_have()

    def _th_make(key, a):
        src = a["f"]
        fobj = open_game_file(src)
        try:
            data = fobj.read()
        finally:
            try:
                fobj.close()
            except Exception:
                pass
        surf = renpy.display.pgrender.load_image(_io.BytesIO(data), src)
        w, h = surf.get_size()
        sc = min(1.0, float(THUMB_MAX) / max(1, max(w, h)))
        tw, th = max(1, int(w * sc)), max(1, int(h * sc))
        pg = _pg()
        try:
            small = pg.transform.smoothscale(surf, (tw, th))
        except Exception:
            small = pg.transform.scale(surf, (tw, th))
        d = _th_dir()
        # JPG ocupa ~5 veces menos; si este motor no sabe guardarlo, PNG.
        for ext in (".jpg", ".png"):
            tmp = os.path.join(d, key + ".tmp" + ext)
            try:
                pg.image.save(small, tmp)
                f = open(tmp, "rb")
                try:
                    head = f.read(4)
                finally:
                    f.close()
                # comprobar que el motor guardo de verdad ese formato
                if not head.startswith(b"\xff\xd8" if ext == ".jpg" else b"\x89PNG"):
                    raise IOError("formato no soportado")
                _replace_file(tmp, os.path.join(d, key + ext))
                return key + ext
            except Exception:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass
        raise IOError("no se pudo guardar la miniatura")

    def _th_pick():
        """Siguiente miniatura: primero las de la pagina que se esta
        mirando, despues las de la pagina siguiente, despues el resto."""
        req = TH["req"]
        for want in (TH["vis"], TH["nextvis"]):
            if want:
                for i, (k, _a) in enumerate(req):
                    if k in want:
                        return req.pop(i)
        return req.pop(0)

    def thumbs_visible(cells, upcoming=()):
        """La pantalla avisa de que miniaturas tiene a la vista."""
        vis = set(c["tkey"] for c in cells if c.get("pending") and c.get("tkey"))
        if vis != TH["vis"]:
            TH["vis"] = vis
        nv = set(upcoming)
        if nv != TH["nextvis"]:
            TH["nextvis"] = nv

    def thumbs_vis_pending():
        return bool(TH["vis"]) and any(k in TH["reqset"] for k in TH["vis"])

    def thumbs_gen():
        while TH["req"]:
            try:
                key, a = _th_pick()
            except IndexError:
                break
            try:
                fname = _th_make(key, a)
                _th_have()[key] = fname
                TH["ver"] += 1
                TH["made"] += 1
                TH["fail"] = 0
            except Exception as e:
                TH["fail"] += 1
                log_error("miniatura %s" % a.get("f"), e)
                if TH["fail"] >= 5:
                    TH["off"] = True              # sin miniaturas en disco: metodo anterior
                    TH["ver"] += 1
                    TH["req"] = []
                    TH["reqset"] = set()
                    return
            finally:
                TH["reqset"].discard(key)
            yield 0.5

    # ---------- 2.10c Paginas precalculadas (rc7) --------------------
    #  La pantalla se vuelve a evaluar entera con cada movimiento del raton
    #  (la linea de ayuda). Antes eso recalculaba miniaturas, nombres y
    #  estados de toda la pagina; ahora se calcula una vez por pagina.
    _CELLS = {}

    def _cells_key(kind, tab, who, q, page, L, n):
        return (kind, tab, who, to_text(q or ""), page, L["cell_w"], L["thumb_h"], n, STORY["ver"], CHARS["ver"],
                _nfav(), TH["ver"], getattr(RT, "gal_where", None) is not None,
                len(getattr(RT, "scenes", None) or ()), bool(getattr(RT, "tr_entry", None)),
                len(RT.gal_assets or ()), bool(getattr(RT, "sa_ready", False)), bool(getattr(RT, "g_ready", False)))

    def gal_cells(tab, who, q, shown, page, L):
        key = _cells_key("img", tab, who, q, page, L, tuple(a.get("k") for a in shown))
        hit = _CELLS.get(key)
        if hit is not None:
            return hit
        out = []
        for gi, a in enumerate(shown):
            locked, video = is_locked(a), is_video(a)
            th = None
            if not locked and not video:
                th = thumb(a, L["in_w"], L["th_in"], cover=True)
            play = gal_can_play(a)
            pend = th is None and not locked and not video and thumb_pending(a)
            out.append({"a": a, "idx": page * L["per"] + gi, "locked": locked, "video": video,
                        "thumb": th, "pending": pend, "tkey": _th_key(a) if pend else None,
                        "fav": is_fav(a), "name": gal_short(gal_name(a), L["in_w"]),
                        "alt": gal_name(a), "play": play,
                        "tip": ("Ver el video" if video else "Ver en grande") +
                               ("  -  tambien puedes jugar desde este momento" if play else "")})
        if len(_CELLS) > 30:
            _CELLS.clear()
        _CELLS[key] = out
        return out

    def scene_cells(who, q, shown, page, L):
        key = _cells_key("scn", "scn", who, q, page, L, tuple((e.get("id"), e.get("n"), len(e.get("branches") or ())) for e in shown))
        hit = _CELLS.get(key)
        if hit is not None:
            return hit
        out = []
        for e in shown:
            ta = scene_thumb(e)
            th = None
            if ta is not None and not is_video(ta):
                th = thumb(ta, L["in_w"], L["sth_in"], cover=True)
            pend = th is None and ta is not None and thumb_pending(ta)
            names = ", ".join(gal_char_name(c) for c in (e.get("who") or [])[:3])
            out.append({"e": e, "thumb": th, "pending": pend, "tkey": _th_key(ta) if pend else None,
                        "title": gal_short(scene_title(e), L["in_w"] * 0.92),
                        "sub": gal_short(scene_sub(e), L["in_w"]),
                        "names": gal_short(names, L["in_w"] * 0.72) if names else "",
                        "lines": lines_text(e.get("n", 0)),
                        "nb": len(e.get("branches") or ()),
                        "quote": gal_short(e.get("first", ""), L["in_w"] * 2),
                        "alt": scene_title(e),
                        "tip": "Elige que hacer con esta escena  -  " + e.get("first", "")[:60]})
        if len(_CELLS) > 30:
            _CELLS.clear()
        _CELLS[key] = out
        return out

    _PF = {"at": None, "keys": ()}

    def prefetch_thumbs(seq, page, per, is_scn):
        """Pide en segundo plano las miniaturas de la pagina siguiente (y
        devuelve sus claves). Solo al cambiar de pagina o de lista."""
        at = (id(seq), len(seq), page, per, is_scn, TH["off"])
        if _PF["at"] == at:
            return _PF["keys"]
        keys = []
        for x in seq[(page + 1) * per:(page + 2) * per]:
            a = scene_thumb(x) if is_scn else x
            if a is not None and thumb_pending(a):
                keys.append(_th_key(a))
                thumb_request(a, soon=False, urgent=False)
        _PF["at"] = at
        _PF["keys"] = tuple(keys)
        return _PF["keys"]

    def tab_opened(tid):
        """Al entrar en Escenas, su busqueda pasa delante de lo demas."""
        if tid == "scn":
            scenes_ensure(front=True)

    # ---------- 2.10d Cartel de escena: ver o jugar (rc7) -------------
    def play_ready():
        try:
            if SCRIPT and not RT.sa_ready:
                return False
            if GRAPH and not RT.g_ready:
                return False
        except Exception:
            return True
        return True

    def play_prepare():
        """Al abrir el cartel: lo que hace falta para 'Jugar' pasa delante."""
        try:
            if SCRIPT and not RT.sa_ready:
                sa_ensure()
                job_bump("sa")
            if GRAPH and not RT.g_ready:
                ng_ensure()
                job_bump("ng")
        except Exception as e:
            log_error("play_prepare", e)

    def play_progress_text():
        parts = []
        for name in ("sa", "ng"):
            j = JOBS.get(name)
            if j and j["status"] == "corriendo":
                parts.append(int(j["p"] * 100))
        if not parts:
            return "Preparando la historia..."
        return "Preparando la historia...  %d%%" % (sum(parts) // len(parts))

    def scene_note(e):
        if scene_exact(e):
            return u"Ya llegaste aqu\u00ed jugando: la partida empezar\u00e1 exactamente como la dejaste en ese punto."
        return u"Lo anterior se simula a partir del gui\u00f3n; puede haber peque\u00f1as diferencias (puntos, decisiones)."

    # ---------- 2.11 Displayables -----------------------------------
    def thumb(a, bw=None, bh=None, cover=False):
        """Miniatura para una celda de bw x bh: la copia pequena en disco si
        existe; si no, se pide al trabajador y mientras tanto no se
        descomprime el original (salvo que las miniaturas en disco esten
        desactivadas por fallos). cover=True llena la celda recortando los
        bordes (como una foto enmarcada), salvo imagenes de otra forma muy
        distinta (sprites altos), que se ven enteras."""
        bw = bw or S(268)
        bh = bh or S(150)
        try:
            if is_video(a):
                return None
            f, d, w, h = a.get("f", ""), a.get("d", ""), a.get("w", 0), a.get("h", 0)
            if not TH["off"] and _th_eligible(a):
                key = _th_key(a)
                if key in _th_have():
                    td = _th_disp(key)
                    if td is not None:
                        # la copia mide como mucho THUMB_MAX: se ajusta en la
                        # tarjeta con la tarjeta grafica (zoom), sin recalcular
                        sc0 = min(1.0, float(THUMB_MAX) / max(w, h))
                        return _fit_box(td, max(1, int(w * sc0)), max(1, int(h * sc0)), bw, bh, cover)
                else:
                    thumb_request(a)
                    return None
            if f and w and h:
                return _fit_box(f, w, h, bw, bh, cover)
            if f:
                return _im.Scale(f, bw, bh)
            if d:
                if at_least(7, 4):
                    return _Transform(d, fit="contain", xysize=(bw, bh))
                return d
        except Exception as e:
            log_error("thumb", e)
        return None

    def _fit_box(disp, w, h, bw, bh, cover):
        """contain: entera; cover: llena la celda recortando (centrada, o algo
        hacia arriba en imagenes altas, donde suelen estar las caras)."""
        r_img = float(w) / max(1, h)
        r_box = float(bw) / max(1, bh)
        if not cover or r_img / r_box > 1.7 or r_box / r_img > 1.7:
            return _zoom(disp, min(float(bw) / w, float(bh) / h))
        sc = max(float(bw) / w, float(bh) / h)
        cw = min(w, int(round(bw / sc)))
        ch = min(h, int(round(bh / sc)))
        cx = (w - cw) // 2
        cy = int((h - ch) * (0.25 if r_img < r_box else 0.5))
        return _Transform(disp, crop=(int(cx), int(cy), int(cw), int(ch)), zoom=sc)

    def _zoom(disp, sc):
        """Escalado en la tarjeta grafica (Transform zoom) en lugar de im.Scale,
        que redimensiona con el procesador cada imagen (decenas de ms)."""
        return _Transform(disp, zoom=sc)

    _PRED = {"cur": [], "at": None}

    def viewer_predict(items, idx):
        """Mientras se mira una imagen, Ren'Py va cargando en segundo plano
        la anterior y las dos siguientes: pasar de una a otra es inmediato."""
        try:
            at = (id(items), idx)
            if _PRED["at"] == at:
                return                      # la pantalla se reevalua a menudo: solo al cambiar
            _PRED["at"] = at
            if 0 <= idx < len(items) and VID["key"] != items[idx].get("k"):
                video_reset()
            sp = getattr(renpy, "start_predict", None)
            st = getattr(renpy, "stop_predict", None)
            if not callable(sp) or not callable(st):
                return
            want = []
            for j in (idx + 1, idx + 2, idx - 1):
                if 0 <= j < len(items) and not is_video(items[j]) and not is_locked(items[j]):
                    fv = fullview(items[j])
                    if fv is not None:
                        want.append(fv)
            old = _PRED["cur"]
            if old:
                st(*old)
            if want:
                sp(*want)
            _PRED["cur"] = want
        except Exception as e:
            log_error("viewer_predict", e)

    def _pred_tick():
        if _PRED["cur"] and not POWER.get("full"):
            viewer_predict_stop()           # galeria cerrada: suelta lo precargado

    def viewer_predict_stop():
        if VID["key"] is not None:
            video_reset()
        if not _PRED["cur"] and _PRED["at"] is None:
            return
        try:
            if _PRED["cur"]:
                renpy.stop_predict(*_PRED["cur"])
        except Exception:
            pass
        _PRED["cur"] = []
        _PRED["at"] = None

    def portrait(a, cw, ch):
        """Retrato de una tarjeta de personaje: si la imagen es mas alta que
        la tarjeta (un sprite de cuerpo entero), se muestra la parte de
        arriba (la cara) en lugar de encogerla entera."""
        try:
            if a is None or is_video(a):
                return None
            f, w, h = a.get("f", ""), a.get("w", 0), a.get("h", 0)
            if f and w and h and float(h) / w > float(ch) / cw:
                sh = max(1, int(h * float(cw) / w))
                return _im.Crop(_im.Scale(f, cw, sh), (0, 0, cw, min(ch, sh)))
            return thumb(a, cw, ch)
        except Exception as e:
            log_error("portrait", e)
            return None

    def viewer_box(a, chrome, L, can_play=False):
        """(ancho, alto, centro y) para la imagen o el video del visor: con
        los controles a la vista, la imagen queda entre la barra de arriba y
        los de abajo; sin ellos, ocupa casi toda la pantalla."""
        sw, sh = L["sw"], L["sh"]
        if not chrome:
            return int(sw * 0.98), int(sh * 0.96), sh // 2
        top = S(80)
        bottom = S(16) + L["fs_h"] + S(12)
        if is_video(a):
            bottom += S(58) + S(12)
        if can_play:
            bottom += S(46) + S(12)
        avail = max(S(200), sh - top - bottom - S(8))
        return int(sw * 0.86), avail, top + avail // 2

    def fullview(a, bw=None, bh=None):
        """Imagen del visor: lo mas grande posible sin recortar."""
        sw, sh = screen_size()
        bw, bh = bw or int(sw * 0.96), bh or int(sh * 0.90)
        try:
            f, d, w, h = a.get("f", ""), a.get("d", ""), a.get("w", 0), a.get("h", 0)
            if f and w and h:
                return _zoom(f, min(float(bw) / w, float(bh) / h))
            if d and at_least(7, 4):
                return _Transform(d, fit="contain", xysize=(bw, bh))
            if f:
                return f
            if d:
                return d
        except Exception as e:
            log_error("fullview", e)
        return None

    _VCHAN = ["movie"]

    # ---------- 2.11b Videos con linea de tiempo (rc11) -------------
    #  Antes el visor creaba un Movie nuevo en cada repintado de la
    #  pantalla; Ren'Py reinicia un video cuando su displayable cambia
    #  (config.replay_movie_sprites), asi que podia volver a empezar solo y
    #  no se sabia ni donde empezaba ni donde acababa. Ahora:
    #   - el Movie se guarda y se reutiliza mientras se mira el mismo video;
    #   - posicion y duracion salen del canal (renpy.music.get_pos /
    #     get_duration, Ren'Py 7.4+), con barra, pausa (set_pause) y saltos:
    #     saltar = el mismo archivo con reproduccion parcial "<from X loop 0>"
    #     (al repetirse vuelve al principio);
    #   - un video declarado con mascara (transparencia) se usa tal cual:
    #     se ve bien, pero sin saltos.
    VID = {"key": None, "start": 0.0, "disp": None, "chan": None, "seek": False,
           "paused": False, "alt": False, "wrap": {}}

    def _movie_obj(a):
        d = a.get("d")
        if not d:
            return None
        try:
            g = getattr(renpy, "get_registered_image", None)
            obj = g(d) if g else None
            if obj is None:
                obj = renpy.display.image.images.get(tuple(d.split()), None)
            return obj
        except Exception:
            return None

    def _bare_path(p):
        p = to_text(p or "")
        if p.startswith("<") and ">" in p:
            p = p[p.index(">") + 1:]
        return p

    def _movie_path(a, obj):
        p = a.get("f") or ""
        if not p and obj is not None:
            pl = getattr(obj, "_original_play", None) or getattr(obj, "_play", None)
            if isinstance(pl, (list, tuple)) and pl:
                pl = pl[0]
            if isinstance(pl, string_types):
                p = pl
        return _bare_path(p)

    def video_reset():
        ch = VID.get("chan")
        if ch and VID.get("paused"):
            try:
                renpy.music.set_pause(False, channel=ch)
            except Exception:
                pass
        VID.update(key=None, start=0.0, disp=None, chan=None, seek=False, paused=False, alt=False, wrap={})

    def gal_video(a, bw=None, bh=None):
        """Displayable del video del visor (en bucle). El Movie es el mismo
        mientras se mira ese video (aunque cambie el tamano al ocultar o
        ensenar los controles): Ren'Py no lo reinicia."""
        key = a.get("k")
        if VID["key"] != key:
            video_reset()
            VID["key"] = key
        sw, sh = screen_size()
        bw, bh = bw or int(sw * 0.96), bh or int(sh * 0.78)
        if VID["disp"] is None:
            VID["wrap"] = {}
            VID["disp"] = _video_movie(a)
        if VID["disp"] is None:
            return None
        if not at_least(7, 4):
            return VID["disp"]
        w = VID["wrap"].get((bw, bh))
        if w is None:
            w = VID["wrap"][(bw, bh)] = _Transform(VID["disp"], fit="contain", xysize=(bw, bh))
        return w

    def _video_movie(a):
        try:
            obj = _movie_obj(a)
            masked = obj is not None and bool(getattr(obj, "mask", None) or getattr(obj, "side_mask", False))
            path = _movie_path(a, obj)
            if path and not masked and renpy.loadable(path):
                st = VID["start"]
                disp = renpy.store.Movie(play=path, loop=True, channel=_VCHAN[0])
                if st > 0.05 or VID["alt"]:
                    # Ren'Py 8 solo acepta en play= un archivo que exista, sin
                    # "<from ...>"; el canal de audio/video si lo entiende, y es
                    # quien recibe _play al empezar (default_play_callback).
                    disp._play = "<from %.2f loop 0.0>%s" % (max(0.0, st), path)
                VID["chan"], VID["seek"] = _VCHAN[0], True
            elif a.get("d"):
                disp = a["d"]
                VID["chan"] = getattr(obj, "channel", None) if obj is not None else None
                VID["seek"] = False
            else:
                return None
            return disp
        except Exception as e:
            log_error("gal_video", e)
            return None

    def video_info():
        """{"pos", "dur", "frac", "paused", "seek", "pause"} del video que se mira."""
        ch = VID.get("chan")
        if not ch:
            return None
        pos, dur = 0.0, 0.0
        try:
            pos = renpy.music.get_pos(channel=ch) or 0.0
        except Exception:
            pos = 0.0
        try:
            gd = getattr(renpy.music, "get_duration", None)
            dur = (gd(channel=ch) or 0.0) if gd else 0.0
        except Exception:
            dur = 0.0
        if dur and pos > dur:
            pos = pos % dur
        return {"pos": pos, "dur": dur, "frac": (pos / dur) if dur else 0.0,
                "paused": VID["paused"], "seek": bool(VID["seek"] and dur),
                "pause": callable(getattr(renpy.music, "set_pause", None))}

    def video_toggle_pause():
        ch = VID.get("chan")
        if not ch:
            return
        try:
            VID["paused"] = not VID["paused"]
            renpy.music.set_pause(VID["paused"], channel=ch)
        except Exception as e:
            log_error("video_pause", e)

    def video_seek(frac):
        info = video_info()
        if not info or not info["seek"]:
            return
        if VID["paused"]:
            video_toggle_pause()
        VID["start"] = max(0.0, min(info["dur"] - 0.25, frac * info["dur"]))
        VID["disp"] = None                 # nuevo Movie con "<from X ...>": Ren'Py lo pone ahi

    def video_restart():
        if VID["paused"]:
            video_toggle_pause()
        if VID["seek"]:
            VID["start"] = 0.0
            VID["alt"] = not VID["alt"]    # otro nombre de archivo: obliga a empezar de cero
            VID["disp"] = None

    # ---------- 2.11c Visor: tira de miniaturas y pasar de escena ------
    def viewer_strip(items, idx, L, n=9):
        """Vecinos de la imagen que se mira: [(indice, miniatura, video, bloqueada)]."""
        half = n // 2
        lo = max(0, min(idx - half, len(items) - n))
        out = []
        for i in range(lo, min(len(items), lo + n)):
            a = items[i]
            v, lk = is_video(a), is_locked(a)
            th = None
            if not v and not lk:
                th = thumb(a, L["fs_w"] - S(6), L["fs_h"] - S(6), cover=True)
            out.append((i, th, v, lk))
        return out

    def scene_nav(seq, pick):
        """(anterior, siguiente, posicion, total) de la escena del cartel."""
        if not pick or not seq:
            return None, None, 0, 0
        pid = pick.get("id")
        for i, e in enumerate(seq):
            if e is pick or e.get("id") == pid:
                return (seq[i - 1] if i > 0 else None, seq[i + 1] if i + 1 < len(seq) else None, i, len(seq))
        return None, None, 0, len(seq)

    def scene_thumb_big(e, L):
        ta = scene_thumb(e) if e else None
        if ta is None or is_video(ta):
            return None
        return thumb(ta, L["dlg_th_w"] - S(8), L["dlg_th_h"] - S(8), cover=True)

    def gal_video_error(a):
        return "No se puede reproducir este video (%s)." % (a.get("f") or a.get("d") or "?")

    def play_video(a):
        """Reproduce en un contexto nuevo: la unica forma segura de lanzar
        una interaccion desde una accion de screen."""
        path = a.get("f", "")
        if not path:
            return
        try:
            renpy.invoke_in_new_context(renpy.movie_cutscene, path)
        except Exception as e:
            log_error("play_video", e)

    def asset_lines(a):
        dims = "%d x %d" % (a["w"], a["h"]) if a.get("w") and a.get("h") else "desconocidas"
        return [
            ("Categoria", "%s (deteccion: %s)" % (
                CAT_LABEL.get(category_of(a), category_of(a)), a.get("why", "?"))),
            ("Imagen", a.get("d") or "(no declarada)"),
            ("Archivo", a.get("f") or "(sin resolver)"),
            ("Tamano", dims),
            ("Vista en el juego", "si" if is_seen(a) else "todavia no"),
            ("Personajes", ", ".join(gal_char_name(c) for c in (a.get("ch") or ())) or "ninguno detectado"),
            ("En la historia", gal_play_where(a) or ("todavia buscando..." if getattr(RT, "gal_where", None) is None else "no encontrado")),
        ]

    # ---------- 2.12 Apertura ---------------------------------------
    GAL_SCREEN = "umod_gallery"

    def gallery_open():
        try:
            power_set(True)             # a fondo desde ya (no esperar al siguiente tick)
            try:
                chars_refresh()         # personajes creados con 'default' o con nombre variable
            except Exception as e:
                log_error("chars_refresh", e)
            gal_ensure()
            story_ensure()
            for s in UMOD_SCREENS:
                if s != GAL_SCREEN:
                    renpy.hide_screen(s)
            renpy.show_screen(GAL_SCREEN)
            renpy.restart_interaction()
        except Exception as e:
            log_error("gallery_open", e)

    def gallery_toggle():
        if _in_replay():
            try:
                renpy.end_replay()
            except Exception as e:
                if type(e).__name__ != "EndReplay":
                    log_error("gallery_toggle.replay", e)
                    return
                raise
            return
        try:
            if renpy.get_screen(GAL_SCREEN):
                renpy.hide_screen(GAL_SCREEN)
                renpy.restart_interaction()
            else:
                gallery_open()
        except Exception as e:
            log_error("gallery_toggle", e)

    def gallery_advanced():
        """Desde el menu '...': las herramientas avanzadas (Inspector)."""
        try:
            renpy.hide_screen(GAL_SCREEN)
            open_panel()
        except Exception as e:
            log_error("gallery_advanced", e)


# ---------------------------------------------------------------------
# 3) Registro: F8, seguimiento de imagenes vistas y preparacion
#    automatica en segundo plano al arrancar el juego.
# ---------------------------------------------------------------------
init -988 python:
    umod.register_key("umod_gallery", umod.GAL_KEYS, umod.gallery_toggle)
    umod.add_callback("interact_callbacks", None, umod.seen_tick, "galeria.vistas")
    umod.AUTOSTART.append(umod.gal_ensure)
    umod.AUTOSTART.append(umod.story_ensure)
    umod.AUTOSTART.append(umod.scenes_ensure)
    umod.AUTOSTART.append(umod.gal_where_ensure)
    try:
        # Canal propio: no interrumpe un video que el juego tenga en pantalla.
        renpy.music.register_channel("umod_movie", "music", loop=True, stop_on_mute=False, movie=True)
        umod._VCHAN[0] = "umod_movie"
    except Exception as _e:
        umod.log_error("canal de video", _e)
    if persistent.umod_gal_show_ui is None:
        persistent.umod_gal_show_ui = False
    if persistent.umod_gal_only_seen is None:
        persistent.umod_gal_only_seen = False
    if persistent.umod_gal_extra is None:
        persistent.umod_gal_extra = False


init 998 python:
    # fin automatico de las escenas que se estan viendo
    if hasattr(umod, "LABEL_HOOKS"):
        umod.LABEL_HOOKS.append(umod.rp_on_label)
    else:
        umod.add_callback("label_callbacks", "label_callback", umod.rp_on_label, "galeria.escenas")
    umod.add_callback("interact_callbacks", None, umod.rp_tick, "galeria.escenas.tick")
    umod.collect_char_sources()


# =====================================================================
# 4) INTERFAZ DE LA GALERIA
# =====================================================================

screen umod_gallery():

    modal True
    zorder 1100
    tag umod_panel

    default tab = "img"
    default who = None
    default q = ""
    default searching = False
    default page = 0
    default viewing = None
    default gear = False
    default chrome = True
    default pick = None
    default whoall = False
    default tt = ""

    $ L = umod.gal_layout()
    $ F = umod.ui_font()
    $ FB = umod.ui_font_bold()
    $ T = umod.THEME
    $ tabs = umod.guard(umod.gal_tabs, [("img", "Imagenes")])
    $ ctab = tab if tab in [t[0] for t in tabs] else tabs[0][0]
    $ is_scn = ctab in ("scn", "play")
    $ items = [] if is_scn else umod.guard(umod.gal_items2, [], ctab, who, q)
    $ scenes = umod.guard(umod.scenes_list, [], who, q) if is_scn else []
    $ seq = scenes if is_scn else items
    $ per = L["sper"] if is_scn else L["per"]
    $ npages = umod.gal_pages_n(seq, per)
    $ shown, cpage = umod.gal_slice(seq, page, per)
    $ all_chips = umod.guard(umod.gal_who_chips, [], ctab, q)
    $ chips = umod.chips_fit(all_chips, int(L["main_w"] * 0.66), who)
    $ more_chips = len(all_chips) - len(chips)
    $ prog = umod.guard(umod.gal_progress, None)
    $ scn_busy = is_scn and umod.RT.scenes is None
    $ qval = ScreenVariableInputValue("q", default=False) if umod.HAS_SVIV else None
    $ back = If(whoall, SetScreenVariable("whoall", False), If(pick is not None, SetScreenVariable("pick", None), If(viewing is not None, SetScreenVariable("viewing", None), If(gear, SetScreenVariable("gear", False), If(who is not None, [SetScreenVariable("who", None), SetScreenVariable("page", 0)], Hide("umod_gallery"))))))
    $ cells = (umod.guard(umod.scene_cells, [], who, q, shown, cpage, L) if is_scn else umod.guard(umod.gal_cells, [], ctab, who, q, shown, cpage, L))
    $ upcoming = umod.guard(umod.prefetch_thumbs, (), seq, cpage, per, is_scn)
    $ umod.guard(umod.thumbs_visible, None, cells, upcoming)
    $ umod.guard(umod.gal_focus, None, ctab, pick is not None)
    $ order_busy = umod.guard(umod.story_busy, False)
    $ by = L["top"] + L["sub"] + L["grid_h"] + (L["sh"] - L["top"] - L["sub"] - L["grid_h"]) // 2
    $ v_ok = viewing is not None and 0 <= viewing < len(items)

    key "game_menu" action back
    key "K_ESCAPE" action back
    key "umod_gallery" action Hide("umod_gallery")
    if not v_ok and not gear and pick is None and not whoall:
        key "K_PAGEDOWN" action SetScreenVariable("page", min(npages - 1, cpage + 1))
        key "K_PAGEUP" action SetScreenVariable("page", max(0, cpage - 1))
        key "mousedown_5" action SetScreenVariable("page", min(npages - 1, cpage + 1))
        key "mousedown_4" action SetScreenVariable("page", max(0, cpage - 1))

    add Solid(T["bg"])

    if not v_ok:
        $ umod.guard(umod.viewer_predict_stop, None)

        # ===================== cabecera: titulo, apartados, buscar =====================
        fixed:
            xpos L["pad"]
            xsize L["main_w"]
            ysize L["top"]
            hbox:
                yalign 0.5
                spacing umod.S(26)
                text umod.ICONS["title"] font FB size umod.S(28) color T["text"] yalign 0.5
                frame:
                    yalign 0.5
                    background umod.RB(T["well"], 22)
                    padding (umod.S(5), umod.S(5))
                    hbox:
                        spacing umod.S(4)
                        for tid, tlabel in tabs:
                            $ t_on = ctab == tid
                            textbutton tlabel:
                                action [SetScreenVariable("tab", tid), SetScreenVariable("who", None), SetScreenVariable("page", 0), SetScreenVariable("viewing", None), SetScreenVariable("pick", None), Function(umod.tab_opened, tid)]
                                padding (umod.S(22), umod.S(9))
                                background (umod.RB(T["accent"], 18) if t_on else None)
                                hover_background (umod.RB(T["accent_hi"], 18) if t_on else umod.RB(T["hover"], 18))
                                text_font (FB if t_on else F)
                                text_size umod.S(18)
                                text_color (T["on_accent"] if t_on else T["muted"])
                                text_hover_color (T["on_accent"] if t_on else T["text"])
                                alt tlabel
                                hovered SetScreenVariable("tt", umod.TAB_HINT.get(tid, ""))
                                unhovered SetScreenVariable("tt", "")
            hbox:
                xalign 1.0
                yalign 0.5
                spacing umod.S(10)
                if (searching or q) and qval:
                    button:
                        action qval.Toggle()
                        xsize umod.S(320)
                        ysize umod.S(46)
                        padding (umod.S(18), umod.S(8))
                        background umod.RB(T["well"], 22)
                        hover_background umod.RB(T["hover"], 22)
                        hover_foreground umod.RB(T["accent"], 22, 2)
                        alt "Buscar"
                        fixed:
                            if not q:
                                text "Buscar por nombre..." font F size umod.S(17) color T["dim"] yalign 0.5
                            input:
                                value qval
                                length 30
                                font F
                                size umod.S(17)
                                color T["text"]
                                yalign 0.5
                    textbutton umod.ICONS["x"]:
                        action [SetScreenVariable("q", ""), SetScreenVariable("searching", False), SetScreenVariable("page", 0)]
                        xsize umod.S(46)
                        ysize umod.S(46)
                        text_xalign 0.5
                        text_yalign 0.5
                        background umod.RB(T["well"], 22)
                        hover_background umod.RB(T["hover"], 22)
                        text_font F
                        text_size umod.S(17)
                        text_color T["muted"]
                        text_hover_color T["text"]
                        alt "Borrar la busqueda"
                elif qval:
                    textbutton "Buscar":
                        action [SetScreenVariable("searching", True), qval.Enable()]
                        padding (umod.S(20), umod.S(11))
                        background umod.RB(T["well"], 22)
                        hover_background umod.RB(T["hover"], 22)
                        text_font F
                        text_size umod.S(17)
                        text_color T["muted"]
                        text_hover_color T["text"]
                        hovered SetScreenVariable("tt", "Buscar por nombre")
                        unhovered SetScreenVariable("tt", "")
                textbutton umod.ICONS["gear"]:
                    action ToggleScreenVariable("gear")
                    xsize umod.S(46)
                    ysize umod.S(46)
                    text_xalign 0.5
                    text_yalign 0.5
                    background umod.RB((T["sel"] if gear else T["well"]), 22)
                    hover_background umod.RB(T["hover"], 22)
                    text_font F
                    text_size umod.S(22)
                    text_color (T["accent"] if gear else T["muted"])
                    text_hover_color T["text"]
                    alt "Opciones"
                    hovered SetScreenVariable("tt", u"Opciones de la galer\u00eda")
                    unhovered SetScreenVariable("tt", "")
                textbutton umod.ICONS["x"]:
                    action Hide("umod_gallery")
                    xsize umod.S(46)
                    ysize umod.S(46)
                    text_xalign 0.5
                    text_yalign 0.5
                    background umod.RB(T["well"], 22)
                    hover_background umod.RB(T["hover"], 22)
                    text_font F
                    text_size umod.S(18)
                    text_color T["muted"]
                    text_hover_color T["text"]
                    alt "Cerrar la galeria (F8)"
                    hovered SetScreenVariable("tt", u"Cerrar la galer\u00eda y volver al juego (F8)")
                    unhovered SetScreenVariable("tt", "")

        # ===================== filtro por personaje =====================
        fixed:
            xpos L["pad"]
            ypos L["top"]
            xsize L["main_w"]
            ysize L["sub"]
            hbox:
                yalign 0.5
                spacing umod.S(8)
                if chips:
                    textbutton "Todos":
                        action [SetScreenVariable("who", None), SetScreenVariable("page", 0)]
                        padding (umod.S(17), umod.S(7))
                        background umod.RB((T["sel"] if who is None else T["card"]), 15)
                        hover_background umod.RB(T["hover"], 15)
                        text_font (FB if who is None else F)
                        text_size umod.S(15)
                        text_color (T["accent"] if who is None else T["text"])
                    for cid, cname, cn in chips:
                        $ c_on = who == cid
                        textbutton umod.chip_label(cname, cn):
                            action [SetScreenVariable("who", cid), SetScreenVariable("page", 0)]
                            padding (umod.S(17), umod.S(7))
                            background umod.RB((T["sel"] if c_on else T["card"]), 15)
                            hover_background umod.RB(T["hover"], 15)
                            text_font (FB if c_on else F)
                            text_size umod.S(15)
                            text_color (T["accent"] if c_on else T["text"])
                            alt cname
                            hovered SetScreenVariable("tt", "Ver solo: " + cname)
                            unhovered SetScreenVariable("tt", "")
                    if more_chips > 0:
                        textbutton ("+%d" % more_chips):
                            action SetScreenVariable("whoall", True)
                            padding (umod.S(17), umod.S(7))
                            background umod.RB(T["card"], 15)
                            hover_background umod.RB(T["hover"], 15)
                            text_font FB
                            text_size umod.S(15)
                            text_color T["accent"]
                            alt "Ver todos los personajes"
                            hovered SetScreenVariable("tt", "Ver todos los personajes (%d)" % len(all_chips))
                            unhovered SetScreenVariable("tt", "")
            text ((u"Ordenando seg\u00fan la historia...    " if order_busy and seq else "") + umod.count_text(ctab, len(seq))):
                font F
                size umod.S(15)
                color T["dim"]
                xalign 1.0
                yalign 0.5

        # ===================== contenido =====================
        fixed:
            xpos L["pad"]
            ypos L["top"] + L["sub"]
            xsize L["main_w"]
            ysize L["grid_h"]

            if (prog is not None and not is_scn and not seq) or (scn_busy and not seq):
                vbox:
                    xalign 0.5
                    yalign 0.42
                    spacing umod.S(16)
                    text ("Buscando las escenas de la historia..." if is_scn else umod.esc(prog[1])) font FB size umod.S(22) color T["text"] xalign 0.5
                    if not is_scn and prog[0] is not None:
                        fixed:
                            xalign 0.5
                            xsize umod.S(380)
                            ysize umod.S(8)
                            frame:
                                xsize umod.S(380)
                                ysize umod.S(8)
                                background umod.RB(T["card"], 3)
                                null
                            frame:
                                xsize max(umod.S(8), int(umod.S(380) * prog[0]))
                                ysize umod.S(8)
                                background umod.RB(T["accent"], 3)
                                null
                    text u"Puedes cerrar la galer\u00eda y seguir jugando: se prepara sola." font F size umod.S(15) color T["muted"] xalign 0.5

            elif not seq:
                vbox:
                    xalign 0.5
                    yalign 0.42
                    spacing umod.S(10)
                    if q:
                        text u"Nada coincide con la b\u00fasqueda." font FB size umod.S(22) color T["text"] xalign 0.5
                        text u"Prueba con otra palabra o borra la b\u00fasqueda con la X." font F size umod.S(15) color T["muted"] xalign 0.5
                    elif is_scn:
                        text u"Este juego no tiene escenas con di\u00e1logo que mostrar." font FB size umod.S(22) color T["text"] xalign 0.5
                    else:
                        text u"Aqu\u00ed no hay nada todav\u00eda." font FB size umod.S(22) color T["text"] xalign 0.5
                        if who is not None:
                            text u"Pulsa Todos para quitar el filtro de personaje." font F size umod.S(15) color T["muted"] xalign 0.5

            elif is_scn:
                # ---------- escenas: al elegir una sale el cartel Ver / Jugar ----------
                grid L["cols"] L["srows"]:
                    spacing L["gap"]
                    for gi in range(L["sper"]):
                        if gi < len(cells):
                            $ c = cells[gi]
                            button:
                                action [SetScreenVariable("pick", c["e"]), Function(umod.play_prepare)]
                                hovered SetScreenVariable("tt", c["tip"])
                                unhovered SetScreenVariable("tt", "")
                                xsize L["cell_w"]
                                ysize L["sthumb_h"] + L["sname_h"]
                                padding (L["inset"], L["inset"])
                                background umod.RB(T["card"], 14)
                                hover_background umod.RB(T["hover"], 14)
                                hover_foreground umod.RB(T["accent"], 14, 2)
                                alt c["alt"]
                                vbox:
                                    spacing umod.S(8)
                                    fixed:
                                        xsize L["in_w"]
                                        ysize L["sth_in"]
                                        add Solid(T["well"])
                                        if c["thumb"] is not None:
                                            add c["thumb"] align (0.5, 0.5)
                                        elif c["pending"]:
                                            text "Cargando..." font F size umod.S(14) color T["dim"] align (0.5, 0.5)
                                        else:
                                            text umod.quote(c["e"]) font F size umod.S(14) color T["muted"] xalign 0.5 yalign 0.5 xmaximum L["in_w"] - umod.S(28) text_align 0.5
                                        if c["nb"]:
                                            frame:
                                                xoffset umod.S(8)
                                                yoffset umod.S(8)
                                                padding (umod.S(10), umod.S(4))
                                                background umod.RB(T["accent"], 10)
                                                text ("%d caminos" % c["nb"]) font FB size umod.S(13) color T["on_accent"]
                                    vbox:
                                        spacing umod.S(4)
                                        xoffset umod.S(5)
                                        text umod.esc(c["title"]) font FB size umod.S(16) color T["text"]
                                        fixed:
                                            xsize L["in_w"] - umod.S(10)
                                            ysize umod.S(19)
                                            text umod.esc(c["names"]) font F size umod.S(13) color T["muted"]
                                            text c["lines"] font F size umod.S(13) color T["dim"] xalign 1.0
                        else:
                            null width L["cell_w"] height 1

            else:
                # ---------- imagenes y videos ----------
                grid L["cols"] L["rows"]:
                    spacing L["gap"]
                    for gi in range(L["per"]):
                        if gi < len(cells):
                            $ c = cells[gi]
                            button:
                                action [SetScreenVariable("viewing", c["idx"]), SetScreenVariable("chrome", True)]
                                xsize L["cell_w"]
                                ysize L["thumb_h"] + L["name_h"]
                                padding (L["inset"], L["inset"])
                                background umod.RB(T["card"], 14)
                                hover_background umod.RB(T["hover"], 14)
                                hover_foreground umod.RB(T["accent"], 14, 2)
                                alt c["alt"]
                                hovered SetScreenVariable("tt", c["tip"])
                                unhovered SetScreenVariable("tt", "")
                                vbox:
                                    spacing umod.S(7)
                                    fixed:
                                        xsize L["in_w"]
                                        ysize L["th_in"]
                                        add Solid(T["well"])
                                        if c["locked"]:
                                            text u"Todav\u00eda no la has visto" font F size umod.S(14) color T["dim"] align (0.5, 0.5)
                                        elif c["video"]:
                                            frame:
                                                align (0.5, 0.5)
                                                xsize umod.S(62)
                                                ysize umod.S(62)
                                                background umod.RB("#00000099", 30)
                                                text umod.ICONS["play"] font F size umod.S(24) color T["text"] align (0.58, 0.5)
                                        elif c["thumb"] is not None:
                                            add c["thumb"] align (0.5, 0.5)
                                        elif c["pending"]:
                                            text "Cargando..." font F size umod.S(14) color T["dim"] align (0.5, 0.5)
                                        else:
                                            text "Sin vista previa" font F size umod.S(14) color T["dim"] align (0.5, 0.5)
                                        if c["fav"]:
                                            text umod.ICONS["star"] font F size umod.S(20) color T["accent"] xalign 1.0 xoffset -umod.S(8) yoffset umod.S(4)
                                    text umod.esc(c["name"]) font F size umod.S(14) color T["muted"] xoffset umod.S(5)
                        else:
                            null width L["cell_w"] height 1

        # ===================== pie: ayuda, paginas, version =====================
        if pick is None:
            text umod.esc(tt or umod.TAB_HINT.get(ctab, "")):
                font F
                size umod.S(14)
                color (T["text"] if tt else T["dim"])
                xpos L["pad"]
                ypos by
                yanchor 0.5
                xmaximum int(L["main_w"] * 0.34)
            text umod.gal_version():
                font F
                size umod.S(12)
                color T["dim"]
                xalign 1.0
                xoffset -L["pad"]
                ypos by
                yanchor 0.5
            if npages > 1:
                hbox:
                    xalign 0.5
                    ypos by
                    yanchor 0.5
                    spacing umod.S(16)
                    textbutton umod.ICONS["prev"]:
                        action If(cpage > 0, SetScreenVariable("page", cpage - 1))
                        xsize umod.S(44)
                        ysize umod.S(44)
                        text_xalign 0.5
                        text_yalign 0.45
                        background umod.RB(T["card"], 21)
                        hover_background umod.RB(T["hover"], 21)
                        text_font F
                        text_size umod.S(28)
                        text_color (T["text"] if cpage > 0 else T["dim"])
                        alt "Pagina anterior"
                    text umod.gal_page_text(cpage, npages) font F size umod.S(15) color T["muted"] yalign 0.5
                    textbutton umod.ICONS["next"]:
                        action If(cpage < npages - 1, SetScreenVariable("page", cpage + 1))
                        xsize umod.S(44)
                        ysize umod.S(44)
                        text_xalign 0.5
                        text_yalign 0.45
                        background umod.RB(T["card"], 21)
                        hover_background umod.RB(T["hover"], 21)
                        text_font F
                        text_size umod.S(28)
                        text_color (T["text"] if cpage < npages - 1 else T["dim"])
                        alt "Pagina siguiente"

    # ===================== opciones =====================
    if gear and not v_ok:
        button:
            action SetScreenVariable("gear", False)
            xfill True
            yfill True
            background None
            alt "Cerrar opciones"
        frame:
            background umod.RB(T["panel"], 16)
            foreground umod.RB(T["line"], 16, 1)
            xalign 1.0
            xoffset -L["pad"]
            ypos L["top"] - umod.S(6)
            padding (umod.S(10), umod.S(10))
            vbox:
                spacing umod.S(2)
                textbutton umod.check_label(umod.gal_extra(), u"Incluir fondos y sprites en Im\u00e1genes"):
                    action [Function(umod.gal_toggle_pref, "umod_gal_extra"), SetScreenVariable("page", 0)]
                    xminimum umod.S(400)
                    padding (umod.S(14), umod.S(10))
                    background None
                    hover_background umod.RB(T["hover"], 10)
                    text_font F
                    text_size umod.S(16)
                    text_color T["text"]
                textbutton umod.check_label(umod.gal_only_seen(), "Solo lo que ya vi"):
                    action [Function(umod.gal_toggle_pref, "umod_gal_only_seen"), SetScreenVariable("page", 0)]
                    xminimum umod.S(400)
                    padding (umod.S(14), umod.S(10))
                    background None
                    hover_background umod.RB(T["hover"], 10)
                    text_font F
                    text_size umod.S(16)
                    text_color T["text"]
                textbutton umod.check_label(False, "Volver a buscar todo"):
                    action [Function(umod.gal_ensure, True), SetScreenVariable("gear", False)]
                    xminimum umod.S(400)
                    padding (umod.S(14), umod.S(10))
                    background None
                    hover_background umod.RB(T["hover"], 10)
                    text_font F
                    text_size umod.S(16)
                    text_color T["text"]
                frame:
                    xsize umod.S(400)
                    ysize 1
                    background Solid(T["line"])
                    null
                textbutton umod.check_label(False, "Herramientas avanzadas..."):
                    action Function(umod.gallery_advanced)
                    xminimum umod.S(400)
                    padding (umod.S(14), umod.S(10))
                    background None
                    hover_background umod.RB(T["hover"], 10)
                    text_font F
                    text_size umod.S(16)
                    text_color T["muted"]
                    text_hover_color T["text"]

    # ===================== todos los personajes =====================
    if whoall and not v_ok:
        button:
            action SetScreenVariable("whoall", False)
            xfill True
            yfill True
            background Solid(T["scrim"])
            alt "Cerrar"
        frame:
            background umod.RB(T["panel"], 20)
            foreground umod.RB(T["line"], 20, 1)
            xalign 0.5
            yalign 0.45
            xsize int(L["sw"] * 0.7)
            padding (umod.S(30), umod.S(26))
            vbox:
                spacing umod.S(16)
                text "Personajes" font FB size umod.S(26) color T["text"]
                viewport:
                    ymaximum int(L["sh"] * 0.58)
                    mousewheel True
                    draggable True
                    scrollbars "vertical"
                    hbox:
                        box_wrap True
                        spacing umod.S(8)
                        xsize int(L["sw"] * 0.7) - umod.S(90)
                        textbutton "Todos":
                            action [SetScreenVariable("who", None), SetScreenVariable("page", 0), SetScreenVariable("whoall", False)]
                            padding (umod.S(17), umod.S(9))
                            background umod.RB((T["sel"] if who is None else T["card"]), 18)
                            hover_background umod.RB(T["hover"], 18)
                            text_font (FB if who is None else F)
                            text_size umod.S(16)
                            text_color (T["accent"] if who is None else T["text"])
                        for cid, cname, cn in all_chips:
                            $ w_on = who == cid
                            textbutton umod.chip_label(cname, cn):
                                action [SetScreenVariable("who", cid), SetScreenVariable("page", 0), SetScreenVariable("whoall", False)]
                                padding (umod.S(17), umod.S(9))
                                background umod.RB((T["sel"] if w_on else T["card"]), 18)
                                hover_background umod.RB(T["hover"], 18)
                                text_font (FB if w_on else F)
                                text_size umod.S(16)
                                text_color (T["accent"] if w_on else T["text"])
                                alt cname
                textbutton "Cerrar":
                    action SetScreenVariable("whoall", False)
                    xalign 1.0
                    padding (umod.S(20), umod.S(10))
                    background umod.RB(T["card"], 14)
                    hover_background umod.RB(T["hover"], 14)
                    text_font F
                    text_size umod.S(16)
                    text_color T["text"]

    # ===================== cartel de escena: ver o jugar =====================
    if pick is not None and not v_ok:
        $ p_ready = umod.guard(umod.play_ready, True)
        $ p_exact = umod.guard(umod.scene_exact, False, pick)
        $ p_nav = umod.scene_nav(seq, pick)
        $ p_prev, p_next, p_i, p_n = p_nav
        $ p_thumb = umod.guard(umod.scene_thumb_big, None, pick, L)
        $ p_notes = umod.guard(umod.scene_end_notes, [], pick)
        $ p_names = umod.guard(umod.scene_names, "", pick)
        $ p_info_w = L["dlg_w"] - L["dlg_th_w"] - umod.S(60) - umod.S(26)
        $ go_prev = [SetScreenVariable("pick", p_prev), SetScreenVariable("page", max(0, p_i - 1) // per), Function(umod.play_prepare)]
        $ go_next = [SetScreenVariable("pick", p_next), SetScreenVariable("page", (p_i + 1) // per), Function(umod.play_prepare)]

        if p_prev is not None:
            key "K_LEFT" action go_prev
            key "repeat_K_LEFT" action go_prev
            key "K_PAGEUP" action go_prev
        if p_next is not None:
            key "K_RIGHT" action go_next
            key "repeat_K_RIGHT" action go_next
            key "K_PAGEDOWN" action go_next

        button:
            action SetScreenVariable("pick", None)
            xfill True
            yfill True
            background Solid(T["scrim"])
            alt "Cerrar"
        frame:
            background umod.RB(T["panel"], 21)
            foreground umod.RB(T["line"], 21, 1)
            xalign 0.5
            yalign 0.5
            xsize L["dlg_w"]
            padding (umod.S(30), umod.S(28))
            vbox:
                spacing umod.S(22)
                hbox:
                    spacing umod.S(26)
                    frame:
                        xsize L["dlg_th_w"]
                        ysize L["dlg_th_h"]
                        padding (umod.S(4), umod.S(4))
                        background umod.RB(T["well"], 14)
                        fixed:
                            if p_thumb is not None:
                                add p_thumb align (0.5, 0.5)
                            else:
                                text umod.quote(pick) font F size umod.S(15) color T["muted"] align (0.5, 0.5) xmaximum L["dlg_th_w"] - umod.S(40) text_align 0.5
                    vbox:
                        spacing umod.S(8)
                        xsize p_info_w
                        text umod.esc(umod.scene_title(pick)) font FB size umod.S(28) color T["text"]
                        if p_names:
                            text umod.esc(p_names) font F size umod.S(16) color T["muted"]
                        text umod.scene_meta(pick) font F size umod.S(15) color T["dim"]
                        if pick.get("first"):
                            null height umod.S(4)
                            text umod.quote(pick) font F size umod.S(16) color T["muted"] italic True
                hbox:
                    spacing umod.S(14)
                    textbutton (umod.ICONS["play_here"] if p_ready else umod.play_progress_text()):
                        action (Function(umod.gal_play_scene, pick) if p_ready else None)
                        padding (umod.S(26), umod.S(15))
                        background umod.RB((T["accent"] if p_ready else T["card"]), 14)
                        hover_background umod.RB((T["accent_hi"] if p_ready else T["card"]), 14)
                        text_font FB
                        text_size umod.S(19)
                        text_color (T["on_accent"] if p_ready else T["dim"])
                        alt "Jugar desde aqui"
                    textbutton umod.ICONS["watch"]:
                        action [SetScreenVariable("pick", None), Function(umod.scene_watch, pick)]
                        padding (umod.S(26), umod.S(15))
                        background umod.RB(T["card"], 14)
                        hover_background umod.RB(T["hover"], 14)
                        foreground umod.RB(T["line"], 14, 1)
                        hover_foreground umod.RB(T["accent"], 14, 2)
                        text_font F
                        text_size umod.S(19)
                        text_color T["text"]
                        alt "Ver como transcurre la escena"
                vbox:
                    spacing umod.S(7)
                    xsize L["dlg_w"] - umod.S(60)
                    if pick.get("branches"):
                        text umod.esc(umod.scene_branch_note(pick)) font F size umod.S(15) color T["accent"]
                    for p_end in p_notes:
                        text umod.warn_line(p_end) font F size umod.S(16) color T["warn"]
                    text umod.esc(umod.scene_note(pick)) font F size umod.S(14) color (T["text"] if p_exact else T["muted"])
                    text "Antes de empezar se guarda una copia de tu partida." font F size umod.S(14) color T["dim"]
                fixed:
                    xsize L["dlg_w"] - umod.S(60)
                    ysize umod.S(44)
                    hbox:
                        yalign 0.5
                        spacing umod.S(12)
                        textbutton umod.ICONS["prev"]:
                            action (go_prev if p_prev is not None else None)
                            xsize umod.S(44)
                            ysize umod.S(44)
                            text_xalign 0.5
                            text_yalign 0.45
                            background umod.RB(T["card"], 21)
                            hover_background umod.RB(T["hover"], 21)
                            text_font F
                            text_size umod.S(28)
                            text_color (T["text"] if p_prev is not None else T["dim"])
                            alt "Escena anterior"
                        text ("%d de %d" % (p_i + 1, p_n)) font F size umod.S(15) color T["muted"] yalign 0.5
                        textbutton umod.ICONS["next"]:
                            action (go_next if p_next is not None else None)
                            xsize umod.S(44)
                            ysize umod.S(44)
                            text_xalign 0.5
                            text_yalign 0.45
                            background umod.RB(T["card"], 21)
                            hover_background umod.RB(T["hover"], 21)
                            text_font F
                            text_size umod.S(28)
                            text_color (T["text"] if p_next is not None else T["dim"])
                            alt "Escena siguiente"
                    textbutton "Cancelar":
                        action SetScreenVariable("pick", None)
                        xalign 1.0
                        yalign 0.5
                        padding (umod.S(20), umod.S(10))
                        background None
                        hover_background umod.RB(T["hover"], 12)
                        text_font F
                        text_size umod.S(16)
                        text_color T["muted"]
                        text_hover_color T["text"]

    # ===================== visor de imagenes y videos =====================
    if v_ok:
        $ cur = items[viewing]
        $ last = len(items) - 1
        $ umod.guard(umod.viewer_predict, None, items, viewing)
        $ isv = umod.is_video(cur)
        $ vinfo = umod.guard(umod.video_info, None) if isv else None
        $ v_prev = SetScreenVariable("viewing", max(0, viewing - 1))
        $ v_next = SetScreenVariable("viewing", min(last, viewing + 1))
        $ strip = umod.guard(umod.viewer_strip, [], items, viewing, L)
        $ v_play = umod.guard(umod.gal_can_play, False, cur)
        $ vbw, vbh, vcy = umod.viewer_box(cur, chrome, L, v_play)

        key "K_LEFT" action v_prev
        key "repeat_K_LEFT" action v_prev
        key "K_RIGHT" action v_next
        key "repeat_K_RIGHT" action v_next
        key "K_a" action v_prev
        key "K_d" action v_next
        key "K_HOME" action SetScreenVariable("viewing", 0)
        key "K_END" action SetScreenVariable("viewing", last)
        key "mousedown_4" action v_prev
        key "mousedown_5" action v_next
        if isv:
            timer 0.25 repeat True action Function(umod.noop)
            if vinfo is not None and vinfo["pause"]:
                key "K_SPACE" action Function(umod.video_toggle_pause)

        add Solid(T["viewer"])
        button:
            action ToggleScreenVariable("chrome")
            xfill True
            yfill True
            background None
            alt umod.gal_name(cur)
            $ fv = umod.guard(umod.fullview, None, cur, vbw, vbh)
            if umod.is_locked(cur):
                text u"Todav\u00eda no ha aparecido en el juego." font F size umod.S(20) color T["muted"] align (0.5, 0.5)
            elif isv:
                $ vd = umod.guard(umod.gal_video, None, cur, vbw, vbh)
                if vd:
                    add vd xalign 0.5 yanchor 0.5 ypos vcy
                else:
                    text umod.esc(umod.gal_video_error(cur)) font F size umod.S(18) color T["muted"] align (0.5, 0.5)
            elif fv:
                add fv xalign 0.5 yanchor 0.5 ypos vcy
            else:
                text "Sin vista previa" font F size umod.S(20) color T["muted"] align (0.5, 0.5)

        # anterior / siguiente: franjas a los lados, siempre visibles
        if viewing > 0:
            button:
                action v_prev
                xalign 0.0
                xsize umod.S(120)
                yfill True
                background None
                alt "Anterior"
                frame:
                    align (0.5, 0.45)
                    xsize umod.S(58)
                    ysize umod.S(58)
                    background umod.RB("#00000080", 28)
                    hover_background umod.RB("#000000c0", 28)
                    text umod.ICONS["prev"] font F size umod.S(40) color "#ffffffb0" hover_color "#ffffff" align (0.46, 0.42)
        if viewing < last:
            button:
                action v_next
                xalign 1.0
                xsize umod.S(120)
                yfill True
                background None
                alt "Siguiente"
                frame:
                    align (0.5, 0.45)
                    xsize umod.S(58)
                    ysize umod.S(58)
                    background umod.RB("#00000080", 28)
                    hover_background umod.RB("#000000c0", 28)
                    text umod.ICONS["next"] font F size umod.S(40) color "#ffffffb0" hover_color "#ffffff" align (0.54, 0.42)

        if chrome:
            # ---------- barra de arriba ----------
            frame:
                xfill True
                ysize umod.S(72)
                padding (L["pad"], 0)
                background Solid("#000000a8")
                fixed:
                    hbox:
                        yalign 0.5
                        spacing umod.S(18)
                        textbutton umod.ICONS["back"]:
                            action SetScreenVariable("viewing", None)
                            padding (umod.S(18), umod.S(9))
                            background umod.RB("#ffffff1c", 17)
                            hover_background umod.RB("#ffffff36", 17)
                            text_font F
                            text_size umod.S(16)
                            text_color T["text"]
                            alt "Volver a la galeria"
                        text umod.esc(umod.gal_short(umod.gal_name(cur), L["sw"] * 0.42)) font FB size umod.S(17) color T["text"] yalign 0.5
                    hbox:
                        xalign 1.0
                        yalign 0.5
                        spacing umod.S(14)
                        text ("%d de %d" % (viewing + 1, len(items))) font F size umod.S(15) color "#ffffffa0" yalign 0.5
                        textbutton (umod.ICONS["star"] if umod.is_fav(cur) else umod.ICONS["star_off"]):
                            action Function(umod.toggle_fav, cur)
                            xsize umod.S(44)
                            ysize umod.S(44)
                            text_xalign 0.5
                            text_yalign 0.5
                            background umod.RB("#ffffff1c", 22)
                            hover_background umod.RB("#ffffff36", 22)
                            text_font F
                            text_size umod.S(22)
                            text_color (T["accent"] if umod.is_fav(cur) else T["text"])
                            alt ("Quitar de favoritas" if umod.is_fav(cur) else "Anadir a favoritas")

            # ---------- abajo: jugar, linea de tiempo, tira ----------
            vbox:
                xalign 0.5
                yalign 1.0
                yoffset -umod.S(16)
                spacing umod.S(12)
                if v_play:
                    hbox:
                        xalign 0.5
                        spacing umod.S(16)
                        textbutton umod.ICONS["play_from"]:
                            action Confirm("Vas a empezar a jugar desde el momento de la historia en que aparece esta imagen.\nAntes se guarda una copia de tu partida.", Function(umod.gal_play_from, cur))
                            padding (umod.S(24), umod.S(12))
                            background umod.RB(T["accent"], 14)
                            hover_background umod.RB(T["accent_hi"], 14)
                            text_font FB
                            text_size umod.S(17)
                            text_color T["on_accent"]
                        text umod.esc("Empieza en: %s" % umod.gal_play_where(cur)) font F size umod.S(14) color "#ffffffb0" yalign 0.5
                    for v_end in umod.guard(umod.asset_end_notes, [], cur):
                        text umod.warn_line(v_end) font F size umod.S(15) color T["warn"] xalign 0.5

                if isv and vinfo is not None:
                    $ TW = int(L["sw"] * 0.44)
                    frame:
                        xalign 0.5
                        background umod.RB("#000000c0", 17)
                        padding (umod.S(16), umod.S(9))
                        hbox:
                            spacing umod.S(14)
                            if vinfo["pause"]:
                                textbutton (umod.ICONS["play"] if vinfo["paused"] else umod.ICONS["pause"]):
                                    action Function(umod.video_toggle_pause)
                                    xsize umod.S(40)
                                    ysize umod.S(40)
                                    yalign 0.5
                                    text_xalign 0.55
                                    text_yalign 0.5
                                    background umod.RB("#ffffff1f", 17)
                                    hover_background umod.RB("#ffffff3a", 17)
                                    text_font FB
                                    text_size umod.S(15)
                                    text_color T["text"]
                                    alt ("Seguir" if vinfo["paused"] else "Pausa (espacio)")
                            if vinfo["seek"]:
                                textbutton umod.ICONS["restart"]:
                                    action Function(umod.video_restart)
                                    xsize umod.S(40)
                                    ysize umod.S(40)
                                    yalign 0.5
                                    text_xalign 0.5
                                    text_yalign 0.5
                                    background umod.RB("#ffffff1f", 17)
                                    hover_background umod.RB("#ffffff3a", 17)
                                    text_font F
                                    text_size umod.S(19)
                                    text_color T["text"]
                                    alt "Desde el principio"
                            text umod.fmt_time(vinfo["pos"]) font F size umod.S(14) color T["text"] yalign 0.5 min_width umod.S(44) text_align 1.0
                            fixed:
                                xsize TW
                                ysize umod.S(30)
                                yalign 0.5
                                frame:
                                    xsize TW
                                    ysize umod.S(6)
                                    yalign 0.5
                                    background umod.RB("#ffffff2e", 2)
                                    null
                                if vinfo["dur"]:
                                    frame:
                                        xsize max(umod.S(6), int(TW * vinfo["frac"]))
                                        ysize umod.S(6)
                                        yalign 0.5
                                        background umod.RB(T["accent"], 2)
                                        null
                                    frame:
                                        xpos max(0, int(TW * vinfo["frac"]) - umod.S(7))
                                        yalign 0.5
                                        xsize umod.S(14)
                                        ysize umod.S(14)
                                        background umod.RB(T["accent_hi"], 6)
                                        null
                                if vinfo["seek"]:
                                    hbox:
                                        for k in range(48):
                                            button:
                                                action Function(umod.video_seek, (k + 0.5) / 48.0)
                                                xsize TW // 48
                                                ysize umod.S(30)
                                                background None
                                                hover_background Solid("#ffffff14")
                                                alt "Saltar a este punto"
                                                null
                            text (umod.fmt_time(vinfo["dur"]) if vinfo["dur"] else "en bucle") font F size umod.S(14) color "#ffffffa0" yalign 0.5

                if len(strip) > 1:
                    hbox:
                        xalign 0.5
                        spacing umod.S(8)
                        for si, sth, sv, slk in strip:
                            $ s_on = si == viewing
                            button:
                                action SetScreenVariable("viewing", si)
                                xsize L["fs_w"]
                                ysize L["fs_h"]
                                padding (umod.S(3), umod.S(3))
                                background umod.RB((T["accent"] if s_on else "#ffffff1c"), 9)
                                hover_background umod.RB((T["accent_hi"] if s_on else "#ffffff44"), 9)
                                alt ("Imagen %d" % (si + 1))
                                fixed:
                                    add Solid("#000000")
                                    if sth is not None:
                                        add sth align (0.5, 0.5)
                                    elif sv:
                                        text umod.ICONS["play"] font F size umod.S(18) color "#ffffffc0" align (0.55, 0.5)
                                    else:
                                        text "-" font F size umod.S(16) color "#ffffff60" align (0.5, 0.5)


# ##################################################################### #
#   universal_mod_script.rpy
# ##################################################################### #

# =====================================================================
#  UNIVERSAL REN'PY MOD (UMOD)  -  FASE 3 / Script Analyzer
# ---------------------------------------------------------------------
#  Requiere universal_mod.rpy (Fase 1) en la misma carpeta.
#
#  Que hace esta fase:
#    - Recorre el AST del juego en tiempo de ejecucion y clasifica los
#      nodos: Label, Say, Menu, Jump, Call, If, While, Python, Scene,
#      Show, Hide, Return, UserStatement, Default, Define.
#    - Descenso recursivo desde cada Label por su .block, de modo que
#      se conserva la CONTENCION (que hay dentro de cada label) en vez
#      de una lista plana sin estructura.
#    - Extrae de cada bloque Python, con el modulo ast de Python:
#        variables leidas / escritas / mutadas
#        incrementos tipo  alice_points += 2
#    - Extrae de cada condicion (if, while, opcion de menu) restricciones
#      estructuradas:  {variable, operador, valor}
#      Esto es EXACTAMENTE la entrada del State Reconstruction Engine
#      de la Fase 6.
#    - Detecta opciones de menu ocultas (condicion distinta de True).
#    - Recoge los valores iniciales de default/define.
#
#  ABRIR:  ALT + S   (o desde Herramientas en el panel principal)
#
#  ADVERTENCIA DE ESTABILIDAD
#  renpy.game.script.all_stmts, renpy.game.script.namemap y las clases
#  de renpy.ast NO son API publica. Funcionan desde hace muchas
#  versiones (los usan unrpyc, el warp del propio motor y otras
#  herramientas) pero pueden cambiar. Cada acceso esta protegido y, si
#  algo falta, el analizador se degrada en vez de romper el juego.
# =====================================================================


# ---------------------------------------------------------------------
# 0) Estado de runtime del analizador
# ---------------------------------------------------------------------
init -1080 python:
    import sys as _umod_sys_s
    try:
        _umod_s = _umod_sys_s.modules["umod_rt"]
        _umod_s.sa_ready = False
        _umod_s.sa_scanning = False
        _umod_s.sa_msg = "Sin analizar"
        _umod_s.sa_kinds = {}        # tipo de nodo -> conteo
        _umod_s.sa_labels = {}       # nombre de label -> resumen
        _umod_s.sa_order = []        # labels en orden de archivo
        _umod_s.sa_menus = []        # todos los menus con sus opciones
        _umod_s.sa_vars = {}         # variable -> {w, r, labels}
        _umod_s.sa_conds = []        # restricciones planas
        _umod_s.sa_defaults = {}     # variable -> valor inicial (fuente)
        _umod_s.sa_files = 0
        _umod_s.sa_seconds = 0.0
        _umod_s.sa_skipped = 0
        del _umod_s
    except Exception:
        pass


# ---------------------------------------------------------------------
# 1) Analizador. Mismo namespace "umod": reutiliza el nucleo.
# ---------------------------------------------------------------------
init -980 python in umod:

    import ast as pyast          # ojo: NO es renpy.ast

    SCRIPT = True                # el nucleo consulta esta bandera

    SA_KEYS      = ["alt_K_y"]      # Alt+S es la captura de pantalla de Ren'Py
    SA_MAX_NODES = 400000
    SA_MAX_SRC   = 20000         # no parseamos bloques Python gigantes
    SA_PAGE      = 100

    # ---------- 1.1 Referencias a las clases del AST ----------------
    def _ast_module():
        m = getattr(renpy, "ast", None)
        if m is None:
            try:
                import renpy.ast as m2
                m = m2
            except Exception:
                m = None
        return m

    A = _ast_module()

    def _cls(name):
        return getattr(A, name, None) if A else None

    C_Label   = _cls("Label")
    C_Say     = _cls("Say")
    C_Menu    = _cls("Menu")
    C_Jump    = _cls("Jump")
    C_Call    = _cls("Call")
    C_If      = _cls("If")
    C_While   = _cls("While")
    C_Python  = _cls("Python")
    C_Scene   = _cls("Scene")
    C_Show    = _cls("Show")
    C_Hide    = _cls("Hide")
    C_Return  = _cls("Return")
    C_User    = _cls("UserStatement")
    C_Default = _cls("Default")
    C_Define  = _cls("Define")
    C_Init    = _cls("Init")
    C_Trans   = _cls("Translate")

    def _isa(n, cls):
        return cls is not None and isinstance(n, cls)

    def sa_available():
        try:
            if A is None:
                return False
            sc = renpy.game.script
            return bool(getattr(sc, "all_stmts", None) or getattr(sc, "namemap", None))
        except Exception:
            return False

    # ---------- 1.2 Filtro de archivos ------------------------------
    # Quitamos el motor, las traducciones (duplican todo el guion) y
    # nuestros propios archivos.
    def _is_game_file(fn):
        f = to_text(fn or "").replace("\\", "/")
        if not f:
            return False
        if f.startswith("renpy/common/") or "/renpy/common/" in f:
            return False
        if f.startswith("common/") or "/common/" in f:
            return False
        if f.startswith("tl/") or "/tl/" in f:
            return False
        base = f.split("/")[-1]
        if base.startswith("universal_mod"):
            return False
        return True

    # ---------- 1.3 Utilidades sobre el ast de Python ---------------
    _NOVAL = object()

    _CMP = {}
    for _n, _s in (("Eq", "=="), ("NotEq", "!="), ("Lt", "<"), ("LtE", "<="),
                   ("Gt", ">"), ("GtE", ">="), ("In", "in"), ("NotIn", "not in"),
                   ("Is", "is"), ("IsNot", "is not")):
        _c = getattr(pyast, _n, None)
        if _c is not None:
            _CMP[_c] = _s

    _AUG = {}
    for _n, _s in (("Add", "+="), ("Sub", "-="), ("Mult", "*="), ("Div", "/="),
                   ("FloorDiv", "//="), ("Mod", "%="), ("Pow", "**=")):
        _c = getattr(pyast, _n, None)
        if _c is not None:
            _AUG[_c] = _s

    # Al invertir los lados de una comparacion hay que invertir el operador:
    # "10 <= alice_points" es "alice_points >= 10", no "alice_points <= 10".
    _FLIP = {
        "==": "==", "!=": "!=",
        "<": ">", "<=": ">=", ">": "<", ">=": "<=",
        "is": "is", "is not": "is not",
        "in": "contiene", "not in": "no contiene",
    }

    # Metodos que mutan el objeto sobre el que se llaman.
    _MUTATORS = set(["append", "extend", "insert", "remove", "pop", "clear",
                     "add", "discard", "update", "sort", "reverse",
                     "setdefault", "popitem"])

    def _dotted(n):
        parts = []
        while isinstance(n, pyast.Attribute):
            parts.append(n.attr)
            n = n.value
        if isinstance(n, pyast.Name):
            parts.append(n.id)
            parts.reverse()
            return ".".join(parts)
        return None

    def _base_name(n):
        """Nombre de la variable afectada, incluso en d['k'] o obj.attr."""
        if isinstance(n, pyast.Name):
            return n.id
        if isinstance(n, pyast.Attribute):
            return _dotted(n)
        if isinstance(n, pyast.Subscript):
            return _base_name(n.value)
        return None

    def _const(n):
        try:
            if isinstance(n, pyast.Name):
                if n.id == "True":
                    return True
                if n.id == "False":
                    return False
                if n.id == "None":
                    return None
                return _NOVAL
            return pyast.literal_eval(n)
        except Exception:
            return _NOVAL

    class _VarVisitor(pyast.NodeVisitor):
        def __init__(self):
            self.reads = set()
            self.writes = set()
            self.calls = set()
            self.deltas = []

        def _target(self, t):
            nm = _base_name(t)
            if nm:
                self.writes.add(nm)
            elif isinstance(t, (pyast.Tuple, pyast.List)):
                for e in t.elts:
                    self._target(e)

        def visit_Assign(self, n):
            for t in n.targets:
                self._target(t)
            self.visit(n.value)

        def visit_AugAssign(self, n):
            self._target(n.target)
            nm = _base_name(n.target)
            if nm:
                self.reads.add(nm)
                v = _const(n.value)
                if v is not _NOVAL:
                    self.deltas.append((nm, _AUG.get(type(n.op), "?="), to_text(v)))
            self.visit(n.value)

        def visit_Name(self, n):
            self.reads.add(n.id)

        def visit_Attribute(self, n):
            d = _dotted(n)
            if d:
                self.reads.add(d)
            else:
                self.generic_visit(n)

        def visit_Call(self, n):
            nm = _base_name(n.func)
            if nm:
                self.calls.add(nm)
                # inventory.append('key') muta inventory: cuenta como escritura.
                if isinstance(n.func, pyast.Attribute) and n.func.attr in _MUTATORS:
                    base = _base_name(n.func.value)
                    if base:
                        self.writes.add(base)
                        self.reads.add(base)
            for a in getattr(n, "args", []):
                self.visit(a)
            for kw in getattr(n, "keywords", []):
                if getattr(kw, "value", None) is not None:
                    self.visit(kw.value)

    def analyze_python(src):
        """Devuelve (reads, writes, calls, deltas) de un fragmento Python."""
        empty = (set(), set(), set(), [])
        s = to_text(src or "").strip()
        if not s or len(s) > SA_MAX_SRC:
            return empty
        try:
            tree = pyast.parse(s)
        except Exception:
            return empty
        try:
            v = _VarVisitor()
            v.visit(tree)
            return (v.reads, v.writes, v.calls, v.deltas)
        except Exception:
            return empty

    def parse_condition(src):
        """Convierte una condicion en restricciones estructuradas.
        'alt' marca las que vienen de un OR: son alternativas, no
        requisitos simultaneos. La Fase 6 necesita esa distincion."""
        out = []
        s = to_text(src or "").strip()
        if not s or s == "True" or len(s) > 2000:
            return out
        try:
            tree = pyast.parse(s, mode="eval")
        except Exception:
            return out

        def walk(n, neg, alt):
            if isinstance(n, pyast.BoolOp):
                is_or = isinstance(n.op, pyast.Or)
                for v in n.values:
                    walk(v, neg, alt or is_or)
            elif isinstance(n, pyast.UnaryOp) and isinstance(n.op, pyast.Not):
                walk(n.operand, not neg, alt)
            elif isinstance(n, pyast.Compare) and len(n.ops) == 1:
                op = _CMP.get(type(n.ops[0]))
                var = _base_name(n.left)
                val = _const(n.comparators[0])
                if op and var and val is not _NOVAL:
                    out.append({"v": var, "op": op, "val": to_text(val),
                                "neg": bool(neg), "alt": bool(alt)})
                elif op:
                    # La variable esta a la derecha: hay que invertir el operador.
                    var2 = _base_name(n.comparators[0])
                    val2 = _const(n.left)
                    if var2 and val2 is not _NOVAL:
                        out.append({"v": var2, "op": _FLIP.get(op, op),
                                    "val": to_text(val2),
                                    "neg": bool(neg), "alt": bool(alt)})
            else:
                nm = _base_name(n) if isinstance(n, (pyast.Name, pyast.Attribute)) else None
                if nm:
                    out.append({"v": nm, "op": "es cierto", "val": to_text(not neg),
                                "neg": bool(neg), "alt": bool(alt)})

        try:
            walk(tree.body, False, False)
        except Exception as e:
            log_error("parse_condition", e)
        return out

    def cond_text(c):
        s = "%s %s %s" % (c["v"], c["op"], c["val"])
        if c.get("neg"):
            s = "NO (" + s + ")"
        if c.get("alt"):
            s += "   [alternativa OR]"
        return s

    # ---------- 1.4 Lectura de nodos --------------------------------
    def _imspec_name(spec):
        try:
            return " ".join(to_text(x) for x in spec[0])
        except Exception:
            return ""

    def _py_source(node):
        for attr in ("code", "expr"):
            c = getattr(node, attr, None)
            src = getattr(c, "source", None)
            if isinstance(src, string_types):
                return src
        src = getattr(node, "source", None)
        return src if isinstance(src, string_types) else ""

    def _new_acc():
        return {"say": 0, "py": 0, "ret": 0, "user": 0, "while": 0,
                "menus": [], "jumps": [], "calls": [], "conds": [],
                "shows": set(), "scenes": set(), "chars": set(),
                "reads": set(), "writes": set(), "deltas": [],
                "first": ""}

    def _first_jump_target(block, depth=0):
        """Primer destino estatico dentro del bloque de una opcion."""
        if not block or depth > 6:
            return ""
        for n in block:
            if _isa(n, C_Jump) and not getattr(n, "expression", False):
                return to_text(getattr(n, "target", ""))
            if _isa(n, C_Call) and not getattr(n, "expression", False):
                return to_text(getattr(n, "label", ""))
        return ""

    def _walk(block, acc, depth):
        if not block or depth > 40:
            return
        for n in block:
            try:
                _node(n, acc, depth)
            except Exception as e:
                log_error("walk", e)

    def _node(n, acc, depth):
        if _isa(n, C_Say):
            acc["say"] += 1
            who = getattr(n, "who", None)
            if who:
                acc["chars"].add(to_text(who))
            if not acc["first"]:
                w = to_text(getattr(n, "what", ""))
                acc["first"] = w[:120]

        elif _isa(n, C_Menu):
            items = []
            for it in (getattr(n, "items", None) or []):
                try:
                    cap = to_text(it[0]) if len(it) > 0 else ""
                    cond = to_text(it[1]) if len(it) > 1 else "True"
                    blk = it[2] if len(it) > 2 else None
                except Exception:
                    continue
                if blk is None:
                    continue          # linea de titulo del menu, no es opcion
                cs = parse_condition(cond)
                for c in cs:
                    acc["conds"].append(c)
                items.append({
                    "cap": cap[:110],
                    "cond": cond,
                    "hidden": (cond.strip() not in ("True", "")),
                    "conds": cs,
                    "to": _first_jump_target(blk),
                })
                _walk(blk, acc, depth + 1)
            acc["menus"].append({
                "line": to_text(getattr(n, "linenumber", "?")),
                "items": items,
            })

        elif _isa(n, C_Jump):
            acc["jumps"].append({
                "to": to_text(getattr(n, "target", "")),
                "expr": bool(getattr(n, "expression", False)),
            })

        elif _isa(n, C_Call):
            acc["calls"].append({
                "to": to_text(getattr(n, "label", "")),
                "expr": bool(getattr(n, "expression", False)),
            })

        elif _isa(n, C_If):
            for entry in (getattr(n, "entries", None) or []):
                try:
                    cond, blk = entry[0], entry[1]
                except Exception:
                    continue
                for c in parse_condition(cond):
                    acc["conds"].append(c)
                _walk(blk, acc, depth + 1)

        elif _isa(n, C_While):
            acc["while"] += 1
            for c in parse_condition(getattr(n, "condition", "")):
                acc["conds"].append(c)
            _walk(getattr(n, "block", None), acc, depth + 1)

        elif _isa(n, C_Python):
            acc["py"] += 1
            r, w, c, d = analyze_python(_py_source(n))
            acc["reads"] |= r
            acc["writes"] |= w
            acc["deltas"].extend(d)

        elif _isa(n, C_Scene):
            nm = _imspec_name(getattr(n, "imspec", None))
            if nm:
                acc["scenes"].add(nm)

        elif _isa(n, C_Show):
            nm = _imspec_name(getattr(n, "imspec", None))
            if nm:
                acc["shows"].add(nm)

        elif _isa(n, C_Return):
            acc["ret"] += 1

        elif _isa(n, C_User):
            acc["user"] += 1

        else:
            blk = getattr(n, "block", None)
            if isinstance(blk, list):
                _walk(blk, acc, depth + 1)

    def _freeze(acc):
        """Convierte a algo serializable en JSON."""
        return {
            "say": acc["say"], "py": acc["py"], "ret": acc["ret"],
            "user": acc["user"], "while": acc["while"],
            "menus": acc["menus"][:30],
            "jumps": acc["jumps"][:60],
            "calls": acc["calls"][:60],
            "conds": acc["conds"][:60],
            "shows": sorted(acc["shows"])[:80],
            "scenes": sorted(acc["scenes"])[:40],
            "chars": sorted(acc["chars"])[:20],
            "reads": sorted(acc["reads"])[:80],
            "writes": sorted(acc["writes"])[:80],
            "deltas": [list(d) for d in acc["deltas"][:40]],
            "first": acc["first"],
        }

    # ---------- 1.5 Escaneo completo --------------------------------
    def _all_stmts():
        sc = renpy.game.script
        st = getattr(sc, "all_stmts", None)
        if st:
            return st
        nm = getattr(sc, "namemap", None)
        return list(nm.values()) if nm else []

    def sa_scan_gen(force=False):
        """Generador: cede el control cada pocos miles de nodos e informa
        del progreso (0..1). Lo ejecuta el planificador de la Fase 10
        (hilo o tramos) o sa_scan() de una sola vez."""
        if RT.sa_scanning:
            return
        if RT.sa_ready and not force:
            return
        if not sa_available():
            RT.sa_msg = "El AST no es accesible en este motor. Analizador desactivado."
            return

        RT.sa_scanning = True
        RT.sa_msg = "Analizando el guion..."
        t0 = time.time()
        try:
            stmts = _all_stmts()
            total = max(1, len(stmts))
            kinds = {}
            labels = {}
            order = []
            menus = []
            varmap = {}
            conds = []
            defaults = {}
            files = set()
            skipped = 0
            seen_nodes = 0

            nexty = time.time() + YIELD_S
            for n in stmts:
                seen_nodes += 1
                if (seen_nodes & 255) == 0 and time.time() >= nexty:
                    yield 0.3 * seen_nodes / total
                    nexty = time.time() + YIELD_S
                if seen_nodes > SA_MAX_NODES:
                    skipped += 1
                    continue
                fn = getattr(n, "filename", "")
                if not _is_game_file(fn):
                    continue
                files.add(to_text(fn))
                k = type(n).__name__
                kinds[k] = kinds.get(k, 0) + 1

                # default / define: valor inicial de cada variable
                if _isa(n, C_Default) or _isa(n, C_Define):
                    vn = to_text(getattr(n, "varname", "") or "")
                    if vn:
                        defaults[vn] = {
                            "kind": "default" if _isa(n, C_Default) else "define",
                            "src": to_text(_py_source(n))[:160],
                            "file": to_text(fn),
                            "line": to_text(getattr(n, "linenumber", "?")),
                        }

            # Descenso recursivo por cada label: conserva la contencion
            li = 0
            for n in stmts:
                li += 1
                if time.time() >= nexty:
                    yield 0.3 + 0.65 * li / total
                    nexty = time.time() + YIELD_S
                if not _isa(n, C_Label):
                    continue
                name = getattr(n, "name", None)
                if not isinstance(name, string_types):
                    continue
                if name.startswith("_"):
                    continue
                fn = getattr(n, "filename", "")
                if not _is_game_file(fn):
                    continue

                acc = _new_acc()
                _walk(getattr(n, "block", None), acc, 0)
                rec = _freeze(acc)
                rec["name"] = name
                rec["file"] = to_text(fn)
                rec["line"] = to_text(getattr(n, "linenumber", "?"))
                labels[name] = rec
                order.append(name)

                for m in rec["menus"]:
                    menus.append({"label": name, "file": rec["file"],
                                  "line": m["line"], "items": m["items"]})

                for c in rec["conds"]:
                    d = dict(c)
                    d["lbl"] = name
                    conds.append(d)

                for v in rec["writes"]:
                    e = varmap.setdefault(v, {"w": 0, "r": 0, "lbl": []})
                    e["w"] += 1
                    if len(e["lbl"]) < 12:
                        e["lbl"].append(name)
                for v in rec["reads"]:
                    e = varmap.setdefault(v, {"w": 0, "r": 0, "lbl": []})
                    e["r"] += 1

            RT.sa_kinds    = kinds
            RT.sa_labels   = labels
            RT.sa_order    = order
            RT.sa_menus    = menus
            RT.sa_vars     = varmap
            RT.sa_conds    = conds
            RT.sa_defaults = defaults
            RT.sa_files    = len(files)
            RT.sa_skipped  = skipped
            RT.sa_seconds  = round(time.time() - t0, 2)
            RT.sa_ready    = True
            RT.sa_msg = "%d labels, %d menus, %d variables, %d condiciones  (%.2f s)" % (
                len(labels), len(menus), len(varmap), len(conds), RT.sa_seconds)
            yield 0.95
            for _x in sa_save_cache_gen():
                yield 0.97
        except Exception as e:
            log_error("sa_scan", e)
            RT.sa_msg = "Error durante el analisis: %s" % e
        finally:
            RT.sa_scanning = False

    def sa_scan(force=False):
        """De una sola vez (pruebas, autodiagnostico)."""
        run_sync(sa_scan_gen(force))
        return True

    def sa_rescan():
        job_start("sa", lambda: sa_scan_gen(True), "Reanalizando el guion")

    def sa_prepare_gen():
        """Cache si sirve; si no, analisis completo. Todo en segundo plano:
        leer una cache grande tambien cuesta (decenas de ms)."""
        if not RT.sa_ready:
            if sa_load_cache():
                return
            yield 0.05
        for p in sa_scan_gen():
            yield p

    def sa_ensure():
        """Nunca bloquea: lanza (o reutiliza) el trabajo en segundo plano."""
        if RT.sa_ready or job_running("sa") or not sa_available():
            return
        job_start("sa", lambda: sa_prepare_gen(), "Analizando el guion")

    # ---------- 1.6 Cache -------------------------------------------
    def sa_save_cache():
        out = [None]
        run_sync(sa_save_cache_gen(out))
        return out[0]

    def sa_save_cache_gen(out=None):
        return write_json_gen(_savedir_path("umod_script.json"), _sa_payload(), out)

    def _sa_payload():
        return ({
            "format":   2,
            "fp":       script_fp(),
            "kinds":    RT.sa_kinds,
            "labels":   RT.sa_labels,
            "order":    RT.sa_order,
            "menus":    RT.sa_menus[:4000],
            "vars":     RT.sa_vars,
            "conds":    RT.sa_conds[:8000],
            "defaults": RT.sa_defaults,
            "seconds":  RT.sa_seconds,
        })

    def sa_load_cache():
        p = _savedir_path("umod_script.json")
        if not p or not os.path.exists(p):
            return False
        try:
            f = open(p, "r")
            try:
                data = json.load(f)
            finally:
                f.close()
            if data.get("format") != 2 or data.get("fp") != script_fp():
                return False
            RT.sa_kinds    = data.get("kinds", {})
            RT.sa_labels   = data.get("labels", {})
            RT.sa_order    = data.get("order") or sorted(RT.sa_labels.keys())
            RT.sa_menus    = data.get("menus", [])
            RT.sa_vars     = data.get("vars", {})
            RT.sa_conds    = data.get("conds", [])
            RT.sa_defaults = data.get("defaults", {})
            RT.sa_ready    = True
            RT.sa_msg = "%d labels (desde cache)" % len(RT.sa_labels)
            return True
        except Exception as e:
            log_error("sa_load_cache", e)
            return False

    # ---------- 1.7 Consultas para la UI ----------------------------
    SA_TABS = [
        ("sum",   "Resumen"),
        ("lbl",   "Labels"),
        ("menu",  "Menus"),
        ("var",   "Variables"),
        ("cond",  "Condiciones"),
        ("def",   "Valores iniciales"),
    ]

    def sa_summary_rows():
        rows = [
            ("Estado",              RT.sa_msg),
            ("Archivos de guion",   to_text(RT.sa_files)),
            ("Labels analizados",   to_text(len(RT.sa_labels))),
            ("Menus encontrados",   to_text(len(RT.sa_menus))),
            ("Opciones ocultas",    to_text(sa_hidden_count())),
            ("Variables tocadas",   to_text(len(RT.sa_vars))),
            ("Condiciones extraidas", to_text(len(RT.sa_conds))),
            ("default / define",    to_text(len(RT.sa_defaults))),
            ("Saltos con expresion", to_text(sa_dynamic_count())),
            ("Tiempo de analisis",  "%s s" % RT.sa_seconds),
        ]
        rows.append(("", ""))
        rows.append(("--- Nodos por tipo ---", ""))
        for k in sorted(RT.sa_kinds.keys(), key=lambda x: -RT.sa_kinds[x]):
            rows.append((k, to_text(RT.sa_kinds[k])))
        return rows

    def sa_hidden_count():
        n = 0
        for m in RT.sa_menus:
            for it in m["items"]:
                if it.get("hidden"):
                    n += 1
        return n

    def sa_dynamic_count():
        """Saltos calculados en tiempo de ejecucion: el analisis estatico
        NO puede resolverlos. Es el limite honesto de esta fase."""
        n = 0
        for rec in itervalues(RT.sa_labels):
            for j in rec.get("jumps", []):
                if j.get("expr"):
                    n += 1
            for c in rec.get("calls", []):
                if c.get("expr"):
                    n += 1
        return n

    def itervalues(d):
        return (d[k] for k in d)

    def sa_labels_filtered(q):
        s = to_text(q or "").strip().lower()
        names = RT.sa_order or sorted(RT.sa_labels.keys())
        if not s:
            return names
        return [n for n in names if s in n.lower()]

    def sa_menu_rows(q):
        s = to_text(q or "").strip().lower()
        out = []
        for m in RT.sa_menus:
            if s and s not in m["label"].lower():
                hit = any(s in to_text(it["cap"]).lower() for it in m["items"])
                if not hit:
                    continue
            out.append(m)
        return out

    def sa_var_rows(q):
        s = to_text(q or "").strip().lower()
        items = []
        for name in RT.sa_vars:
            if s and s not in name.lower():
                continue
            e = RT.sa_vars[name]
            items.append((name, e.get("w", 0), e.get("r", 0)))
        items.sort(key=lambda t: (-t[1], -t[2], t[0]))
        return ["%-40s  escrituras: %-5d  lecturas: %-5d" % (t[0][:40], t[1], t[2])
                for t in items]

    def sa_cond_rows(q):
        s = to_text(q or "").strip().lower()
        out = []
        for c in RT.sa_conds:
            line = "%s   @ %s" % (cond_text(c), c.get("lbl", "?"))
            if s and s not in line.lower():
                continue
            out.append(line)
        return out

    def sa_def_rows(q):
        s = to_text(q or "").strip().lower()
        out = []
        for name in sorted(RT.sa_defaults.keys()):
            d = RT.sa_defaults[name]
            line = "%-34s %-8s %s" % (name[:34], d.get("kind", ""), d.get("src", ""))
            if s and s not in line.lower():
                continue
            out.append(line)
        return out

    def sa_rows(tab, q):
        if tab == "lbl":
            return sa_labels_filtered(q)
        if tab == "var":
            return sa_var_rows(q)
        if tab == "cond":
            return sa_cond_rows(q)
        if tab == "def":
            return sa_def_rows(q)
        return []

    def sa_pages(items):
        n = len(items)
        return 1 if n == 0 else (n + SA_PAGE - 1) // SA_PAGE

    def sa_page(items, page):
        try:
            start = max(0, int(page)) * SA_PAGE
        except Exception:
            start = 0
        return items[start:start + SA_PAGE]

    def sa_counter(items, page):
        return "%d resultados   -   pagina %d / %d" % (
            len(items), int(page) + 1, sa_pages(items))

    # ---------- 1.8 Detalle de un label -----------------------------
    def sa_detail(name):
        rec = RT.sa_labels.get(name)
        if not rec:
            return [("Sin datos", "ejecuta el analisis")]
        out = [
            ("Archivo",  "%s : %s" % (rec.get("file", "?"), rec.get("line", "?"))),
            ("Dialogos", to_text(rec.get("say", 0))),
            ("Bloques Python", to_text(rec.get("py", 0))),
            ("Menus",    to_text(len(rec.get("menus", [])))),
            ("Return",   to_text(rec.get("ret", 0))),
        ]
        if rec.get("chars"):
            out.append(("Personajes", ", ".join(rec["chars"])))
        if rec.get("first"):
            out.append(("Primera linea", rec["first"]))
        for j in rec.get("jumps", [])[:12]:
            out.append(("jump", j["to"] + ("   (calculado)" if j["expr"] else "")))
        for c in rec.get("calls", [])[:12]:
            out.append(("call", c["to"] + ("   (calculado)" if c["expr"] else "")))
        if rec.get("writes"):
            out.append(("Escribe", ", ".join(rec["writes"][:24])))
        if rec.get("reads"):
            out.append(("Lee", ", ".join(rec["reads"][:24])))
        for d in rec.get("deltas", [])[:12]:
            out.append(("delta", "%s %s %s" % (d[0], d[1], d[2])))
        for c in rec.get("conds", [])[:16]:
            out.append(("condicion", cond_text(c)))
        if rec.get("scenes"):
            out.append(("scene", ", ".join(rec["scenes"][:12])))
        if rec.get("shows"):
            out.append(("show", ", ".join(rec["shows"][:16])))
        return out

    # ---------- 1.9 Apertura ----------------------------------------
    SA_SCREEN = "umod_script"

    def script_open():
        try:
            if not RT.ready:
                scan_all()
            sa_ensure()
            renpy.hide_screen(SCREEN)
            renpy.show_screen(SA_SCREEN)
            renpy.restart_interaction()
        except Exception as e:
            log_error("script_open", e)

    def script_toggle():
        try:
            if renpy.get_screen(SA_SCREEN):
                renpy.hide_screen(SA_SCREEN)
                renpy.restart_interaction()
            else:
                script_open()
        except Exception as e:
            log_error("script_toggle", e)


# ---------------------------------------------------------------------
# 2) Registro de tecla
# ---------------------------------------------------------------------
init -978 python:
    umod.register_key("umod_script", umod.adv_keys(umod.SA_KEYS), umod.script_toggle)
    umod.AUTOSTART.append(umod.sa_ensure)


# =====================================================================
# 3) INTERFAZ DEL ANALIZADOR
# =====================================================================

screen umod_script():

    modal True
    zorder 1100
    tag umod_panel

    default tab = "sum"
    default q = ""
    default page = 0
    default sel = None

    key "K_ESCAPE" action Hide("umod_script")
    key "umod_script" action Hide("umod_script")

    $ islist = tab in ("lbl", "var", "cond", "def")
    $ items = umod.guard(umod.sa_rows, [], tab, q) if islist else []
    $ shown = umod.sa_page(items, page) if islist else []
    $ npages = umod.sa_pages(items)
    $ menus = umod.guard(umod.sa_menu_rows, [], q) if tab == "menu" else []
    $ qval = ScreenVariableInputValue("q", default=False) if umod.HAS_SVIV else None

    add Solid("#000000dd")

    frame:
        background Solid("#0f1117f5")
        xalign 0.5
        yalign 0.5
        xsize umod.S(1480)
        ysize umod.S(880)
        padding (umod.S(18), umod.S(14))

        vbox:
            spacing umod.S(9)

            # ---------------- Cabecera ----------------
            fixed:
                xfill True
                ysize umod.S(38)
                hbox:
                    xalign 0.0
                    yalign 0.5
                    spacing umod.S(16)
                    text "ANALIZADOR DE GUION" size umod.S(22) color "#7fd4ff"
                    text umod.RT.sa_msg size umod.S(13) color "#78839a" yalign 0.5
                hbox:
                    xalign 1.0
                    yalign 0.5
                    spacing umod.S(6)
                    textbutton "Reanalizar":
                        action Function(umod.sa_rescan)
                        text_size umod.S(14)
                        background Solid("#1d2734")
                        hover_background Solid("#2b3a4e")
                        padding (umod.S(12), umod.S(6))
                    textbutton "Panel":
                        action [Hide("umod_script"), Function(umod.open_panel)]
                        text_size umod.S(14)
                        background Solid("#232a36")
                        padding (umod.S(12), umod.S(6))
                    textbutton "Cerrar  (Esc)":
                        action Hide("umod_script")
                        text_size umod.S(14)
                        text_color "#ffd9d9"
                        background Solid("#43222a")
                        hover_background Solid("#6a3340")
                        padding (umod.S(12), umod.S(6))

            # ---------------- Pestanas ----------------
            hbox:
                spacing umod.S(4)
                box_wrap True
                for tid, tlabel in umod.SA_TABS:
                    textbutton tlabel:
                        action [SetScreenVariable("tab", tid),
                                SetScreenVariable("page", 0),
                                SetScreenVariable("sel", None)]
                        text_size umod.S(16)
                        text_color ("#ffffff" if tab == tid else "#98a3b5")
                        background (Solid("#2b3446") if tab == tid else Solid("#191d26"))
                        hover_background Solid("#333e54")
                        padding (umod.S(14), umod.S(7))

            # ---------------- Barra de filtro ----------------
            fixed:
                xfill True
                ysize umod.S(36)
                if tab != "sum":
                    hbox:
                        yalign 0.5
                        spacing umod.S(10)
                        text "Filtro:" size umod.S(15) color "#98a3b5" yalign 0.5
                        if qval:
                            button:
                                action qval.Toggle()
                                background Solid("#0c0f14")
                                hover_background Solid("#161c26")
                                xsize umod.S(400)
                                ysize umod.S(32)
                                padding (umod.S(9), umod.S(5))
                                input:
                                    value qval
                                    length 48
                                    size umod.S(15)
                                    color "#e8eef7"
                        textbutton "limpiar":
                            action [SetScreenVariable("q", ""), SetScreenVariable("page", 0)]
                            text_size umod.S(13)
                            background Solid("#232a36")
                            padding (umod.S(10), umod.S(6))
                        if islist:
                            text umod.sa_counter(items, page):
                                size umod.S(14)
                                color "#98a3b5"
                                yalign 0.5
                            textbutton "<":
                                action SetScreenVariable("page", max(0, page - 1))
                                text_size umod.S(15)
                                background Solid("#232a36")
                                padding (umod.S(14), umod.S(6))
                            textbutton ">":
                                action SetScreenVariable("page", min(npages - 1, page + 1))
                                text_size umod.S(15)
                                background Solid("#232a36")
                                padding (umod.S(14), umod.S(6))

            # ---------------- Contenido ----------------
            frame:
                background Solid("#0c0f14")
                xsize umod.S(1444)
                ysize umod.S(706)
                padding (umod.S(12), umod.S(10))

                # ---- Resumen ----
                if tab == "sum":
                    viewport:
                        xsize umod.S(1418)
                        ysize umod.S(684)
                        scrollbars "vertical"
                        mousewheel True
                        draggable True
                        vbox:
                            spacing umod.S(4)
                            for srow in umod.guard(umod.sa_summary_rows, umod.ERR_PAIRS):
                                hbox:
                                    spacing umod.S(10)
                                    text umod.esc(srow[0]):
                                        size umod.S(15)
                                        color "#7f8ca1"
                                        xsize umod.S(320)
                                    text umod.esc(srow[1]):
                                        size umod.S(15)
                                        color "#dfe7f2"
                            null height umod.S(14)
                            text "Los saltos 'calculados' son jump/call cuyo destino es una expresion evaluada en tiempo de ejecucion. El analisis estatico no puede resolverlos: quedaran como huecos en el grafo de la Fase 4.":
                                size umod.S(13)
                                color "#66707f"

                # ---- Menus ----
                elif tab == "menu":
                    viewport:
                        xsize umod.S(1418)
                        ysize umod.S(684)
                        scrollbars "vertical"
                        mousewheel True
                        draggable True
                        vbox:
                            spacing umod.S(10)
                            for m in menus[:150]:
                                vbox:
                                    spacing umod.S(2)
                                    text umod.esc("%s   (%s : %s)" % (m["label"], m["file"], m["line"])):
                                        size umod.S(15)
                                        color "#8fe0ff"
                                    for it in m["items"]:
                                        hbox:
                                            spacing umod.S(8)
                                            text ("[oculta]" if it["hidden"] else "        "):
                                                size umod.S(12)
                                                color "#e0b585"
                                                xsize umod.S(80)
                                            text umod.esc(it["cap"]):
                                                size umod.S(13)
                                                color "#dfe7f2"
                                                xsize umod.S(600)
                                            text umod.esc(it["cond"] if it["hidden"] else ""):
                                                size umod.S(12)
                                                color "#9aa8bd"
                                                xsize umod.S(420)
                                            text umod.esc(("-> " + it["to"]) if it["to"] else ""):
                                                size umod.S(12)
                                                color "#7f8ca1"

                # ---- Listados ----
                else:
                    hbox:
                        spacing umod.S(12)
                        viewport:
                            xsize (umod.S(880) if tab == "lbl" else umod.S(1418))
                            ysize umod.S(684)
                            scrollbars "vertical"
                            mousewheel True
                            draggable True
                            vbox:
                                spacing umod.S(1)
                                for it in shown:
                                    if tab == "lbl":
                                        textbutton umod.esc(it):
                                            action SetScreenVariable("sel", it)
                                            text_size umod.S(14)
                                            text_color ("#8fe0ff" if sel == it else "#dfe7f2")
                                            background None
                                            hover_background Solid("#1b2431")
                                            padding (umod.S(6), umod.S(2))
                                            xfill True
                                    else:
                                        text umod.esc(it):
                                            size umod.S(13)
                                            color "#dfe7f2"

                        if tab == "lbl":
                            frame:
                                background Solid("#141924")
                                xsize umod.S(526)
                                ysize umod.S(684)
                                padding (umod.S(12), umod.S(10))
                                if sel:
                                    viewport:
                                        xsize umod.S(500)
                                        ysize umod.S(660)
                                        scrollbars "vertical"
                                        mousewheel True
                                        vbox:
                                            spacing umod.S(4)
                                            text umod.esc(sel) size umod.S(16) color "#8fe0ff"
                                            null height umod.S(6)
                                            for drow in umod.guard(umod.sa_detail, umod.ERR_PAIRS, sel):
                                                hbox:
                                                    spacing umod.S(8)
                                                    text umod.esc(drow[0]):
                                                        size umod.S(12)
                                                        color "#7f8ca1"
                                                        xsize umod.S(120)
                                                    text umod.esc(drow[1]):
                                                        size umod.S(12)
                                                        color "#dfe7f2"
                                                        xsize umod.S(350)
                                else:
                                    text "Selecciona un label para ver que variables toca, que condiciones lo gobiernan y a donde salta.":
                                        size umod.S(13)
                                        color "#66707f"


# ##################################################################### #
#   universal_mod_graph.rpy
# ##################################################################### #

# =====================================================================
#  UNIVERSAL REN'PY MOD (UMOD)  -  FASE 4 / Narrative Graph
# ---------------------------------------------------------------------
#  Requiere universal_mod.rpy (Fase 1) y universal_mod_script.rpy
#  (Fase 3) en la misma carpeta.
#
#  Que hace esta fase:
#    - Construye un grafo dirigido entre labels a partir del AST.
#      Aristas: jump, call, caida al label siguiente (fall-through),
#      renpy.jump/renpy.call con destino literal dentro de Python, y
#      acciones Jump()/Call() en bloques Python de UI antigua.
#    - CADA ARISTA LLEVA SU GUARDA: la conjuncion de condiciones que
#      deben cumplirse para que ese salto ocurra (ramas de if previas
#      negadas, condicion de la opcion de menu, condicion del while) y
#      las DECISIONES de menu que hay que tomar para llegar a el.
#    - Detecta cuando un bloque termina (jump/return, if con else en el
#      que todas las ramas terminan, menu en el que todas las opciones
#      terminan) para no inventar caidas al label siguiente.
#    - Busca caminos origen -> destino con Dijkstra, en dos modos:
#        "menos condiciones"  y  "menos pasos".
#    - Normaliza los requisitos del camino en restricciones
#      {variable, operador, valor}: entrada directa de la Fase 6.
#    - Detecta contradicciones estaticas en el camino y comprueba si
#      los incrementos (+=) del propio camino bastan para alcanzar los
#      umbrales que se exigen.
#    - Navegador narrativo: arbol por archivo de guion en orden de
#      aparicion, con labels huerfanos marcados.
#    - Exporta el grafo a Graphviz (.dot).
#
#  ABRIR:  ALT + N
#
#  LIMITES QUE ESTA FASE NO PUEDE SUPERAR (y los muestra):
#    - Saltos calculados (jump expression, renpy.jump(variable)).
#    - Navegacion desde screens (mapas, menus libres, telefonos): las
#      screens no son parte del script, sus Jump() no estan en el AST
#      de labels. En juegos sandbox muchos labels saldran huerfanos.
#    - Las guardas se leen, no se evaluan: el grafo dice que condicion
#      hace falta, no si es alcanzable con los valores reales.
# =====================================================================


# ---------------------------------------------------------------------
# 0) Estado de runtime del grafo
# ---------------------------------------------------------------------
init -1070 python:
    import sys as _umod_sys_n
    try:
        _umod_n = _umod_sys_n.modules["umod_rt"]
        _umod_n.g_ready = False
        _umod_n.g_scanning = False
        _umod_n.g_msg = "Sin construir"
        _umod_n.g_nodes = {}        # label -> {file, line, grp, out, in, dyn}
        _umod_n.g_edges = []        # lista de aristas
        _umod_n.g_groups = []       # [[grupo, [labels en orden de archivo]]]
        _umod_n.g_reach = set()     # alcanzables desde el origen
        _umod_n.g_origin = "start"
        _umod_n.g_expanded = set()
        _umod_n.g_pathcache = {}
        _umod_n.g_seconds = 0.0
        _umod_n.g_last_dot = None
        del _umod_n
    except Exception:
        pass


# ---------------------------------------------------------------------
# 1) Constructor del grafo
# ---------------------------------------------------------------------
init -970 python in umod:

    import heapq, io
    import ast as pyast

    GRAPH = True

    NG_KEYS     = ["alt_K_n"]
    NG_MAX_HOPS = 30
    NG_TREE_CAP = 400
    NG_STEP_CAP = 120
    NG_BIG      = 10 ** 12

    EDGE_LABEL = {
        "jump":   "jump",
        "call":   "call",
        "fall":   "continua en",
        "pyjump": "renpy.jump",
        "pycall": "renpy.call",
        "accion": "accion Jump",
    }

    PY_JUMPS = {
        "renpy.jump":                 "pyjump",
        "renpy.jump_out_of_context":  "pyjump",
        "renpy.call":                 "pycall",
        "renpy.call_in_new_context":  "pycall",
        "Jump":                       "accion",
        "Call":                       "accion",
    }

    def ng_available():
        try:
            return bool(SCRIPT) and sa_available()
        except Exception:
            return False

    # ---------- 1.1 Utilidades --------------------------------------
    _NAT = re.compile(r"(\d+)")

    def natkey(s):
        out = []
        for p in _NAT.split(to_text(s).lower()):
            if p.isdigit():
                out.append((0, int(p), ""))
            else:
                out.append((1, 0, p))
        return out

    def _line_int(s):
        try:
            return int(s)
        except Exception:
            return 0

    def _group_of(fn):
        f = to_text(fn or "").replace("\\", "/")
        if f.startswith("game/"):
            f = f[5:]
        return re.sub(r"\.rpym?c?$", "", f) or "?"

    def _num(s):
        try:
            return float(s)
        except Exception:
            return None

    def _py_jumps(src):
        """Destinos literales de renpy.jump('x'), renpy.call('x'), Jump('x')..."""
        out = []
        s = to_text(src or "").strip()
        if not s or len(s) > SA_MAX_SRC:
            return out
        try:
            tree = pyast.parse(s)
        except Exception:
            return out
        try:
            for node in pyast.walk(tree):
                if not isinstance(node, pyast.Call):
                    continue
                name = _base_name(node.func)
                kind = PY_JUMPS.get(name)
                if not kind or not node.args:
                    continue
                v = _const(node.args[0])
                if isinstance(v, string_types):
                    out.append((to_text(v), kind))
        except Exception as e:
            log_error("py_jumps", e)
        return out

    # ---------- 1.2 Recorrido con guardas ---------------------------
    # Devuelve True si el bloque TERMINA (no continua al siguiente
    # statement): tras un jump o return el resto es inalcanzable.
    def _edge(G, a, b, t, guards, decs, dyn=False):
        G["edges"].append({
            "a": a, "b": b, "t": t,
            "g": [list(x) for x in guards],
            "d": [dict(x) for x in decs],
            "dyn": bool(dyn),
        })

    def _ng_walk(G, block, src, guards, decs, depth):
        if not block or depth > 40:
            return False
        for n in block:
            try:
                ended = _ng_node(G, n, src, guards, decs, depth)
            except Exception as e:
                log_error("ng_walk", e)
                ended = False
            if ended:
                return True
        return False

    def _ng_node(G, n, src, guards, decs, depth):

        if _isa(n, C_Jump):
            if getattr(n, "expression", False):
                _edge(G, src, None, "jump", guards, decs, True)
            else:
                _edge(G, src, to_text(getattr(n, "target", "")), "jump", guards, decs)
            return True

        if _isa(n, C_Call):
            if getattr(n, "expression", False):
                _edge(G, src, None, "call", guards, decs, True)
            else:
                _edge(G, src, to_text(getattr(n, "label", "")), "call", guards, decs)
            return False                    # tras el call, se vuelve aqui

        if _isa(n, C_Return):
            return True

        if _isa(n, C_If):
            prev = []
            any_entry = False
            has_else = False
            all_end = True
            for entry in (getattr(n, "entries", None) or []):
                try:
                    cond, blk = entry[0], entry[1]
                except Exception:
                    continue
                any_entry = True
                c = to_text(cond).strip()
                g = list(guards) + [[p, False] for p in prev]
                if c in ("True", ""):
                    has_else = True
                else:
                    g.append([c, True])
                ended = _ng_walk(G, blk, src, g, decs, depth + 1)
                all_end = all_end and ended
                if has_else:
                    break
                prev.append(c)
            # Sin else, siempre existe el camino "ninguna rama": no termina.
            return bool(any_entry and has_else and all_end)

        if _isa(n, C_Menu):
            any_choice = False
            all_end = True
            line = to_text(getattr(n, "linenumber", "?"))
            for i, it in enumerate(getattr(n, "items", None) or []):
                try:
                    cap = to_text(it[0]) if len(it) > 0 else ""
                    cond = to_text(it[1]) if len(it) > 1 else "True"
                    blk = it[2] if len(it) > 2 else None
                except Exception:
                    continue
                if blk is None:
                    continue                # titulo del menu
                any_choice = True
                g = list(guards)
                c = cond.strip()
                if c not in ("True", ""):
                    g.append([c, True])
                d = list(decs) + [{"cap": cap[:90], "line": line, "i": i}]
                ended = _ng_walk(G, blk, src, g, d, depth + 1)
                all_end = all_end and ended
            return bool(any_choice and all_end)

        if _isa(n, C_While):
            c = to_text(getattr(n, "condition", "")).strip()
            g = list(guards)
            if c not in ("True", ""):
                g.append([c, True])
            _ng_walk(G, getattr(n, "block", None), src, g, decs, depth + 1)
            return False

        if _isa(n, C_Python):
            for tgt, kind in _py_jumps(_py_source(n)):
                _edge(G, src, tgt, kind, guards, decs)
            return False                    # puede estar dentro de un if de Python

        if _isa(n, C_Label):
            nm = getattr(n, "name", None)
            if isinstance(nm, string_types):
                _edge(G, src, nm, "fall", guards, decs)
            return True

        blk = getattr(n, "block", None)     # Translate y similares
        if isinstance(blk, list):
            return _ng_walk(G, blk, src, guards, decs, depth + 1)
        return False

    def _ng_after(n):
        """Primer label alcanzable siguiendo .next desde n."""
        hops = 0
        while n is not None and hops < NG_MAX_HOPS:
            hops += 1
            if _isa(n, C_Label):
                nm = getattr(n, "name", None)
                return nm if isinstance(nm, string_types) else None
            if _isa(n, C_Return):
                return None
            if _isa(n, C_Jump):
                if getattr(n, "expression", False):
                    return None
                return to_text(getattr(n, "target", ""))
            n = getattr(n, "next", None)
        return None

    def _ng_body(lab):
        """(cuerpo, label al que cae si el cuerpo no termina).
        Label.next apunta al statement que sigue al bloque del label."""
        blk = getattr(lab, "block", None)
        if blk:
            return blk, _ng_after(getattr(lab, "next", None))
        # Sintaxis antigua: label sin bloque indentado.
        body = []
        n = getattr(lab, "next", None)
        while n is not None and len(body) < 5000 and not _isa(n, C_Label):
            body.append(n)
            n = getattr(n, "next", None)
        fall = None
        if _isa(n, C_Label):
            nm = getattr(n, "name", None)
            fall = nm if isinstance(nm, string_types) else None
        return body, fall

    # ---------- 1.3 Construccion ------------------------------------
    def ng_build_gen(force=False):
        """Generador (ver sa_scan_gen). Publica el grafo de una vez al final:
        una pantalla nunca ve un grafo a medio construir."""
        if RT.g_scanning:
            return
        if RT.g_ready and not force:
            return
        if not ng_available():
            RT.g_msg = "Necesita el Analizador de guion (Fase 3) y acceso al AST."
            return

        RT.g_scanning = True
        RT.g_msg = "Construyendo grafo..."
        t0 = time.time()
        try:
            G = {"nodes": {}, "edges": []}
            labs = []
            stmts = _all_stmts()
            total = max(1, len(stmts))
            si = 0
            nexty = time.time() + YIELD_S
            for n in stmts:
                si += 1
                if (si & 255) == 0 and time.time() >= nexty:
                    yield 0.2 * si / total
                    nexty = time.time() + YIELD_S
                if not _isa(n, C_Label):
                    continue
                nm = getattr(n, "name", None)
                if not isinstance(nm, string_types) or nm.startswith("_"):
                    continue
                fn = getattr(n, "filename", "")
                if not _is_game_file(fn) or nm in G["nodes"]:
                    continue
                G["nodes"][nm] = {
                    "file": to_text(fn),
                    "line": to_text(getattr(n, "linenumber", "?")),
                    "grp":  _group_of(fn),
                    "out":  [], "in": [], "dyn": 0,
                }
                labs.append((nm, n))

            nl = max(1, len(labs))
            for li, (nm, n) in enumerate(labs):
                if time.time() >= nexty:
                    yield 0.2 + 0.7 * li / nl
                    nexty = time.time() + YIELD_S
                body, fall = _ng_body(n)
                ended = _ng_walk(G, body, nm, [], [], 0)
                if not ended and fall:
                    _edge(G, nm, fall, "fall", [], [])

            yield 0.9
            _ng_index(G)
            groups = _ng_groups(G["nodes"])
            yield 0.92
            RT.g_nodes = G["nodes"]
            RT.g_edges = G["edges"]
            RT.g_groups = groups
            if RT.g_origin not in RT.g_nodes:
                RT.g_origin = "start" if "start" in RT.g_nodes else (
                    RT.g_groups[0][1][0] if RT.g_groups and RT.g_groups[0][1] else "")
            ng_recompute_reach()
            RT.g_pathcache = {}
            RT.g_seconds = round(time.time() - t0, 2)
            RT.g_ready = True
            ng_update_msg()
            yield 0.94
            for _x in ng_save_cache_gen():
                yield 0.97
            # Cada integracion reindexa el grafo: un tramo para cada una.
            if TRACKER:
                yield 0.98
                tr_merge_into_graph()      # Fase 5: transiciones observadas
            if ADAPTERS:
                yield 0.99
                ad_merge_into_graph()      # Fase 9: aristas declaradas
        except Exception as e:
            log_error("ng_build", e)
            RT.g_msg = "Error construyendo el grafo: %s" % e
        finally:
            RT.g_scanning = False

    def ng_build(force=False):
        """De una sola vez (pruebas, autodiagnostico)."""
        run_sync(ng_build_gen(force))
        return True

    def ng_rebuild():
        job_start("ng", lambda: ng_build_gen(True), "Reconstruyendo el grafo")

    def ng_prepare_gen():
        if not RT.g_ready:
            if ng_load_cache():
                return
            yield 0.05
        for p in ng_build_gen():
            yield p

    def ng_ensure():
        """Nunca bloquea: lanza (o reutiliza) el trabajo en segundo plano."""
        if RT.g_ready or job_running("ng") or not ng_available():
            return
        job_start("ng", lambda: ng_prepare_gen(), "Preparando el mapa de la historia")

    def _ng_index(G):
        N = G["nodes"]
        for i, e in enumerate(G["edges"]):
            a = N.get(e["a"])
            if a is not None:
                a["out"].append(i)
                if e["dyn"]:
                    a["dyn"] += 1
            if e["b"] is not None:
                b = N.get(e["b"])
                if b is not None:
                    b["in"].append(i)
                else:
                    e["ext"] = True         # label del motor o inexistente

    def _ng_groups(N):
        groups = {}
        for nm in N:
            groups.setdefault(N[nm]["grp"], []).append(nm)
        out = []
        for g in sorted(groups.keys(), key=natkey):
            out.append([g, sorted(groups[g], key=lambda x: _line_int(N[x]["line"]))])
        return out

    def ng_replace_extra(flag, new_edges):
        """Sustituye las aristas extra marcadas con 'flag' ("obs" = Fase 5,
        "adp" = Fase 9) por new_edges. Si no habia ninguna (grafo recien
        construido) solo indexa las nuevas: reindexar 40.000 aristas cuesta
        decenas de ms y congelaria un tramo."""
        if any(e.get(flag) for e in RT.g_edges):
            edges = [e for e in RT.g_edges if not e.get(flag)] + list(new_edges)
            for nm in RT.g_nodes:
                nd = RT.g_nodes[nm]
                nd["out"] = []
                nd["in"] = []
                nd["dyn"] = 0
            _ng_index({"nodes": RT.g_nodes, "edges": edges})
            RT.g_edges = edges
        elif new_edges:
            base = len(RT.g_edges)
            RT.g_edges.extend(new_edges)
            for i, e in enumerate(new_edges):
                a = RT.g_nodes.get(e["a"])
                b = RT.g_nodes.get(e["b"])
                if a is not None:
                    a["out"].append(base + i)
                if b is not None:
                    b["in"].append(base + i)
        else:
            return
        RT.g_pathcache = {}
        ng_recompute_reach()
        ng_update_msg()

    def ng_recompute_reach():
        seen = set()
        o = RT.g_origin
        if o in RT.g_nodes:
            stack = [o]
            seen.add(o)
            while stack:
                u = stack.pop()
                for ei in RT.g_nodes[u]["out"]:
                    e = RT.g_edges[ei]
                    v = e["b"]
                    if e["dyn"] or v is None or v in seen or v not in RT.g_nodes:
                        continue
                    seen.add(v)
                    stack.append(v)
        RT.g_reach = seen

    def ng_stats():
        st = {"dyn": 0, "ext": 0}
        for e in RT.g_edges:
            st[e["t"]] = st.get(e["t"], 0) + 1
            if e["dyn"]:
                st["dyn"] += 1
            if e.get("ext"):
                st["ext"] += 1
        return st

    def ng_update_msg():
        st = ng_stats()
        n = len(RT.g_nodes)
        orph = n - len(RT.g_reach)
        RT.g_msg = "%d labels, %d aristas, %d calculadas, %d huerfanos desde '%s'  (%.2f s)" % (
            n, len(RT.g_edges), st["dyn"], orph, RT.g_origin, RT.g_seconds)

    # ---------- 1.4 Cache -------------------------------------------
    def ng_save_cache():
        out = [None]
        run_sync(ng_save_cache_gen(out))
        return out[0]

    def ng_save_cache_gen(out=None):
        return write_json_gen(_savedir_path("umod_graph.json"), _ng_payload(), out)

    def _ng_payload():
        return ({
            "format": 1,
            "fp":     script_fp(),
            "nodes":  RT.g_nodes,
            "edges":  RT.g_edges,
            "groups": RT.g_groups,
            "origin": RT.g_origin,
        })

    def ng_load_cache():
        p = _savedir_path("umod_graph.json")
        if not p or not os.path.exists(p):
            return False
        try:
            f = open(p, "r")
            try:
                data = json.load(f)
            finally:
                f.close()
            if data.get("fp") != script_fp():
                return False
            RT.g_nodes = data.get("nodes", {})
            RT.g_edges = data.get("edges", [])
            RT.g_groups = data.get("groups", [])
            RT.g_origin = data.get("origin", "start")
            RT.g_pathcache = {}
            ng_recompute_reach()
            RT.g_ready = True
            ng_update_msg()
            RT.g_msg += "  [cache]"
            if TRACKER:
                tr_merge_into_graph()      # Fase 5: transiciones observadas
            if ADAPTERS:
                ad_merge_into_graph()      # Fase 9: aristas declaradas
            return True
        except Exception as e:
            log_error("ng_load_cache", e)
            return False

    # ---------- 1.5 Busqueda de caminos (Dijkstra) ------------------
    # Modo "guards": cada condicion cuesta 2. Prefiere caminos con menos
    #                requisitos aunque sean mas largos.
    # Modo "short":  cada arista cuesta 1. Camino mas corto en saltos.
    def ng_path(src, dst, mode):
        N, E = RT.g_nodes, RT.g_edges
        if src not in N or dst not in N:
            return None
        if src == dst:
            return []
        dist = {src: 0}
        prev = {}
        done = set()
        heap = [(0, 0, src)]
        cnt = 0
        while heap:
            d, _c, u = heapq.heappop(heap)
            if u in done:
                continue
            done.add(u)
            if u == dst:
                break
            for ei in N[u]["out"]:
                e = E[ei]
                v = e["b"]
                if e["dyn"] or v is None or v not in N or v in done:
                    continue
                w = 1 + (2 * len(e["g"]) if mode == "guards" else 0)
                nd = d + w
                if nd < dist.get(v, NG_BIG):
                    dist[v] = nd
                    prev[v] = ei
                    cnt += 1
                    heapq.heappush(heap, (nd, cnt, v))
        if dst not in prev:
            return None
        path = []
        v = dst
        guard = 0
        while v != src and guard < 100000:
            guard += 1
            ei = prev[v]
            path.append(ei)
            v = E[ei]["a"]
        path.reverse()
        return path

    # ---------- 1.6 Normalizacion de requisitos ---------------------
    _NEG = {"==": "!=", "!=": "==", "<": ">=", "<=": ">", ">": "<=", ">=": "<",
            "in": "not in", "not in": "in", "contiene": "no contiene",
            "no contiene": "contiene", "is": "is not", "is not": "is"}

    def _norm(c, flip):
        c = dict(c)
        if c["op"] == "es cierto":
            truth = (c["val"] == "True")
            if flip:
                truth = not truth
            c["val"] = "True" if truth else "False"
        elif bool(c.get("neg")) != bool(flip):
            c["op"] = _NEG.get(c["op"], c["op"])
        c["neg"] = False
        return c

    def guard_constraints(raw, pol):
        """(restricciones, tipo)  tipo: '' | 'or' | 'compleja'."""
        cs = parse_condition(raw)
        if not cs:
            return ([], "compleja")
        if pol:
            if any(c.get("alt") for c in cs):
                return ([_norm(c, False) for c in cs], "or")
            return ([_norm(c, False) for c in cs], "")
        # NO (a) es trivial; NO (a and b) ya no es una conjuncion.
        if len(cs) == 1 and not cs[0].get("alt"):
            return ([_norm(cs[0], True)], "")
        return ([], "compleja")

    def req_text(c):
        if c["op"] == "es cierto":
            return "%s es %s" % (c["v"], "verdadero" if c["val"] == "True" else "falso")
        return "%s %s %s" % (c["v"], c["op"], c["val"])

    def ng_requirements(path):
        reqs, alts, cplx, decisions = [], [], [], []
        seen = set()
        for ei in path:
            e = RT.g_edges[ei]
            for d in e["d"]:
                decisions.append((e["a"], d["cap"], d.get("line", "?")))
            for raw, pol in e["g"]:
                key = (raw, bool(pol))
                if key in seen:
                    continue
                seen.add(key)
                cs, kind = guard_constraints(raw, pol)
                if kind == "compleja":
                    cplx.append(("" if pol else "NO ") + "(" + raw + ")")
                elif kind == "or":
                    alts.append(" O ".join(req_text(c) for c in cs))
                else:
                    reqs.extend(cs)
        return reqs, alts, cplx, decisions

    def ng_conflicts(reqs):
        """Contradicciones si la variable NO cambia entre una guarda y otra."""
        by = {}
        for c in reqs:
            by.setdefault(c["v"], []).append(c)
        out = []
        eps = 1e-9
        for v in sorted(by.keys()):
            lo = hi = None
            eq, ne, truth = set(), set(), set()
            for c in by[v]:
                op, x = c["op"], _num(c["val"])
                if op == "es cierto":
                    truth.add(c["val"])
                elif op == "==":
                    eq.add(c["val"])
                elif op == "!=":
                    ne.add(c["val"])
                elif x is not None and op in (">", ">="):
                    b = x + eps if op == ">" else x
                    lo = b if lo is None else max(lo, b)
                elif x is not None and op in ("<", "<="):
                    b = x - eps if op == "<" else x
                    hi = b if hi is None else min(hi, b)
            if len(truth) > 1:
                out.append("%s debe ser verdadero y falso a la vez" % v)
            if len(eq) > 1:
                out.append("%s debe valer %s a la vez" % (v, " y ".join(sorted(eq))))
            if eq & ne:
                out.append("%s debe ser y no ser %s" % (v, ", ".join(sorted(eq & ne))))
            if lo is not None and hi is not None and lo > hi:
                out.append("%s necesita un minimo mayor que su maximo" % v)
            for val in eq:
                x = _num(val)
                if x is None:
                    continue
                if (lo is not None and x < lo) or (hi is not None and x > hi):
                    out.append("%s == %s choca con sus limites" % (v, val))
        return out

    def ng_deltas(path):
        """Suma de incrementos numericos de los labels del camino.
        Es una COTA SUPERIOR: cuenta los += de todas las ramas del label,
        no solo las que se recorren."""
        agg = {}
        for ei in path:
            rec = RT.sa_labels.get(RT.g_edges[ei]["a"]) or {}
            for d in rec.get("deltas", []):
                try:
                    var, op, val = d[0], d[1], _num(d[2])
                except Exception:
                    continue
                if val is None:
                    continue
                if op == "+=":
                    agg[var] = agg.get(var, 0) + val
                elif op == "-=":
                    agg[var] = agg.get(var, 0) - val
        return agg

    def _initial_value(var):
        d = RT.sa_defaults.get(var)
        if not d:
            return (0.0, False)
        x = _num(d.get("src", ""))
        return (x, True) if x is not None else (0.0, False)

    def _fmt(x):
        try:
            return ("%d" % x) if float(x) == int(x) else ("%.2f" % x)
        except Exception:
            return to_text(x)

    def ng_budget(reqs, path):
        """Compara umbrales >= / > con valor inicial + incrementos del camino."""
        agg = ng_deltas(path)
        out = []
        done = set()
        for c in reqs:
            if c["op"] not in (">", ">=") or c["v"] in done:
                continue
            thr = _num(c["val"])
            if thr is None:
                continue
            done.add(c["v"])
            init, known = _initial_value(c["v"])
            gain = agg.get(c["v"], 0)
            total = init + gain
            enough = total > thr if c["op"] == ">" else total >= thr
            msg = "%s %s %s : inicial %s%s + hasta %s en el camino = %s" % (
                c["v"], c["op"], c["val"], _fmt(init),
                "" if known else " (supuesto)", _fmt(gain), _fmt(total))
            out.append(("ok" if enough else "warn", msg))
        return out

    # ---------- 1.7 Vistas para la UI -------------------------------
    def ng_view(origin, target, mode):
        key = (origin, target, mode)
        cached = RT.g_pathcache.get(key)
        if cached is not None:
            return cached

        out = [("h", "%s  ->  %s" % (origin, target))]
        if origin not in RT.g_nodes:
            out.append(("warn", "El origen no existe. Fija otro label como origen."))
            RT.g_pathcache[key] = out
            return out

        path = ng_path(origin, target, mode)

        if path is None:
            out.append(("warn", "No existe camino ESTATICO desde el origen."))
            out.append(("note", "Puede alcanzarse desde una screen (mapa, menu libre, telefono), por un salto calculado, desde un replay o desde otra rama que no pasa por este origen."))
            n_in = len(RT.g_nodes.get(target, {}).get("in", []))
            out.append(("note", "Aristas de entrada conocidas: %d" % n_in))
            RT.g_pathcache[key] = out
            return out

        if not path:
            out.append(("ok", "Es el propio origen."))
            RT.g_pathcache[key] = out
            return out

        out.append(("h", "CAMINO  (%d pasos)" % len(path)))
        for ei in path[:NG_STEP_CAP]:
            e = RT.g_edges[ei]
            out.append(("step", "%s   %s  ->  %s" % (EDGE_LABEL.get(e["t"], e["t"]), e["a"], e["b"])))
            for d in e["d"]:
                out.append(("dec", "elegir: \"%s\"" % d["cap"]))
            for raw, pol in e["g"]:
                out.append(("guard", ("si  " if pol else "si NO  ") + raw))
        if len(path) > NG_STEP_CAP:
            out.append(("note", "... %d pasos mas" % (len(path) - NG_STEP_CAP)))

        reqs, alts, cplx, decisions = ng_requirements(path)

        out.append(("h", "REQUISITOS NORMALIZADOS  (entrada de la Fase 6)"))
        if not (reqs or alts or cplx):
            out.append(("ok", "Ninguna condicion en el camino."))
        for c in reqs:
            out.append(("req", req_text(c)))
        for a in alts:
            out.append(("req", "una de:  " + a))
        for c in cplx:
            out.append(("warn", "no normalizable:  " + c))

        out.append(("h", "DECISIONES  (%d)" % len(decisions)))
        if not decisions:
            out.append(("note", "No hay que elegir nada en ningun menu."))
        for lb, cap, ln in decisions[:60]:
            out.append(("dec", "%s  (linea %s):  \"%s\"" % (lb, ln, cap)))

        out.append(("h", "COHERENCIA"))
        conf = ng_conflicts(reqs)
        if conf:
            for c in conf:
                out.append(("warn", c))
            out.append(("note", "Solo es contradiccion si la variable no cambia entre las dos guardas."))
        else:
            out.append(("ok", "Sin contradicciones estaticas."))

        budget = ng_budget(reqs, path)
        if budget:
            out.append(("h", "PRESUPUESTO DE PUNTOS  (estimacion)"))
            for kind, msg in budget:
                out.append((kind, msg))
            if any(k == "warn" for k, _m in budget):
                out.append(("note", "Si el camino no basta, los puntos vienen de eventos fuera de el: rutas laterales, free-roam, eventos repetibles. Eso es trabajo de las fases 5-7."))

        RT.g_pathcache[key] = out
        return out

    def ng_detail(name):
        nd = RT.g_nodes.get(name)
        if not nd:
            return [("warn", "Label desconocido")]
        out = [("h", name),
               ("note", "%s : %s" % (nd["file"], nd["line"]))]
        if name in RT.g_reach:
            out.append(("ok", "alcanzable desde '%s'" % RT.g_origin))
        else:
            out.append(("warn", "huerfano: no alcanzable estaticamente desde '%s'" % RT.g_origin))
        if nd.get("dyn"):
            out.append(("warn", "%d salto(s) calculado(s): destino desconocido" % nd["dyn"]))

        rec = RT.sa_labels.get(name) or {}
        if rec.get("writes"):
            out.append(("note", "escribe: " + ", ".join(rec["writes"][:16])))
        if rec.get("chars"):
            out.append(("note", "personajes: " + ", ".join(rec["chars"][:10])))

        out.append(("h", "ENTRADAS  (%d)" % len(nd["in"])))
        for ei in nd["in"][:40]:
            e = RT.g_edges[ei]
            extra = ""
            if e["g"]:
                extra += "   [%d cond]" % len(e["g"])
            if e["d"]:
                extra += "   [menu]"
            out.append(("step", "<- %s   %s%s" % (EDGE_LABEL.get(e["t"], e["t"]), e["a"], extra)))

        out.append(("h", "SALIDAS  (%d)" % len(nd["out"])))
        for ei in nd["out"][:40]:
            e = RT.g_edges[ei]
            if e["dyn"]:
                out.append(("warn", "%s  ->  (calculado)" % EDGE_LABEL.get(e["t"], e["t"])))
                continue
            tgt = e["b"] + ("   (fuera del juego)" if e.get("ext") else "")
            out.append(("step", "%s  ->  %s" % (EDGE_LABEL.get(e["t"], e["t"]), tgt)))
            for d in e["d"][-2:]:
                out.append(("dec", "elegir: \"%s\"" % d["cap"]))
            for raw, pol in e["g"][:4]:
                out.append(("guard", ("si  " if pol else "si NO  ") + raw))
        return out

    KIND_COLOR = {
        "h":     "#8fe0ff",
        "step":  "#dfe7f2",
        "guard": "#e7c58a",
        "dec":   "#b9a6ff",
        "req":   "#9fe0b0",
        "ok":    "#7ee0a5",
        "warn":  "#ff9b8a",
        "note":  "#7f8ca1",
    }

    def kcolor(k):
        return KIND_COLOR.get(k, "#dfe7f2")

    def ksize(k):
        return S(15) if k == "h" else S(13)

    def kindent(k):
        return S(18) if k in ("guard", "dec") else 0

    # ---------- 1.8 Arbol del navegador -----------------------------
    def ng_tree_rows(q, orphans_only):
        s = to_text(q or "").strip().lower()
        rows = []
        if s or orphans_only:
            for g, labs in RT.g_groups:
                for lb in labs:
                    if s and s not in lb.lower():
                        continue
                    if orphans_only and lb in RT.g_reach:
                        continue
                    rows.append(("l", lb, g))
                    if len(rows) >= NG_TREE_CAP:
                        return rows
            return rows
        for g, labs in RT.g_groups:
            rows.append(("g", g, len(labs)))
            if g in RT.g_expanded:
                for lb in labs[:NG_TREE_CAP]:
                    rows.append(("l", lb, g))
        return rows

    def ng_group_label(g, n):
        return "%s %s   (%d)" % ("[-]" if g in RT.g_expanded else "[+]", g, n)

    def ng_toggle_group(g):
        if g in RT.g_expanded:
            RT.g_expanded.discard(g)
        else:
            RT.g_expanded.add(g)
        renpy.restart_interaction()

    def ng_set_origin(name):
        if name in RT.g_nodes:
            RT.g_origin = name
            RT.g_pathcache = {}
            ng_recompute_reach()
            ng_update_msg()
            renpy.restart_interaction()

    def ng_is_orphan(name):
        return name not in RT.g_reach

    # ---------- 1.9 Exportacion Graphviz ----------------------------
    def _dq(s):
        return to_text(s).replace("\\", "\\\\").replace('"', '\\"')

    def ng_export_dot():
        lines = [u"digraph umod {", u"  rankdir=LR;",
                 u"  node [shape=box, fontsize=10];"]
        for i, (g, labs) in enumerate(RT.g_groups):
            lines.append(u'  subgraph cluster_%d { label="%s";' % (i, _dq(g)))
            for lb in labs:
                lines.append(u'    "%s";' % _dq(lb))
            lines.append(u"  }")
        style = {"call": "dashed", "fall": "dotted", "pycall": "dashed"}
        for e in RT.g_edges:
            if e["dyn"] or e["b"] is None:
                continue
            lab = ""
            if e["d"]:
                lab = e["d"][-1]["cap"][:32]
            elif e["g"]:
                lab = e["g"][-1][0][:32]
            lines.append(u'  "%s" -> "%s" [style=%s, label="%s"];' % (
                _dq(e["a"]), _dq(e["b"]), style.get(e["t"], "solid"), _dq(lab)))
        lines.append(u"}")
        p = _savedir_path("umod_graph.dot")
        if not p:
            return None
        try:
            f = io.open(p, "w", encoding="utf-8")
            try:
                f.write(u"\n".join(to_text(x) for x in lines))
            finally:
                f.close()
            RT.g_last_dot = p
            renpy.notify("Grafo exportado a umod_graph.dot")
        except Exception as e:
            log_error("ng_export_dot", e)
        return RT.g_last_dot

    # ---------- 1.10 Apertura ---------------------------------------
    NG_SCREEN = "umod_graph"

    def graph_open():
        try:
            if not RT.ready:
                scan_all()
            sa_ensure()
            ng_ensure()
            renpy.hide_screen(SCREEN)
            renpy.show_screen(NG_SCREEN)
            renpy.restart_interaction()
        except Exception as e:
            log_error("graph_open", e)

    def graph_toggle():
        try:
            if renpy.get_screen(NG_SCREEN):
                renpy.hide_screen(NG_SCREEN)
                renpy.restart_interaction()
            else:
                graph_open()
        except Exception as e:
            log_error("graph_toggle", e)


# ---------------------------------------------------------------------
# 2) Registro de tecla
# ---------------------------------------------------------------------
init -968 python:
    umod.register_key("umod_graph", umod.adv_keys(umod.NG_KEYS), umod.graph_toggle)
    umod.AUTOSTART.append(umod.ng_ensure)


# =====================================================================
# 3) INTERFAZ: NAVEGADOR NARRATIVO
# =====================================================================

screen umod_graph():

    modal True
    zorder 1100
    tag umod_panel

    default q = ""
    default sel = None
    default mode = "guards"
    default orph = False

    key "K_ESCAPE" action Hide("umod_graph")
    key "umod_graph" action Hide("umod_graph")

    $ rows = umod.guard(umod.ng_tree_rows, [], q, orph)
    $ qval = ScreenVariableInputValue("q", default=False) if umod.HAS_SVIV else None

    add Solid("#000000dd")

    frame:
        background Solid("#0f1117f5")
        xalign 0.5
        yalign 0.5
        xsize umod.S(1480)
        ysize umod.S(880)
        padding (umod.S(18), umod.S(14))

        vbox:
            spacing umod.S(9)

            # ---------------- Cabecera ----------------
            fixed:
                xfill True
                ysize umod.S(38)
                hbox:
                    xalign 0.0
                    yalign 0.5
                    spacing umod.S(16)
                    text "NAVEGADOR NARRATIVO" size umod.S(22) color "#7fd4ff"
                    text umod.esc(umod.RT.g_msg) size umod.S(12) color "#78839a" yalign 0.5
                hbox:
                    xalign 1.0
                    yalign 0.5
                    spacing umod.S(6)
                    textbutton "Reconstruir":
                        action Function(umod.ng_rebuild)
                        text_size umod.S(13)
                        background Solid("#1d2734")
                        hover_background Solid("#2b3a4e")
                        padding (umod.S(10), umod.S(6))
                    textbutton "Exportar .dot":
                        action Function(umod.ng_export_dot)
                        text_size umod.S(13)
                        background Solid("#1d2734")
                        hover_background Solid("#2b3a4e")
                        padding (umod.S(10), umod.S(6))
                    textbutton "Panel":
                        action [Hide("umod_graph"), Function(umod.open_panel)]
                        text_size umod.S(13)
                        background Solid("#232a36")
                        padding (umod.S(10), umod.S(6))
                    textbutton "Cerrar  (Esc)":
                        action Hide("umod_graph")
                        text_size umod.S(13)
                        text_color "#ffd9d9"
                        background Solid("#43222a")
                        hover_background Solid("#6a3340")
                        padding (umod.S(10), umod.S(6))

            # ---------------- Barra de control ----------------
            fixed:
                xfill True
                ysize umod.S(36)
                hbox:
                    yalign 0.5
                    spacing umod.S(8)
                    if qval:
                        button:
                            action qval.Toggle()
                            background Solid("#0c0f14")
                            hover_background Solid("#161c26")
                            xsize umod.S(300)
                            ysize umod.S(32)
                            padding (umod.S(9), umod.S(5))
                            input:
                                value qval
                                length 40
                                size umod.S(15)
                                color "#e8eef7"
                    textbutton "limpiar":
                        action SetScreenVariable("q", "")
                        text_size umod.S(13)
                        background Solid("#232a36")
                        padding (umod.S(10), umod.S(6))
                    textbutton ("Solo huerfanos ON" if orph else "Solo huerfanos"):
                        action ToggleScreenVariable("orph")
                        text_size umod.S(13)
                        text_color ("#ffb38a" if orph else "#98a3b5")
                        background Solid("#232a36")
                        padding (umod.S(10), umod.S(6))
                    text "Origen:" size umod.S(14) color "#98a3b5" yalign 0.5
                    text umod.esc(umod.RT.g_origin) size umod.S(14) color "#9fe0b0" yalign 0.5
                    text "  Busqueda:" size umod.S(14) color "#98a3b5" yalign 0.5
                    textbutton "menos condiciones":
                        action SetScreenVariable("mode", "guards")
                        text_size umod.S(13)
                        text_color ("#ffffff" if mode == "guards" else "#98a3b5")
                        background (Solid("#2b3446") if mode == "guards" else Solid("#191d26"))
                        padding (umod.S(10), umod.S(6))
                    textbutton "menos pasos":
                        action SetScreenVariable("mode", "short")
                        text_size umod.S(13)
                        text_color ("#ffffff" if mode == "short" else "#98a3b5")
                        background (Solid("#2b3446") if mode == "short" else Solid("#191d26"))
                        padding (umod.S(10), umod.S(6))

            # ---------------- Tres columnas ----------------
            hbox:
                spacing umod.S(12)

                # ---- Arbol ----
                frame:
                    background Solid("#0c0f14")
                    xsize umod.S(400)
                    ysize umod.S(722)
                    padding (umod.S(8), umod.S(8))
                    viewport:
                        xsize umod.S(384)
                        ysize umod.S(706)
                        scrollbars "vertical"
                        mousewheel True
                        draggable True
                        vbox:
                            spacing umod.S(1)
                            for r in rows:
                                if r[0] == "g":
                                    textbutton umod.esc(umod.ng_group_label(r[1], r[2])):
                                        action Function(umod.ng_toggle_group, r[1])
                                        text_size umod.S(14)
                                        text_color "#8fe0ff"
                                        background Solid("#141a24")
                                        hover_background Solid("#1d2636")
                                        padding (umod.S(6), umod.S(4))
                                        xfill True
                                else:
                                    textbutton umod.esc("    " + r[1]):
                                        action SetScreenVariable("sel", r[1])
                                        text_size umod.S(13)
                                        text_color ("#ffffff" if sel == r[1] else ("#d99a6c" if umod.ng_is_orphan(r[1]) else "#c3ccda"))
                                        background (Solid("#26324a") if sel == r[1] else None)
                                        hover_background Solid("#1b2431")
                                        padding (umod.S(6), umod.S(2))
                                        xfill True

                # ---- Detalle del label ----
                frame:
                    background Solid("#121722")
                    xsize umod.S(470)
                    ysize umod.S(722)
                    padding (umod.S(10), umod.S(8))
                    if sel:
                        vbox:
                            spacing umod.S(6)
                            textbutton "Fijar como origen":
                                action Function(umod.ng_set_origin, sel)
                                text_size umod.S(13)
                                background Solid("#1d3428")
                                hover_background Solid("#2b4d3a")
                                padding (umod.S(10), umod.S(5))
                            viewport:
                                xsize umod.S(450)
                                ysize umod.S(664)
                                scrollbars "vertical"
                                mousewheel True
                                draggable True
                                vbox:
                                    spacing umod.S(3)
                                    for drow in umod.guard(umod.ng_detail, umod.ERR_ROWS, sel):
                                        text umod.esc(drow[1]):
                                            size umod.ksize(drow[0])
                                            color umod.kcolor(drow[0])
                                            xoffset umod.kindent(drow[0])
                                            xsize umod.S(420)
                    else:
                        text "Selecciona un label del arbol. Los marcados en naranja no son alcanzables estaticamente desde el origen.":
                            size umod.S(13)
                            color "#66707f"

                # ---- Camino desde el origen ----
                frame:
                    background Solid("#121722")
                    xsize umod.S(530)
                    ysize umod.S(722)
                    padding (umod.S(10), umod.S(8))
                    if sel:
                        viewport:
                            xsize umod.S(510)
                            ysize umod.S(706)
                            scrollbars "vertical"
                            mousewheel True
                            draggable True
                            vbox:
                                spacing umod.S(3)
                                for prow in umod.guard(umod.ng_view, umod.ERR_ROWS, umod.RT.g_origin, sel, mode):
                                    if prow[0] == "h":
                                        null height umod.S(6)
                                    text umod.esc(prow[1]):
                                        size umod.ksize(prow[0])
                                        color umod.kcolor(prow[0])
                                        xoffset umod.kindent(prow[0])
                                        xsize umod.S(480)
                    else:
                        text "Aqui aparecera el camino desde el origen hasta el label seleccionado, con sus condiciones, decisiones y requisitos.":
                            size umod.S(13)
                            color "#66707f"


# ##################################################################### #
#   universal_mod_tracker.rpy
# ##################################################################### #

# =====================================================================
#  UNIVERSAL REN'PY MOD (UMOD)  -  FASE 5 / State Tracker
# ---------------------------------------------------------------------
#  Requiere universal_mod.rpy (Fase 1). Se integra con la Fase 3
#  (variables narrativas) y la Fase 4 (grafo) si estan presentes.
#
#  Que hace esta fase:
#    - Observa la partida REAL mientras se juega:
#        * cada entrada en un label (config.label_callback(s))
#        * cada eleccion de menu (envoltorio de renpy.exports.menu)
#    - En cada label toma un snapshot resumido del store y de
#      persistent, y calcula el DIFF respecto al anterior. Ese diff se
#      atribuye al label que estaba ejecutandose: "pasar por A pone
#      met_alice = True y suma alice_points +5".
#    - Diffs estructurados: numeros (con delta), cadenas, listas y
#      sets (elementos anadidos/quitados), diccionarios (por clave) y
#      objetos Python (por atributo: player.affection 3 -> 5).
#    - Reconstruye la pila de llamadas con renpy.get_return_stack(),
#      asi el predecesor de un label es el correcto aunque haya habido
#      call/return en medio.
#    - Aprende TRANSICIONES OBSERVADAS: incluidas las que salen de
#      screens (mapas, telefonos, free-roam) y de saltos calculados,
#      que el grafo estatico no puede ver. Se pueden integrar en el
#      grafo de la Fase 4.
#    - Guarda el ESTADO DE ENTRADA de cada label visitado: el estado
#      real, conocido como bueno, con el que el juego llego ahi. Es la
#      materia prima de la reconstruccion de la Fase 6.
#    - Snapshot manual A / B para comparar dos momentos cualesquiera.
#    - Todo se guarda en la carpeta de saves (umod_track.json). Nada
#      entra en los savegames.
#
#  ABRIR:  ALT + T
#
#  LIMITES CONOCIDOS
#    - Tras un call/return, los cambios hechos por el llamador despues
#      del return se atribuyen al label llamado (el evento se marca
#      como "mixto"). Ren'Py no avisa al volver de un call.
#    - Rollback y carga de partida no se atribuyen a nadie: el tracker
#      se resincroniza en silencio.
#    - Los contextos anidados (call_in_new_context: minijuegos,
#      telefonos) no se registran; sus efectos aparecen en el siguiente
#      label del contexto principal.
# =====================================================================


# ---------------------------------------------------------------------
# 0) Estado de runtime del tracker (fuera del store)
# ---------------------------------------------------------------------
init -1060 python:
    import sys as _umod_sys_t
    try:
        _umod_t = _umod_sys_t.modules["umod_rt"]
        _umod_t.tr_labels = {}        # conocimiento aprendido por label
        _umod_t.tr_entry = {}         # label -> estado real de entrada
        _umod_t.tr_entry_order = []   # LRU de estados de entrada
        _umod_t.tr_timeline = []      # ultimos eventos
        _umod_t.tr_seq = 0
        _umod_t.tr_prev = None        # snapshot anterior (resumido)
        _umod_t.tr_cur = None         # label que posee el segmento actual
        _umod_t.tr_frames = []        # label activo en cada nivel de call
        _umod_t.tr_seg_choices = []   # elecciones del segmento actual
        _umod_t.tr_manual = None
        _umod_t.tr_manual_t = ""
        _umod_t.tr_manual_diff = None
        _umod_t.tr_ms = 0.0
        _umod_t.tr_ms_max = 0.0
        _umod_t.tr_dirty = 0
        _umod_t.tr_last_save = 0.0
        _umod_t.tr_loaded = False
        _umod_t.tr_stale = False
        _umod_t.tr_msg = "Esperando el primer label"
        _umod_t.tr_menu_hooked = False
        _umod_t.tr_label_mode = "no instalado"
        _umod_t.tr_paused = False     # la Fase 7 lo usara durante la emulacion
        _umod_t.tr_merged = 0
        _umod_t.tr_nv = None
        _umod_t.tr_nv_key = None
        _umod_t.tr_last_file = None
        _umod_t.tr_snap_mode = "completo"
        del _umod_t
    except Exception:
        pass


# ---------------------------------------------------------------------
# 1) Preferencias persistentes del tracker
# ---------------------------------------------------------------------
init -959 python:
    if persistent.umod_track_on is None:
        persistent.umod_track_on = True
    if persistent.umod_track_menu is None:
        persistent.umod_track_menu = True


# ---------------------------------------------------------------------
# 2) Motor del tracker
# ---------------------------------------------------------------------
init -960 python in umod:

    TRACKER = True

    TR_KEYS           = ["alt_K_t"]
    TR_TIMELINE_CAP   = 1500
    TR_TIMELINE_SAVE  = 400
    TR_ENTRY_CAP      = 600       # labels con estado de entrada guardado
    TR_STATE_VARS_CAP = 800       # variables por estado de entrada
    TR_STORE_CAP      = 5000      # variables del store por snapshot
    TR_CONTAINER_CAP  = 150       # contenedores mas grandes: solo tamano
    TR_ATTR_CAP       = 60
    TR_VALS_CAP       = 6
    TR_WRITES_CAP     = 300
    TR_SAVE_EVERY     = 60.0
    TR_SAVE_EVENTS    = 40
    TR_LIVE_EVENTS    = 120
    TR_SLOW_MS        = 40.0      # por encima: snapshot solo de variables narrativas

    # Labels previos a una partida: el paso de ellos a "start" no es un
    # cambio narrativo, es la inicializacion de una partida nueva.
    TR_PRESTART = set(["splashscreen", "before_main_menu", "main_menu",
                       "after_load", "quit"])

    _INT_TYPES = (int, long) if PY2 else (int,)       # noqa (long solo en Py2)
    _PRIM_TYPES = (bool, float) + _INT_TYPES

    class _Miss(object):
        def __repr__(self):
            return "(no existia)"
    _MISS = _Miss()

    # ---------- 2.1 Preferencias ------------------------------------
    def _tr_pref(name, default):
        try:
            v = getattr(renpy.store.persistent, name, None)
        except Exception:
            v = None
        return default if v is None else bool(v)

    def tr_enabled():
        return _tr_pref("umod_track_on", True)

    def tr_menu_enabled():
        return _tr_pref("umod_track_menu", True)

    def tr_toggle_on():
        try:
            renpy.store.persistent.umod_track_on = not tr_enabled()
            RT.tr_prev = None            # al reactivar, resincroniza
        except Exception as e:
            log_error("tr_toggle_on", e)

    def tr_toggle_menu():
        try:
            renpy.store.persistent.umod_track_menu = not tr_menu_enabled()
        except Exception as e:
            log_error("tr_toggle_menu", e)

    # ---------- 2.2 Resumen de valores ------------------------------
    def _is_prim(v):
        return v is None or isinstance(v, _PRIM_TYPES + string_types)

    def _isnum(x):
        return isinstance(x, (float,) + _INT_TYPES) and not isinstance(x, bool)

    def _prim(v):
        if v is None or isinstance(v, _PRIM_TYPES):
            return v
        if isinstance(v, string_types):
            return v[:120]
        try:
            return "<%s>" % type(v).__name__
        except Exception:
            return "<?>"

    def _summ(v):
        """Resumen comparable y barato. Los contenedores grandes solo
        conservan su tamano; los objetos, sus atributos primitivos."""
        try:
            if v is None or isinstance(v, _PRIM_TYPES):
                return ("p", v)
            if isinstance(v, string_types):
                return ("p", v[:300])
            if isinstance(v, dict):
                if len(v) > TR_CONTAINER_CAP:
                    return ("L", "dict", len(v))
                items = [(to_text(k)[:60], _prim(v[k])) for k in v]
                items.sort(key=lambda t: t[0])
                return ("d", tuple(items))
            if isinstance(v, (set, frozenset)):
                if len(v) > TR_CONTAINER_CAP:
                    return ("L", "set", len(v))
                return ("s", tuple(sorted(to_text(_prim(x)) for x in v)))
            if isinstance(v, (list, tuple)):
                if len(v) > TR_CONTAINER_CAP:
                    return ("L", type(v).__name__, len(v))
                return ("l", tuple(_prim(x) for x in v))
            d = getattr(v, "__dict__", None)
            if isinstance(d, dict):
                items = []
                for k in d:
                    if not isinstance(k, string_types) or k.startswith("_"):
                        continue
                    x = d[k]
                    if _is_prim(x):
                        items.append((k, _prim(x)))
                    elif isinstance(x, (list, tuple, set, frozenset, dict)):
                        items.append((k, "<%s len=%d>" % (type(x).__name__, len(x))))
                    if len(items) >= TR_ATTR_CAP:
                        break
                items.sort(key=lambda t: t[0])
                return ("O", type(v).__name__, tuple(items))
            return ("x", type(v).__name__)
        except Exception:
            return ("x", "?")

    def _vt(x):
        if x is _MISS:
            return "(no existia)"
        if isinstance(x, string_types):
            s = x if len(x) <= 60 else x[:57] + "..."
            return "'%s'" % s
        return to_text(x)

    def _summ_text(s):
        k = s[0]
        if k == "p":
            return _vt(s[1])
        if k == "l":
            return "lista(%d)" % len(s[1])
        if k == "s":
            return "set(%d)" % len(s[1])
        if k == "d":
            return "dict(%d)" % len(s[1])
        if k == "L":
            return "%s(%d)" % (s[1], s[2])
        if k == "O":
            return "<%s>" % s[1]
        return "<%s>" % s[1]

    def _tr_num(d):
        try:
            if float(d) == int(d):
                return "%d" % d
        except Exception:
            pass
        return "%.2f" % d

    # ---------- 2.3 Snapshot ----------------------------------------
    def _tr_state_ok(k, v):
        if not isinstance(k, string_types) or k.startswith("_") or k in NEVER_VARS:
            return False
        if not _is_state_value(v):
            return False
        try:
            if type(v).__name__ in ("StoreModule", "StoreDict"):
                return False
        except Exception:
            pass
        return True

    def tr_snapshot():
        """Modo "completo": todo el store. Si la media supera TR_SLOW_MS y la
        Fase 3 sabe que variables usa el guion, pasa a modo "narrativo":
        solo esas (mas persistent). En stores enormes es mucho mas barato y
        no pierde nada que el guion compare o modifique."""
        t0 = time.time()
        snap = {}
        nv = None
        # Una vez en modo narrativo se queda (si no, oscilaria: el modo
        # barato baja la media y devolveria al modo caro).
        if RT.tr_snap_mode == "narrativo" or RT.tr_ms > TR_SLOW_MS:
            nv = _narrative_vars()
        RT.tr_snap_mode = "narrativo" if nv is not None else "completo"
        try:
            d = vars(renpy.store)
            n = 0
            for k in (sorted(nv) if nv is not None else list(d.keys())):
                if k not in d:
                    continue
                try:
                    v = d[k]
                except Exception:
                    continue
                if not _tr_state_ok(k, v):
                    continue
                snap[k] = _summ(v)
                n += 1
                if n >= TR_STORE_CAP:
                    break
        except Exception as e:
            log_error("tr_snapshot.store", e)
        try:
            p = vars(renpy.store.persistent)
            for k in list(p.keys()):
                if not isinstance(k, string_types) or k.startswith("_") or k.startswith("umod_"):
                    continue
                v = p[k]
                if not _is_state_value(v):
                    continue
                snap["persistent." + k] = _summ(v)
        except Exception:
            pass
        ms = (time.time() - t0) * 1000.0
        RT.tr_ms = ms if not RT.tr_ms else (0.8 * RT.tr_ms + 0.2 * ms)
        RT.tr_ms_max = max(RT.tr_ms_max, ms)
        return snap

    # ---------- 2.4 Diff --------------------------------------------
    # Cada cambio: (ruta, antes, despues, delta o None)
    def _diff_one(k, na, nb, out):
        if na[0] != nb[0]:
            out.append((k, _summ_text(na), _summ_text(nb), None))
            return
        kind = na[0]

        if kind == "p":
            d = None
            if _isnum(na[1]) and _isnum(nb[1]):
                d = nb[1] - na[1]
            out.append((k, _vt(na[1]), _vt(nb[1]), d))
            return

        if kind in ("l", "s"):
            # Diff de multiconjunto: detecta tambien repetidos anadidos o quitados.
            old, new = list(na[1]), list(nb[1])
            co, cn = {}, {}
            for x in old:
                co[x] = co.get(x, 0) + 1
            for x in new:
                cn[x] = cn.get(x, 0) + 1
            added, removed = [], []
            for x in new:
                if cn.get(x, 0) > co.get(x, 0) and x not in added:
                    added.extend([x] * (cn[x] - co.get(x, 0)))
            for x in old:
                if co.get(x, 0) > cn.get(x, 0) and x not in removed:
                    removed.extend([x] * (co[x] - cn.get(x, 0)))
            for x in added[:5]:
                out.append((k, "", "+ " + _vt(x), None))
            for x in removed[:5]:
                out.append((k, "- " + _vt(x), "", None))
            extra = len(added) + len(removed) - min(5, len(added)) - min(5, len(removed))
            if extra > 0:
                out.append((k, "", "... %d cambios mas" % extra, None))
            if not added and not removed:
                out.append((k, "", "reordenada (mismos elementos)", None))
            return

        if kind == "d":
            da, db = dict(na[1]), dict(nb[1])
            for key in sorted(set(da) | set(db)):
                va, vb = da.get(key, _MISS), db.get(key, _MISS)
                if va == vb:
                    continue
                d = (vb - va) if (_isnum(va) and _isnum(vb)) else None
                out.append(("%s['%s']" % (k, key), _vt(va), _vt(vb), d))
            return

        if kind == "O":
            if na[1] != nb[1]:
                out.append((k, "<%s>" % na[1], "<%s>" % nb[1], None))
                return
            da, db = dict(na[2]), dict(nb[2])
            for key in sorted(set(da) | set(db)):
                va, vb = da.get(key, _MISS), db.get(key, _MISS)
                if va == vb:
                    continue
                d = (vb - va) if (_isnum(va) and _isnum(vb)) else None
                out.append(("%s.%s" % (k, key), _vt(va), _vt(vb), d))
            return

        out.append((k, _summ_text(na), _summ_text(nb), None))

    def tr_diff(a, b):
        out = []
        if a is None or b is None:
            return out
        for k in sorted(b.keys()):
            nb = b[k]
            na = a.get(k)
            if na == nb:
                continue
            if na is None:
                out.append((k, "(no existia)", _summ_text(nb), None))
                continue
            _diff_one(k, na, nb, out)
        for k in sorted(a.keys()):
            if k not in b:
                out.append((k, _summ_text(a[k]), "(eliminada)", None))
        return out

    def change_text(c):
        p, o, n, d = c
        if o == "":
            return "%s  %s" % (p, n)
        if n == "":
            return "%s  %s" % (p, o)
        s = "%s: %s -> %s" % (p, o, n)
        if d:
            s += "   (%s%s)" % ("+" if d > 0 else "", _tr_num(d))
        return s

    # ---------- 2.5 Valores JSON-seguros para estados de entrada ----
    def jsafe(v, depth=0):
        if v is None or isinstance(v, _PRIM_TYPES):
            return v
        if isinstance(v, string_types):
            return v[:400]
        tn = "?"
        try:
            tn = type(v).__name__
        except Exception:
            pass
        if depth > 2:
            return {"~": tn}
        try:
            if isinstance(v, list):
                if len(v) > 200:
                    return {"~": tn, "len": len(v)}
                return [jsafe(x, depth + 1) for x in v]
            if isinstance(v, tuple):
                if len(v) > 200:
                    return {"~": tn, "len": len(v)}
                return {"~tuple": [jsafe(x, depth + 1) for x in v]}
            if isinstance(v, (set, frozenset)):
                if len(v) > 200:
                    return {"~": tn, "len": len(v)}
                vals = [jsafe(x, depth + 1) for x in v]
                vals.sort(key=lambda x: to_text(x))
                return {"~set": vals}
            if isinstance(v, dict):
                if len(v) > 200:
                    return {"~": tn, "len": len(v)}
                return {"~dict": [[to_text(k)[:80], jsafe(v[k], depth + 1)] for k in v]}
            d = getattr(v, "__dict__", None)
            if isinstance(d, dict):
                a = {}
                for k in d:
                    if not isinstance(k, string_types) or k.startswith("_"):
                        continue
                    if _is_prim(d[k]):
                        a[k] = jsafe(d[k], depth + 1)
                    if len(a) >= TR_ATTR_CAP:
                        break
                return {"~": tn, "a": a}
        except Exception:
            pass
        return {"~": tn}

    # ---------- 2.6 Variables narrativas ----------------------------
    def _narrative_vars():
        """Si la Fase 3 esta disponible, solo guardamos en los estados de
        entrada las variables que el guion lee o escribe. Si no, todas
        las variables de estado primitivas."""
        try:
            if not (SCRIPT and RT.sa_ready):
                return None
        except Exception:
            return None
        key = (len(RT.sa_vars), len(RT.sa_conds), len(RT.sa_defaults))
        if RT.tr_nv is not None and RT.tr_nv_key == key:
            return RT.tr_nv
        nv = set()
        for name in list(RT.sa_vars.keys()) + list(RT.sa_defaults.keys()):
            nv.add(name.split(".")[0])
        for c in RT.sa_conds:
            v = c.get("v", "")
            if v:
                nv.add(v.split(".")[0])
        nv.discard("persistent")
        nv.discard("renpy")
        RT.tr_nv = nv
        RT.tr_nv_key = key
        return nv

    def _tr_store_entry(name, snap):
        try:
            store = vars(renpy.store)
            nv = _narrative_vars()
            if nv is None:
                keys = [k for k in snap if snap[k][0] == "p" and not k.startswith("persistent.")]
            else:
                keys = [k for k in nv if k in store]
            keys.sort()
            st = {}
            for k in keys:
                if k in store and _tr_state_ok(k, store[k]):
                    st[k] = jsafe(store[k])
                    if len(st) >= TR_STATE_VARS_CAP:
                        break
            ps = {}
            for k in snap:
                if k.startswith("persistent.") and snap[k][0] == "p":
                    ps[k] = snap[k][1]
            # Tras una reconstruccion (Fase 6) el estado es sintetico: se
            # guarda marcado y nunca sustituye a uno real ya conocido.
            syn = bool(getattr(RT, "tr_synthetic", False))
            old = RT.tr_entry.get(name)
            if syn and old and not old.get("syn"):
                return
            RT.tr_entry[name] = {"t": time.strftime("%Y-%m-%d %H:%M:%S"),
                                 "seq": RT.tr_seq, "s": st, "ps": ps,
                                 "nv": nv is not None, "syn": syn}
            try:
                RT.tr_entry_order.remove(name)
            except ValueError:
                pass
            RT.tr_entry_order.append(name)
            while len(RT.tr_entry_order) > TR_ENTRY_CAP:
                old = RT.tr_entry_order.pop(0)
                RT.tr_entry.pop(old, None)
        except Exception as e:
            log_error("tr_store_entry", e)

    # ---------- 2.7 Conocimiento por label --------------------------
    def _tr_lab(name):
        lab = RT.tr_labels.get(name)
        if lab is None:
            lab = {"v": 0, "in": {}, "out": {}, "oc": {}, "ik": {},
                   "w": {}, "ch": {}}
            RT.tr_labels[name] = lab
        return lab

    def _learn_writes(owner, changes):
        for p, o, n, d in changes:
            w = owner["w"].get(p)
            if w is None:
                if len(owner["w"]) >= TR_WRITES_CAP:
                    continue
                w = {"n": 0, "vals": [], "d": []}
                owner["w"][p] = w
            w["n"] += 1
            if n and n not in w["vals"] and len(w["vals"]) < TR_VALS_CAP:
                w["vals"].append(n)
            if d is not None and len(w["d"]) < TR_VALS_CAP:
                w["d"].append(d)

    # ---------- 2.8 Eventos -----------------------------------------
    def _tr_depth():
        try:
            return len(renpy.get_return_stack())
        except Exception:
            return 0

    def _tr_in_rollback():
        try:
            return bool(renpy.in_rollback())
        except Exception:
            return False

    def tr_on_label(name, abnormal=False):
        """Punto de entrada desde config.label_callback(s). Nunca lanza."""
        try:
            if not tr_enabled() or RT.tr_paused:
                return
            if not isinstance(name, string_types) or name.startswith("_"):
                return
            try:
                if renpy.context_nesting_level() > 0:
                    return
            except Exception:
                pass
            try:
                if getattr(renpy.store, "_in_replay", None):
                    return
            except Exception:
                pass
            _tr_event(to_text(name), bool(abnormal))
        except Exception as e:
            log_error("tr_on_label", e)

    def _tr_event(name, abnormal):
        if not RT.tr_loaded:
            tr_load()

        snap = tr_snapshot()
        rolled = _tr_in_rollback()
        depth = _tr_depth()
        frames = RT.tr_frames
        prev_cur = RT.tr_cur
        returned = depth < len(frames) - 1

        # Predecesor real segun la pila de llamadas
        if depth >= len(frames):
            pred = frames[depth - 1] if 1 <= depth <= len(frames) else prev_cur
            kind = "call" if frames else "inicio"
        else:
            pred = frames[depth]
            kind = "salto" if abnormal else "caida"

        nf = list(frames[:depth])
        while len(nf) < depth:
            nf.append(None)
        nf.append(name)
        RT.tr_frames = nf

        # Si el snapshot cambio de modo (completo -> narrativo), los dos no
        # son comparables: las variables omitidas parecerian "eliminadas".
        mode_changed = getattr(RT, "tr_prev_mode", None) not in (None, RT.tr_snap_mode)
        RT.tr_prev_mode = RT.tr_snap_mode
        resync = (RT.tr_prev is None or rolled or name == "start" or
                  prev_cur is None or prev_cur in TR_PRESTART or mode_changed)
        if name == "start":
            RT.tr_synthetic = False          # partida nueva: estado real otra vez

        changes = [] if resync else tr_diff(RT.tr_prev, snap)
        choices = list(RT.tr_seg_choices)
        RT.tr_seg_choices = []
        RT.tr_prev = snap
        RT.tr_cur = name
        RT.tr_seq += 1

        lab = _tr_lab(name)
        lab["v"] += 1

        if not resync:
            owner = _tr_lab(prev_cur)
            _learn_writes(owner, changes)
            for cap in choices:
                owner["ch"][cap] = owner["ch"].get(cap, 0) + 1
            if pred:
                pl = _tr_lab(pred)
                pl["out"][name] = pl["out"].get(name, 0) + 1
                if choices:
                    oc = pl["oc"].setdefault(name, {})
                    for cap in choices:
                        oc[cap] = oc.get(cap, 0) + 1
                lab["in"][pred] = lab["in"].get(pred, 0) + 1
                lab["ik"][pred] = kind

        # Un estado capturado durante un rollback no es un estado de entrada
        # fiable: no sobrescribimos el ultimo bueno conocido.
        if not rolled:
            _tr_store_entry(name, snap)

        if resync:
            ek = "rollback" if rolled else "resincronizado"
        else:
            ek = kind
        RT.tr_timeline.append({
            "i": RT.tr_seq, "l": name, "p": pred or "", "o": prev_cur or "",
            "k": ek, "m": bool(returned and not resync),
            "ch": choices[:6], "n": len(changes),
            "d": [change_text(c) for c in changes[:30]],
            "t": time.strftime("%H:%M:%S"),
        })
        if len(RT.tr_timeline) > TR_TIMELINE_CAP:
            del RT.tr_timeline[:len(RT.tr_timeline) - TR_TIMELINE_CAP]

        RT.tr_dirty += 1
        RT.tr_msg = "Grabando  -  %d eventos, %d labels, snapshot %.1f ms" % (
            RT.tr_seq, len(RT.tr_labels), RT.tr_ms)
        _tr_maybe_save()

    def tr_on_menu(items, rv):
        try:
            if not tr_enabled() or RT.tr_paused or rv is None:
                return
            if _tr_in_rollback():
                return
            cap = None
            for it in (items or []):
                try:
                    if it[-1] == rv:
                        cap = to_text(it[0])
                        break
                except Exception:
                    continue
            if cap is None:
                return
            RT.tr_seg_choices.append(cap[:90])
            if len(RT.tr_seg_choices) > 20:
                del RT.tr_seg_choices[:-20]
        except Exception as e:
            log_error("tr_on_menu", e)

    def tr_after_load():
        """Una carga no es un cambio narrativo: resincronizamos."""
        RT.tr_prev = None
        RT.tr_cur = None
        RT.tr_frames = []
        RT.tr_seg_choices = []
        RT.tr_synthetic = False

    # ---------- 2.9 Instalacion de los ganchos ----------------------
    # Puntos de enganche para otras fases (la Fase 7 los usa). Asi solo
    # existe UN envoltorio de menus y UN callback de labels en el motor.
    #   LABEL_HOOKS:   f(name, abnormal), tras registrar el evento
    #   MENU_DECIDERS: f(items, args, kwargs) -> valor elegido o NO_DECISION
    LABEL_HOOKS = []
    MENU_DECIDERS = []

    class _NoDecision(object):
        def __repr__(self):
            return "NO_DECISION"
    NO_DECISION = _NoDecision()

    def tr_label_cb(name, abnormal=False):
        tr_on_label(name, abnormal)
        for h in list(LABEL_HOOKS):
            try:
                h(name, abnormal)
            except Exception as e:
                log_error("label_hook", e)
    tr_label_cb._umod = True

    def tr_install_label():
        try:
            cfg = renpy.config
            cbs = getattr(cfg, "label_callbacks", None)
            if isinstance(cbs, list):
                if not any(getattr(f, "_umod", False) for f in cbs):
                    cbs.append(tr_label_cb)
                RT.tr_label_mode = "config.label_callbacks"
                return
            prev = getattr(cfg, "label_callback", None)
            if getattr(prev, "_umod", False):
                return

            def _chained(name, abnormal=False, _prev=prev):
                if _prev is not None:
                    _prev(name, abnormal)
                tr_label_cb(name, abnormal)
            _chained._umod = True
            cfg.label_callback = _chained
            RT.tr_label_mode = ("config.label_callback (encadenado al del juego)"
                                if prev is not None else "config.label_callback")
        except Exception as e:
            log_error("tr_install_label", e)
            RT.tr_label_mode = "fallo: %s" % e

    def tr_ensure():
        """Si el juego reasigna config.label_callback despues del init,
        volvemos a encadenarnos. Coste: un getattr por interaccion."""
        try:
            if RT.tr_label_mode.startswith("config.label_callback"):
                if not getattr(renpy.config.label_callback, "_umod", False):
                    tr_install_label()
        except Exception:
            pass

    def tr_install_menu():
        if RT.tr_menu_hooked or not tr_menu_enabled():
            return
        try:
            ex = renpy.exports
            orig = ex.menu
            if getattr(orig, "_umod", False):
                RT.tr_menu_hooked = True
                return

            def _menu(items, *args, **kwargs):
                for dec in list(MENU_DECIDERS):
                    try:
                        rv = dec(items, args, kwargs)
                    except Exception as e:
                        log_error("menu_decider", e)
                        rv = NO_DECISION
                    if rv is not NO_DECISION:
                        try:
                            tr_on_menu(items, rv)
                        except Exception:
                            pass
                        return rv
                rv = orig(items, *args, **kwargs)
                try:
                    tr_on_menu(items, rv)
                except Exception:
                    pass
                return rv
            _menu._umod = True
            _menu._umod_orig = orig
            ex.menu = _menu
            if getattr(renpy, "menu", None) is orig:
                renpy.menu = _menu
            RT.tr_menu_hooked = True
        except Exception as e:
            log_error("tr_install_menu", e)

    # ---------- 2.10 Persistencia -----------------------------------
    def tr_save(force=False):
        if not force and not RT.tr_dirty:
            return RT.tr_last_file
        RT.tr_last_file = _write_json(_savedir_path("umod_track.json"), {
            "format":   1,
            "game_id":  game_id(),
            "fp":       script_fp(),
            "seq":      RT.tr_seq,
            "labels":   RT.tr_labels,
            "entry":    RT.tr_entry,
            "order":    RT.tr_entry_order,
            "timeline": RT.tr_timeline[-TR_TIMELINE_SAVE:],
        })
        RT.tr_dirty = 0
        RT.tr_last_save = time.time()
        return RT.tr_last_file

    def tr_save_quit(*args):
        try:
            tr_save(True)
        except Exception:
            pass

    def _tr_maybe_save():
        if not RT.tr_dirty:
            return
        if RT.tr_dirty >= TR_SAVE_EVENTS or time.time() - RT.tr_last_save > TR_SAVE_EVERY:
            tr_save(True)

    def tr_load():
        if RT.tr_loaded:
            return False
        RT.tr_loaded = True
        RT.tr_last_save = time.time()
        p = _savedir_path("umod_track.json")
        if not p or not os.path.exists(p):
            return False
        try:
            f = open(p, "r")
            try:
                data = json.load(f)
            finally:
                f.close()
        except Exception as e:
            log_error("tr_load", e)
            return False
        if data.get("game_id") != game_id():
            return False
        RT.tr_labels = data.get("labels", {}) or {}
        RT.tr_entry = data.get("entry", {}) or {}
        RT.tr_entry_order = data.get("order", []) or []
        RT.tr_timeline = data.get("timeline", []) or []
        RT.tr_seq = int(data.get("seq", 0) or 0)
        # Un guion distinto no invalida lo aprendido, pero hay que avisar.
        RT.tr_stale = (data.get("fp") != script_fp())
        RT.tr_msg = "Grabacion cargada: %d labels, %d eventos%s" % (
            len(RT.tr_labels), RT.tr_seq,
            "  (de otra version del guion)" if RT.tr_stale else "")
        return True

    def tr_clear():
        RT.tr_labels = {}
        RT.tr_entry = {}
        RT.tr_entry_order = []
        RT.tr_timeline = []
        RT.tr_seq = 0
        RT.tr_prev = None
        RT.tr_cur = None
        RT.tr_frames = []
        RT.tr_seg_choices = []
        RT.tr_stale = False
        RT.tr_dirty = 1
        tr_save(True)
        RT.tr_msg = "Grabacion borrada"
        try:
            if GRAPH and RT.g_ready:
                tr_merge_into_graph()
        except Exception:
            pass

    # ---------- 2.11 Snapshot manual A / B --------------------------
    def tr_snap_take():
        RT.tr_manual = tr_snapshot()
        RT.tr_manual_mode = RT.tr_snap_mode
        RT.tr_manual_t = time.strftime("%H:%M:%S")
        RT.tr_manual_diff = None

    def tr_snap_compare():
        if RT.tr_manual is None:
            RT.tr_manual_diff = ["Primero toma el snapshot A."]
            return
        now = tr_snapshot()
        a = RT.tr_manual
        if set(a.keys()) != set(now.keys()) and getattr(RT, "tr_manual_mode", None) != RT.tr_snap_mode:
            common = set(a.keys()) & set(now.keys())      # cambio de modo: solo lo comparable
            a = dict((k, a[k]) for k in common)
            now = dict((k, now[k]) for k in common)
        ch = tr_diff(a, now)
        RT.tr_manual_diff = [change_text(c) for c in ch] or ["Sin cambios desde el snapshot A."]

    def tr_snap_clear():
        RT.tr_manual = None
        RT.tr_manual_t = ""
        RT.tr_manual_diff = None

    def tr_snap_info():
        if RT.tr_manual is None:
            return "Sin snapshot A. Tomalo, avanza en el juego (o carga otra partida) y compara."
        return "Snapshot A tomado a las %s  (%d variables)" % (RT.tr_manual_t, len(RT.tr_manual))

    # ---------- 2.12 Integracion con el grafo (Fase 4) --------------
    def tr_merge_into_graph():
        """Anade como aristas 'observado' las transiciones reales que el
        grafo estatico no conoce. Idempotente: quita las anteriores."""
        try:
            if not (GRAPH and RT.g_ready):
                return 0
        except Exception:
            return 0
        if not RT.tr_loaded:
            tr_load()
        static = set((e["a"], e["b"]) for e in RT.g_edges
                     if not e.get("obs") and e.get("b") is not None)
        new = []
        added = 0
        for a in sorted(RT.tr_labels.keys()):
            outs = RT.tr_labels[a].get("out", {})
            for b in sorted(outs.keys()):
                if a not in RT.g_nodes or b not in RT.g_nodes or (a, b) in static:
                    continue
                oc = RT.tr_labels[a].get("oc", {}).get(b, {})
                d = []
                if oc:
                    best = max(oc.keys(), key=lambda c: oc[c])
                    d = [{"cap": best, "line": "?", "i": -1}]
                new.append({"a": a, "b": b, "t": "obs", "g": [], "d": d,
                            "dyn": False, "obs": True, "n": outs[b]})
                added += 1
        ng_replace_extra("obs", new)
        if added:
            RT.g_msg += "  (+%d observadas)" % added
        RT.tr_merged = added
        return added

    try:
        _el = globals().get("EDGE_LABEL")
        if isinstance(_el, dict):
            _el["obs"] = "observado"
    except Exception:
        pass

    def tr_static_pairs():
        try:
            if GRAPH and RT.g_ready:
                return set((e["a"], e["b"]) for e in RT.g_edges
                           if not e.get("obs") and e.get("b") is not None)
        except Exception:
            pass
        return None

    # ---------- 2.13 API para la Fase 6 -----------------------------
    def tr_entry_state(label, allow_syn=False):
        """Estado real con el que el juego entro en 'label' la ultima vez.
        Los estados sinteticos (tras una reconstruccion) se excluyen salvo
        que se pidan expresamente."""
        e = RT.tr_entry.get(label)
        if not e or (e.get("syn") and not allow_syn):
            return None
        return e.get("s")

    def tr_label_effects(label):
        """Escrituras observadas al pasar por 'label'."""
        lab = RT.tr_labels.get(label)
        return lab.get("w", {}) if lab else {}

    # ---------- 2.14 Vistas para la UI ------------------------------
    TR_TABS = [
        ("vivo",  "En vivo"),
        ("snap",  "Snapshot A/B"),
        ("lab",   "Labels aprendidos"),
        ("trans", "Transiciones"),
        ("tools", "Herramientas"),
    ]

    TR_COLOR = {
        "h":    "#8fe0ff",
        "ev":   "#dfe7f2",
        "chg":  "#9fe0b0",
        "ch":   "#b9a6ff",
        "warn": "#ff9b8a",
        "note": "#7f8ca1",
        "ok":   "#7ee0a5",
        "new":  "#ffcf7a",
        "lab":  "#dfe7f2",
    }

    def tr_color(k):
        return TR_COLOR.get(k, "#dfe7f2")

    def tr_size(k):
        return S(15) if k == "h" else S(13)

    def tr_indent(k):
        return S(22) if k in ("chg", "ch") else 0

    def tr_status_rows():
        rows = [
            ("h", "Estado"),
            ("ok" if tr_enabled() else "warn",
             "Grabacion: %s" % ("ACTIVA" if tr_enabled() else "DESACTIVADA")),
            ("note", "Gancho de labels: %s" % RT.tr_label_mode),
            ("note", "Gancho de menus: %s" % (
                "instalado" if RT.tr_menu_hooked else
                ("desactivado" if not tr_menu_enabled() else "no instalado"))),
            ("note", "Label actual: %s   -   profundidad de call: %d" % (
                RT.tr_cur or "(desconocido)", max(0, len(RT.tr_frames) - 1))),
            ("note", "Eventos: %d   -   labels aprendidos: %d   -   estados de entrada: %d" % (
                RT.tr_seq, len(RT.tr_labels), len(RT.tr_entry))),
            ("note" if RT.tr_ms_max < 80 else "warn",
             "Coste del snapshot: media %.1f ms, maximo %.1f ms" % (RT.tr_ms, RT.tr_ms_max)),
        ]
        if RT.tr_stale:
            rows.append(("warn", "La grabacion procede de otra version del guion: lo aprendido puede no coincidir."))
        return rows

    def tr_live_rows():
        rows = tr_status_rows()
        rows.append(("h", "Ultimos eventos (el mas reciente arriba)"))
        if not RT.tr_timeline:
            rows.append(("note", "Todavia no hay eventos: juega un poco y vuelve."))
        for ev in reversed(RT.tr_timeline[-TR_LIVE_EVENTS:]):
            head = "#%s  %s   %s -> %s   [%s]" % (
                ev.get("i", "?"), ev.get("t", ""), ev.get("p") or "?",
                ev.get("l", "?"), ev.get("k", "?"))
            if ev.get("m"):
                head += "  (mixto: hubo return)"
            if ev.get("n"):
                head += "   %d cambio(s) en '%s'" % (ev["n"], ev.get("o") or "?")
            rows.append(("ev", head))
            for cap in ev.get("ch", []):
                rows.append(("ch", "eligio: \"%s\"" % cap))
            for line in ev.get("d", [])[:10]:
                rows.append(("chg", line))
            if ev.get("n", 0) > 10:
                rows.append(("note", "      ... %d cambios mas" % (ev["n"] - 10)))
        return rows

    def tr_lab_text(name):
        lab = RT.tr_labels.get(name) or {}
        return "%s   (visitas %d, cambios %d%s)" % (
            name, lab.get("v", 0), len(lab.get("w", {})),
            ", estado" if name in RT.tr_entry else "")

    def tr_lab_detail(name):
        lab = RT.tr_labels.get(name)
        if not lab:
            return [("warn", "Sin datos para este label.")]
        static = tr_static_pairs()
        out = [("h", name), ("note", "Visitas observadas: %d" % lab.get("v", 0))]

        out.append(("h", "Llega desde"))
        if not lab.get("in"):
            out.append(("note", "(sin entradas observadas)"))
        for p in sorted(lab.get("in", {}).keys(), key=lambda x: -lab["in"][x]):
            mark = ""
            if static is not None and (p, name) not in static:
                mark = "   NUEVA"
            out.append(("new" if mark else "ev", "<- %s  x%d  [%s]%s" % (
                p, lab["in"][p], lab.get("ik", {}).get(p, "?"), mark)))

        out.append(("h", "Continua en"))
        if not lab.get("out"):
            out.append(("note", "(sin salidas observadas)"))
        for b in sorted(lab.get("out", {}).keys(), key=lambda x: -lab["out"][x]):
            mark = ""
            if static is not None and (name, b) not in static:
                mark = "   NUEVA"
            out.append(("new" if mark else "ev", "-> %s  x%d%s" % (b, lab["out"][b], mark)))
            oc = lab.get("oc", {}).get(b, {})
            for cap in sorted(oc.keys(), key=lambda c: -oc[c])[:3]:
                out.append(("ch", "eligiendo \"%s\"  x%d" % (cap, oc[cap])))

        out.append(("h", "Cambios observados al pasar por aqui"))
        w = lab.get("w", {})
        if not w:
            out.append(("note", "(ninguno registrado)"))
        for p in sorted(w.keys(), key=lambda x: (-w[x]["n"], x))[:60]:
            e = w[p]
            s = "%s   x%d" % (p, e["n"])
            if e.get("d"):
                s += "   deltas: " + ", ".join(
                    ("+" if d > 0 else "") + _tr_num(d) for d in e["d"])
            elif e.get("vals"):
                s += "   valores: " + ", ".join(e["vals"])
            out.append(("chg", s))

        if lab.get("ch"):
            out.append(("h", "Elecciones hechas aqui"))
            for cap in sorted(lab["ch"].keys(), key=lambda c: -lab["ch"][c])[:12]:
                out.append(("ch", "\"%s\"  x%d" % (cap, lab["ch"][cap])))

        ent = RT.tr_entry.get(name)
        out.append(("h", "Estado de entrada"))
        if ent:
            out.append(("ok", "Guardado (%s): %d variables%s" % (
                ent.get("t", "?"), len(ent.get("s", {})),
                "" if ent.get("nv") else "  (sin filtro narrativo: falta la Fase 3)")))
            keys = sorted(ent.get("s", {}).keys())
            for k in keys[:25]:
                out.append(("note", "%s = %s" % (k, to_text(ent["s"][k])[:80])))
            if len(keys) > 25:
                out.append(("note", "... %d mas" % (len(keys) - 25)))
        else:
            out.append(("note", "No guardado. Se guardara la proxima vez que entres en este label."))
        return out

    def tr_rows(tab, q, onlynew):
        s = to_text(q or "").strip().lower()
        out = []
        if tab == "lab":
            names = sorted(RT.tr_labels.keys(),
                           key=lambda n: (-RT.tr_labels[n].get("v", 0), n))
            for n in names:
                if s and s not in n.lower():
                    continue
                out.append(("lab", n))
            return out
        if tab == "trans":
            static = tr_static_pairs()
            for a in sorted(RT.tr_labels.keys()):
                outs = RT.tr_labels[a].get("out", {})
                for b in sorted(outs.keys()):
                    known = None if static is None else ((a, b) in static)
                    if onlynew and known is not False:
                        continue
                    if known is None:
                        tag = "   (grafo no construido)"
                    elif known:
                        tag = ""
                    else:
                        tag = "   NUEVA: el grafo estatico no la conoce"
                    line = "%s  ->  %s   x%d%s" % (a, b, outs[b], tag)
                    if s and s not in line.lower():
                        continue
                    out.append(("new" if known is False else "ev", line))
            return out
        if tab == "snap":
            for line in (RT.tr_manual_diff or []):
                if s and s not in line.lower():
                    continue
                out.append(("chg", line))
            return out
        return out

    def tr_tools_rows():
        rows = tr_status_rows()
        rows.append(("h", "Archivo"))
        rows.append(("note", to_text(RT.tr_last_file or _savedir_path("umod_track.json") or "?")))
        try:
            if GRAPH:
                rows.append(("h", "Grafo"))
                rows.append(("note", "Aristas observadas integradas: %d" % RT.tr_merged))
        except Exception:
            pass
        rows.append(("h", "Notas"))
        rows.append(("note", "El gancho de menus solo se instala al arrancar: activarlo o desactivarlo requiere reiniciar el juego."))
        rows.append(("note", "Los cambios despues de un return se atribuyen al label llamado (evento 'mixto')."))
        return rows

    # ---------- 2.15 Apertura ---------------------------------------
    TR_SCREEN = "umod_tracker"

    def tracker_open():
        try:
            tr_load()
            if not RT.ready:
                scan_all()
            renpy.hide_screen(SCREEN)
            renpy.show_screen(TR_SCREEN)
            renpy.restart_interaction()
        except Exception as e:
            log_error("tracker_open", e)

    def tracker_close():
        try:
            tr_save()
            renpy.hide_screen(TR_SCREEN)
            renpy.restart_interaction()
        except Exception as e:
            log_error("tracker_close", e)

    def tracker_toggle():
        try:
            if renpy.get_screen(TR_SCREEN):
                tracker_close()
            else:
                tracker_open()
        except Exception as e:
            log_error("tracker_toggle", e)


# ---------------------------------------------------------------------
# 3) Registro de tecla, carga y salida
# ---------------------------------------------------------------------
init -958 python:
    umod.register_key("umod_tracker", umod.adv_keys(umod.TR_KEYS), umod.tracker_toggle)
    umod.add_callback("after_load_callbacks", None, umod.tr_after_load, "tracker.after_load")
    umod.add_callback("quit_callbacks", None, umod.tr_save_quit, "tracker.quit")
    umod.add_callback("interact_callbacks", None, umod.tr_ensure, "tracker.ensure")


# ---------------------------------------------------------------------
# 4) Ganchos de labels y menus: se instalan AL FINAL del init.
#    Muchos juegos asignan config.label_callback en su propio init;
#    si nos registraramos antes, nos sobrescribirian.
# ---------------------------------------------------------------------
init 1000 python:
    umod.tr_install_label()
    umod.tr_install_menu()


# =====================================================================
# 5) INTERFAZ DEL TRACKER
# =====================================================================

screen umod_tracker():

    modal True
    zorder 1100
    tag umod_panel

    default tab = "vivo"
    default q = ""
    default page = 0
    default sel = None
    default onlynew = False

    key "K_ESCAPE" action Function(umod.tracker_close)
    key "umod_tracker" action Function(umod.tracker_close)

    $ islist = tab in ("lab", "trans", "snap")
    $ items = umod.guard(umod.tr_rows, [], tab, q, onlynew) if islist else []
    $ shown = umod.page_slice(items, page) if islist else []
    $ npages = umod.page_count(items)
    $ qval = ScreenVariableInputValue("q", default=False) if umod.HAS_SVIV else None

    add Solid("#000000dd")

    frame:
        background Solid("#0f1117f5")
        xalign 0.5
        yalign 0.5
        xsize umod.S(1480)
        ysize umod.S(880)
        padding (umod.S(18), umod.S(14))

        vbox:
            spacing umod.S(9)

            # ---------------- Cabecera ----------------
            fixed:
                xfill True
                ysize umod.S(38)
                hbox:
                    xalign 0.0
                    yalign 0.5
                    spacing umod.S(16)
                    text "STATE TRACKER" size umod.S(22) color "#7fd4ff"
                    text umod.esc(umod.RT.tr_msg) size umod.S(13) color "#78839a" yalign 0.5
                hbox:
                    xalign 1.0
                    yalign 0.5
                    spacing umod.S(6)
                    textbutton "Panel":
                        action [Function(umod.tracker_close), Function(umod.open_panel)]
                        text_size umod.S(14)
                        background Solid("#232a36")
                        padding (umod.S(12), umod.S(6))
                    textbutton "Cerrar  (Esc)":
                        action Function(umod.tracker_close)
                        text_size umod.S(14)
                        text_color "#ffd9d9"
                        background Solid("#43222a")
                        hover_background Solid("#6a3340")
                        padding (umod.S(12), umod.S(6))

            # ---------------- Pestanas ----------------
            hbox:
                spacing umod.S(4)
                box_wrap True
                for tid, tlabel in umod.TR_TABS:
                    textbutton tlabel:
                        action [SetScreenVariable("tab", tid),
                                SetScreenVariable("page", 0),
                                SetScreenVariable("sel", None)]
                        text_size umod.S(16)
                        text_color ("#ffffff" if tab == tid else "#98a3b5")
                        background (Solid("#2b3446") if tab == tid else Solid("#191d26"))
                        hover_background Solid("#333e54")
                        padding (umod.S(14), umod.S(7))

            # ---------------- Barra de filtro ----------------
            fixed:
                xfill True
                ysize umod.S(36)
                if islist:
                    hbox:
                        yalign 0.5
                        spacing umod.S(10)
                        text "Filtro:" size umod.S(15) color "#98a3b5" yalign 0.5
                        if qval:
                            button:
                                action qval.Toggle()
                                background Solid("#0c0f14")
                                hover_background Solid("#161c26")
                                xsize umod.S(380)
                                ysize umod.S(32)
                                padding (umod.S(9), umod.S(5))
                                input:
                                    value qval
                                    length 48
                                    size umod.S(15)
                                    color "#e8eef7"
                        textbutton "limpiar":
                            action [SetScreenVariable("q", ""), SetScreenVariable("page", 0)]
                            text_size umod.S(13)
                            background Solid("#232a36")
                            padding (umod.S(10), umod.S(6))
                        if tab == "trans":
                            textbutton ("Solo nuevas ON" if onlynew else "Solo nuevas"):
                                action [ToggleScreenVariable("onlynew"), SetScreenVariable("page", 0)]
                                text_size umod.S(13)
                                text_color ("#ffcf7a" if onlynew else "#98a3b5")
                                background Solid("#232a36")
                                padding (umod.S(10), umod.S(6))
                        text umod.counter_line(items, page):
                            size umod.S(14)
                            color "#98a3b5"
                            yalign 0.5
                        textbutton "<":
                            action SetScreenVariable("page", max(0, page - 1))
                            text_size umod.S(15)
                            background Solid("#232a36")
                            padding (umod.S(14), umod.S(6))
                        textbutton ">":
                            action SetScreenVariable("page", min(npages - 1, page + 1))
                            text_size umod.S(15)
                            background Solid("#232a36")
                            padding (umod.S(14), umod.S(6))

            # ---------------- Contenido ----------------
            frame:
                background Solid("#0c0f14")
                xsize umod.S(1444)
                ysize umod.S(706)
                padding (umod.S(12), umod.S(10))

                # ---- En vivo ----
                if tab == "vivo":
                    viewport:
                        xsize umod.S(1418)
                        ysize umod.S(684)
                        scrollbars "vertical"
                        mousewheel True
                        draggable True
                        vbox:
                            spacing umod.S(3)
                            for r in umod.guard(umod.tr_live_rows, umod.ERR_ROWS):
                                if r[0] == "h":
                                    null height umod.S(6)
                                text umod.esc(r[1]):
                                    size umod.tr_size(r[0])
                                    color umod.tr_color(r[0])
                                    xoffset umod.tr_indent(r[0])
                                    xsize umod.S(1380)

                # ---- Snapshot A/B ----
                elif tab == "snap":
                    vbox:
                        spacing umod.S(8)
                        hbox:
                            spacing umod.S(8)
                            textbutton "Tomar snapshot A":
                                action Function(umod.tr_snap_take)
                                text_size umod.S(15)
                                background Solid("#1d3428")
                                hover_background Solid("#2b4d3a")
                                padding (umod.S(14), umod.S(8))
                            textbutton "Comparar A con ahora":
                                action [Function(umod.tr_snap_compare), SetScreenVariable("page", 0)]
                                text_size umod.S(15)
                                background Solid("#1d2734")
                                hover_background Solid("#2b3a4e")
                                padding (umod.S(14), umod.S(8))
                            textbutton "Descartar A":
                                action Function(umod.tr_snap_clear)
                                text_size umod.S(15)
                                background Solid("#232a36")
                                padding (umod.S(14), umod.S(8))
                        text umod.esc(umod.tr_snap_info()) size umod.S(13) color "#7f8ca1"
                        viewport:
                            xsize umod.S(1418)
                            ysize umod.S(600)
                            scrollbars "vertical"
                            mousewheel True
                            draggable True
                            vbox:
                                spacing umod.S(2)
                                for it in shown:
                                    text umod.esc(it[1]) size umod.S(13) color umod.tr_color(it[0])

                # ---- Labels aprendidos ----
                elif tab == "lab":
                    hbox:
                        spacing umod.S(12)
                        viewport:
                            xsize umod.S(700)
                            ysize umod.S(684)
                            scrollbars "vertical"
                            mousewheel True
                            draggable True
                            vbox:
                                spacing umod.S(1)
                                if not shown:
                                    text "Todavia no hay labels aprendidos. Juega con la grabacion activa.":
                                        size umod.S(13)
                                        color "#66707f"
                                for it in shown:
                                    textbutton umod.esc(umod.tr_lab_text(it[1])):
                                        action SetScreenVariable("sel", it[1])
                                        text_size umod.S(13)
                                        text_color ("#8fe0ff" if sel == it[1] else "#dfe7f2")
                                        background (Solid("#26324a") if sel == it[1] else None)
                                        hover_background Solid("#1b2431")
                                        padding (umod.S(6), umod.S(2))
                                        xfill True
                        frame:
                            background Solid("#121722")
                            xsize umod.S(706)
                            ysize umod.S(684)
                            padding (umod.S(10), umod.S(8))
                            if sel:
                                viewport:
                                    xsize umod.S(686)
                                    ysize umod.S(668)
                                    scrollbars "vertical"
                                    mousewheel True
                                    draggable True
                                    vbox:
                                        spacing umod.S(3)
                                        for r in umod.guard(umod.tr_lab_detail, umod.ERR_ROWS, sel):
                                            if r[0] == "h":
                                                null height umod.S(5)
                                            text umod.esc(r[1]):
                                                size umod.tr_size(r[0])
                                                color umod.tr_color(r[0])
                                                xoffset umod.tr_indent(r[0])
                                                xsize umod.S(640)
                            else:
                                text "Selecciona un label para ver de donde llego, a donde siguio, que cambio y con que estado entro.":
                                    size umod.S(13)
                                    color "#66707f"

                # ---- Transiciones ----
                elif tab == "trans":
                    viewport:
                        xsize umod.S(1418)
                        ysize umod.S(684)
                        scrollbars "vertical"
                        mousewheel True
                        draggable True
                        vbox:
                            spacing umod.S(2)
                            if not shown:
                                text "Sin transiciones observadas todavia.":
                                    size umod.S(13)
                                    color "#66707f"
                            for it in shown:
                                text umod.esc(it[1]) size umod.S(13) color umod.tr_color(it[0])

                # ---- Herramientas ----
                elif tab == "tools":
                    hbox:
                        spacing umod.S(16)
                        vbox:
                            spacing umod.S(8)
                            xsize umod.S(420)
                            textbutton ("Grabacion: ACTIVA" if umod.tr_enabled() else "Grabacion: DESACTIVADA"):
                                action Function(umod.tr_toggle_on)
                                text_size umod.S(15)
                                text_color ("#7ee0a5" if umod.tr_enabled() else "#ff9b8a")
                                background Solid("#1d2734")
                                hover_background Solid("#2b3a4e")
                                padding (umod.S(14), umod.S(8))
                                xfill True
                            textbutton ("Registrar menus: SI" if umod.tr_menu_enabled() else "Registrar menus: NO"):
                                action Function(umod.tr_toggle_menu)
                                text_size umod.S(15)
                                background Solid("#1d2734")
                                hover_background Solid("#2b3a4e")
                                padding (umod.S(14), umod.S(8))
                                xfill True
                            textbutton "Guardar grabacion ahora":
                                action Function(umod.tr_save, True)
                                text_size umod.S(15)
                                background Solid("#1d2734")
                                hover_background Solid("#2b3a4e")
                                padding (umod.S(14), umod.S(8))
                                xfill True
                            if umod.GRAPH:
                                textbutton "Integrar transiciones en el grafo":
                                    action Function(umod.tr_merge_into_graph)
                                    text_size umod.S(15)
                                    background Solid("#2e2a1c")
                                    hover_background Solid("#4a4329")
                                    padding (umod.S(14), umod.S(8))
                                    xfill True
                            null height umod.S(16)
                            textbutton "Borrar toda la grabacion":
                                action Confirm("Se perdera todo lo aprendido de este juego. Continuar?", Function(umod.tr_clear))
                                text_size umod.S(15)
                                text_color "#ffd9d9"
                                background Solid("#43222a")
                                hover_background Solid("#6a3340")
                                padding (umod.S(14), umod.S(8))
                                xfill True
                        viewport:
                            xsize umod.S(960)
                            ysize umod.S(684)
                            scrollbars "vertical"
                            mousewheel True
                            vbox:
                                spacing umod.S(3)
                                for r in umod.guard(umod.tr_tools_rows, umod.ERR_ROWS):
                                    if r[0] == "h":
                                        null height umod.S(5)
                                    text umod.esc(r[1]):
                                        size umod.tr_size(r[0])
                                        color umod.tr_color(r[0])
                                        xsize umod.S(930)


# ##################################################################### #
#   universal_mod_reconstruct.rpy
# ##################################################################### #

# =====================================================================
#  UNIVERSAL REN'PY MOD (UMOD)  -  FASE 6 / State Reconstruction
# ---------------------------------------------------------------------
#  Requiere universal_mod.rpy (Fase 1). Usa, si estan presentes:
#    Fase 3 (valores iniciales, variables que lee cada escena)
#    Fase 4 (camino y requisitos hasta la escena)
#    Fase 5 (estados reales observados y efectos de cada label)
#  Cuantas mas fases haya, mejor y mas fiable es el plan.
#
#  Que hace esta fase:
#    1. PLAN (no modifica nada): para una escena objetivo calcula el
#       estado que necesita, combinando por orden de fiabilidad:
#         a) estado de entrada OBSERVADO de la propia escena  -> exacto
#         b) estado observado del ancestro mas cercano en el camino
#            + efectos observados de los labels intermedios
#         c) partida actual (o valores iniciales en el menu principal)
#       y despues fuerza los REQUISITOS del camino (Fase 4) con un
#       resolutor ligero por variable (intervalos, igualdades,
#       booleanos, pertenencia), y rellena las variables que la
#       escena lee y no existen (evita el NameError tipico de saltar
#       a un label sin estado).
#    2. VALIDACION: evalua las guardas del camino contra el estado
#       propuesto, pero SOLO las expresiones puras (sin llamadas a
#       funciones): evaluar codigo del juego podria tener efectos.
#    3. APLICACION SEGURA:
#         copia de seguridad (_umod_backup)  ->  aplicar  ->  saltar
#       Si la copia falla, no se aplica nada. La copia se restaura
#       desde el propio panel.
#
#  ABRIR:  ALT + R
#
#  REGLAS DE SEGURIDAD
#    - persistent nunca se modifica salvo que lo actives a mano.
#    - Nunca se sustituye un contenedor u objeto por un valor simple.
#    - Si el juego define 'label after_warp' (el gancho oficial de
#      Ren'Py para preparar estado al usar warp), se llama antes de
#      aplicar el plan; nuestros valores tienen la ultima palabra.
#    - El estado sintetizado se marca: el tracker no lo confunde con
#      un estado real observado.
#
#  LO QUE ESTA FASE NO HACE (Fase 7)
#    - No ejecuta los eventos intermedios: salta directamente.
#    - No reconstruye imagenes en pantalla ni musica: limpia la capa
#      principal y deja que la escena dibuje lo suyo.
# =====================================================================


# ---------------------------------------------------------------------
# 0) Estado de runtime
# ---------------------------------------------------------------------
init -1050 python:
    import sys as _umod_sys_r
    try:
        _umod_r = _umod_sys_r.modules["umod_rt"]
        _umod_r.rc_cache = {}
        _umod_r.rc_pending = None
        _umod_r.rc_target = None
        _umod_r.rc_last = None
        _umod_r.rc_msg = "Selecciona una escena"
        _umod_r.rc_journal = []
        _umod_r.rc_backup_info = None
        _umod_r.tr_synthetic = False
        del _umod_r
    except Exception:
        pass


init -949 python:
    if persistent.umod_rc_after_warp is None:
        persistent.umod_rc_after_warp = True
    if persistent.umod_rc_persistent is None:
        persistent.umod_rc_persistent = False


# ---------------------------------------------------------------------
# 1) Motor de reconstruccion
# ---------------------------------------------------------------------
init -950 python in umod:

    import copy
    import ast as pyast

    RECONSTRUCT = True

    # Utilidades que normalmente aporta el tracker (Fase 5). Si no esta
    # instalado, definimos las nuestras para no depender de el.
    try:
        _PRIM_TYPES
    except NameError:
        _INT_TYPES = (int, long) if PY2 else (int,)      # noqa (long solo en Py2)
        _PRIM_TYPES = (bool, float) + _INT_TYPES

        class _Miss(object):
            def __repr__(self):
                return "(no existia)"
        _MISS = _Miss()

        def _isnum(x):
            return isinstance(x, (float,) + _INT_TYPES) and not isinstance(x, bool)

        def _is_prim(v):
            return v is None or isinstance(v, _PRIM_TYPES + string_types)

        def _tr_num(d):
            try:
                if float(d) == int(d):
                    return "%d" % d
            except Exception:
                pass
            return "%.2f" % d

    RC_KEYS     = ["alt_K_r"]
    RC_BACKUP   = "_umod_backup"
    RC_WARP     = "_umod_warp"

    _NOCHANGE = object()

    class _ObjPatch(object):
        """Atributos observados de un objeto: se aplican sobre el objeto
        existente del mismo tipo, nunca se crea uno nuevo."""
        def __init__(self, tn, attrs):
            self.tn = tn
            self.attrs = attrs

    class _NoRestore(object):
        def __init__(self, tn):
            self.tn = tn

    # ---------- 1.1 Preferencias ------------------------------------
    def _rc_pref(name, default):
        try:
            v = getattr(renpy.store.persistent, name, None)
        except Exception:
            v = None
        return default if v is None else bool(v)

    def rc_use_after_warp():
        return _rc_pref("umod_rc_after_warp", True) and _rc_has_label("after_warp")

    def rc_allow_persistent():
        return _rc_pref("umod_rc_persistent", False)

    def rc_toggle_pref(name):
        try:
            cur = _rc_pref(name, name == "umod_rc_after_warp")
            setattr(renpy.store.persistent, name, not cur)
            RT.rc_cache = {}
        except Exception as e:
            log_error("rc_toggle_pref", e)

    def _rc_has_label(name):
        try:
            return bool(renpy.has_label(name))
        except Exception:
            return False

    # ---------- 1.2 Acceso a variables por ruta ---------------------
    _PATH_RE = re.compile(r"^([A-Za-z_]\w*)((?:\.[A-Za-z_]\w*)*)(?:\['(.*)'\])?$")

    def _rc_split(path):
        """'a' | 'a.b.c' | "a['k']"  ->  (base, [attrs], key o None)"""
        m = _PATH_RE.match(to_text(path))
        if not m:
            return None
        attrs = [x for x in (m.group(2) or "").split(".") if x]
        return (m.group(1), attrs, m.group(3))

    def rc_get(path):
        """(existe, valor) leyendo del store, sin modificar nada."""
        if path.startswith("persistent."):
            try:
                p = vars(renpy.store.persistent)
                k = path[len("persistent."):]
                return (k in p, p.get(k))
            except Exception:
                return (False, None)
        sp = _rc_split(path)
        if not sp:
            return (False, None)
        base, attrs, key = sp
        d = vars(renpy.store)
        if base not in d:
            return (False, None)
        obj = d[base]
        try:
            for a in attrs:
                if not hasattr(obj, a):
                    return (False, None)
                obj = getattr(obj, a)
            if key is not None:
                if not isinstance(obj, dict):
                    return (False, None)
                for k in obj:
                    if to_text(k) == key:
                        return (True, obj[k])
                return (False, None)
        except Exception:
            return (False, None)
        return (True, obj)

    def _rc_lookup(W, path):
        if path in W:
            return (True, W[path]["val"])
        return rc_get(path)

    def rc_vt(v):
        if isinstance(v, _ObjPatch):
            return "<%s: %d atributos>" % (v.tn, len(v.attrs))
        if isinstance(v, _NoRestore):
            return "<%s no restaurable>" % v.tn
        try:
            s = repr(v)
        except Exception:
            s = "<?>"
        return s if len(s) <= 70 else s[:67] + "..."

    # ---------- 1.3 Decodificacion de estados observados ------------
    def rc_decode(j, cur=None):
        if j is None or isinstance(j, _PRIM_TYPES + string_types):
            return j
        if isinstance(j, list):
            return [rc_decode(x) for x in j]
        if isinstance(j, dict):
            if "~tuple" in j:
                return tuple(rc_decode(x) for x in j["~tuple"])
            if "~set" in j:
                out = set()
                for x in j["~set"]:
                    try:
                        out.add(rc_decode(x))
                    except TypeError:
                        pass
                return out
            if "~dict" in j:
                keymap = {}
                if isinstance(cur, dict):
                    for k in cur:
                        keymap[to_text(k)] = k
                out = {}
                for pair in j["~dict"]:
                    try:
                        k = keymap.get(pair[0], pair[0])
                        out[k] = rc_decode(pair[1], cur.get(k) if isinstance(cur, dict) else None)
                    except Exception:
                        pass
                return out
            if "a" in j and "~" in j:
                return _ObjPatch(j["~"], j.get("a") or {})
            if "~" in j:
                return _NoRestore(j["~"])
        return _NoRestore(type(j).__name__)

    def _literal(text):
        try:
            return (True, pyast.literal_eval(to_text(text)))
        except Exception:
            return (False, None)

    def rc_coerce(text, cur, exists):
        """parse_condition guarda los valores como texto: 'night', '10',
        'True'. El tipo correcto lo decide la variable actual."""
        t = to_text(text)
        if exists and isinstance(cur, bool):
            if t in ("True", "False"):
                return t == "True"
        if exists and _isnum(cur):
            try:
                x = float(t)
                return int(x) if x == int(x) and not isinstance(cur, float) else x
            except Exception:
                pass
        if exists and isinstance(cur, string_types):
            return t
        ok, v = _literal(t)
        if ok:
            return v
        return t

    def _types_compatible(cur, new):
        if new is None or cur is None:
            return True
        if isinstance(new, _ObjPatch):
            try:
                return type(cur).__name__ == new.tn
            except Exception:
                return False
        if isinstance(cur, bool) or isinstance(new, bool):
            return isinstance(cur, bool) and isinstance(new, bool)
        if _isnum(cur) and _isnum(new):
            return True
        if isinstance(cur, string_types) and isinstance(new, string_types):
            return True
        for group in ((list, tuple), (set, frozenset), (dict,)):
            if isinstance(cur, group) and isinstance(new, group):
                return True
        if _is_prim(cur) != _is_prim(new):
            return False
        try:
            return type(cur) is type(new)
        except Exception:
            return False

    # ---------- 1.4 Resolutor de restricciones por variable ---------
    def rc_satisfy(cur, exists, c):
        """Devuelve (nuevo_valor | _NOCHANGE, problema | None)."""
        op, raw = c["op"], c["val"]

        if op == "es cierto":
            want = (raw == "True")
            if exists and bool(cur) == want:
                return (_NOCHANGE, None)
            if not exists or cur is None or isinstance(cur, bool):
                return (want, None)
            if _isnum(cur):
                return ((cur if cur else 1) if want else 0, None)
            if isinstance(cur, (list, set, dict)) and not want:
                return (type(cur)(), None)
            return (_NOCHANGE, "no se sabe que valor de tipo %s es 'verdadero'" % type(cur).__name__)

        if op in (">", ">=", "<", "<="):
            try:
                thr = float(raw)
            except Exception:
                return (_NOCHANGE, "umbral no numerico: %s" % raw)
            if exists and cur is not None and not _isnum(cur):
                return (_NOCHANGE, "la variable no es numerica (%s)" % type(cur).__name__)
            x = cur if (exists and _isnum(cur)) else 0
            ok = {">": x > thr, ">=": x >= thr, "<": x < thr, "<=": x <= thr}[op]
            if exists and ok:
                return (_NOCHANGE, None)
            as_int = (thr == int(thr)) and not isinstance(cur, float)
            step = 1 if as_int else 0.01
            if op == ">=":
                nv = thr
            elif op == ">":
                nv = thr + step
            elif op == "<=":
                nv = thr
            else:
                nv = thr - step
            if as_int:
                nv = int(nv)
            return (nv, None)

        if op == "==":
            want = rc_coerce(raw, cur, exists)
            if exists and cur == want:
                return (_NOCHANGE, None)
            return (want, None)

        if op == "!=":
            bad = rc_coerce(raw, cur, exists)
            if exists and cur != bad:
                return (_NOCHANGE, None)
            if isinstance(bad, bool):
                return (not bad, None)
            if _isnum(bad):
                return (bad + 1, None)
            if bad is None:
                return (_NOCHANGE, "hace falta un valor distinto de None: no se puede inventar")
            return (_NOCHANGE, "hace falta un valor distinto de %s: no se puede inventar" % rc_vt(bad))

        if op in ("contiene", "no contiene"):
            ok, item = _literal(raw)
            if not ok:
                item = to_text(raw)
            if not exists or not isinstance(cur, (list, set, tuple, dict)):
                return (_NOCHANGE, "se necesita una coleccion existente")
            has = item in cur
            if (op == "contiene") == has:
                return (_NOCHANGE, None)
            if isinstance(cur, dict):
                return (_NOCHANGE, "no se puede anadir una clave a un diccionario sin conocer su valor")
            nv = copy.copy(cur)
            if op == "contiene":
                if isinstance(nv, set):
                    nv.add(item)
                elif isinstance(nv, tuple):
                    nv = nv + (item,)
                else:
                    nv.append(item)
            else:
                if isinstance(nv, set):
                    nv.discard(item)
                elif isinstance(nv, tuple):
                    nv = tuple(x for x in nv if x != item)
                else:
                    nv = [x for x in nv if x != item]
            return (nv, None)

        if op in ("in", "not in"):
            ok, coll = _literal(raw)
            if not ok:
                return (_NOCHANGE, "coleccion no literal: %s" % raw)
            try:
                inside = exists and cur in coll
            except Exception:
                inside = False
            if op == "in":
                if inside:
                    return (_NOCHANGE, None)
                try:
                    return (sorted(coll)[0] if isinstance(coll, (set, frozenset)) else list(coll)[0], None)
                except Exception:
                    return (_NOCHANGE, "coleccion vacia")
            if exists and not inside:
                return (_NOCHANGE, None)
            nums = [x for x in coll if _isnum(x)]
            if nums:
                return (max(nums) + 1, None)
            return (_NOCHANGE, "no se puede inventar un valor fuera de %s" % raw)

        if op in ("is", "is not"):
            if raw == "None":
                if op == "is":
                    return ((_NOCHANGE if exists and cur is None else None), None)
                if exists and cur is not None:
                    return (_NOCHANGE, None)
                return (_NOCHANGE, "hace falta un valor distinto de None: no se puede inventar")
            return (_NOCHANGE, "comparacion 'is' no soportada")

        return (_NOCHANGE, "operador no soportado: %s" % op)

    # ---------- 1.5 Construccion del plan ---------------------------
    def _rc_assign(W, path, val, src, why):
        W[path] = {"val": val, "src": src, "why": why}

    def _rc_path_labels(path, origin):
        labs = [origin]
        for ei in path:
            labs.append(RT.g_edges[ei]["b"])
        return labs

    def _rc_entry(label):
        try:
            e = RT.tr_entry.get(label)
        except Exception:
            return None
        if not e or e.get("syn"):
            return None
        return e

    def _rc_apply_effect(W, path, info, label):
        """Aplica el efecto observado de pasar por 'label' sobre W."""
        exists, cur = _rc_lookup(W, path)
        ds = info.get("d") or []
        vals = info.get("vals") or []
        if ds and _isnum(ds[0]):
            base = cur if (exists and _isnum(cur)) else 0
            _rc_assign(W, path, base + ds[0], "efecto observado",
                       "pasar por %s: %s%s" % (label, "+" if ds[0] > 0 else "", _tr_num(ds[0])))
            return
        if not vals:
            return
        last = to_text(vals[-1])
        if last.startswith("+ ") or last.startswith("- "):
            ok, item = _literal(last[2:])
            if not ok or not exists or not isinstance(cur, (list, set)):
                return
            nv = copy.copy(cur)
            if last.startswith("+ "):
                if item not in nv:
                    nv.add(item) if isinstance(nv, set) else nv.append(item)
            else:
                if isinstance(nv, set):
                    nv.discard(item)
                else:
                    nv = [x for x in nv if x != item]
            _rc_assign(W, path, nv, "efecto observado", "pasar por %s: %s" % (label, last))
            return
        ok, v = _literal(last)
        if ok and _is_prim(v):
            _rc_assign(W, path, v, "efecto observado", "pasar por %s: = %s" % (label, last))

    def rc_requirements(path):
        reqs, alts, cplx, decisions, guards = [], [], [], [], []
        seen = set()
        for ei in path:
            e = RT.g_edges[ei]
            for d in e.get("d", []):
                decisions.append((e["a"], d.get("cap", "?")))
            for raw, pol in e.get("g", []):
                key = (raw, bool(pol))
                if key in seen:
                    continue
                seen.add(key)
                guards.append((raw, bool(pol), e["a"]))
                cs, kind = guard_constraints(raw, pol)
                if kind == "compleja":
                    cplx.append(("" if pol else "NO ") + "(" + raw + ")")
                elif kind == "or":
                    alts.append(cs)
                else:
                    reqs.extend(cs)
        return reqs, alts, cplx, decisions, guards

    def _state_like(name):
        """Una variable 'de estado': la escribe el guion o tiene default."""
        try:
            if name in RT.sa_defaults:
                return True
            e = RT.sa_vars.get(name)
            return bool(e and e.get("w"))
        except Exception:
            return False

    def _rc_default_value(name):
        try:
            d = RT.sa_defaults.get(name)
        except Exception:
            d = None
        if not d:
            return (False, None)
        return _literal(d.get("src", ""))

    def rc_plan(target, origin=None, mode="guards", base_pref="auto"):
        key = (target, origin, mode, base_pref, rc_allow_persistent(),
               getattr(RT, "tr_seq", 0), len(getattr(RT, "g_edges", [])))
        hit = RT.rc_cache.get(key)
        if hit is not None:
            return hit

        P = {"target": target, "origin": origin, "mode": mode, "base": "",
             "path": None, "assigns": [], "skipped": [], "unresolved": [],
             "warnings": [], "decisions": [], "validation": [], "conf": "baja",
             "conf_why": "", "reqs": 0, "in_menu": _rc_in_main_menu()}
        W = {}

        # ---- a) camino ----
        graph_ok = False
        try:
            graph_ok = bool(GRAPH and RT.g_ready)
        except Exception:
            graph_ok = False
        if graph_ok:
            if not origin:
                origin = RT.g_origin
                P["origin"] = origin
            if target in RT.g_nodes and origin in RT.g_nodes:
                P["path"] = ng_path(origin, target, mode)
        else:
            P["warnings"].append("Sin grafo (Fase 4): no se pueden calcular requisitos del camino.")

        path = P["path"] or []
        labs = _rc_path_labels(path, origin) if P["path"] is not None else [target]

        # ---- b) base ----
        exact = False
        base_label = None
        if base_pref in ("auto", "observado"):
            if _rc_entry(target):
                base_label = target
                exact = True
            elif P["path"] is not None:
                for lb in reversed(labs[:-1]):
                    if _rc_entry(lb):
                        base_label = lb
                        break
        if base_pref == "observado" and base_label is None:
            P["warnings"].append("No hay ningun estado observado en el camino: se usa la partida actual.")

        if base_label:
            ent = _rc_entry(base_label)
            for var in sorted(ent.get("s", {}).keys()):
                exists, cur = rc_get(var)
                val = rc_decode(ent["s"][var], cur)
                if isinstance(val, _NoRestore):
                    P["skipped"].append("%s: %s (demasiado grande o complejo para restaurar)" % (var, rc_vt(val)))
                    continue
                if exists and _rc_equal(cur, val):
                    continue
                _rc_assign(W, var, val, "observado",
                           "estado real al entrar en %s (%s)" % (base_label, ent.get("t", "?")))
            if exact:
                P["base"] = "Estado OBSERVADO de la propia escena (ya jugaste hasta aqui)"
            else:
                k = len(labs) - 1 - labs.index(base_label)
                P["base"] = "Estado observado en '%s', a %d paso(s) de la escena" % (base_label, k)
                # efectos observados de los labels intermedios
                for lb in labs[labs.index(base_label):-1]:
                    try:
                        eff = tr_label_effects(lb)
                    except Exception:
                        eff = {}
                    for pth in sorted(eff.keys()):
                        if pth.startswith("persistent."):
                            continue
                        _rc_apply_effect(W, pth, eff[pth], lb)
        else:
            P["base"] = ("Valores iniciales del juego (estas en el menu principal)"
                         if P["in_menu"] else "Tu partida actual")

        # ---- c) requisitos del camino ----
        if P["path"] is not None:
            reqs, alts, cplx, decisions, guards = rc_requirements(path)
            P["decisions"] = decisions
            P["reqs"] = len(reqs) + len(alts)
            for c in reqs:
                _rc_force(W, P, c)
            for group in alts:
                if any(_rc_holds(W, c) for c in group):
                    continue
                for c in group:
                    before = len(P["unresolved"])
                    _rc_force(W, P, c)
                    if len(P["unresolved"]) == before:
                        break
            P["cplx"] = cplx               # se resuelven tras la validacion
            for c in ng_conflicts(reqs):
                P["warnings"].append("contradiccion en el camino: %s (solo es real si la variable no cambia entre las dos condiciones)" % c)
            P["guards"] = guards
        elif graph_ok:
            if exact:
                P["warnings"].append("No hay camino estatico, pero existe el estado observado: se usa tal cual.")
            else:
                P["warnings"].append("No hay camino estatico hasta la escena (screens, saltos calculados o rama no alcanzable desde el origen).")

        # ---- c2) reglas del adaptador (Fase 9): escritas por personas,
        #          tienen la ultima palabra sobre lo deducido ----
        try:
            if ADAPTERS:
                ad_apply_rules(W, P, target)
        except Exception as e:
            log_error("rc_plan.adapter", e)

        # ---- d) dependencias implicitas de la escena ----
        try:
            rec = RT.sa_labels.get(target) if (SCRIPT and RT.sa_ready) else None
        except Exception:
            rec = None
        if rec is not None:
            names = set(x.split(".")[0] for x in rec.get("reads", []))
            for c in rec.get("conds", []):
                names.add(c.get("v", "").split(".")[0])
            names.discard("")
            names.discard("persistent")
            for name in sorted(names):
                if not _state_like(name) or name in W:
                    continue
                exists, _cur = rc_get(name)
                if exists:
                    continue
                ok, dv = _rc_default_value(name)
                if ok:
                    _rc_assign(W, name, dv, "valor inicial",
                               "la escena lee '%s' y no existe: se usa su default" % name)
                else:
                    P["unresolved"].append("la escena lee '%s', que no existe y no tiene default: posible NameError" % name)
        else:
            P["warnings"].append("Sin el Analizador de guion (Fase 3) no se comprueban las variables que lee la escena.")

        # ---- e) filtros de seguridad ----
        for pth in sorted(W.keys()):
            item = W[pth]
            ign = False
            if ADAPTERS and item["src"] != "adaptador":
                try:
                    ign = ad_ignored(pth)
                except Exception:
                    ign = False
            if ign:
                P["skipped"].append("%s  (el adaptador la marca como ignorable)" % pth)
                continue
            if pth.startswith("persistent.") and not rc_allow_persistent():
                P["skipped"].append("%s = %s  (persistent: no se modifica sin tu permiso)" % (pth, rc_vt(item["val"])))
                continue
            exists, cur = rc_get(pth)
            if exists and not _types_compatible(cur, item["val"]):
                P["unresolved"].append("%s: no se sustituye %s por %s (tipos incompatibles)" % (
                    pth, type(cur).__name__, rc_vt(item["val"])))
                continue
            if isinstance(item["val"], _ObjPatch) and not exists:
                P["unresolved"].append("%s: el objeto no existe en la partida; no se puede crear" % pth)
                continue
            P["assigns"].append({"v": pth, "val": item["val"], "src": item["src"],
                                 "why": item["why"],
                                 "old": rc_vt(cur) if exists else "(no existe)"})

        # ---- f) validacion y confianza ----
        P["validation"] = rc_validate(P)
        fails = [v for v in P["validation"] if v[0] == "no"]
        # Una condicion compleja no se puede deducir, pero si se puede
        # comprobar: si el estado propuesto ya la cumple, esta resuelta.
        ok_txt = set(t for k, t in P["validation"] if k == "si")
        for t in P.get("cplx", []):
            # "NO (expr)" -> "NO expr"   |   "(expr)" -> "expr"
            label = ("NO " + t[4:-1]) if t.startswith("NO (") else t[1:-1]
            if label not in ok_txt:
                P["unresolved"].append("condicion no deducible automaticamente: %s" % t)
        if exact and not P["unresolved"] and not fails:
            P["conf"], P["conf_why"] = "alta", "es el estado real con el que llegaste a esta escena"
        elif P.get("rule") and not P["unresolved"] and not fails:
            P["conf"], P["conf_why"] = "alta", "la escena tiene una regla del adaptador '%s' y el camino valida" % P.get("adapter", "?")
        elif P["unresolved"] or fails or (graph_ok and P["path"] is None and not exact):
            P["conf"] = "baja"
            P["conf_why"] = "hay condiciones sin resolver o que no se cumplen: la escena puede comportarse distinto o fallar"
        elif base_label:
            P["conf"], P["conf_why"] = "media", "basado en un estado real cercano mas efectos observados"
        else:
            P["conf"], P["conf_why"] = "media", "solo se fuerzan los requisitos visibles; variables que el guion no compara podrian faltar"

        RT.rc_cache[key] = P
        RT.rc_last = P
        return P

    def _rc_equal(a, b):
        if isinstance(b, (_ObjPatch, _NoRestore)):
            if isinstance(b, _ObjPatch):
                try:
                    return all(getattr(a, k, _MISS) == b.attrs[k] for k in b.attrs)
                except Exception:
                    return False
            return False
        try:
            if isinstance(a, bool) != isinstance(b, bool):
                return False
            return a == b
        except Exception:
            return False

    def _rc_holds(W, c):
        exists, cur = _rc_lookup(W, c["v"])
        nv, prob = rc_satisfy(cur, exists, c)
        return nv is _NOCHANGE and prob is None

    def _rc_force(W, P, c):
        exists, cur = _rc_lookup(W, c["v"])
        nv, prob = rc_satisfy(cur, exists, c)
        txt = req_text(c)
        if prob:
            P["unresolved"].append("%s: %s" % (txt, prob))
            return
        if nv is _NOCHANGE:
            return
        _rc_assign(W, c["v"], nv, "requisito", "el camino exige %s" % txt)

    # ---------- 1.6 Validacion (solo expresiones puras) -------------
    _UNSAFE = tuple(c for c in (getattr(pyast, "Call", None), getattr(pyast, "Lambda", None),
                                getattr(pyast, "Yield", None), getattr(pyast, "Await", None),
                                getattr(pyast, "NamedExpr", None)) if c is not None)

    def _pure(expr):
        try:
            tree = pyast.parse(to_text(expr), mode="eval")
        except Exception:
            return None
        for n in pyast.walk(tree):
            if isinstance(n, _UNSAFE):
                return None
        return tree

    class _PersistOverlay(object):
        """persistent visto a traves del plan, sin modificar el real."""
        def __init__(self, real, over):
            self.__dict__["_real"] = real
            self.__dict__["_over"] = over

        def __getattr__(self, k):
            over = self.__dict__["_over"]
            if k in over:
                return over[k]
            return getattr(self.__dict__["_real"], k)

    def _overlay_ns(P):
        ns = dict(vars(renpy.store))
        pover = {}
        for a in P["assigns"]:
            if a["v"].startswith("persistent."):
                pover[a["v"][len("persistent."):]] = a["val"]
        try:
            ns["persistent"] = _PersistOverlay(renpy.store.persistent, pover)
        except Exception:
            pass
        clones = {}
        for a in P["assigns"]:
            sp = _rc_split(a["v"])
            if a["v"].startswith("persistent.") or not sp:
                continue
            base, attrs, key = sp
            val = a["val"]
            if not attrs and key is None and not isinstance(val, _ObjPatch):
                ns[base] = val
                continue
            try:
                if base not in clones:
                    clones[base] = copy.copy(ns[base])
                    ns[base] = clones[base]
                obj = ns[base]
                for at in attrs[:-1]:
                    nxt = copy.copy(getattr(obj, at))
                    setattr(obj, at, nxt)
                    obj = nxt
                if isinstance(val, _ObjPatch):
                    tgt = getattr(obj, attrs[-1]) if attrs else obj
                    for k in val.attrs:
                        setattr(tgt, k, val.attrs[k])
                elif key is not None:
                    holder = getattr(obj, attrs[-1]) if attrs else obj
                    holder = copy.copy(holder)
                    if attrs:
                        setattr(obj, attrs[-1], holder)
                    else:
                        ns[base] = holder
                    holder[key] = val
                else:
                    setattr(obj, attrs[-1], val)
            except Exception:
                pass
        return ns

    def rc_validate(P):
        out = []
        guards = P.get("guards") or []
        if not guards:
            return out
        try:
            ns = _overlay_ns(P)
        except Exception as e:
            log_error("rc_validate.ns", e)
            return [("?", "no se pudo preparar la validacion")]
        for raw, pol, lab in guards:
            tree = _pure(raw)
            label = ("" if pol else "NO ") + raw
            if tree is None:
                out.append(("?", "%s   (no evaluable sin ejecutar codigo del juego)" % label))
                continue
            try:
                # Sin builtins: una expresion pura no los necesita. True,
                # False y None se dan explicitamente (en Py2 son nombres).
                g = {"__builtins__": {}, "True": True, "False": False, "None": None}
                r = bool(eval(compile(tree, "<umod>", "eval"), g, ns))
                ok = (r == pol)
                out.append(("si" if ok else "no", label))
            except Exception as e:
                out.append(("?", "%s   (%s)" % (label, type(e).__name__)))
        return out

    # ---------- 1.7 Aplicacion segura -------------------------------
    def _rc_in_main_menu():
        try:
            return bool(getattr(renpy.store, "main_menu", False))
        except Exception:
            return False

    def _rc_rev(v):
        """Contenedores nuevos como Revertable*: participan del rollback.
        La ubicacion de las clases la resuelve la Compatibility Layer."""
        try:
            if type(v) is list:
                c = revertable_class("RevertableList")
                return c(v) if c else v
            if type(v) is dict:
                c = revertable_class("RevertableDict")
                return c(v) if c else v
            if type(v) is set:
                c = revertable_class("RevertableSet")
                return c(v) if c else v
        except Exception:
            pass
        return v

    def _rc_set(path, val):
        """Escribe en el store. Devuelve (ok, valor_anterior_o_None)."""
        if path.startswith("persistent."):
            if not rc_allow_persistent():
                return (False, None)
            k = path[len("persistent."):]
            old = getattr(renpy.store.persistent, k, None)
            setattr(renpy.store.persistent, k, val)
            return (True, old)
        sp = _rc_split(path)
        if not sp:
            return (False, None)
        base, attrs, key = sp
        st = renpy.store
        if not attrs and key is None:
            old = getattr(st, base, _MISS)
            if isinstance(val, _ObjPatch):
                obj = getattr(st, base)
                for k in val.attrs:
                    setattr(obj, k, val.attrs[k])
                return (True, old)
            setattr(st, base, _rc_rev(val))
            return (True, old)
        obj = getattr(st, base)
        for a in attrs[:-1]:
            obj = getattr(obj, a)
        if key is not None:
            holder = getattr(obj, attrs[-1]) if attrs else obj
            real = key
            for k in holder:
                if to_text(k) == key:
                    real = k
                    break
            old = holder.get(real, _MISS)
            holder[real] = _rc_rev(val)
            return (True, old)
        old = getattr(obj, attrs[-1], _MISS)
        if isinstance(val, _ObjPatch):
            tgt = getattr(obj, attrs[-1])
            for k in val.attrs:
                setattr(tgt, k, val.attrs[k])
        else:
            setattr(obj, attrs[-1], _rc_rev(val))
        return (True, old)

    def rc_apply(P):
        """Aplica las asignaciones. Devuelve (aplicadas, fallidas)."""
        done, failed = 0, []
        RT.rc_journal = []
        for a in P["assigns"]:
            try:
                ok, old = _rc_set(a["v"], a["val"])
                if ok:
                    done += 1
                    RT.rc_journal.append((a["v"], old))
                else:
                    failed.append(a["v"])
            except Exception as e:
                failed.append("%s (%s)" % (a["v"], e))
                log_error("rc_apply", e)
        # El tracker no debe atribuir estos cambios a ningun label ni
        # guardar los estados siguientes como "observados reales".
        RT.tr_prev = None
        RT.tr_synthetic = True
        return done, failed

    def rc_backup():
        try:
            try:
                renpy.take_screenshot()
            except Exception:
                pass
            renpy.save(RC_BACKUP, "UMOD: copia antes de saltar a %s" % (RT.rc_last or {}).get("target", "?"))
            RT.rc_backup_info = "%s  (antes de saltar a '%s')" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), (RT.rc_last or {}).get("target", "?"))
            return True
        except Exception as e:
            log_error("rc_backup", e)
            return False

    def rc_has_backup():
        try:
            return bool(renpy.can_load(RC_BACKUP))
        except Exception:
            return False

    def rc_restore():
        try:
            if rc_has_backup():
                renpy.load(RC_BACKUP)
        except Exception as e:
            # renpy.load termina con una excepcion de control propia del
            # motor: solo registramos errores reales.
            if type(e).__name__ not in ("RestartContext", "RestartTopContext", "FullRestartException"):
                log_error("rc_restore", e)
            raise

    ALL_SCREENS = ["umod_main", "umod_gallery", "umod_script", "umod_graph",
                   "umod_tracker", "umod_reconstruct"]

    def _rc_hide_all():
        for s in ALL_SCREENS:
            try:
                renpy.hide_screen(s)
            except Exception:
                pass

    def rc_execute(P):
        """Copia de seguridad -> (en el label de salto) aplicar -> saltar."""
        if P is None:
            return
        try:
            if getattr(renpy.store, "_in_replay", None):
                RT.rc_msg = "No disponible durante un replay."
                return
        except Exception:
            pass
        in_menu = _rc_in_main_menu()
        if not in_menu:
            if not rc_backup():
                RT.rc_msg = "No se pudo crear la copia de seguridad: NO se ha aplicado nada."
                renpy.restart_interaction()
                return
        RT.rc_pending = P
        RT.rc_msg = "Saltando a '%s'..." % P["target"]
        _rc_hide_all()
        nested = 0
        try:
            nested = renpy.context_nesting_level()
        except Exception:
            nested = 0
        if in_menu or nested > 0:
            renpy.jump_out_of_context(RC_WARP)
        else:
            renpy.jump(RC_WARP)

    def rc_apply_pending():
        P = RT.rc_pending
        RT.rc_pending = None
        if not P:
            RT.rc_target = None
            return
        done, failed = rc_apply(P)
        RT.rc_target = P["target"]
        RT.rc_msg = "Aplicadas %d asignaciones%s; escena '%s'" % (
            done, (", %d fallidas" % len(failed)) if failed else "", P["target"])
        try:
            if "notice" in P:
                # desde la galeria: lenguaje sencillo, y el aviso de final si lo hay
                renpy.notify(P["notice"] or u"Listo: empiezas a jugar desde aqu\u00ed.")
            else:
                renpy.notify("UMOD: estado reconstruido (%d cambios)" % done)
        except Exception:
            pass

    def rc_finish():
        """Aplicar el plan, limpiar la capa principal, reconstruir las
        visuales del camino (Fase 7) y saltar. Todo en una sola llamada:
        ejecutar un nodo scene/show cambia el 'siguiente statement' del
        contexto, y el salto inmediato lo anula."""
        P = RT.rc_pending
        rc_apply_pending()
        try:
            renpy.scene()
        except Exception as e:
            log_error("rc_finish.scene", e)
        try:
            if P and EMULATOR:
                em_replay_for_plan(P)
        except Exception as e:
            log_error("rc_finish.visuals", e)
        try:
            if P and ADAPTERS:
                ad_run_setup(P)            # codigo 'setup' de un adaptador Python
        except Exception as e:
            log_error("rc_finish.setup", e)
        label = rc_take_target()
        node = (P or {}).get("node")
        if node is not None and rc_node_exists(node):
            # "Jugar desde aqui": comienzo exacto de la escena dentro del label.
            # Todas las sentencias tienen nombre en script.namemap, igual que
            # usa el warp del propio Ren'Py.
            renpy.jump(node)
        renpy.jump(label)

    def rc_node_exists(name):
        try:
            return renpy.game.script.lookup(name) is not None
        except Exception:
            return False

    def rc_take_target():
        t = RT.rc_target
        RT.rc_target = None
        if t and _rc_has_label(t):
            return t
        return "start"

    def rc_undo():
        """Deshace la ultima aplicacion en esta sesion sin cargar nada."""
        n = 0
        for path, old in reversed(RT.rc_journal):
            try:
                if old is _MISS:
                    sp = _rc_split(path)
                    if sp and not sp[1] and sp[2] is None:
                        delattr(renpy.store, sp[0])
                        n += 1
                    continue
                _rc_set(path, old)
                n += 1
            except Exception as e:
                log_error("rc_undo", e)
        RT.rc_journal = []
        RT.rc_msg = "Deshechos %d cambios" % n
        RT.tr_prev = None
        renpy.restart_interaction()

    # ---------- 1.8 Exportar como regla (semilla de la Fase 9) -------
    def rc_export_rule(P):
        if not P:
            return None
        p = _savedir_path("umod_rules.json")
        data = {"format": 1, "game_id": game_id(), "rules": {}}
        try:
            if p and os.path.exists(p):
                f = open(p, "r")
                try:
                    old = json.load(f)
                finally:
                    f.close()
                if old.get("game_id") == game_id():
                    data = old
        except Exception as e:
            log_error("rc_export_rule.read", e)
        rule = {}
        for a in P["assigns"]:
            v = a["val"]
            if isinstance(v, _ObjPatch):
                rule[a["v"]] = {"~": v.tn, "a": v.attrs}
            else:
                rule[a["v"]] = jsafe(v) if TRACKER else (v if _is_prim(v) else to_text(v))
        data["rules"][P["target"]] = {"set": rule, "conf": P["conf"],
                                      "created": time.strftime("%Y-%m-%d %H:%M:%S")}
        data["fp"] = script_fp()
        out = _write_json(p, data, pretty=True)
        if out:
            RT.rc_msg = "Regla guardada en umod_rules.json (%d variables)" % len(rule)
        return out

    # ---------- 1.9 Vistas ------------------------------------------
    RC_COLOR = {
        "h":    "#8fe0ff",
        "ev":   "#dfe7f2",
        "set":  "#9fe0b0",
        "why":  "#7f8ca1",
        "ok":   "#7ee0a5",
        "warn": "#ff9b8a",
        "note": "#7f8ca1",
        "q":    "#e7c58a",
        "dec":  "#b9a6ff",
    }

    def rc_color(k):
        return RC_COLOR.get(k, "#dfe7f2")

    def rc_size(k):
        return S(15) if k == "h" else S(13)

    def rc_indent(k):
        return S(22) if k in ("why", "dec") else 0

    CONF_COLOR = {"alta": "#7ee0a5", "media": "#e7c58a", "baja": "#ff9b8a"}

    def rc_conf_color(P):
        return CONF_COLOR.get((P or {}).get("conf"), "#dfe7f2")

    def rc_conf_text(P):
        if not P:
            return ""
        return "Confianza %s: %s" % (P["conf"].upper(), P["conf_why"])

    def rc_rows(P):
        rows = []
        if not P:
            return [("note", "Selecciona una escena para calcular el plan.")]
        rows.append(("h", "BASE"))
        rows.append(("ev", P["base"]))

        rows.append(("h", "CAMINO"))
        if P["path"] is None:
            rows.append(("note", "sin camino estatico conocido"))
        else:
            rows.append(("ev", "%d paso(s) desde '%s', %d requisito(s)" % (
                len(P["path"]), P["origin"], P["reqs"])))
            if P["decisions"]:
                rows.append(("note", "Decisiones que implica (la Fase 7 podra recorrerlas; aqui solo se salta):"))
                for lb, cap in P["decisions"][:12]:
                    rows.append(("dec", "%s:  \"%s\"" % (lb, cap)))
                if len(P["decisions"]) > 12:
                    rows.append(("dec", "... %d mas" % (len(P["decisions"]) - 12)))

        rows.append(("h", "CAMBIOS QUE SE APLICARAN  (%d)" % len(P["assigns"])))
        if not P["assigns"]:
            rows.append(("ok", "Ninguno: el estado actual ya sirve."))
        for a in P["assigns"][:120]:
            rows.append(("set", "%s = %s      (antes: %s)" % (a["v"], rc_vt(a["val"]), a["old"])))
            rows.append(("why", "[%s] %s" % (a["src"], a["why"])))
        if len(P["assigns"]) > 120:
            rows.append(("note", "... %d mas" % (len(P["assigns"]) - 120)))

        if P["validation"]:
            rows.append(("h", "VALIDACION DE LAS CONDICIONES DEL CAMINO"))
            for kind, txt in P["validation"]:
                if kind == "si":
                    rows.append(("ok", "cumple:  " + txt))
                elif kind == "no":
                    rows.append(("warn", "NO cumple:  " + txt))
                else:
                    rows.append(("q", "?  " + txt))

        if P["unresolved"]:
            rows.append(("h", "SIN RESOLVER  (%d)" % len(P["unresolved"])))
            for t in P["unresolved"][:40]:
                rows.append(("warn", t))
        if P["warnings"]:
            rows.append(("h", "AVISOS"))
            for t in P["warnings"][:20]:
                rows.append(("q", t))
        if P["skipped"]:
            rows.append(("h", "NO SE TOCAN  (%d)" % len(P["skipped"])))
            for t in P["skipped"][:30]:
                rows.append(("note", t))

        rows.append(("h", "SEGURIDAD"))
        if P["in_menu"]:
            rows.append(("note", "Estas en el menu principal: se empezara una partida nueva directamente en la escena. No hay nada que respaldar."))
        else:
            rows.append(("ok", "Antes de aplicar se guarda una copia de tu partida en el slot oculto '%s'." % RC_BACKUP))
            rows.append(("note", "Si la copia falla, no se aplica nada. Puedes restaurarla desde este panel."))
        if rc_use_after_warp():
            rows.append(("note", "El juego define 'after_warp': se ejecutara antes de aplicar el plan."))
        try:
            emu = bool(EMULATOR and em_visuals_enabled())
        except Exception:
            emu = False
        if emu:
            rows.append(("note", "Se reconstruyen fondo, personajes y musica del camino (como --warp) si la escena no empieza con su propio 'scene'."))
        else:
            rows.append(("note", "Se limpia la capa principal: la escena dibuja su propio fondo. Imagenes previas y musica no se reconstruyen (activa la Fase 7)."))
        return rows

    def rc_label_list(q):
        s = to_text(q or "").strip().lower()
        try:
            if GRAPH and RT.g_ready:
                names = [lb for _g, labs in RT.g_groups for lb in labs]
            elif SCRIPT and RT.sa_ready:
                names = list(RT.sa_order)
            else:
                names = list(RT.labels.get("game", []))
        except Exception:
            names = list(RT.labels.get("game", []))
        if s:
            names = [n for n in names if s in n.lower()]
        return names

    def rc_label_text(name):
        tags = []
        try:
            if _rc_entry(name):
                tags.append("observado")
        except Exception:
            pass
        try:
            if GRAPH and RT.g_ready and name not in RT.g_reach:
                tags.append("huerfano")
        except Exception:
            pass
        extra = ""
        try:
            if ADAPTERS:
                extra = ad_label_suffix(name)
        except Exception:
            extra = ""
        return name + extra + (("   [" + ", ".join(tags) + "]") if tags else "")

    def rc_label_color(name):
        if _rc_entry(name):
            return "#7ee0a5"
        try:
            if GRAPH and RT.g_ready and name not in RT.g_reach:
                return "#d99a6c"
        except Exception:
            pass
        return "#c3ccda"

    def rc_backup_text():
        if rc_has_backup():
            return "Copia de seguridad disponible: %s" % (RT.rc_backup_info or RC_BACKUP)
        return "Sin copia de seguridad."

    # ---------- 1.10 Apertura ---------------------------------------
    RC_SCREEN = "umod_reconstruct"

    def reconstruct_open():
        try:
            if not RT.ready:
                scan_all()
            try:
                if SCRIPT:
                    sa_ensure()            # cache o segundo plano: no bloquea
                if GRAPH:
                    ng_ensure()
            except Exception as e:
                log_error("rc_open.deps", e)
            try:
                if TRACKER:
                    tr_load()
            except Exception as e:
                log_error("rc_open.tr", e)
            RT.rc_cache = {}
            renpy.hide_screen(SCREEN)
            renpy.show_screen(RC_SCREEN)
            renpy.restart_interaction()
        except Exception as e:
            log_error("reconstruct_open", e)

    def reconstruct_toggle():
        try:
            if renpy.get_screen(RC_SCREEN):
                renpy.hide_screen(RC_SCREEN)
                renpy.restart_interaction()
            else:
                reconstruct_open()
        except Exception as e:
            log_error("reconstruct_toggle", e)


# ---------------------------------------------------------------------
# 2) Registro de tecla
# ---------------------------------------------------------------------
init -948 python:
    umod.register_key("umod_reconstruct", umod.adv_keys(umod.RC_KEYS), umod.reconstruct_toggle)


# ---------------------------------------------------------------------
# 3) Label de salto. Empieza por "_": el tracker lo ignora.
# ---------------------------------------------------------------------
label _umod_warp:
    if umod.rc_use_after_warp():
        call expression "after_warp"
    $ umod.rc_finish()
    # Respaldo: rc_finish ya salta; solo se llega aqui si algo fallo antes.
    jump expression umod.rc_take_target()


# =====================================================================
# 4) INTERFAZ
# =====================================================================

screen umod_reconstruct():

    modal True
    zorder 1100
    tag umod_panel

    default q = ""
    default page = 0
    default sel = None
    default mode = "guards"
    default base = "auto"

    key "K_ESCAPE" action Hide("umod_reconstruct")
    key "umod_reconstruct" action Hide("umod_reconstruct")

    $ names = umod.guard(umod.rc_label_list, [], q)
    $ shown = umod.page_slice(names, page)
    $ npages = umod.page_count(names)
    $ plan = umod.guard(umod.rc_plan, None, sel, None, mode, base) if sel else None
    $ qval = ScreenVariableInputValue("q", default=False) if umod.HAS_SVIV else None

    add Solid("#000000dd")

    frame:
        background Solid("#0f1117f5")
        xalign 0.5
        yalign 0.5
        xsize umod.S(1480)
        ysize umod.S(880)
        padding (umod.S(18), umod.S(14))

        vbox:
            spacing umod.S(9)

            # ---------------- Cabecera ----------------
            fixed:
                xfill True
                ysize umod.S(38)
                hbox:
                    xalign 0.0
                    yalign 0.5
                    spacing umod.S(16)
                    text "RECONSTRUCCION DE ESTADO" size umod.S(22) color "#7fd4ff"
                    text umod.esc(umod.RT.rc_msg) size umod.S(13) color "#78839a" yalign 0.5
                hbox:
                    xalign 1.0
                    yalign 0.5
                    spacing umod.S(6)
                    textbutton "Panel":
                        action [Hide("umod_reconstruct"), Function(umod.open_panel)]
                        text_size umod.S(14)
                        background Solid("#232a36")
                        padding (umod.S(12), umod.S(6))
                    textbutton "Cerrar  (Esc)":
                        action Hide("umod_reconstruct")
                        text_size umod.S(14)
                        text_color "#ffd9d9"
                        background Solid("#43222a")
                        hover_background Solid("#6a3340")
                        padding (umod.S(12), umod.S(6))

            # ---------------- Opciones ----------------
            fixed:
                xfill True
                ysize umod.S(36)
                hbox:
                    yalign 0.5
                    spacing umod.S(8)
                    if qval:
                        button:
                            action qval.Toggle()
                            background Solid("#0c0f14")
                            hover_background Solid("#161c26")
                            xsize umod.S(260)
                            ysize umod.S(32)
                            padding (umod.S(9), umod.S(5))
                            input:
                                value qval
                                length 40
                                size umod.S(15)
                                color "#e8eef7"
                    textbutton "<":
                        action SetScreenVariable("page", max(0, page - 1))
                        text_size umod.S(14)
                        background Solid("#232a36")
                        padding (umod.S(12), umod.S(6))
                    textbutton ">":
                        action SetScreenVariable("page", min(npages - 1, page + 1))
                        text_size umod.S(14)
                        background Solid("#232a36")
                        padding (umod.S(12), umod.S(6))
                    text "  Base:" size umod.S(14) color "#98a3b5" yalign 0.5
                    for bid, blabel in (("auto", "auto"), ("observado", "observado"), ("actual", "partida actual")):
                        textbutton blabel:
                            action SetScreenVariable("base", bid)
                            text_size umod.S(13)
                            text_color ("#ffffff" if base == bid else "#98a3b5")
                            background (Solid("#2b3446") if base == bid else Solid("#191d26"))
                            padding (umod.S(9), umod.S(6))
                    text "  Camino:" size umod.S(14) color "#98a3b5" yalign 0.5
                    for mid, mlabel in (("guards", "menos condiciones"), ("short", "menos pasos")):
                        textbutton mlabel:
                            action SetScreenVariable("mode", mid)
                            text_size umod.S(13)
                            text_color ("#ffffff" if mode == mid else "#98a3b5")
                            background (Solid("#2b3446") if mode == mid else Solid("#191d26"))
                            padding (umod.S(9), umod.S(6))
                    textbutton ("persistent: SI" if umod.rc_allow_persistent() else "persistent: NO"):
                        action Function(umod.rc_toggle_pref, "umod_rc_persistent")
                        text_size umod.S(13)
                        text_color ("#ff9b8a" if umod.rc_allow_persistent() else "#98a3b5")
                        background Solid("#191d26")
                        padding (umod.S(9), umod.S(6))

            # ---------------- Dos columnas ----------------
            hbox:
                spacing umod.S(12)

                frame:
                    background Solid("#0c0f14")
                    xsize umod.S(430)
                    ysize umod.S(722)
                    padding (umod.S(8), umod.S(8))
                    viewport:
                        xsize umod.S(414)
                        ysize umod.S(706)
                        scrollbars "vertical"
                        mousewheel True
                        draggable True
                        vbox:
                            spacing umod.S(1)
                            for n in shown:
                                textbutton umod.esc(umod.rc_label_text(n)):
                                    action SetScreenVariable("sel", n)
                                    text_size umod.S(13)
                                    text_color ("#ffffff" if sel == n else umod.rc_label_color(n))
                                    background (Solid("#26324a") if sel == n else None)
                                    hover_background Solid("#1b2431")
                                    padding (umod.S(6), umod.S(2))
                                    xfill True

                frame:
                    background Solid("#121722")
                    xsize umod.S(1002)
                    ysize umod.S(722)
                    padding (umod.S(12), umod.S(10))
                    if plan:
                        vbox:
                            spacing umod.S(8)
                            text umod.esc(plan["target"]) size umod.S(19) color "#8fe0ff"
                            text umod.esc(umod.rc_conf_text(plan)) size umod.S(14) color umod.rc_conf_color(plan)
                            hbox:
                                spacing umod.S(8)
                                textbutton "Aplicar y saltar":
                                    action Confirm("Se guardara una copia de seguridad de tu partida y se saltara a la escena con el estado propuesto. Continuar?", Function(umod.rc_execute, plan))
                                    text_size umod.S(15)
                                    background Solid("#1d3428")
                                    hover_background Solid("#2b4d3a")
                                    padding (umod.S(14), umod.S(7))
                                textbutton "Guardar como regla":
                                    action Function(umod.rc_export_rule, plan)
                                    text_size umod.S(14)
                                    background Solid("#1d2734")
                                    hover_background Solid("#2b3a4e")
                                    padding (umod.S(12), umod.S(7))
                                if umod.RT.rc_journal:
                                    textbutton "Deshacer ultimo salto":
                                        action Function(umod.rc_undo)
                                        text_size umod.S(14)
                                        background Solid("#232a36")
                                        padding (umod.S(12), umod.S(7))
                                if umod.rc_has_backup():
                                    textbutton "Restaurar copia":
                                        action Confirm("Se cargara la copia de seguridad y se perdera lo que hayas hecho despues. Continuar?", Function(umod.rc_restore))
                                        text_size umod.S(14)
                                        text_color "#ffd9d9"
                                        background Solid("#43222a")
                                        hover_background Solid("#6a3340")
                                        padding (umod.S(12), umod.S(7))
                            text umod.esc(umod.rc_backup_text()) size umod.S(12) color "#7f8ca1"
                            viewport:
                                xsize umod.S(978)
                                ysize umod.S(560)
                                scrollbars "vertical"
                                mousewheel True
                                draggable True
                                vbox:
                                    spacing umod.S(3)
                                    for r in umod.guard(umod.rc_rows, umod.ERR_ROWS, plan):
                                        if r[0] == "h":
                                            null height umod.S(6)
                                        text umod.esc(r[1]):
                                            size umod.rc_size(r[0])
                                            color umod.rc_color(r[0])
                                            xoffset umod.rc_indent(r[0])
                                            xsize umod.S(940)
                    else:
                        vbox:
                            spacing umod.S(10)
                            text "Elige una escena de la lista." size umod.S(16) color "#8fe0ff"
                            text "En verde: escenas a las que ya llegaste jugando (el tracker guardo su estado real: reconstruccion exacta).":
                                size umod.S(13)
                                color "#7ee0a5"
                            text "En naranja: escenas sin camino estatico desde el origen.":
                                size umod.S(13)
                                color "#d99a6c"
                            text "Nada se modifica hasta que pulses 'Aplicar y saltar', y siempre con copia de seguridad previa.":
                                size umod.S(13)
                                color "#7f8ca1"
                            text umod.esc(umod.rc_backup_text()) size umod.S(13) color "#7f8ca1"


# ##################################################################### #
#   universal_mod_emulator.rpy
# ##################################################################### #

# =====================================================================
#  UNIVERSAL REN'PY MOD (UMOD)  -  FASE 7 / Scene Emulator
# ---------------------------------------------------------------------
#  Requiere: universal_mod.rpy (1), universal_mod_script.rpy (3),
#            universal_mod_graph.rpy (4) y universal_mod_tracker.rpy (5)
#            con sus ganchos instalados.
#  Usa si esta: Fase 6 (copia de seguridad y salto de reconstruccion,
#  al que esta fase anade la reconstruccion visual).
#
#  Dos capacidades:
#
#  A) RECONSTRUCCION VISUAL al saltar (se integra en la Fase 6)
#     Igual que el --warp del propio Ren'Py: busca hacia atras en el
#     camino el ultimo 'scene' y ejecuta solo los scene/show/hide desde
#     ahi, mas la ultima orden de musica. Si la escena empieza con su
#     propio 'scene', no hace nada.
#
#  B) EMULACION REAL DEL RECORRIDO
#     Ejecuta el juego de verdad desde el origen hasta la escena:
#       - copia de seguridad previa (si estas en una partida)
#       - avance rapido forzado (config.skipping = "fast", texto no
#         visto incluido; las preferencias del jugador se restauran)
#       - respuestas automaticas a los menus:
#           1. la decision que exige el camino del grafo
#           2. si el menu no esta en el camino: la opcion cuyo bloque
#              favorece las variables que la escena necesita (o las que
#              elijas: "ruta Alice" = favorecer alice_points), mas la
#              que lleva hacia la escena
#           3. si no hay criterio: primera opcion, o te pregunta a ti
#       - se detiene al entrar en la escena objetivo.
#     Como el codigo del juego se ejecuta de verdad, el estado final es
#     el REAL (y el tracker lo aprende como tal).
#
#  VIGILANTE: si el juego deja de avanzar (minijuego, 'call screen',
#  pausa dura, input), si vuelve al menu principal, si se agota el
#  presupuesto de labels o el tiempo, la emulacion se detiene y ofrece
#  seguir manualmente, terminar ahi o restaurar la copia.
#
#  ABRIR:  ALT + E
# =====================================================================


# ---------------------------------------------------------------------
# 0) Estado de runtime
# ---------------------------------------------------------------------
init -1040 python:
    import sys as _umod_sys_e
    try:
        _umod_e = _umod_sys_e.modules["umod_rt"]
        _umod_e.em = None            # emulacion en curso (o recien terminada)
        _umod_e.em_last = None       # informe de la ultima emulacion
        _umod_e.em_msg = "Selecciona una escena"
        _umod_e.em_cache = {}
        del _umod_e
    except Exception:
        pass


init -939 python:
    if persistent.umod_em_visuals is None:
        persistent.umod_em_visuals = True
    if persistent.umod_em_music is None:
        persistent.umod_em_music = True
    if persistent.umod_em_ask is None:
        persistent.umod_em_ask = False


# ---------------------------------------------------------------------
# 1) Motor
# ---------------------------------------------------------------------
init -940 python in umod:

    import ast as pyast

    EMULATOR = True

    EM_KEYS         = ["alt_K_e"]
    EM_STALL_S      = 12.0       # segundos sin ninguna interaccion nueva
    EM_TIMEOUT_S    = 900.0
    EM_BUDGET_MIN   = 300        # labels maximos (minimo)
    EM_BUDGET_STEP  = 30         # labels por paso del camino
    EM_INTER_MAX    = 60000      # interacciones maximas
    EM_PAUSE_GRACE  = 1.5        # margen antes de interpretar una pausa del jugador

    try:
        _EM_NODEC = NO_DECISION
    except NameError:
        _EM_NODEC = object()

    # ---------- 1.1 Preferencias ------------------------------------
    def _em_pref(name, default):
        try:
            v = getattr(renpy.store.persistent, name, None)
        except Exception:
            v = None
        return default if v is None else bool(v)

    def em_visuals_enabled():
        return _em_pref("umod_em_visuals", True)

    def em_music_enabled():
        return _em_pref("umod_em_music", True)

    def em_ask_enabled():
        return _em_pref("umod_em_ask", False)

    def em_toggle(name, default):
        try:
            setattr(renpy.store.persistent, name, not _em_pref(name, default))
        except Exception as e:
            log_error("em_toggle", e)

    # ---------- 1.2 Acceso al AST -----------------------------------
    def _em_lookup(name):
        try:
            return renpy.game.script.lookup(name)
        except Exception:
            return None

    def _em_children(n):
        """Bloques hijos de un nodo (ramas de if, opciones de menu...)."""
        out = []
        try:
            if _isa(n, C_If):
                for entry in (getattr(n, "entries", None) or []):
                    out.append(entry[1])
            elif _isa(n, C_Menu):
                for it in (getattr(n, "items", None) or []):
                    if len(it) > 2 and it[2]:
                        out.append(it[2])
            else:
                blk = getattr(n, "block", None)
                if isinstance(blk, list):
                    out.append(blk)
        except Exception:
            pass
        return out

    def _em_walk(block, fn, depth=0):
        if not block or depth > 30:
            return
        for n in block:
            fn(n)
            for b in _em_children(n):
                _em_walk(b, fn, depth + 1)

    def _em_body(label):
        node = _em_lookup(label)
        if node is None:
            return []
        try:
            return _ng_body(node)[0] or []
        except Exception:
            return getattr(node, "block", None) or []

    def _user_line(n):
        try:
            return to_text(getattr(n, "line", "") or "").strip()
        except Exception:
            return ""

    # ---------- 1.3 A) Reconstruccion visual ------------------------
    def _starts_with_scene(label):
        for n in _em_body(label):
            if _isa(n, C_Scene):
                return True
            if _isa(n, C_Say) or _isa(n, C_Menu) or _isa(n, C_Jump) or _isa(n, C_Call):
                return False
        return False

    def em_visual_nodes(path, origin, target):
        """(nodos visuales en orden, nodo de musica o None).
        Mismo criterio que renpy/warp.py: desde el ultimo 'scene'."""
        if _starts_with_scene(target):
            return [], None
        labs = [origin] + [RT.g_edges[ei]["b"] for ei in (path or [])]
        collected, music = [], None
        for lb in reversed(labs[:-1]):
            body = _em_body(lb)
            seq = [n for n in body if _isa(n, C_Scene) or _isa(n, C_Show) or _isa(n, C_Hide)]
            if music is None:
                for n in reversed(body):
                    if _isa(n, C_User):
                        ln = _user_line(n)
                        if ln.startswith("play music") or ln.startswith("stop music"):
                            music = n
                            break
            last_scene = None
            for i, n in enumerate(seq):
                if _isa(n, C_Scene):
                    last_scene = i
            if last_scene is not None:
                collected = seq[last_scene:] + collected
                break
            collected = seq + collected
        return collected, music

    def em_replay_for_plan(P):
        """Llamado desde la Fase 6 justo antes de saltar. Ejecutar un nodo
        cambia el 'siguiente statement' del contexto, pero la Fase 6 salta
        inmediatamente despues, asi que eso no tiene efecto."""
        if not em_visuals_enabled() or not P:
            return 0
        try:
            if not (GRAPH and RT.g_ready):
                return 0
        except Exception:
            return 0
        nodes, music = em_visual_nodes(P.get("path"), P.get("origin"), P.get("target"))
        n = 0
        for node in nodes:
            try:
                node.execute()
                n += 1
            except Exception as e:
                log_error("em_visual", e)
        if music is not None and em_music_enabled():
            try:
                music.execute()
            except Exception as e:
                log_error("em_music", e)
        return n

    # ---------- 1.4 Efectos de un bloque (para puntuar opciones) ----
    def _block_effects(block):
        """var -> ('d', delta) | ('s', valor literal). Recorre ramas."""
        eff = {}

        def visit(n):
            if not _isa(n, C_Python):
                return
            try:
                src = _py_source(n)
                tree = pyast.parse(to_text(src).strip())
            except Exception:
                return
            for st in pyast.walk(tree):
                try:
                    if isinstance(st, pyast.AugAssign):
                        nm = _base_name(st.target)
                        v = _const(st.value)
                        if nm and _isnum(v) and not isinstance(v, bool):
                            sign = -1 if isinstance(st.op, pyast.Sub) else 1
                            if isinstance(st.op, (pyast.Add, pyast.Sub)):
                                old = eff.get(nm, ("d", 0))
                                base = old[1] if old[0] == "d" else 0
                                eff[nm] = ("d", base + sign * v)
                    elif isinstance(st, pyast.Assign) and len(st.targets) == 1:
                        nm = _base_name(st.targets[0])
                        v = _const(st.value)
                        if nm and v is not _NOVAL:
                            eff[nm] = ("s", v)
                except Exception:
                    continue

        _em_walk(block, visit)
        return eff

    def _em_menu_node():
        try:
            cur = renpy.game.context().current
        except Exception:
            return None
        n = _em_lookup(cur)
        return n if _isa(n, C_Menu) else None

    def em_score(E, block):
        """Cuanto acerca una opcion a lo que necesita la escena."""
        score = 0.0
        why = []
        eff = _block_effects(block) if block else {}
        for v, kind, arg in E["favor"]:
            e = eff.get(v)
            if not e:
                continue
            if kind == "max" and e[0] == "d":
                score += e[1]
                why.append("%s %+g" % (v, e[1]))
            elif kind == "min" and e[0] == "d":
                score -= e[1]
                why.append("%s %+g" % (v, e[1]))
            elif kind in ("true", "false") and e[0] == "s":
                good = bool(e[1]) == (kind == "true")
                score += 3 if good else -3
                why.append("%s = %s" % (v, e[1]))
            elif kind == "eq" and e[0] == "s":
                good = to_text(e[1]) == to_text(arg)
                score += 3 if good else -1
                why.append("%s = %s" % (v, e[1]))
        jt = _first_jump_target(block) if block else ""
        if jt:
            try:
                if jt == E["target"] or ng_path(jt, E["target"], "short") is not None:
                    score += 2
                    why.append("lleva hacia la escena")
                elif jt in RT.g_nodes:
                    score -= 1
            except Exception:
                pass
        return score, why

    # ---------- 1.5 Plan de emulacion (vista previa) ----------------
    def em_ready():
        try:
            if not TRACKER:
                return (False, "Falta el State Tracker (universal_mod_tracker.rpy).")
        except Exception:
            return (False, "Falta el State Tracker.")
        if not RT.tr_label_mode.startswith("config.label_callback"):
            return (False, "El gancho de labels del tracker no esta instalado (%s)." % RT.tr_label_mode)
        if not RT.tr_menu_hooked:
            return (False, "El gancho de menus no esta instalado: activa 'Registrar menus' en el tracker y reinicia el juego.")
        if not tr_enabled():
            return (False, "La grabacion del tracker esta desactivada.")
        try:
            if not (GRAPH and RT.g_ready):
                return (False, "El grafo (Fase 4) no esta construido.")
        except Exception:
            return (False, "Falta el grafo (Fase 4).")
        return (True, "")

    def em_candidate_vars():
        """Variables que el guion incrementa: candidatas a 'ruta'."""
        cnt = {}
        try:
            for rec in RT.sa_labels.values():
                for d in rec.get("deltas", []):
                    if d and d[1] in ("+=", "-="):
                        cnt[d[0]] = cnt.get(d[0], 0) + 1
        except Exception:
            pass
        return [v for v, _n in sorted(cnt.items(), key=lambda t: (-t[1], t[0]))][:14]

    def em_risks(labels):
        """Busca en los labels del camino cosas que el avance rapido no
        puede atravesar solo."""
        out = []
        pat = ("renpy.input(", "renpy.call_screen(", "ui.interact(", "renpy.pause(hard",
               "renpy.full_restart(", "renpy.quit(")
        for lb in labels:
            hits = []

            def visit(n):
                if _isa(n, C_User):
                    ln = _user_line(n)
                    if ln.startswith("call screen"):
                        hits.append(ln[:60])
                elif _isa(n, C_Python):
                    src = to_text(_py_source(n))
                    for p in pat:
                        if p in src:
                            hits.append(p.rstrip("("))

            _em_walk(_em_body(lb), visit)
            for h in hits[:3]:
                out.append("%s: %s" % (lb, h))
        return out

    def em_plan(target, origin=None, mode="guards", extra_favor=(), route=None):
        key = (target, origin, mode, tuple(extra_favor), route, len(RT.g_edges))
        hit = RT.em_cache.get(key)
        if hit is not None:
            return hit
        E = {"target": target, "origin": origin or RT.g_origin, "mode": mode,
             "path": None, "labels": [], "decisions": [], "favor": [],
             "risks": [], "unplanned_hint": 0}
        E["path"] = ng_path(E["origin"], target, mode)
        if E["path"] is not None:
            E["labels"] = [E["origin"]] + [RT.g_edges[ei]["b"] for ei in E["path"]]
            for ei in E["path"]:
                e = RT.g_edges[ei]
                for d in e.get("d", []):
                    E["decisions"].append((e["a"], d.get("cap", "")))
            reqs = ng_requirements(E["path"])[0]
            seen = set()
            for c in reqs:
                v, op = c["v"], c["op"]
                if v in seen or v.startswith("persistent."):
                    continue
                seen.add(v)
                if op in (">", ">="):
                    E["favor"].append((v, "max", None))
                elif op in ("<", "<="):
                    E["favor"].append((v, "min", None))
                elif op == "es cierto":
                    E["favor"].append((v, "true" if c["val"] == "True" else "false", None))
                elif op == "==":
                    E["favor"].append((v, "eq", c["val"]))
            E["risks"] = em_risks(E["labels"])
        # Ruta del adaptador (Fase 9): variables a favorecer y decisiones
        E["route"], E["route_dec"] = None, {}
        if route:
            try:
                if ADAPTERS:
                    r = ad_route(route)
                    E["route"] = route
                    E["route_name"] = to_text(r.get("name") or route)
                    E["route_dec"] = dict(r.get("decisions") or {})
                    for v in (r.get("favor") or []):
                        if not any(f[0] == v for f in E["favor"]):
                            E["favor"].append((v, "max", None))
            except Exception as e:
                log_error("em_plan.route", e)
        for v in extra_favor:
            if not any(f[0] == v for f in E["favor"]):
                E["favor"].append((v, "max", None))
        RT.em_cache[key] = E
        return E

    # ---------- 1.6 Preferencias del jugador: guardar y restaurar ---
    def _em_save_prefs():
        pr = renpy.game.preferences
        d = {
            "skip_unseen": getattr(pr, "skip_unseen", False),
            "_skipping": getattr(renpy.store, "_skipping", True),
            "allow_skipping": getattr(renpy.config, "allow_skipping", True),
        }
        # Si el juego se cierra a mitad, al proximo arranque se restaura.
        try:
            renpy.store.persistent.umod_em_restore = {"skip_unseen": d["skip_unseen"]}
        except Exception:
            pass
        return d

    def _em_skip_on(E):
        try:
            renpy.game.preferences.skip_unseen = True
        except Exception:
            pass
        try:
            renpy.store._skipping = True
        except Exception:
            pass
        try:
            renpy.config.allow_skipping = True
        except Exception:
            pass
        renpy.config.skipping = "fast"
        E["assert_t"] = time.time()

    def _em_restore_prefs(E):
        d = E.get("prefs") or {}
        try:
            renpy.config.skipping = None
        except Exception:
            pass
        try:
            if "skip_unseen" in d:
                renpy.game.preferences.skip_unseen = d["skip_unseen"]
        except Exception:
            pass
        try:
            if "_skipping" in d:
                renpy.store._skipping = d["_skipping"]
        except Exception:
            pass
        try:
            if "allow_skipping" in d:
                renpy.config.allow_skipping = d["allow_skipping"]
        except Exception:
            pass
        try:
            renpy.store.persistent.umod_em_restore = None
        except Exception:
            pass

    def em_crash_recovery():
        """Al arrancar: si una emulacion quedo a medias, deshace sus cambios
        en las preferencias del jugador."""
        try:
            r = getattr(renpy.store.persistent, "umod_em_restore", None)
            if r:
                if "skip_unseen" in r:
                    renpy.game.preferences.skip_unseen = r["skip_unseen"]
                renpy.store.persistent.umod_em_restore = None
        except Exception as e:
            log_error("em_crash_recovery", e)

    # ---------- 1.7 Ciclo de la emulacion ---------------------------
    def _em_log(E, kind, text):
        E["log"].append((kind, text))
        if len(E["log"]) > 400:
            del E["log"][:100]

    def _em_backup(target):
        try:
            if RECONSTRUCT:
                RT.rc_last = {"target": target}
                return rc_backup()
        except Exception:
            pass
        try:
            renpy.save("_umod_backup", "UMOD: copia antes de emular hasta %s" % target)
            return True
        except Exception as e:
            log_error("em_backup", e)
            return False

    def _em_in_main_menu():
        try:
            return bool(getattr(renpy.store, "main_menu", False))
        except Exception:
            return False

    def em_start(E, policy_ask=None):
        ok, why = em_ready()
        if not ok:
            RT.em_msg = why
            renpy.restart_interaction()
            return
        if E is None or E.get("path") is None:
            RT.em_msg = "No hay camino estatico hasta la escena: no se puede emular."
            renpy.restart_interaction()
            return
        in_menu = _em_in_main_menu()
        if not in_menu and not _em_backup(E["target"]):
            RT.em_msg = "No se pudo crear la copia de seguridad: NO se ha emulado nada."
            renpy.restart_interaction()
            return
        ask = em_ask_enabled() if policy_ask is None else bool(policy_ask)
        R = {
            "target": E["target"], "origin": E["origin"], "path": E["path"],
            "decisions": list(E["decisions"]), "consumed": set(),
            "route_dec": dict(E.get("route_dec") or {}),
            "favor": list(E["favor"]), "ask": ask,
            "t0": time.time(), "progress_t": time.time(), "assert_t": time.time(),
            "labels": 0, "inter": 0, "picks": 0, "planned": 0,
            "budget": max(EM_BUDGET_MIN, len(E["path"]) * EM_BUDGET_STEP),
            "cur": "", "visited": [], "log": [], "status": "corriendo",
            "reason": "", "prefs": _em_save_prefs(), "backup": not in_menu,
        }
        _em_log(R, "h", "Inicio: %s -> %s (%d pasos, %d decisiones previstas)" % (
            R["origin"], R["target"], len(R["path"]), len(R["decisions"])))
        RT.em = R
        RT.em_msg = "Emulando hacia '%s'..." % R["target"]
        _em_skip_on(R)
        for s in UMOD_SCREENS:
            try:
                renpy.hide_screen(s)
            except Exception:
                pass
        nested = 0
        try:
            nested = renpy.context_nesting_level()
        except Exception:
            nested = 0
        if in_menu or nested > 0:
            renpy.jump_out_of_context(R["origin"])
        else:
            renpy.jump(R["origin"])

    def em_finish(reason, ok=False):
        R = RT.em
        if not R or R["status"] in ("completada", "abortada"):
            return
        R["status"] = "completada" if ok else "abortada"
        R["reason"] = reason
        R["t_end"] = time.time()
        _em_restore_prefs(R)
        _em_log(R, "ok" if ok else "warn", reason)
        RT.em_last = R
        RT.em_msg = reason
        try:
            renpy.notify("UMOD: " + reason)
        except Exception:
            pass

    def em_pause(reason):
        R = RT.em
        if not R or R["status"] != "corriendo":
            return
        R["status"] = "detenida"
        R["reason"] = reason
        try:
            renpy.config.skipping = None
        except Exception:
            pass
        _em_log(R, "warn", reason)

    def em_resume():
        R = RT.em
        if not R or R["status"] not in ("detenida", "pregunta"):
            return
        R["status"] = "corriendo"
        R["reason"] = ""
        R["progress_t"] = time.time()
        _em_skip_on(R)
        _em_log(R, "note", "Reanudada")
        renpy.restart_interaction()

    def em_stop_here():
        em_finish("Detenida por el jugador en '%s'" % ((RT.em or {}).get("cur") or "?"), ok=False)
        renpy.restart_interaction()

    def em_close():
        R = RT.em
        if R and R["status"] in ("corriendo", "detenida", "pregunta"):
            em_finish("Cancelada por el jugador", ok=False)
        RT.em = None
        renpy.restart_interaction()

    def em_restore_backup():
        R = RT.em
        if R and R["status"] in ("corriendo", "detenida", "pregunta"):
            em_finish("Cancelada: se restaura la copia", ok=False)
        RT.em = None
        try:
            if RECONSTRUCT:
                rc_restore()
            elif renpy.can_load("_umod_backup"):
                renpy.load("_umod_backup")
        except Exception as e:
            if type(e).__name__ not in ("RestartContext", "RestartTopContext", "FullRestartException"):
                log_error("em_restore_backup", e)
            raise

    # ---------- 1.8 Ganchos -----------------------------------------
    def em_on_label(name, abnormal=False):
        R = RT.em
        if not R or R["status"] not in ("corriendo", "pregunta"):
            return
        if not isinstance(name, string_types) or name.startswith("_"):
            return
        R["labels"] += 1
        R["cur"] = name
        R["progress_t"] = time.time()
        R["visited"].append(name)
        if len(R["visited"]) > 400:
            del R["visited"][:100]
        if name == R["target"]:
            em_finish("Llegaste a '%s' en %.1f s (%d labels, %d decisiones automaticas)" % (
                name, time.time() - R["t0"], R["labels"], R["picks"]), ok=True)
            return
        if R["labels"] > R["budget"]:
            em_finish("Abortada: %d labels sin llegar a la escena (posible bucle o rama equivocada)" % R["labels"])
            return
        if time.time() - R["t0"] > EM_TIMEOUT_S:
            em_finish("Abortada: tiempo maximo agotado")
            return
        if R["status"] == "pregunta":
            R["status"] = "corriendo"
        if R["status"] == "corriendo":
            _em_skip_on(R)

    def em_tick():
        """interact_callbacks: cada interaccion nueva es progreso."""
        R = RT.em
        if not R or R["status"] != "corriendo":
            return
        R["inter"] += 1
        R["progress_t"] = time.time()
        if R["inter"] > EM_INTER_MAX:
            em_finish("Abortada: demasiadas interacciones sin llegar a la escena")

    def em_periodic():
        R = RT.em
        if not R or R["status"] != "corriendo":
            return
        now = time.time()
        if _em_in_main_menu():
            em_finish("Abortada: el juego volvio al menu principal")
        elif now - R["progress_t"] > EM_STALL_S:
            em_pause("El juego lleva %d s sin avanzar en '%s': probablemente espera una accion tuya (minijuego, pantalla interactiva o pausa)." % (
                int(now - R["progress_t"]), R["cur"] or "?"))
        elif now - R["t0"] > EM_TIMEOUT_S:
            em_finish("Abortada: tiempo maximo agotado")
        else:
            try:
                if renpy.config.skipping is None and now - R["assert_t"] > EM_PAUSE_GRACE:
                    em_pause("Avance rapido interrumpido (pulsaste una tecla o el juego lo detuvo).")
            except Exception:
                pass

    def em_decide(items, args, kwargs):
        """MENU_DECIDER: devuelve el valor de la opcion elegida o NO_DECISION."""
        R = RT.em
        if not R or R["status"] != "corriendo":
            return _EM_NODEC
        try:
            if renpy.in_rollback():
                return _EM_NODEC
        except Exception:
            pass

        set_expr = args[0] if args else kwargs.get("set_expr")
        chosen = None
        if set_expr:
            try:
                chosen = renpy.python.py_eval(set_expr)
            except Exception:
                chosen = None

        opts = []
        for it in (items or []):
            try:
                cap, val = it[0], it[-1]
                cond = it[1] if len(it) >= 3 else "True"
            except Exception:
                continue
            if val is None:
                continue
            if chosen is not None:
                try:
                    if cap in chosen:
                        continue
                except Exception:
                    pass
            try:
                if isinstance(cond, string_types):
                    ok = bool(renpy.python.py_eval(cond))
                else:
                    ok = bool(cond)
            except Exception:
                ok = False
            if ok:
                opts.append((to_text(cap), val, cap))
        if not opts:
            return _EM_NODEC

        cur = RT.tr_cur
        pick, why = None, ""

        # 1) decision prevista por el camino
        for i, (lb, cap) in enumerate(R["decisions"]):
            if i in R["consumed"] or lb != cur:
                continue
            for o in opts:
                if o[0].strip() == to_text(cap).strip():
                    pick, why = o, "decision del camino"
                    R["consumed"].add(i)
                    R["planned"] += 1
                    break
            if pick:
                break

        # 1b) decision que indica la ruta del adaptador para este label
        if pick is None and R.get("route_dec"):
            want = R["route_dec"].get(cur)
            wants = want if isinstance(want, list) else ([want] if want else [])
            for w in wants:
                for o in opts:
                    if o[0].strip() == to_text(w).strip():
                        pick, why = o, "ruta del adaptador"
                        break
                if pick:
                    break

        # 2) opcion que mas favorece lo que necesita la escena
        if pick is None:
            node = _em_menu_node()
            best, best_s, best_w = None, 0.0, []
            for o in opts:
                block = None
                try:
                    if node is not None and isinstance(o[1], _INT_TYPES):
                        block = node.items[o[1]][2]
                except Exception:
                    block = None
                s, w = em_score(R, block)
                if s > best_s:
                    best, best_s, best_w = o, s, w
            if best is not None:
                pick, why = best, "favorece: " + ", ".join(best_w)

        # 3) sin criterio
        if pick is None:
            if R["ask"]:
                R["status"] = "pregunta"
                try:
                    renpy.config.skipping = None
                except Exception:
                    pass
                _em_log(R, "q", "%s: sin criterio, eliges tu" % (cur or "?"))
                return _EM_NODEC
            pick, why = opts[0], "primera opcion (sin criterio)"

        if chosen is not None:
            try:
                if isinstance(chosen, set):
                    chosen.add(pick[2])
                else:
                    chosen.append(pick[2])
            except Exception:
                pass
        R["picks"] += 1
        _em_log(R, "dec", "%s:  \"%s\"   [%s]" % (cur or "?", pick[0][:70], why))
        return pick[1]

    # ---------- 1.9 Vistas ------------------------------------------
    EM_COLOR = {
        "h": "#8fe0ff", "ev": "#dfe7f2", "dec": "#b9a6ff", "ok": "#7ee0a5",
        "warn": "#ff9b8a", "note": "#7f8ca1", "q": "#e7c58a", "fav": "#9fe0b0",
    }

    def em_color(k):
        return EM_COLOR.get(k, "#dfe7f2")

    def em_size(k):
        return S(15) if k == "h" else S(13)

    def em_indent(k):
        return S(22) if k in ("dec",) else 0

    def _favor_text(f):
        v, kind, arg = f
        return {"max": "maximizar %s" % v, "min": "minimizar %s" % v,
                "true": "%s verdadero" % v, "false": "%s falso" % v,
                "eq": "%s == %s" % (v, arg)}.get(kind, v)

    def em_plan_rows(E):
        rows = []
        ok, why = em_ready()
        if not ok:
            rows.append(("warn", "No se puede emular: " + why))
        if E["path"] is None:
            rows.append(("warn", "No hay camino estatico desde '%s'. La emulacion necesita un camino." % E["origin"]))
            return rows
        rows.append(("h", "RECORRIDO"))
        rows.append(("ev", "%d paso(s) desde '%s' hasta '%s'" % (len(E["path"]), E["origin"], E["target"])))
        rows.append(("note", " -> ".join(E["labels"][:14]) + (" ..." if len(E["labels"]) > 14 else "")))
        rows.append(("h", "DECISIONES PREVISTAS  (%d)" % len(E["decisions"])))
        if not E["decisions"]:
            rows.append(("note", "El camino no pasa por ningun menu."))
        for lb, cap in E["decisions"][:20]:
            rows.append(("dec", "%s:  \"%s\"" % (lb, cap)))
        if E.get("route"):
            rows.append(("h", "RUTA DEL ADAPTADOR: %s" % E.get("route_name", E["route"])))
            for lb in sorted(E["route_dec"].keys())[:12]:
                rows.append(("dec", "%s:  \"%s\"" % (lb, E["route_dec"][lb])))
        rows.append(("h", "EN MENUS FUERA DEL CAMINO SE ELEGIRA"))
        if E["favor"]:
            for f in E["favor"]:
                rows.append(("fav", "la opcion que tienda a: " + _favor_text(f)))
        rows.append(("fav", "la opcion que lleve hacia la escena"))
        rows.append(("note", "si nada decide: %s" % ("te pregunta a ti" if em_ask_enabled() else "la primera opcion disponible")))
        if E["risks"]:
            rows.append(("h", "PUNTOS DONDE PUEDE DETENERSE  (%d)" % len(E["risks"])))
            for r in E["risks"][:12]:
                rows.append(("q", r))
            rows.append(("note", "Ahi el vigilante pausara la emulacion: resuelves tu esa parte y pulsas 'Seguir'."))
        rows.append(("h", "SEGURIDAD"))
        if _em_in_main_menu():
            rows.append(("note", "Desde el menu principal se empieza una partida nueva y limpia: es la forma mas fiel de emular."))
        else:
            rows.append(("ok", "Se guardara una copia de tu partida en '_umod_backup' antes de empezar."))
            rows.append(("q", "Se emula desde '%s' con el estado de TU partida actual. Para un recorrido limpio, lanzalo desde el menu principal." % E["origin"]))
        rows.append(("note", "El avance rapido incluye texto no visto; tus preferencias se restauran al terminar (o al reiniciar si el juego se cierra a mitad)."))
        return rows

    def em_report_rows(R):
        if not R:
            return [("note", "Todavia no hay ninguna emulacion.")]
        rows = [("h", "ULTIMA EMULACION:  %s" % R["status"].upper()),
                ("ok" if R["status"] == "completada" else "warn", R.get("reason") or ""),
                ("note", "%d labels, %d interacciones, %d decisiones automaticas (%d previstas)" % (
                    R["labels"], R["inter"], R["picks"], R["planned"]))]
        for kind, txt in R["log"][-120:]:
            rows.append((kind, txt))
        return rows

    def em_status_line():
        R = RT.em
        if not R:
            return ""
        el = (R.get("t_end") or time.time()) - R["t0"]
        return "%s  -  hacia '%s'  -  ahora en '%s'  -  %d labels, %d decisiones  -  %.0f s" % (
            R["status"].upper(), R["target"], R["cur"] or "?", R["labels"], R["picks"], el)

    def em_status_color():
        R = RT.em or {}
        return {"corriendo": "#8fe0ff", "pregunta": "#e7c58a", "detenida": "#ff9b8a",
                "completada": "#7ee0a5", "abortada": "#ff9b8a"}.get(R.get("status"), "#dfe7f2")

    def em_label_list(q):
        s = to_text(q or "").strip().lower()
        try:
            names = [lb for _g, labs in RT.g_groups for lb in labs]
        except Exception:
            names = []
        if s:
            names = [n for n in names if s in n.lower()]
        return names

    def em_label_text(n):
        try:
            if ADAPTERS:
                return n + ad_label_suffix(n)
        except Exception:
            pass
        return n

    def em_label_color(n):
        try:
            if n not in RT.g_reach:
                return "#5e6676"
        except Exception:
            pass
        return "#c3ccda"

    # ---------- 1.10 Apertura ---------------------------------------
    EM_SCREEN = "umod_emulator"

    def emulator_open():
        try:
            if not RT.ready:
                scan_all()
            try:
                if SCRIPT:
                    sa_ensure()            # cache o segundo plano: no bloquea
                if GRAPH:
                    ng_ensure()
                if TRACKER:
                    tr_load()
            except Exception as e:
                log_error("em_open.deps", e)
            RT.em_cache = {}
            renpy.hide_screen(SCREEN)
            renpy.show_screen(EM_SCREEN)
            renpy.restart_interaction()
        except Exception as e:
            log_error("emulator_open", e)

    def emulator_toggle():
        try:
            if renpy.get_screen(EM_SCREEN):
                renpy.hide_screen(EM_SCREEN)
                renpy.restart_interaction()
            else:
                emulator_open()
        except Exception as e:
            log_error("emulator_toggle", e)


# ---------------------------------------------------------------------
# 2) Registro: tecla, overlay de estado, vigilante y ganchos
# ---------------------------------------------------------------------
init -938 python:
    umod.register_key("umod_emulator", umod.adv_keys(umod.EM_KEYS), umod.emulator_toggle)
    umod.add_overlay_screen("umod_em_overlay")
    umod.add_callback("interact_callbacks", None, umod.em_tick, "emulador.progreso")
    umod.add_callback("periodic_callbacks", "periodic_callback", umod.em_periodic, "emulador.vigilante")
    try:
        umod.LABEL_HOOKS.append(umod.em_on_label)
        umod.MENU_DECIDERS.append(umod.em_decide)
    except Exception as e:
        umod.log_error("em.hooks", e)


init 1001 python:
    umod.em_crash_recovery()


# =====================================================================
# 3) INTERFAZ
# =====================================================================

# Barra de estado durante la emulacion. Es un overlay: aparece en cada
# interaccion, incluso tras saltar de contexto.
screen umod_em_overlay():
    zorder 1200
    if umod.RT.em is not None:
        frame:
            background Solid("#0b0e14ee")
            xalign 0.5
            yalign 0.0
            yoffset umod.S(8)
            xsize umod.S(1300)
            padding (umod.S(14), umod.S(8))
            vbox:
                spacing umod.S(6)
                text umod.esc(umod.em_status_line()) size umod.S(15) color umod.em_status_color()
                if umod.RT.em["reason"]:
                    text umod.esc(umod.RT.em["reason"]) size umod.S(13) color "#c3ccda"
                if umod.RT.em["status"] == "pregunta":
                    text "Este menu no esta en el camino: elige tu. La emulacion seguira en el siguiente label." size umod.S(13) color "#e7c58a"
                hbox:
                    spacing umod.S(8)
                    if umod.RT.em["status"] in ("detenida", "pregunta"):
                        textbutton "Seguir":
                            action Function(umod.em_resume)
                            text_size umod.S(14)
                            background Solid("#1d3428")
                            hover_background Solid("#2b4d3a")
                            padding (umod.S(12), umod.S(5))
                        textbutton "Terminar aqui":
                            action Function(umod.em_stop_here)
                            text_size umod.S(14)
                            background Solid("#232a36")
                            padding (umod.S(12), umod.S(5))
                    if umod.RT.em["status"] == "corriendo":
                        textbutton "Pausar":
                            action Function(umod.em_pause, "Pausada por el jugador")
                            text_size umod.S(14)
                            background Solid("#232a36")
                            padding (umod.S(12), umod.S(5))
                    if umod.RT.em["backup"] and umod.RT.em["status"] != "completada":
                        textbutton "Restaurar copia":
                            action Confirm("Se cargara la copia de seguridad hecha antes de emular. Continuar?", Function(umod.em_restore_backup))
                            text_size umod.S(14)
                            text_color "#ffd9d9"
                            background Solid("#43222a")
                            hover_background Solid("#6a3340")
                            padding (umod.S(12), umod.S(5))
                    if umod.RT.em["status"] in ("completada", "abortada"):
                        textbutton "Cerrar":
                            action Function(umod.em_close)
                            text_size umod.S(14)
                            background Solid("#232a36")
                            padding (umod.S(12), umod.S(5))


screen umod_emulator():

    modal True
    zorder 1100
    tag umod_panel

    default q = ""
    default page = 0
    default sel = None
    default mode = "guards"
    default extra = []
    default route = None

    key "K_ESCAPE" action Hide("umod_emulator")
    key "umod_emulator" action Hide("umod_emulator")

    $ names = umod.guard(umod.em_label_list, [], q)
    $ shown = umod.page_slice(names, page)
    $ npages = umod.page_count(names)
    $ E = umod.guard(umod.em_plan, None, sel, None, mode, tuple(extra), route) if sel else None
    $ routes = umod.ad_routes() if umod.ADAPTERS else []
    $ cands = umod.guard(umod.em_candidate_vars, [])
    $ qval = ScreenVariableInputValue("q", default=False) if umod.HAS_SVIV else None

    add Solid("#000000dd")

    frame:
        background Solid("#0f1117f5")
        xalign 0.5
        yalign 0.5
        xsize umod.S(1480)
        ysize umod.S(880)
        padding (umod.S(18), umod.S(14))

        vbox:
            spacing umod.S(9)

            fixed:
                xfill True
                ysize umod.S(38)
                hbox:
                    xalign 0.0
                    yalign 0.5
                    spacing umod.S(16)
                    text "EMULADOR DE RECORRIDO" size umod.S(22) color "#7fd4ff"
                    text umod.esc(umod.RT.em_msg) size umod.S(13) color "#78839a" yalign 0.5
                hbox:
                    xalign 1.0
                    yalign 0.5
                    spacing umod.S(6)
                    textbutton "Panel":
                        action [Hide("umod_emulator"), Function(umod.open_panel)]
                        text_size umod.S(14)
                        background Solid("#232a36")
                        padding (umod.S(12), umod.S(6))
                    textbutton "Cerrar  (Esc)":
                        action Hide("umod_emulator")
                        text_size umod.S(14)
                        text_color "#ffd9d9"
                        background Solid("#43222a")
                        hover_background Solid("#6a3340")
                        padding (umod.S(12), umod.S(6))

            fixed:
                xfill True
                ysize umod.S(36)
                hbox:
                    yalign 0.5
                    spacing umod.S(8)
                    if qval:
                        button:
                            action qval.Toggle()
                            background Solid("#0c0f14")
                            hover_background Solid("#161c26")
                            xsize umod.S(260)
                            ysize umod.S(32)
                            padding (umod.S(9), umod.S(5))
                            input:
                                value qval
                                length 40
                                size umod.S(15)
                                color "#e8eef7"
                    textbutton "<":
                        action SetScreenVariable("page", max(0, page - 1))
                        text_size umod.S(14)
                        background Solid("#232a36")
                        padding (umod.S(12), umod.S(6))
                    textbutton ">":
                        action SetScreenVariable("page", min(npages - 1, page + 1))
                        text_size umod.S(14)
                        background Solid("#232a36")
                        padding (umod.S(12), umod.S(6))
                    text "  Camino:" size umod.S(14) color "#98a3b5" yalign 0.5
                    for mid, mlabel in (("guards", "menos condiciones"), ("short", "menos pasos")):
                        textbutton mlabel:
                            action SetScreenVariable("mode", mid)
                            text_size umod.S(13)
                            text_color ("#ffffff" if mode == mid else "#98a3b5")
                            background (Solid("#2b3446") if mode == mid else Solid("#191d26"))
                            padding (umod.S(9), umod.S(6))
                    textbutton ("Sin criterio: preguntarme" if umod.em_ask_enabled() else "Sin criterio: primera opcion"):
                        action Function(umod.em_toggle, "umod_em_ask", False)
                        text_size umod.S(13)
                        background Solid("#191d26")
                        padding (umod.S(9), umod.S(6))
                    textbutton ("Visuales al saltar: SI" if umod.em_visuals_enabled() else "Visuales al saltar: NO"):
                        action Function(umod.em_toggle, "umod_em_visuals", True)
                        text_size umod.S(13)
                        background Solid("#191d26")
                        padding (umod.S(9), umod.S(6))
                    textbutton ("Musica: SI" if umod.em_music_enabled() else "Musica: NO"):
                        action Function(umod.em_toggle, "umod_em_music", True)
                        text_size umod.S(13)
                        background Solid("#191d26")
                        padding (umod.S(9), umod.S(6))

            hbox:
                spacing umod.S(12)

                frame:
                    background Solid("#0c0f14")
                    xsize umod.S(400)
                    ysize umod.S(722)
                    padding (umod.S(8), umod.S(8))
                    viewport:
                        xsize umod.S(384)
                        ysize umod.S(706)
                        scrollbars "vertical"
                        mousewheel True
                        draggable True
                        vbox:
                            spacing umod.S(1)
                            for n in shown:
                                textbutton umod.esc(umod.em_label_text(n)):
                                    action SetScreenVariable("sel", n)
                                    text_size umod.S(13)
                                    text_color ("#ffffff" if sel == n else umod.em_label_color(n))
                                    background (Solid("#26324a") if sel == n else None)
                                    hover_background Solid("#1b2431")
                                    padding (umod.S(6), umod.S(2))
                                    xfill True

                frame:
                    background Solid("#121722")
                    xsize umod.S(1032)
                    ysize umod.S(722)
                    padding (umod.S(12), umod.S(10))
                    vbox:
                        spacing umod.S(8)
                        if E:
                            text umod.esc(E["target"]) size umod.S(19) color "#8fe0ff"
                            hbox:
                                spacing umod.S(8)
                                textbutton "Emular hasta aqui":
                                    action Confirm("Se ejecutara el juego en avance rapido desde el origen hasta esta escena, respondiendo a los menus automaticamente. Continuar?", Function(umod.em_start, E))
                                    text_size umod.S(15)
                                    background Solid("#1d3428")
                                    hover_background Solid("#2b4d3a")
                                    padding (umod.S(14), umod.S(7))
                            if routes:
                                hbox:
                                    spacing umod.S(6)
                                    box_wrap True
                                    text "Ruta del adaptador:" size umod.S(13) color "#98a3b5" yalign 0.5
                                    textbutton "ninguna":
                                        action SetScreenVariable("route", None)
                                        text_size umod.S(12)
                                        text_color ("#ffffff" if route is None else "#98a3b5")
                                        background (Solid("#2b3446") if route is None else Solid("#191d26"))
                                        padding (umod.S(8), umod.S(4))
                                    for rid, rname in routes:
                                        textbutton umod.esc(rname):
                                            action SetScreenVariable("route", rid)
                                            text_size umod.S(12)
                                            text_color ("#9fe0b0" if route == rid else "#98a3b5")
                                            background (Solid("#1d3428") if route == rid else Solid("#191d26"))
                                            padding (umod.S(8), umod.S(4))
                            if cands:
                                hbox:
                                    spacing umod.S(6)
                                    box_wrap True
                                    text "Ruta: favorecer" size umod.S(13) color "#98a3b5" yalign 0.5
                                    for v in cands:
                                        textbutton umod.esc(v):
                                            action If(v in extra, SetScreenVariable("extra", [x for x in extra if x != v]), SetScreenVariable("extra", extra + [v]))
                                            text_size umod.S(12)
                                            text_color ("#9fe0b0" if v in extra else "#98a3b5")
                                            background (Solid("#1d3428") if v in extra else Solid("#191d26"))
                                            padding (umod.S(8), umod.S(4))
                            viewport:
                                xsize umod.S(1008)
                                ysize umod.S(330)
                                scrollbars "vertical"
                                mousewheel True
                                draggable True
                                vbox:
                                    spacing umod.S(3)
                                    for r in umod.guard(umod.em_plan_rows, umod.ERR_ROWS, E):
                                        if r[0] == "h":
                                            null height umod.S(5)
                                        text umod.esc(r[1]):
                                            size umod.em_size(r[0])
                                            color umod.em_color(r[0])
                                            xoffset umod.em_indent(r[0])
                                            xsize umod.S(970)
                        else:
                            text "Elige la escena hasta la que quieres llegar recorriendo el juego de verdad." size umod.S(15) color "#8fe0ff"
                            text "En gris: escenas sin camino estatico desde el origen (no se pueden emular)." size umod.S(13) color "#7f8ca1"
                        null height umod.S(4)
                        viewport:
                            xsize umod.S(1008)
                            ysize (umod.S(200) if E else umod.S(560))
                            scrollbars "vertical"
                            mousewheel True
                            draggable True
                            vbox:
                                spacing umod.S(2)
                                for r in umod.guard(umod.em_report_rows, umod.ERR_ROWS, umod.RT.em_last):
                                    text umod.esc(r[1]):
                                        size umod.em_size(r[0])
                                        color umod.em_color(r[0])
                                        xoffset umod.em_indent(r[0])
                                        xsize umod.S(970)


# ##################################################################### #
#   universal_mod_adapters.rpy
# ##################################################################### #

# =====================================================================
#  UNIVERSAL REN'PY MOD (UMOD)  -  FASE 9 / Adaptadores
# ---------------------------------------------------------------------
#  Requiere universal_mod.rpy (Fase 1). Se integra con todas las demas.
#
#  Un ADAPTADOR es un perfil opcional para un juego concreto: lo que el
#  sistema generico no puede deducir solo.
#
#  DONDE SE BUSCAN
#    - game/umod_adapter*.json     (tambien dentro de .rpa)
#    - <carpeta de saves>/umod_adapter*.json
#    - archivos .rpy que llamen a umod.register_adapter({...})
#      (solo estos pueden incluir codigo: la clave "setup")
#
#  FORMATO (todas las secciones son opcionales)
#  {
#    "format": 1,
#    "name": "Mi juego - perfil",  "author": "...",
#    "match":  {"name": "MiJuego", "version": "1.2" | ["1.2","1.3"] | "*",
#               "fp": ["huella..."], "labels": ["start", "cap2_inicio"]},
#    "characters": {"alice": {"name": "Alice", "vars": ["alice_points"]}},
#    "routes": {"alice": {"name": "Romance con Alice",
#                         "favor": ["alice_points"],
#                         "set": {"alice_route": true},
#                         "decisions": {"park": "Saludar a Alice"}}},
#    "variables": {"important": ["alice_points", "met_alice"],
#                  "ignore": ["ui_*", "tmp_*"],
#                  "names": {"alice_points": "Afecto de Alice"}},
#    "chapters": [{"pattern": "ch1_*", "chapter": "Capitulo 1"}],
#    "scenes": {"alice_date": {"name": "Cita con Alice",
#                              "chapter": "Capitulo 2", "route": "alice",
#                              "set": {"alice_points": 10, "met_alice": true}}},
#    "edges": [{"from": "map_hub", "to": "alice_date",
#               "cond": "day >= 3", "choice": "Ir al parque"}],
#    "gallery": {"categories": {"images/cg/*": "cg", "tag:alice": "sprite"},
#                "names": {"cg alice_date": "Cita con Alice"},
#                "hide": ["gui/*"]}
#  }
#
#  PRECEDENCIA
#    Tus correcciones manuales  >  adaptador  >  deteccion automatica.
#  Las reglas de escena pasan por los mismos filtros de seguridad que la
#  Fase 6 (tipos compatibles, persistent solo con permiso, copia previa).
#
#  ABRIR:  ALT + A
# =====================================================================


# ---------------------------------------------------------------------
# 0) Estado de runtime
# ---------------------------------------------------------------------
init -1030 python:
    import sys as _umod_sys_a
    try:
        _umod_a = _umod_sys_a.modules["umod_rt"]
        _umod_a.ad_loaded = False
        _umod_a.ad_all = []           # [{"A": dict, "src": str, "score": n, "why": [...], "warn": [...]}]
        _umod_a.ad_active = None      # adaptador en uso (dict) o None
        _umod_a.ad_msg = "Sin cargar"
        _umod_a.ad_catcache = {}
        _umod_a.ad_merged = 0
        _umod_a.ad_last_draft = None
        del _umod_a
    except Exception:
        pass


init -929 python:
    # "" = automatico, "none" = desactivado, otro = nombre del adaptador
    if persistent.umod_adapter_choice is None:
        persistent.umod_adapter_choice = ""


# ---------------------------------------------------------------------
# 1) Motor
# ---------------------------------------------------------------------
init -930 python in umod:

    import fnmatch

    ADAPTERS = True

    AD_KEYS = ["alt_K_a"]
    AD_FORMAT = 1
    AD_MIN_SCORE = 10          # puntuacion minima para activarse solo

    _PY_ADAPTERS = []          # registrados desde .rpy

    def register_adapter(A):
        """Para adaptadores en Python:
             init python:
                 umod.register_adapter({"name": "...", "match": {...}, ...})
        Admite la clave "setup": funcion(target, plan) que se ejecuta tras
        aplicar una reconstruccion y antes de saltar."""
        if isinstance(A, dict):
            _PY_ADAPTERS.append(A)
            RT.ad_loaded = False          # se recargara en el proximo uso

    # ---------- 1.1 Carga -------------------------------------------
    def _read_json_game(path):
        f = open_game_file(path)
        try:
            raw = f.read()
        finally:
            try:
                f.close()
            except Exception:
                pass
        if not isinstance(raw, string_types):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def _read_json_disk(path):
        f = open(path, "r")
        try:
            return json.load(f)
        finally:
            f.close()

    def _ad_sources():
        out = []
        try:
            for fn in renpy.list_files():
                base = to_text(fn).replace("\\", "/").split("/")[-1]
                if base.startswith("umod_adapter") and base.endswith(".json"):
                    out.append(("game", to_text(fn)))
        except Exception as e:
            log_error("ad_sources.game", e)
        try:
            sd = renpy.config.savedir
            if sd and os.path.isdir(sd):
                for base in sorted(os.listdir(sd)):
                    if base.startswith("umod_adapter") and base.endswith(".json"):
                        out.append(("saves", os.path.join(sd, base)))
        except Exception as e:
            log_error("ad_sources.saves", e)
        return out

    def ad_load(force=False):
        if RT.ad_loaded and not force:
            return
        RT.ad_loaded = True
        RT.ad_catcache = {}
        found = []
        for where, path in _ad_sources():
            try:
                A = _read_json_game(path) if where == "game" else _read_json_disk(path)
                if isinstance(A, dict):
                    found.append({"A": A, "src": "%s: %s" % (where, path)})
                else:
                    log_error("ad_load", "%s no es un objeto JSON" % path)
            except Exception as e:
                log_error("ad_load %s" % path, e)
                found.append({"A": {"name": path, "_broken": to_text(e)}, "src": "%s: %s" % (where, path)})
        for A in _PY_ADAPTERS:
            found.append({"A": A, "src": "python (register_adapter)"})
        for item in found:
            item["score"], item["why"] = ad_match(item["A"])
            item["warn"] = ad_validate(item["A"]) if item["score"] >= 0 else []
        found.sort(key=lambda it: -it["score"])
        RT.ad_all = found
        _ad_choose()

    def _ad_choose():
        choice = ""
        try:
            choice = to_text(getattr(renpy.store.persistent, "umod_adapter_choice", "") or "")
        except Exception:
            choice = ""
        RT.ad_active = None
        if choice == "none":
            RT.ad_msg = "Adaptadores desactivados"
            return
        usable = [it for it in RT.ad_all if it["score"] >= 0 and not it["A"].get("_broken")]
        if choice:
            for it in usable:
                if ad_name(it["A"]) == choice:
                    RT.ad_active = it["A"]
                    break
        if RT.ad_active is None and usable and usable[0]["score"] >= AD_MIN_SCORE:
            RT.ad_active = usable[0]["A"]
        if RT.ad_active is not None:
            RT.ad_msg = "Activo: %s" % ad_name(RT.ad_active)
        elif RT.ad_all:
            RT.ad_msg = "%d adaptador(es) encontrado(s), ninguno coincide con este juego" % len(RT.ad_all)
        else:
            RT.ad_msg = "Ningun adaptador instalado"
        _ad_after_change()

    def _ad_after_change():
        RT.ad_catcache = {}
        for name in ("rc_cache", "em_cache"):
            try:
                setattr(RT, name, {})
            except Exception:
                pass
        try:
            if GALLERY and RT.gal_ready:
                RT.gal_counts = gal_count_by_cat(RT.gal_assets)
        except Exception:
            pass
        try:
            if GRAPH and RT.g_ready:
                ad_merge_into_graph()
        except Exception:
            pass

    def ad_set_choice(name):
        try:
            renpy.store.persistent.umod_adapter_choice = name
        except Exception as e:
            log_error("ad_set_choice", e)
        _ad_choose()
        try:
            renpy.restart_interaction()
        except Exception:
            pass

    def ad_name(A):
        return to_text((A or {}).get("name") or "(sin nombre)")

    def AD():
        """Adaptador activo (dict vacio si no hay)."""
        if not RT.ad_loaded:
            ad_load()
        return RT.ad_active or {}

    # ---------- 1.2 Identificacion ----------------------------------
    def _as_list(v):
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    def ad_match(A):
        """(puntuacion, motivos). Negativa = es de otro juego."""
        if not isinstance(A, dict) or A.get("_broken"):
            return (-1, ["no se pudo leer"])
        if A.get("format", AD_FORMAT) > AD_FORMAT:
            return (-1, ["formato %s mas nuevo que el del mod (%d)" % (A.get("format"), AD_FORMAT)])
        m = A.get("match") or {}
        score, why = 0, []
        gname = to_text(getattr(renpy.config, "name", "") or "")
        gver = to_text(getattr(renpy.config, "version", "") or "")
        if "name" in m:
            if to_text(m["name"]) == gname:
                score += 10
                why.append("nombre del juego coincide")
            else:
                return (-1, ["es para '%s', este juego es '%s'" % (m["name"], gname)])
        vers = [to_text(v) for v in _as_list(m.get("version"))]
        if vers:
            if "*" in vers or gver in vers:
                score += 3
                why.append("version compatible")
            else:
                why.append("version distinta (%s; adaptador: %s): puede no coincidir" % (gver, ", ".join(vers)))
        fps = [to_text(v) for v in _as_list(m.get("fp"))]
        if fps:
            if script_fp() in fps:
                score += 5
                why.append("huella del guion identica")
            else:
                why.append("huella del guion distinta")
        labs = [to_text(v) for v in _as_list(m.get("labels"))]
        if labs:
            have = 0
            for lb in labs:
                try:
                    if renpy.has_label(lb):
                        have += 1
                except Exception:
                    pass
            if have * 2 < len(labs):
                return (-1, ["solo %d de %d labels del adaptador existen" % (have, len(labs))])
            score += min(10, 2 * have)
            why.append("%d de %d labels presentes" % (have, len(labs)))
        if not m:
            score = 1
            why.append("sin criterios de identificacion: solo se activa a mano")
        return (score, why)

    # ---------- 1.3 Validacion --------------------------------------
    def _known_label(lb):
        try:
            return bool(renpy.has_label(lb))
        except Exception:
            return False

    def _known_var(v):
        base = to_text(v).split(".")[0].split("[")[0]
        if base == "persistent":
            return True
        try:
            if base in vars(renpy.store):
                return True
        except Exception:
            pass
        try:
            if base in RT.sa_vars or base in RT.sa_defaults:
                return True
        except Exception:
            pass
        return False

    def ad_validate(A):
        w = []
        if not isinstance(A, dict):
            return ["no es un objeto JSON"]
        for sec in ("characters", "routes", "scenes", "variables", "gallery"):
            if sec in A and not isinstance(A[sec], dict):
                w.append("'%s' deberia ser un objeto" % sec)
        routes = A.get("routes") or {}
        for rid, r in (routes.items() if isinstance(routes, dict) else []):
            for lb in (r.get("decisions") or {}):
                if not _known_label(lb):
                    w.append("ruta '%s': el label '%s' no existe" % (rid, lb))
            for v in list(r.get("favor") or []) + list((r.get("set") or {}).keys()):
                if not _known_var(v):
                    w.append("ruta '%s': variable desconocida '%s'" % (rid, v))
        scenes = A.get("scenes") or {}
        for lb, sc in (scenes.items() if isinstance(scenes, dict) else []):
            if not _known_label(lb):
                w.append("escena '%s': el label no existe" % lb)
            if sc.get("route") and sc["route"] not in routes:
                w.append("escena '%s': la ruta '%s' no esta definida" % (lb, sc["route"]))
            for v in (sc.get("set") or {}):
                if not _known_var(v):
                    w.append("escena '%s': variable desconocida '%s'" % (lb, v))
        for e in (A.get("edges") or []):
            for k in ("from", "to"):
                if not _known_label(e.get(k, "")):
                    w.append("arista %s -> %s: '%s' no existe" % (e.get("from"), e.get("to"), e.get(k)))
        cats = ((A.get("gallery") or {}).get("categories") or {})
        valid = set(["cg", "sprite", "bg", "anim", "video", "ui", "other"])
        for k, v in cats.items():
            if v not in valid:
                w.append("galeria: categoria '%s' no valida para '%s'" % (v, k))
        return w

    # ---------- 1.4 Consultas para las demas fases ------------------
    def ad_scene(label):
        return ((AD().get("scenes") or {}).get(label)) or {}

    def ad_chapter(label):
        sc = ad_scene(label)
        if sc.get("chapter"):
            return to_text(sc["chapter"])
        for rule in (AD().get("chapters") or []):
            try:
                if fnmatch.fnmatchcase(label, rule.get("pattern", "")):
                    return to_text(rule.get("chapter", ""))
            except Exception:
                continue
        return ""

    def ad_label_suffix(label):
        """Texto extra para las listas de escenas: nombre y capitulo."""
        if not RT.ad_active:
            return ""
        sc = ad_scene(label)
        parts = []
        if sc.get("name"):
            parts.append(to_text(sc["name"]))
        ch = ad_chapter(label)
        if ch:
            parts.append(ch)
        return ("   - " + " / ".join(parts)) if parts else ""

    def ad_var_name(v):
        return to_text(((AD().get("variables") or {}).get("names") or {}).get(v, ""))

    def ad_ignored(path):
        pats = (AD().get("variables") or {}).get("ignore") or []
        base = to_text(path)
        for p in pats:
            try:
                if fnmatch.fnmatchcase(base, p) or fnmatch.fnmatchcase(base.split(".")[0], p):
                    return True
            except Exception:
                continue
        return False

    def ad_routes():
        r = AD().get("routes") or {}
        return [(rid, to_text(r[rid].get("name") or rid)) for rid in sorted(r.keys())]

    def ad_route(rid):
        return ((AD().get("routes") or {}).get(rid)) or {}

    # -- galeria --
    def ad_category(a):
        if not RT.ad_active:
            return None
        k = a.get("k")
        if k in RT.ad_catcache:
            return RT.ad_catcache[k]
        cats = ((AD().get("gallery") or {}).get("categories") or {})
        res = None
        name, fpath, tag = a.get("d") or a.get("n", ""), a.get("f", ""), a.get("t", "")
        for pat, cat in cats.items():
            p = to_text(pat)
            try:
                if p.startswith("tag:"):
                    hit = (tag == p[4:])
                else:
                    hit = (p == name or p == fpath or
                           (fpath and fnmatch.fnmatchcase(fpath, p)) or
                           (name and fnmatch.fnmatchcase(name, p)))
            except Exception:
                hit = False
            if hit:
                res = cat
                break
        RT.ad_catcache[k] = res
        return res

    def ad_hidden(a):
        if not RT.ad_active:
            return False
        for p in ((AD().get("gallery") or {}).get("hide") or []):
            try:
                if fnmatch.fnmatchcase(a.get("f", "") or "", p) or fnmatch.fnmatchcase(a.get("n", ""), p):
                    return True
            except Exception:
                continue
        return False

    def ad_asset_name(a):
        if not RT.ad_active:
            return ""
        names = ((AD().get("gallery") or {}).get("names") or {})
        return to_text(names.get(a.get("d") or "", "") or names.get(a.get("f") or "", "") or "")

    # -- grafo --
    def ad_merge_into_graph():
        """Aristas que el adaptador declara (navegacion desde screens,
        mapas...). Idempotente, como las observadas de la Fase 5."""
        try:
            if not (GRAPH and RT.g_ready):
                return 0
        except Exception:
            return 0
        pairs = set((e["a"], e["b"]) for e in RT.g_edges
                    if not e.get("adp") and e.get("b") is not None)
        new = []
        added = 0
        for spec in (AD().get("edges") or []):
            a, b = to_text(spec.get("from", "")), to_text(spec.get("to", ""))
            if a not in RT.g_nodes or b not in RT.g_nodes or (a, b) in pairs:
                continue
            g = [[to_text(spec["cond"]), True]] if spec.get("cond") else []
            d = [{"cap": to_text(spec["choice"]), "line": "?", "i": -1}] if spec.get("choice") else []
            new.append({"a": a, "b": b, "t": "adp", "g": g, "d": d,
                        "dyn": False, "adp": True, "via": to_text(spec.get("via", ""))})
            pairs.add((a, b))
            added += 1
        ng_replace_extra("adp", new)
        if added:
            RT.g_msg += "  (+%d del adaptador)" % added
        RT.ad_merged = added
        return added

    try:
        _el = globals().get("EDGE_LABEL")
        if isinstance(_el, dict):
            _el["adp"] = "adaptador"
    except Exception:
        pass

    # -- reconstruccion --
    def ad_value(v, cur=None):
        """Valores JSON del adaptador -> Python. Ademas del formato del
        tracker ({"~set": ...}), acepta diccionarios normales."""
        if isinstance(v, dict) and not any(k.startswith("~") for k in v.keys()):
            keymap = {}
            if isinstance(cur, dict):
                for k in cur:
                    keymap[to_text(k)] = k
            out = {}
            for k in v:
                kk = keymap.get(to_text(k), k)
                out[kk] = ad_value(v[k], cur.get(kk) if isinstance(cur, dict) else None)
            return out
        try:
            return rc_decode(v, cur)
        except Exception:
            return v

    def ad_apply_rules(W, P, target):
        """Reglas del adaptador para la escena (y su ruta) sobre el plan."""
        A = AD()
        if not A:
            return
        sc = ad_scene(target)
        sources = []
        rid = sc.get("route")
        if rid:
            sources.append(("ruta '%s'" % rid, ad_route(rid).get("set") or {}))
        if sc.get("set"):
            sources.append(("escena", sc["set"]))
        for origin, rules in sources:
            for path in sorted(rules.keys()):
                exists, cur = rc_get(path)
                _rc_assign(W, path, ad_value(rules[path], cur), "adaptador",
                           "%s: %s" % (ad_name(A), origin))
                P["rule"] = True
        P["adapter"] = ad_name(A)
        imp = (A.get("variables") or {}).get("important") or []
        loose = [v for v in imp if v not in W]
        if loose:
            P["warnings"].append("Variables importantes que el plan no fija (quedan con el valor de tu partida): %s" % ", ".join(loose[:12]))

    def ad_run_setup(P):
        fn = AD().get("setup")
        if callable(fn) and P:
            try:
                fn(P.get("target"), P)
            except Exception as e:
                log_error("adapter.setup", e)

    # ---------- 1.5 Borrador generado desde lo aprendido ------------
    def _slug(s):
        s = re.sub(r"[^A-Za-z0-9]+", "_", to_text(s)).strip("_").lower()
        return s or "juego"

    def ad_generate():
        """Escribe umod_adapter_<juego>_borrador.json en la carpeta de saves
        con todo lo que el mod sabe de este juego. Es un punto de partida
        para editar y compartir, no un adaptador terminado."""
        if not RT.ready:
            scan_all()
        gname = to_text(getattr(renpy.config, "name", "") or "")
        A = {"format": AD_FORMAT,
             "name": "%s (borrador)" % (gname or "juego"),
             "author": "",
             "note": "Generado por UMOD %s el %s. Revisalo antes de compartirlo." % (
                 VERSION, time.strftime("%Y-%m-%d"))}
        labs = ["start"] if _known_label("start") else []
        try:
            if GRAPH and RT.g_ready:
                more = sorted(RT.g_nodes.keys(), key=lambda n: -len(RT.g_nodes[n]["in"]))
                labs += [x for x in more if x not in labs][:4]
        except Exception:
            pass
        if not labs:
            labs = RT.labels.get("game", [])[:5]
        A["match"] = {"name": gname,
                      "version": to_text(getattr(renpy.config, "version", "") or "*"),
                      "fp": [script_fp()], "labels": labs}

        # variables que el guion incrementa y las que compara
        deltas, conds = {}, {}
        try:
            for rec in RT.sa_labels.values():
                for d in rec.get("deltas", []):
                    deltas[d[0]] = deltas.get(d[0], 0) + 1
            for c in RT.sa_conds:
                conds[c["v"]] = conds.get(c["v"], 0) + 1
        except Exception:
            pass

        # personajes: objetos Character del store
        chars = {}
        try:
            for k, v in vars(renpy.store).items():
                if k.startswith("_") or "Character" not in type(v).__name__:
                    continue
                nm = getattr(v, "name", None)
                if not isinstance(nm, string_types) or not nm or "[" in nm:
                    continue
                rel = [x for x in deltas if k.lower() in x.lower() or nm.lower() in x.lower()]
                chars[k] = {"name": nm, "vars": sorted(rel)[:6]}
        except Exception as e:
            log_error("ad_generate.chars", e)
        A["characters"] = chars

        A["routes"] = {}
        for v in sorted(deltas, key=lambda x: -deltas[x])[:10]:
            if v.startswith("persistent."):
                continue
            A["routes"]["favorecer_" + _slug(v)] = {"name": "Favorecer %s" % v, "favor": [v]}

        A["variables"] = {
            "important": [v for v in sorted(conds, key=lambda x: -conds[x]) if not v.startswith("persistent.")][:30],
            "ignore": [], "names": {}}

        # escenas: reglas guardadas desde la Fase 6
        scenes = {}
        p = _savedir_path("umod_rules.json")
        try:
            if p and os.path.exists(p):
                rules = _read_json_disk(p)
                if rules.get("game_id") == game_id():
                    for lb, r in (rules.get("rules") or {}).items():
                        scenes[lb] = {"name": "", "set": r.get("set") or {}}
        except Exception as e:
            log_error("ad_generate.rules", e)
        A["scenes"] = scenes

        # aristas: transiciones observadas que el analisis estatico no ve
        edges = []
        try:
            if TRACKER and GRAPH and RT.g_ready:
                static = tr_static_pairs() or set()
                for a in sorted(RT.tr_labels.keys()):
                    for b in sorted(RT.tr_labels[a].get("out", {}).keys()):
                        if (a, b) not in static and a in RT.g_nodes and b in RT.g_nodes:
                            edges.append({"from": a, "to": b, "via": "observado jugando"})
        except Exception as e:
            log_error("ad_generate.edges", e)
        A["edges"] = edges[:500]

        cats = {}
        try:
            for k, c in (renpy.store.persistent.umod_cat or {}).items():
                key = k[2:] if k[:2] in ("i:", "f:") else k
                cats[key] = c
        except Exception:
            pass
        A["gallery"] = {"categories": cats, "names": {}, "hide": []}

        out = _savedir_path("umod_adapter_%s_borrador.json" % _slug(gname))
        RT.ad_last_draft = _write_json(out, A, pretty=True)
        RT.ad_msg = ("Borrador escrito: %d personajes, %d rutas, %d escenas, %d aristas" % (
            len(chars), len(A["routes"]), len(scenes), len(edges))) if RT.ad_last_draft else "No se pudo escribir el borrador"
        return RT.ad_last_draft

    # ---------- 1.6 Vistas ------------------------------------------
    AD_COLOR = {"h": "#8fe0ff", "ok": "#7ee0a5", "warn": "#ff9b8a", "note": "#7f8ca1",
                "ev": "#dfe7f2", "q": "#e7c58a"}

    def ad_color(k):
        return AD_COLOR.get(k, "#dfe7f2")

    def ad_list_rows():
        if not RT.ad_loaded:
            ad_load()
        return RT.ad_all

    def ad_item_text(it):
        s = it["score"]
        mark = ""
        if RT.ad_active is it["A"]:
            mark = "  [ACTIVO]"
        if s < 0:
            return "%s   (no aplicable)%s" % (ad_name(it["A"]), mark)
        return "%s   (coincidencia %d)%s" % (ad_name(it["A"]), s, mark)

    def ad_detail(it):
        if not it:
            return [("note", "Selecciona un adaptador.")]
        A = it["A"]
        rows = [("h", ad_name(A)), ("note", it["src"])]
        if A.get("author"):
            rows.append(("note", "Autor: %s" % A["author"]))
        if A.get("_broken"):
            rows.append(("warn", "No se pudo leer: %s" % A["_broken"]))
            return rows
        rows.append(("h", "IDENTIFICACION"))
        for w in it["why"]:
            rows.append(("ok" if it["score"] >= AD_MIN_SCORE else "q", w))
        rows.append(("h", "CONTENIDO"))
        for sec, label in (("characters", "personajes"), ("routes", "rutas"), ("scenes", "escenas"),
                           ("edges", "aristas"), ("chapters", "reglas de capitulo")):
            v = A.get(sec)
            n = len(v) if isinstance(v, (dict, list)) else 0
            rows.append(("ev", "%d %s" % (n, label)))
        g = A.get("gallery") or {}
        rows.append(("ev", "galeria: %d categorias, %d nombres, %d ocultos" % (
            len(g.get("categories") or {}), len(g.get("names") or {}), len(g.get("hide") or []))))
        if callable(A.get("setup")):
            rows.append(("q", "incluye codigo 'setup' (adaptador Python)"))
        for rid, rname in [(k, (A.get("routes") or {})[k].get("name", k)) for k in sorted((A.get("routes") or {}).keys())][:12]:
            rows.append(("note", "ruta %s: %s" % (rid, rname)))
        rows.append(("h", "VALIDACION  (%d avisos)" % len(it["warn"])))
        if not it["warn"]:
            rows.append(("ok", "Todo lo que menciona existe en este juego."))
        for w in it["warn"][:40]:
            rows.append(("warn", w))
        return rows

    def ad_choice_text():
        try:
            c = to_text(getattr(renpy.store.persistent, "umod_adapter_choice", "") or "")
        except Exception:
            c = ""
        if c == "none":
            return "Modo: desactivado"
        if c:
            return "Modo: fijado a '%s'" % c
        return "Modo: automatico (se activa el que mejor coincide, si llega a %d)" % AD_MIN_SCORE

    # ---------- 1.7 Apertura ----------------------------------------
    AD_SCREEN = "umod_adapters"

    def adapters_open():
        try:
            if not RT.ready:
                scan_all()
            ad_load(True)
            renpy.hide_screen(SCREEN)
            renpy.show_screen(AD_SCREEN)
            renpy.restart_interaction()
        except Exception as e:
            log_error("adapters_open", e)

    def adapters_toggle():
        try:
            if renpy.get_screen(AD_SCREEN):
                renpy.hide_screen(AD_SCREEN)
                renpy.restart_interaction()
            else:
                adapters_open()
        except Exception as e:
            log_error("adapters_toggle", e)


init -928 python:
    umod.register_key("umod_adapters", umod.adv_keys(umod.AD_KEYS), umod.adapters_toggle)


# =====================================================================
# 2) INTERFAZ
# =====================================================================

screen umod_adapters():

    modal True
    zorder 1100
    tag umod_panel

    default sel = 0

    key "K_ESCAPE" action Hide("umod_adapters")
    key "umod_adapters" action Hide("umod_adapters")

    $ items = umod.guard(umod.ad_list_rows, [])
    $ cur = items[sel] if (items and 0 <= sel < len(items)) else None

    add Solid("#000000dd")

    frame:
        background Solid("#0f1117f5")
        xalign 0.5
        yalign 0.5
        xsize umod.S(1480)
        ysize umod.S(880)
        padding (umod.S(18), umod.S(14))

        vbox:
            spacing umod.S(9)

            fixed:
                xfill True
                ysize umod.S(38)
                hbox:
                    xalign 0.0
                    yalign 0.5
                    spacing umod.S(16)
                    text "ADAPTADORES" size umod.S(22) color "#7fd4ff"
                    text umod.esc(umod.RT.ad_msg) size umod.S(13) color "#78839a" yalign 0.5
                hbox:
                    xalign 1.0
                    yalign 0.5
                    spacing umod.S(6)
                    textbutton "Panel":
                        action [Hide("umod_adapters"), Function(umod.open_panel)]
                        text_size umod.S(14)
                        background Solid("#232a36")
                        padding (umod.S(12), umod.S(6))
                    textbutton "Cerrar  (Esc)":
                        action Hide("umod_adapters")
                        text_size umod.S(14)
                        text_color "#ffd9d9"
                        background Solid("#43222a")
                        hover_background Solid("#6a3340")
                        padding (umod.S(12), umod.S(6))

            hbox:
                spacing umod.S(8)
                textbutton "Recargar":
                    action Function(umod.ad_load, True)
                    text_size umod.S(14)
                    background Solid("#1d2734")
                    hover_background Solid("#2b3a4e")
                    padding (umod.S(12), umod.S(6))
                textbutton "Automatico":
                    action Function(umod.ad_set_choice, "")
                    text_size umod.S(14)
                    background Solid("#191d26")
                    padding (umod.S(12), umod.S(6))
                textbutton "Desactivar":
                    action Function(umod.ad_set_choice, "none")
                    text_size umod.S(14)
                    background Solid("#191d26")
                    padding (umod.S(12), umod.S(6))
                textbutton "Generar borrador desde lo aprendido":
                    action Function(umod.ad_generate)
                    text_size umod.S(14)
                    background Solid("#1d3428")
                    hover_background Solid("#2b4d3a")
                    padding (umod.S(12), umod.S(6))
                text umod.esc(umod.ad_choice_text()) size umod.S(13) color "#98a3b5" yalign 0.5

            hbox:
                spacing umod.S(12)

                frame:
                    background Solid("#0c0f14")
                    xsize umod.S(560)
                    ysize umod.S(722)
                    padding (umod.S(8), umod.S(8))
                    viewport:
                        xsize umod.S(544)
                        ysize umod.S(706)
                        scrollbars "vertical"
                        mousewheel True
                        vbox:
                            spacing umod.S(2)
                            if not items:
                                text "No hay adaptadores. Coloca archivos umod_adapter*.json en la carpeta game/ o en la de saves, o genera un borrador con lo que el mod ya ha aprendido.":
                                    size umod.S(13)
                                    color "#66707f"
                            for i, it in enumerate(items):
                                textbutton umod.esc(umod.ad_item_text(it)):
                                    action SetScreenVariable("sel", i)
                                    text_size umod.S(13)
                                    text_color ("#ffffff" if sel == i else ("#7ee0a5" if it["score"] >= umod.AD_MIN_SCORE else "#98a3b5"))
                                    background (Solid("#26324a") if sel == i else None)
                                    hover_background Solid("#1b2431")
                                    padding (umod.S(6), umod.S(3))
                                    xfill True

                frame:
                    background Solid("#121722")
                    xsize umod.S(872)
                    ysize umod.S(722)
                    padding (umod.S(12), umod.S(10))
                    vbox:
                        spacing umod.S(8)
                        if cur and cur["score"] >= 0 and not cur["A"].get("_broken"):
                            textbutton "Usar este adaptador":
                                action Function(umod.ad_set_choice, umod.ad_name(cur["A"]))
                                text_size umod.S(14)
                                background Solid("#1d3428")
                                hover_background Solid("#2b4d3a")
                                padding (umod.S(12), umod.S(6))
                        viewport:
                            xsize umod.S(848)
                            ysize umod.S(640)
                            scrollbars "vertical"
                            mousewheel True
                            draggable True
                            vbox:
                                spacing umod.S(3)
                                for r in umod.guard(umod.ad_detail, umod.ERR_ROWS, cur):
                                    if r[0] == "h":
                                        null height umod.S(5)
                                    text umod.esc(r[1]):
                                        size (umod.S(15) if r[0] == "h" else umod.S(13))
                                        color umod.ad_color(r[0])
                                        xsize umod.S(820)
                        if umod.RT.ad_last_draft:
                            text umod.esc("Ultimo borrador: %s" % umod.RT.ad_last_draft) size umod.S(12) color "#7f8ca1"


