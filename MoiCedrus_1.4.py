#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Nombre del script: MoiCedrus_1.4.py
Copyright (C) 2025 M. Rojas-Badilla
Licencia: GNU General Public License v3.0 (GPL-3.0)
Para más detalles, ver el archivo LICENSE en la raíz del repositorio.
Requisitos: prompt_toolkit, pyserial
Instalar: pip install prompt_toolkit pyserial
"""

import platform
import serial.tools.list_ports
import threading
import queue
import time
import glob
import re
import serial
import sys
import os
from datetime import datetime
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.widgets import TextArea, Frame
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.document import Document

# ---------------- CONFIG  ----------------
DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_BAUD = 9600
PORT_GLOBS = ["/dev/ttyUSB*", "/dev/ttyACM*"]
RE_FLOAT = re.compile(r"[-+]?\d*\.\d+|[-+]?\d+")
PREVIEW_MAX_LINES = 2000
REFRESH_INTERVAL = 0.08  # s
PAGE_CHAR_STEP = 800     # caracteres para PgUp/PgDn (aprox. una "página")
# -----------------------------------------

PORT_GLOBS = [
    "/dev/ttyUSB*",   # Linux USB serial
    "/dev/ttyACM*",   # Linux ACM serial
    "/dev/tty.*",     # macOS
    "/dev/cu.*",      # macOS
]

def detectar_puerto(interactive=False):
    """
    Detecta y devuelve un puerto serie adecuado.
    - Primero intenta con serial.tools.list_ports (Windows/Linux/Mac).
    - Prioriza puertos USB (FTDI, CP210x, CH340, 'USB Serial', etc.) y excluye Bluetooth.
    - Si interactive=True mostrará la lista y permitirá elegir por índice.
    - Si falla, hace fallback con glob usando PORT_GLOBS (útil en Linux).
    """
    try:
        ports = list(serial.tools.list_ports.comports())
    except Exception as e:
        print(f"⚠️ Error listando puertos con serial.tools.list_ports: {e}")
        ports = []

    if ports:
        print("🔍 Puertos detectados:")
        for i, p in enumerate(ports):
            print(f"  [{i}] {p.device} - {p.description} - {p.manufacturer or 'n/a'}")

        # Si el usuario quiere elegir manualmente, ofrecer selección
        if interactive:
            try:
                choice = input("Elige puerto por índice (Enter = auto): ").strip()
                if choice != "":
                    idx = int(choice)
                    if 0 <= idx < len(ports):
                        print(f"✅ Usando (manual): {ports[idx].device}")
                        return ports[idx].device
            except Exception:
                pass

        # Construir lista de candidatos preferentes (no-Bluetooth + indicios USB)
        candidates = []
        for p in ports:
            desc = (p.description or "").lower()
            manu = (p.manufacturer or "").lower()
            hwid = (p.hwid or "").lower()

            # excluir explícitamente bluetooth
            if "bluetooth" in desc or "bluetooth" in manu or "bth" in hwid:
                continue

            # buscar indicios de puerto USB/FTDI/CH340/CP210/USB Serial
            if ("usb" in desc or "usb" in manu or "usb serial" in desc
                    or "ftdi" in desc or "ftdi" in manu
                    or "ch340" in desc or "cp210" in desc
                    or "prolific" in desc or "silicon labs" in manu
                    or "usb" in hwid):
                candidates.append(p)

        # si no hay candidatos fuertes, tomar cualquier puerto que NO sea bluetooth
        if not candidates:
            non_bt = [p for p in ports if "bluetooth" not in ((p.description or "").lower()) and "bluetooth" not in ((p.manufacturer or "") or "").lower()]
            if non_bt:
                candidates = non_bt

        # elegir el primer candidato si existe
        if candidates:
            chosen = candidates[0]
            print(f"✅ Usando puerto preferente: {chosen.device}  ({chosen.description})")
            return chosen.device

        # si aún no hay, fallback al primero listado
        print(f"⚠️ No se encontró puerto USB preferente, usando: {ports[0].device}")
        return ports[0].device

    # si no hubo resultados via list_ports, usar fallback glob (útil en Linux/mac)
    for g in PORT_GLOBS:
        devices = glob.glob(g)
        if devices:
            print(f"✅ Usando puerto (fallback glob): {devices[0]}")
            return devices[0]

    return None

def append_log(self, tag, msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {tag.upper()}: {msg}"
    self.logs.append(line)

    # refrescar el buffer
    buf = get_app().layout.get_buffer_by_name("LOG_BUFFER")
    if buf:
        buf.text = "\n".join(self.logs)
        buf.cursor_position = len(buf.text)  # autoscroll al final

# --- parseo sigue igual ---
import re
RE_FLOAT = re.compile(r"[-+]?[0-9]*\.?[0-9]+")
def parsear_valor_linea(linea):
    if not linea:
        return None
    m = RE_FLOAT.search(linea)
    if not m:
        return None
    try:
        return float(m.group())
    except:
        return None


def play_beep():
    """
    Reproduce una señal corta. En Windows usa winsound.Beep,
    en otros sistemas imprime el BEL '\a' (campana de terminal) como fallback.
    """
    try:
        if sys.platform.startswith("win"):
            try:
                import winsound
                # frecuencia 1000Hz, duración 120 ms (ajusta si quieres)
                winsound.Beep(1000, 120)
            except Exception:
                # fallback: BEL
                print("\a", end="", flush=True)
        else:
            # En Linux/macOS la BEL suele sonar en la terminal si está habilitada.
            print("\a", end="", flush=True)
    except Exception:
        # No queremos que un error de sonido rompa la app
        pass

def update_next_sound_year(state):
    """
    Calcula y asigna state.next_sound_year basado en:
     - si hay mediciones: calcula el siguiente múltiplo de sound_step > último año medido
     - si no hay: calcula el siguiente múltiplo de sound_step > anio_inicio
    Usa state.sound_step (por defecto 10 si no existe).
    """
    try:
        step = getattr(state, "sound_step", 10)
        if step <= 0:
            step = 10
        if state.measurements:
            last_year = state.anio_inicio + len(state.measurements) - 1
            state.next_sound_year = ((last_year // step) + 1) * step
        else:
            state.next_sound_year = ((state.anio_inicio // step) + 1) * step
    except Exception:
        state.next_sound_year = None

###########################################################################################
def escribir_tucson(codigo, anio_inicio, mediciones, ruta):
    """Escribe Tucson con -9999 en la línea correcta:
       - si la última fila quedó completa (10 valores) -> -9999 en la siguiente década (línea separada)
       - si no -> -9999 al final de la última línea
       FORMATO: código (8 chars), año (4 cols), valores (6 cols cada uno)
    """
    if not ruta.lower().endswith(".txt"):
        ruta = ruta + ".txt"
    codigo = codigo[:8]
    n = len(mediciones)
    lines = []
    rem = anio_inicio % 10
    first_block = 10 - rem if rem != 0 else 10
    idx = 0

    # primer bloque (posible <10)
    if first_block < 10:
        take = min(first_block, n - idx)
        if take > 0:
            fila_vals = mediciones[idx:idx+take]
            fila_anio = anio_inicio + idx
            fila = f"{codigo:8s}{fila_anio:4d}"
            for v in fila_vals:
                fila += f"{v:6d}"
            lines.append(fila)
            idx += take

    # bloques de 10 en adelante
    while idx < n:
        take = min(10, n - idx)
        fila_vals = mediciones[idx:idx+take]
        fila_anio = anio_inicio + idx
        fila = f"{codigo:8s}{fila_anio:4d}"
        for v in fila_vals:
            fila += f"{v:6d}"
        lines.append(fila)
        idx += take

    # colocar sentinel -9999 en el lugar correcto
    if n == 0:
        # sin mediciones -> -9999 en la línea del año inicial
        lines = [f"{codigo:8s}{anio_inicio:4d}{(-9999):6d}"]
    else:
        # contar cuántos valores tiene la última línea
        last_tokens = lines[-1].split()
        num_vals_last_line = max(0, len(last_tokens) - 2)  # -2 por código y año
        if num_vals_last_line >= 10:
            # fila completa: poner -9999 en la siguiente década (línea separada)
            last_year = int(last_tokens[1])
            next_decade = last_year + 10
            sentinel_line = f"{codigo:8s}{next_decade:4d}{(-9999):6d}"
            lines.append(sentinel_line)
        else:
            # fila incompleta: anexar -9999 a la misma línea
            lines[-1] = lines[-1] + f"{(-9999):6d}"

    # grabar
    with open(ruta, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln.rstrip() + "\n")


def format_preview_lines(codigo, anio_inicio, measures, max_lines=1000):
    """
    Genera lista de líneas formateadas (Tucson) para vista previa.
    Usa el mismo formato que escribir_tucson: año ancho=4, valores ancho=6.
    """
    codigo_fmt = f"{codigo[:8]:<8s}"
    n = len(measures)
    idx = 0
    lines = []

    next_decade = ((anio_inicio // 10) + 1) * 10
    first_block_len = next_decade - anio_inicio
    if first_block_len <= 0:
        first_block_len = 10

    # primer bloque (posible <10)
    if idx < n:
        take = min(first_block_len, n - idx)
        vals = measures[idx: idx + take]
        parts = [codigo_fmt + f"{anio_inicio:4d}"] + [f"{v:6d}" for v in vals]
        lines.append("".join(parts))
        idx += take
        current_decade_start = next_decade
    else:
        current_decade_start = next_decade

    # bloques completos de 10 en adelante
    while idx < n:
        vals = measures[idx: idx + 10]
        parts = [codigo_fmt + f"{current_decade_start:4d}"] + [f"{v:6d}" for v in vals]
        lines.append("".join(parts))
        idx += len(vals)
        current_decade_start += 10

    # decidir dónde poner -9999 (misma lógica que escribir_tucson)
    if n == 0:
        lines = [f"{codigo_fmt}{anio_inicio:4d}{(-9999):6d}"]
    else:
        last_tokens = lines[-1].split()
        num_vals_last_line = max(0, len(last_tokens) - 2)
        if num_vals_last_line >= 10:
            last_year = int(last_tokens[1])
            next_dec = last_year + 10
            lines.append(codigo_fmt + f"{next_dec:4d}{(-9999):6d}")
        else:
            lines[-1] = lines[-1] + f"{(-9999):6d}"

    return lines[-max_lines:]

# ----------------- THREAD LECTOR -----------------
def lector_serial_worker(port, baud, out_queue, stop_event, log_queue):
    try:
        ser = serial.Serial(port, baud, timeout=0.2)
        time.sleep(0.5)
        log_queue.put(("info", f"Puerto abierto: {port} @ {baud}"))
    except Exception as e:
        log_queue.put(("error", f"Error abriendo puerto {port}: {e}"))
        out_queue.put(("fatal", str(e)))
        return

    try:
        while not stop_event.is_set():
            raw = ser.readline()
            if not raw:
                continue
            try:
                s = raw.decode(errors="ignore").strip()
            except:
                s = str(raw)
            val = parsear_valor_linea(s)
            if val is not None:
                out_queue.put(("reading", val))
    except Exception as e:
        log_queue.put(("error", f"Error lectura serial: {e}"))
        out_queue.put(("fatal", str(e)))
    finally:
        try:
            ser.close()
            log_queue.put(("info", "Puerto serial cerrado."))
        except:
            pass


# ----------------- PROCESSOR -----------------
class VROState:
    def __init__(self, codigo, anio_inicio, out_name):
        self.waiting_reference = True
        self.auto_ref_mode = True
        self.codigo = codigo[:8]
        self.anio_inicio = anio_inicio
        self.out_name = out_name
        self.measurements = []
        self.last_cumulative = None
        self.paused = False
        self.logs = []
        self.year_counter = 0
        # Sonido por décadas: habilitar y configurar
        self.sound_enabled = True            # True = emitir beep en umbrales
        self.sound_step = 10                 # paso en años (10 = décadas)
        # siguiente año que disparará sonido (p. ej. la próxima década)
        self.next_sound_year = None
        # ... y luego, justo después de terminar __init__, podrías:
        update_next_sound_year(self)
        # <-- NEW: autoscroll global (compartido entre hilos)
        self.auto_scroll = True


    def append_log(self, level, msg):
        t = datetime.now().strftime("%H:%M:%S")
        text = f"[{t}] {level.upper()}: {msg}"
        self.logs.append(text)
        if len(self.logs) > 1200:
            self.logs = self.logs[-1200:]


def processor_worker(reader_q, state: VROState, stop_event, log_q):
    """
    Toma eventos del reader_q y transforma lecturas en mediciones,
    registra logs y dispara el beep cuando corresponde.
    """
    while not stop_event.is_set():
        try:
            ev = reader_q.get(timeout=0.2)
        except queue.Empty:
            continue

        try:
            if ev[0] == "reading":
                mm_val = ev[1]
                current_mil = int(round(mm_val * 1000))

                # Fijar referencia automática con la 1ª lectura válida
                if state.waiting_reference and state.auto_ref_mode:
                    state.last_cumulative = current_mil
                    state.waiting_reference = False
                    state.append_log(
                        "ok",
                        f"Referencia automática fijada (acum {state.last_cumulative/1000:.3f} mm)"
                    )
                else:
                    if not state.paused:
                        if state.last_cumulative is None:
                            state.last_cumulative = current_mil
                            state.append_log("info", f"Referencia inicial fijada {state.last_cumulative}")
                        else:
                            delta = current_mil - state.last_cumulative
                            if delta > 0:
                                measured = int(round(delta))
                                state.measurements.append(measured)
                                 # <-- nuevo: reactivar autoscroll cuando llega medición nueva
                                state.auto_scroll = True
                                year_measured = state.anio_inicio + (len(state.measurements) - 1)
                                year_measured = state.anio_inicio + (len(state.measurements) - 1)
                                accumulated = current_mil
                                state.year_counter += 1
                                state.last_cumulative = current_mil

                                # Log de la medición
                                state.append_log(
                                    "ok",
                                    f"{year_measured}: {measured} (acum {accumulated/1000:.3f} mm)"
                                )

                                # ---------- comprobación sonora ----------
                                try:
                                    if getattr(state, "sound_enabled", False):
                                        # Asegurar next_sound_year inicializado
                                        if getattr(state, "next_sound_year", None) is None:
                                            # calcular primer umbral (ej.: si sound_step=10 -> siguiente década)
                                            state.next_sound_year = ((state.anio_inicio // state.sound_step) + 1) * state.sound_step

                                        # Disparar beep(s) si el año medido alcanzó o superó el umbral
                                        while year_measured >= state.next_sound_year:
                                            try:
                                                play_beep()
                                            except Exception:
                                                # no fatal si el beep falla
                                                pass
                                            state.append_log("info", f"Década: {state.next_sound_year}")
                                            state.next_sound_year += state.sound_step
                                except Exception:
                                    # proteger contra cualquier fallo en la lógica sonora
                                    pass
                                # ------------------------------------------------

                            elif delta < 0:
                                # retroceso/reseteo del acumulado: resincronizar baseline
                                state.last_cumulative = current_mil
                                state.append_log("info", "Reset/retroceso detectado; resincronizando.")

            elif ev[0] == "fatal":
                state.append_log("fatal", ev[1])
                stop_event.set()

        finally:
            try:
                reader_q.task_done()
            except Exception:
                pass



# ----------------- UI -----------------
def build_app(state: VROState, reader_q, log_q, stop_event, puerto, baud):
    # TextAreas
    preview_area = TextArea(text="(preview vacío)\n", scrollbar=True, wrap_lines=False, read_only=True)
    logs_area = TextArea(text="(logs...)\n", scrollbar=True, wrap_lines=False, read_only=True, height=8)

    # status_area ahora tiene más altura (5 filas) para mostrar comandos en línea separada
    status_area = TextArea(text="", height=6, read_only=True, style="class:status")


    kb = KeyBindings()

    # mutable flag para controlar autoscroll desde closures
    auto_scroll = {"value": True}

    # flag para captura interactiva del nuevo año (modo "entrada de año" dentro de la UI)
    awaiting_year = {"on": False, "buf": ""}

    @kb.add("p")
    def _(event):
        state.paused = not state.paused
        state.append_log("info", "PAUSADO" if state.paused else "REANUDADO")

    @kb.add("r")
    def _(event):
        if state.measurements:
            rem = state.measurements.pop()
            state.year_counter = max(0, state.year_counter - 1)
            # Recalcular el umbral sonoro al quitar una medición
            try:
                update_next_sound_year(state)
            except Exception:
                # no fatal si falla la función (log para debug)
                state.append_log("warn", "No se pudo recalcular umbral sonoro tras eliminar.")
            state.append_log("ok", f"Removido: {rem}  (next_sound_year={getattr(state,'next_sound_year','N/A')})")
        else:
            state.append_log("warn", "No hay mediciones para eliminar.")

    @kb.add("g")
    def _(event):
        try:
            escribir_tucson(state.codigo, state.anio_inicio, state.measurements, state.out_name)
            state.append_log("ok", f"Guardado en {state.out_name}")
        except Exception as e:
            state.append_log("error", f"Error guardando: {e}")

    @kb.add("s")
    def _(event):
        try:
            escribir_tucson(state.codigo, state.anio_inicio, state.measurements, state.out_name)
            state.append_log("ok", f"Guardado en {state.out_name}")
        except Exception as e:
            state.append_log("error", f"Error guardando: {e}")
        stop_event.set()
        event.app.exit()

    @kb.add("h")
    def _(event):
        state.append_log("info", "Ayuda: p pausar, r remedir, g guardar, s guardar+salir, y editar año, h ayuda")
        
    # Ir al inicio de la vista (Ctrl+Up)
    @kb.add("c-up")
    def _(event):
        buff = event.app.layout.get_buffer_by_name("LOG_BUFFER")
        if buff:
            buff.cursor_position = 0   # mover cursor al inicio

    # Ir al final de la vista (Ctrl+Down)
    @kb.add("c-down")
    def _(event):
        buff = event.app.layout.get_buffer_by_name("LOG_BUFFER")
        if buff:
            buff.cursor_position = len(buff.text)  # mover cursor al final

       # --- Navegación rápida: ir al inicio/fin de preview ---
    # Home / Ctrl-Home / Ctrl-Up -> ir al inicio
    @kb.add("home")
    @kb.add("c-home")
    @kb.add("c-up")
    def _(event):
        try:
            preview_area.buffer.cursor_position = 0
            state.append_log("info", "Vista: inicio (home)")
        except Exception:
            pass

    # End / Ctrl-End / Ctrl-Down -> ir al final
    @kb.add("end")
    @kb.add("c-end")
    @kb.add("c-down")
    def _(event):
        try:
            preview_area.buffer.cursor_position = len(preview_area.text)
            state.auto_scroll = True    # <-- reactivar autoscroll al forzar al final
            state.append_log("info", "Vista: final (end)")
        except Exception:
            pass


    @kb.add("pageup")
    def _(event):
        try:
            cp = preview_area.buffer.cursor_position
            preview_area.buffer.cursor_position = max(0, cp - PAGE_CHAR_STEP)
            state.auto_scroll = False
        except Exception:
            pass

    @kb.add("pagedown")
    def _(event):
        try:
            cp = preview_area.buffer.cursor_position
            preview_area.buffer.cursor_position = min(len(preview_area.text), cp + PAGE_CHAR_STEP)
            state.auto_scroll = False
        except Exception:
            pass

    @kb.add("up")
    def _(event):
        try:
            cp = preview_area.buffer.cursor_position
            preview_area.buffer.cursor_position = max(0, cp - 30)
            state.auto_scroll = False
        except Exception:
            pass

    @kb.add("down")
    def _(event):
        try:
            cp = preview_area.buffer.cursor_position
            preview_area.buffer.cursor_position = min(len(preview_area.text), cp + 30)
            state.auto_scroll = False
        except Exception:
            pass
    
    # --- Cambiar año inicial en caliente (simple, via run_in_terminal) ---
    # --- Estado para edición de año dentro de la propia UI ---
    # --- Cambiar año inicial en caliente (modo UI: y -> escribir dígitos -> Enter) ---
    awaiting_year = {"on": False, "buf": ""}

    @kb.add("y")
    def _(event):
        awaiting_year["on"] = True
        awaiting_year["buf"] = ""
        state.append_log("info", "Editar año: escribe el año y pulsa Enter (Esc para cancelar).")

    # Digitos 0..9 (mientras awaiting_year['on'] sea True)
    for _ch in "0123456789":
        @kb.add(_ch)
        def _(event, ch=_ch):
            if awaiting_year["on"]:
                if len(awaiting_year["buf"]) < 6:
                    awaiting_year["buf"] += ch
                return

    @kb.add("backspace")
    def _(event):
        if awaiting_year["on"]:
            if awaiting_year["buf"]:
                awaiting_year["buf"] = awaiting_year["buf"][:-1]
            return

    @kb.add("enter")
    def _(event):
        if awaiting_year["on"]:
            txt = awaiting_year["buf"].strip()
            if txt == "":
                state.append_log("warn", "Edición de año cancelada (vacío).")
            else:
                try:
                    new_year = int(txt)
                    state.anio_inicio = new_year
                    # Recalcular umbral sonoro inmediatamente
                    try:
                        update_next_sound_year(state)
                    except Exception:
                        state.append_log("warn", "No se pudo recalcular umbral sonoro tras cambiar año.")
                    state.append_log("ok", f"Año inicial cambiado a {state.anio_inicio}; próximo beep en {getattr(state,'next_sound_year','N/A')}")
                except Exception as e:
                    state.append_log("error", f"Año inválido: '{txt}' ({e})")
            awaiting_year["on"] = False
            awaiting_year["buf"] = ""
            return

    @kb.add("escape")
    def _(event):
        if awaiting_year["on"]:
            awaiting_year["on"] = False
            awaiting_year["buf"] = ""
            state.append_log("info", "Edición de año cancelada (Esc).")
            return
    
    body = HSplit([
        Frame(status_area, title="=^.^= Estado =^.^="),
        Frame(preview_area, title="*=*=*=* Vista Previa *=*=*=*"),
        Frame(logs_area, title="~:~:~:~ Registros ~:~:~:~"),
    ])

    style = Style.from_dict({
        "frame.label": "bg:#004466 #ffffff",
        "frame.border": "#666666",
        "textarea": "bg:#000000 #ffffff",
        "status": "bg:#003366 #ffffff bold", # estilo específico para el status area (fondo oscuro-azulado, texto blanco y negrita) Puedes cambiar #003366 por otro color en hex si prefieres; p. ej. #004466, #2A7F62, etc.
    })

    app = Application(layout=Layout(body), key_bindings=kb, style=style, full_screen=True)

    # refresher loop: actualiza preview/logs/status periódicamente
    # refresher_loop
    def refresher_loop():
        # texto de comandos que queremos mostrar (unificado)
        commands_line = "Comandos: p=pausar/reanudar   r=remedir   g=guardar   s=guardar+salir   y=editar año   (Ctrl) ↑ ↓"
        signature = "M. Rojas-Badilla".rjust(100)

        # initial fill (antes de entrar al bucle)
        preview_lines = format_preview_lines(state.codigo, state.anio_inicio, state.measurements, max_lines=PREVIEW_MAX_LINES)
        preview_text = "\n".join(preview_lines[-PREVIEW_MAX_LINES:]) if preview_lines else "(vacío)"
        logs_text = "\n".join(state.logs[-300:]) if state.logs else "(sin logs)"
        status_text = (
             "Puerto: {0}    Baud: {1}\n"
             "Serie : {2}    Año inicio: {3}    Anillos: {4}\n"
             "Estado : {5}    Baseline: {6}\n"
             "{7}\n"
             "{8}"
         ).format(
             puerto, baud, state.codigo, state.anio_inicio, len(state.measurements),
             "PAUSADO" if state.paused else "MIDIENDO",
             state.last_cumulative if state.last_cumulative is not None else "N/A",
             commands_line,
             signature
         )

        try:
            preview_area.buffer.set_document(Document(preview_text), bypass_readonly=True)
            if auto_scroll["value"]:
                try:
                    preview_area.buffer.cursor_position = len(preview_text)
                except Exception:
                    pass
            logs_area.buffer.set_document(Document(logs_text), bypass_readonly=True)
            status_area.buffer.set_document(Document(status_text), bypass_readonly=True)
            app.invalidate()
        except Exception:
            pass

        # bucle principal de refresco
        while not stop_event.is_set():
            try:
                preview_lines = format_preview_lines(state.codigo, state.anio_inicio, state.measurements, max_lines=PREVIEW_MAX_LINES)
                preview_text = "\n".join(preview_lines[-PREVIEW_MAX_LINES:]) if preview_lines else "(vacío)"
                logs_text = "\n".join(state.logs[-300:]) if state.logs else "(sin logs)"
                # usar la variable commands_line para mantener consistencia
                # comandos permanentes
                commands_line = "Comandos: p=pausar/reanudar  r=remedir  g=guardar  s=guardar+salir  y=editar año inicio   (Ctrl) ↑ ↓"
                signature = "M. Rojas-Badilla".rjust(100)

                # mostrar prompt de entrada de año si estamos en ese modo
                year_prompt_line = ""
                if awaiting_year["on"]:
                    year_prompt_line = f"Nuevo año inicial (Enter=OK Esc=Cancelar): {awaiting_year['buf']}"

                status_text = (
                    "Puerto: {0}    Baud: {1}\n"
                    "Serie : {2}    Año inicio: {3}    Anillos: {4}\n"
                    "Estado : {5}    Dato base: {6}\n"
                    "{7}\n"
                    "{8}\n"
                    "{9}"
                ).format(
                    puerto, baud, state.codigo, state.anio_inicio, len(state.measurements),
                    "PAUSADO" if state.paused else "MIDIENDO",
                    state.last_cumulative if state.last_cumulative is not None else "N/A",
                    commands_line,
                    year_prompt_line,
                    signature
                )


                # Actualizar TextAreas:
                if state.auto_scroll:
                    preview_area.buffer.set_document(Document(preview_text), bypass_readonly=True)
                    try:
                        preview_area.buffer.cursor_position = len(preview_text)
                    except Exception:
                        pass
                else:
                    # mantener la posición del cursor del usuario
                    try:
                        curpos = preview_area.buffer.cursor_position
                    except Exception:
                        curpos = None
                    preview_area.buffer.set_document(Document(preview_text), bypass_readonly=True)
                    if curpos is not None:
                        try:
                            preview_area.buffer.cursor_position = min(curpos, len(preview_text))
                        except Exception:
                            pass

                logs_area.buffer.set_document(Document(logs_text), bypass_readonly=True)
                status_area.buffer.set_document(Document(status_text), bypass_readonly=True)

                app.invalidate()
            except Exception:
                pass

            time.sleep(REFRESH_INTERVAL)

    refresher = threading.Thread(target=refresher_loop, daemon=True)
    refresher.start()

    return app, preview_area, logs_area, status_area


# ----------------- MAIN -----------------
def main():
    print("=== VRO prompt_toolkit launcher ===")
    codigo = input("Código (ej. CLL431B): ").strip()[:8] or "SERIE1"
    try:
        anio_inicio = int(input("Año inicial (ej. 1696): ").strip())
    except:
        anio_inicio = 1
    out_name = input("Nombre de archivo salida (sin .txt): ").strip()
    if not out_name:
        out_name = f"{codigo}_{datetime.now().strftime('%Y%m%d')}"
    if not out_name.lower().endswith(".txt"):
        out_name = out_name + ".txt"

    puerto = detectar_puerto() ## Si quieres que el usuario pueda elegir manualmente el puerto cambiar a: puerto = detectar_puerto(interactive=True)

    if not puerto:
        puerto = input(f"No se detectó puerto; indica (ej. {DEFAULT_PORT}): ").strip() or DEFAULT_PORT

    reader_q = queue.Queue()
    log_q = queue.Queue()
    stop_event = threading.Event()
    state = VROState(codigo, anio_inicio, out_name)
    state.append_log("info", "Referencia: se fijará AUTOMÁTICAMENTE con la PRIMERA lectura válida.")
    state.append_log("info", f"Archivo de salida: {out_name}")
    state.append_log("info", f"Puerto objetivo: {puerto}")

    # Reader thread (serial)
    reader_thread = threading.Thread(target=lector_serial_worker, args=(puerto, DEFAULT_BAUD, reader_q, stop_event, log_q), daemon=True)
    reader_thread.start()

    # Processor thread (convierte lecturas en mediciones y logs)
    processor_thread = threading.Thread(target=processor_worker, args=(reader_q, state, stop_event, log_q), daemon=True)
    processor_thread.start()

    # Construir UI
    app, preview_area, logs_area, status_area = build_app(state, reader_q, log_q, stop_event, puerto, DEFAULT_BAUD)

    try:
        app.run()
    except Exception as e:
        print("Error app:", e)
    finally:
        stop_event.set()
        reader_thread.join(timeout=1)
        processor_thread.join(timeout=1)
        print("Saliendo...")

if __name__ == "__main__":
    main()

