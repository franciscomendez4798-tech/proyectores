from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import datetime
import os
import sqlite3
import math
from datetime import timedelta
from functools import wraps
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

load_dotenv()

# ─── CIFRADO ──────────────────────────────────────────────────────────────────
llave_maestra = os.environ.get('LLAVE_MAESTRA')

if llave_maestra:
    cifrador = Fernet(llave_maestra.encode() if isinstance(llave_maestra, str) else llave_maestra)
else:
    cifrador = None

def desencriptar(texto_cifrado):
    if not texto_cifrado or not cifrador:
        return texto_cifrado
    if texto_cifrado.startswith('gAAAA'):
        try:
            return cifrador.decrypt(texto_cifrado.encode()).decode()
        except Exception as e:
            # FIX #19: Reemplazado 'except: pass' por logging real
            app.logger.error(f"Error al desencriptar: {e}")
            return "DATOS_PROTEGIDOS"
    return texto_cifrado

# ─── APLICACIÓN ───────────────────────────────────────────────────────────────
app = Flask(__name__)

# FIX #6: secret_key desde variable de entorno (no aleatoria en cada reinicio)
_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    raise RuntimeError(
        "❌ SECRET_KEY no configurada. Agrégala a tu archivo .env: SECRET_KEY=<clave-larga-aleatoria>"
    )
app.secret_key = _secret_key

# FIX #5: Protección CSRF global
# IMPORTANTE: Todos los formularios HTML deben incluir {{ csrf_token() }} o
#             usar un campo oculto: <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
csrf = CSRFProtect(app)

# FIX #14: Rate limiting — evita fuerza bruta en login
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=2)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')

# FIX #15: Extensiones permitidas para subida de archivos
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

DB_NAME = 'uat.db'
CONFIG = {
    "TIEMPO_ESPERA_MINUTOS": 15,
    "MAX_HORAS_PRESTAMO": 2
}

MESES_ESP = [
    'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
]

# ─── DECORADORES DE AUTENTICACIÓN ─────────────────────────────────────────────

# FIX #2 y #7: Decoradores centralizados para verificar sesión en lugar de
#              repetir la lógica en cada ruta (o peor, omitirla).

def requiere_sesion_alumno(f):
    """Protege rutas de alumno: verifica sesión activa y que la matrícula
    en la URL coincida con la matrícula almacenada en sesión (anti-IDOR)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('matricula'):
            return redirect(url_for('home'))
        # FIX #3: Verifica que la matrícula de la URL pertenezca al usuario en sesión
        matricula_url = kwargs.get('matricula', '').upper()
        if matricula_url and matricula_url != session.get('matricula'):
            app.logger.warning(
                f"Intento de acceso IDOR: sesión={session.get('matricula')} url={matricula_url}"
            )
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

def requiere_admin(f):
    """Protege todas las rutas de administración.
    Para peticiones fetch/AJAX (Accept: application/json) devuelve 401 JSON
    en lugar de un redirect 302, que el browser seguiría automáticamente y
    rompería el polling del panel admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged'):
            # Si es una petición fetch (AJAX), devolver 401 en lugar de redirect
            if request.headers.get('Accept', '').find('application/json') != -1 or \
               request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'No autorizado'}), 401
            return redirect(url_for('admin_login_page'))
        return f(*args, **kwargs)
    return decorated

# ─── UTILIDADES ───────────────────────────────────────────────────────────────

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def hora_mexico():
    """Ajusta UTC a Hora Central de México (-6)."""
    return datetime.datetime.utcnow() - datetime.timedelta(hours=6)

def allowed_file(filename):
    """FIX #15: Valida la extensión del archivo."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validar_magic_bytes(data: bytes) -> bool:
    """FIX #15: Valida el tipo real del archivo inspeccionando sus magic bytes,
    sin depender del nombre o extensión declarada por el cliente."""
    jpeg_magic = [b'\xff\xd8\xff\xe0', b'\xff\xd8\xff\xe1', b'\xff\xd8\xff\xdb', b'\xff\xd8\xff\xee']
    png_magic  = b'\x89PNG\r\n\x1a\n'
    webp_riff  = b'RIFF'
    webp_type  = b'WEBP'

    if any(data[:4] == m for m in jpeg_magic):
        return True
    if data[:8] == png_magic:
        return True
    if data[:4] == webp_riff and data[8:12] == webp_type:
        return True
    return False

# ─── LIMPIEZA AUTOMÁTICA ──────────────────────────────────────────────────────

def liberar_reservas_vencidas():
    """FIX #9: Ahora compara fecha+hora completas (YYYY-MM-DD HH:MM) para
    evitar el bug de diferencia negativa al cambiar de día (ej. 23:50 → 00:10)."""
    try:
        conn = get_db_connection()
        reservados = conn.execute(
            "SELECT * FROM proyectores WHERE estado = 'Reservado'"
        ).fetchall()
        ahora = hora_mexico()
        cambios = False

        for p in reservados:
            if p['hora_reserva']:
                try:
                    fecha_reserva = datetime.datetime.strptime(
                        p['hora_reserva'], "%Y-%m-%d %H:%M"
                    )
                    diferencia = (ahora - fecha_reserva).total_seconds() / 60

                    if diferencia > CONFIG["TIEMPO_ESPERA_MINUTOS"]:
                        conn.execute(
                            """UPDATE proyectores
                               SET estado='Disponible', usuario=NULL, telefono=NULL,
                                   salon=NULL, maestro=NULL, hora_reserva=NULL,
                                   hora_limite=NULL, duracion_solicitada=0
                               WHERE id=?""",
                            (p['id'],)
                        )
                        cambios = True
                except Exception as e:
                    app.logger.error(f"Error procesando reserva id={p['id']}: {e}")

        if cambios:
            conn.commit()
        conn.close()
    except Exception as e:
        app.logger.error(f"Error en liberar_reservas_vencidas: {e}")

# ─── VALIDACIONES DE NEGOCIO ──────────────────────────────────────────────────

def obtener_alumno(matricula):
    conn = get_db_connection()
    alumno = conn.execute(
        "SELECT * FROM alumnos WHERE matricula = ?", (matricula,)
    ).fetchone()
    conn.close()
    return alumno

def tiene_proyector_activo(matricula):
    conn = get_db_connection()
    count = conn.execute(
        "SELECT count(*) FROM proyectores WHERE usuario = ?", (matricula,)
    ).fetchone()[0]
    conn.close()
    return count > 0

# ─── INICIALIZACIÓN ───────────────────────────────────────────────────────────

def init_db():
    """Crea todas las tablas del sistema si no existen.
    Esto evita que la aplicación falle silenciosamente cuando la BD es nueva
    o fue borrada (vacía = alumno no puede ver equipos, préstamos no se registran)."""
    conn = get_db_connection()

    # Tabla de alumnos con cifrado Fernet en el campo 'nombre'
    conn.execute('''
        CREATE TABLE IF NOT EXISTS alumnos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            matricula  TEXT    NOT NULL UNIQUE,
            nombre     TEXT    NOT NULL,
            strikes    INTEGER NOT NULL DEFAULT 0,
            bloqueado  INTEGER NOT NULL DEFAULT 0
        )
    ''')

    # Tabla central de proyectores/equipos
    conn.execute('''
        CREATE TABLE IF NOT EXISTS proyectores (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            estado              TEXT    NOT NULL DEFAULT 'Disponible',
            marca               TEXT    NOT NULL DEFAULT 'Generico',
            modelo              TEXT    NOT NULL DEFAULT '-',
            serie               TEXT    NOT NULL DEFAULT 'S/N',
            color               TEXT    NOT NULL DEFAULT '-',
            foto                TEXT,
            usuario             TEXT,
            telefono            TEXT,
            salon               TEXT,
            maestro             TEXT,
            hora_reserva        TEXT,
            hora_limite         TEXT,
            duracion_solicitada REAL    NOT NULL DEFAULT 0
        )
    ''')

    # Historial de préstamos completados
    conn.execute('''
        CREATE TABLE IF NOT EXISTS historial (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha         TEXT,
            matricula     TEXT,
            nombre        TEXT,
            proyector     TEXT,
            estatus       TEXT,
            sancion       TEXT,
            telefono      TEXT    DEFAULT 'N/A',
            docente_clase TEXT    DEFAULT 'N/A'
        )
    ''')

    # Catálogo de docentes para el datalist del formulario
    conn.execute('''
        CREATE TABLE IF NOT EXISTS docentes (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT    NOT NULL UNIQUE
        )
    ''')

    # Buzón de sugerencias y mejoras
    conn.execute('''
        CREATE TABLE IF NOT EXISTS buzon_mejoras (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha   TEXT,
            nombre  TEXT,
            correo  TEXT,
            mensaje TEXT
        )
    ''')

    conn.commit()
    conn.close()
    app.logger.info("✅ Base de datos inicializada correctamente.")

init_db()

# ═══════════════════════════════════════════════════════════════════════════════
# RUTAS INFORMATIVAS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/acerca_de')
def acerca_de():
    return render_template('acerca.html')

@app.route('/preguntas')
def preguntas():
    return render_template('preguntas.html')

@app.route('/buzon', methods=['GET', 'POST'])
def buzon():
    if request.method == 'POST':
        try:
            # FIX #17: Límite de longitud en campos de formulario
            nombre  = request.form.get('nombre',  'Anónimo')[:100]
            correo  = request.form.get('correo',  'Sin correo')[:100]
            mensaje = request.form.get('mensaje', '')[:1000]

            ahora = hora_mexico()
            fecha = ahora.strftime("%d/%m/%Y - %H:%M")

            conn = get_db_connection()
            conn.execute(
                'INSERT INTO buzon_mejoras (fecha, nombre, correo, mensaje) VALUES (?, ?, ?, ?)',
                (fecha, nombre, correo, mensaje)
            )
            conn.commit()
            conn.close()

            return render_template('buzon.html', exito=True)
        except Exception as e:
            app.logger.error(f"Error en buzón: {e}")
            return "Ocurrió un error interno. Por favor avisa a la administración.", 500

    return render_template('buzon.html', exito=False)

@app.route('/')
def home():
    return render_template('index.html')

# ═══════════════════════════════════════════════════════════════════════════════
# AUTENTICACIÓN ALUMNO
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/login', methods=['POST'])
@limiter.limit("10 per minute")   # FIX #14: Anti fuerza bruta
def login():
    if not request.form.get('terminos'):
        return redirect(url_for('home', alerta='terminos'))

    matricula = request.form.get('matricula', '').strip().upper()

    # FIX #17: Validación básica de entrada
    if not matricula or len(matricula) > 20:
        return redirect(url_for('home', alerta='not_found'))

    alumno = obtener_alumno(matricula)

    if alumno:
        if alumno['bloqueado'] == 1:
            return redirect(url_for('home', alerta='bloqueado', strikes=alumno['strikes']))

        # FIX #2 y #3: Guardar matrícula en sesión para verificación posterior
        session['nombre']    = desencriptar(alumno['nombre']).title()
        session['matricula'] = matricula
        return redirect(url_for('dashboard', matricula=matricula))
    else:
        return redirect(url_for('home', alerta='not_found'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# ─── API PÚBLICA ──────────────────────────────────────────────────────────────

@app.route('/api/admin/data')
@requiere_admin
def api_admin_data():
    """Endpoint exclusivo del panel admin: devuelve TODOS los campos, incluyendo
    usuario, telefono, salon, maestro, horas. Solo accesible con sesión de admin."""
    liberar_reservas_vencidas()
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM proyectores').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/data')
def api_data():
    """FIX #4: Solo expone campos no sensibles. Usuario, teléfono y salón
    ya no se incluyen en la respuesta pública."""
    liberar_reservas_vencidas()
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT id, estado, marca, modelo, color, serie, foto FROM proyectores'
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ═══════════════════════════════════════════════════════════════════════════════
# RUTAS ALUMNO  (protegidas con @requiere_sesion_alumno)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/dashboard/<matricula>')
@requiere_sesion_alumno   # FIX #2 + #3
def dashboard(matricula):
    matricula_limpia = matricula.strip().upper()
    liberar_reservas_vencidas()

    conn = get_db_connection()
    alumno = conn.execute(
        "SELECT * FROM alumnos WHERE matricula = ?", (matricula_limpia,)
    ).fetchone()

    nombre_real = desencriptar(alumno['nombre']).title() if alumno else "Alumno"

    # FIX #4: El dashboard del alumno tampoco devuelve datos privados de otros usuarios
    proyectores = conn.execute(
        'SELECT id, estado, marca, modelo, color, serie, foto FROM proyectores'
    ).fetchall()

    # FIX PERFORMANE: Consultamos 'mi_equipo' desde aquí para inyectarlo en el HTML
    # y evitar las peticiones fetch() en cascada que trababan la pantalla del alumno.
    mi_equipo = conn.execute(
        '''SELECT id, estado, marca, modelo, hora_reserva, hora_limite
           FROM proyectores WHERE usuario = ?''',
        (matricula_limpia,)
    ).fetchone()

    conn.close()

    return render_template(
        'dashboard.html',
        matricula=matricula_limpia,
        nombre=nombre_real,
        # Convertimos a diccionarios para que Jinja2 pueda usar | tojson sin fallar
        proyectores=[dict(p) for p in proyectores],
        mi_equipo=dict(mi_equipo) if mi_equipo else None
    )

@app.route('/pre_apartado/<int:proyector_id>/<matricula>', methods=['GET', 'POST'])
@requiere_sesion_alumno   # FIX #2 + #3
def pre_apartado(proyector_id, matricula):
    if tiene_proyector_activo(matricula):
        # FIX #16: flash + redirect en lugar de f-string con JS crudo
        flash('⚠️ YA TIENES UN EQUIPO. No puedes apartar otro hasta entregar el actual.', 'warning')
        return redirect(url_for('dashboard', matricula=matricula))

    if request.method == 'POST':
        # FIX #17: Validación y sanitización de entradas
        telefono = request.form.get('telefono', '').strip()[:20]
        salon    = request.form.get('salon',    '').strip()[:50]
        maestro  = request.form.get('maestro',  '').strip()[:100]

        try:
            horas = float(request.form.get('horas', 1))
            # Clamp al rango permitido
            horas = max(0.5, min(horas, CONFIG["MAX_HORAS_PRESTAMO"]))
        except (ValueError, TypeError):
            horas = 1.0

        # FIX #9: Guardamos fecha+hora completa para evitar bug de cambio de día
        hora_reserva = hora_mexico().strftime("%Y-%m-%d %H:%M")

        conn = get_db_connection()
        cursor = conn.execute(
            '''UPDATE proyectores
               SET estado='Reservado', usuario=?, telefono=?, salon=?,
                   maestro=?, hora_reserva=?, duracion_solicitada=?
               WHERE id=? AND estado='Disponible' ''',
            (matricula, telefono, salon, maestro, hora_reserva, horas, proyector_id)
        )
        conn.commit()

        # FIX #10: Verificar rowcount para detectar race condition
        if cursor.rowcount == 0:
            conn.close()
            flash('⚠️ El proyector ya no está disponible. Intenta con otro.', 'warning')
            return redirect(url_for('dashboard', matricula=matricula))

        conn.close()
        return redirect(url_for('dashboard', matricula=matricula))

    alumno      = obtener_alumno(matricula)
    nombre_real = desencriptar(alumno['nombre']).title() if alumno else "Alumno"

    conn = get_db_connection()
    try:
        docentes_db  = conn.execute("SELECT nombre FROM docentes ORDER BY nombre ASC").fetchall()
        lista_docentes = [d['nombre'] for d in docentes_db]
    except sqlite3.OperationalError:
        lista_docentes = []
    conn.close()

    return render_template(
        'formulario.html',
        proyector_id=proyector_id,
        matricula=matricula,
        nombre=nombre_real,
        docentes=lista_docentes
    )

@app.route('/api/mi_equipo')
def api_mi_equipo():
    """Endpoint autenticado: devuelve el proyector activo del alumno en sesión.
    Separa los datos privados (hora_reserva, hora_limite) de la API pública,
    evitando que /api/data exponga información sensible de otros usuarios."""
    matricula = session.get('matricula')
    if not matricula:
        return jsonify(None), 401
    conn = get_db_connection()
    p = conn.execute(
        '''SELECT id, estado, marca, modelo, hora_reserva, hora_limite
           FROM proyectores WHERE usuario = ?''',
        (matricula,)
    ).fetchone()
    conn.close()
    return jsonify(dict(p) if p else None)

@app.route('/cancelar_alumno/<int:proyector_id>/<matricula>', methods=['POST'])
@requiere_sesion_alumno   # FIX #2 + #11
def cancelar_alumno(proyector_id, matricula):
    # FIX: Ahora es POST — las acciones destructivas no deben ejecutarse con GET
    conn = get_db_connection()
    conn.execute(
        """UPDATE proyectores
           SET estado='Disponible', usuario=NULL, telefono=NULL, salon=NULL,
               maestro=NULL, hora_reserva=NULL, duracion_solicitada=0
           WHERE id=? AND usuario=?""",
        (proyector_id, matricula)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard', matricula=matricula))

# ═══════════════════════════════════════════════════════════════════════════════
# RUTAS ADMIN  (todas protegidas con @requiere_admin — FIX #7)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/admin')
def admin_login_page():
    if session.get('admin_logged'):
        return redirect(url_for('admin_panel'))
    return render_template('admin_login.html')

@app.route('/admin_auth', methods=['POST'])
@limiter.limit("5 per minute")   # FIX #14: Anti fuerza bruta en panel admin
def admin_auth():
    # NOTA: Las credenciales se mantienen como solicitó el usuario.
    # Se recomienda moverlas a .env en el futuro.
    if (request.form.get('usuario') == "SECADMIN2026" and
            request.form.get('password') == "Sec_Admin_202670@"):
        session['admin_logged'] = True
        session.permanent = True
        return redirect(url_for('admin_panel'))
    return "Password incorrecto <a href='/admin'>Volver</a>"

@app.route('/admin_panel')
@requiere_admin
def admin_panel():
    liberar_reservas_vencidas()
    conn = get_db_connection()
    proyectores = conn.execute('SELECT * FROM proyectores').fetchall()
    conn.close()
    return render_template(
        'admin_panel.html',
        proyectores=[dict(p) for p in proyectores],
        config=CONFIG
    )

@app.route('/api/estadisticas')
@requiere_admin   # FIX #7
def api_estadisticas():
    conn = get_db_connection()

    try:
        total_prestamos = conn.execute('SELECT COUNT(*) FROM historial').fetchone()[0]
    except sqlite3.OperationalError:
        total_prestamos = 0

    stats_totales = {
        "prestamos": total_prestamos,
        "hojas":     total_prestamos,
        "pesos":     round(total_prestamos * 0.80, 2),
        "co2_kg":    round((total_prestamos * 15) / 1000, 2)
    }

    labels = []
    data_mensual = []
    ahora       = hora_mexico()
    mes_actual  = ahora.month
    anio_actual = ahora.year

    for i in range(11, -1, -1):
        mes_target  = mes_actual - i
        anio_target = anio_actual

        while mes_target <= 0:
            mes_target  += 12
            anio_target -= 1

        nombre_mes  = f"{MESES_ESP[mes_target - 1]} {anio_target}"
        mes_anio_db = f"{mes_target:02d}/{anio_target:04d}"

        try:
            cantidad = conn.execute(
                "SELECT COUNT(*) FROM historial WHERE fecha LIKE ?",
                (f"%{mes_anio_db}%",)
            ).fetchone()[0]
        except sqlite3.OperationalError:
            cantidad = 0

        labels.append(nombre_mes)
        data_mensual.append(cantidad)

    conn.close()

    return jsonify({
        "totales": stats_totales,
        "mensual": {"labels": labels, "data": data_mensual}
    })

@app.route('/admin/agregar_alumno', methods=['POST'])
@requiere_admin   # FIX #7
def agregar_alumno():
    matricula   = request.form.get('matricula', '').strip().upper()[:20]
    nombre_real = request.form.get('nombre', '').strip().upper()[:150]

    if not matricula or not nombre_real:
        return redirect(url_for('admin_panel', alerta='datos_invalidos'))

    # FIX #18: Abortar explícitamente si el cifrador no está disponible
    if not cifrador:
        app.logger.error("Cifrador no disponible. No se puede registrar al alumno de forma segura.")
        return redirect(url_for('admin_panel', alerta='error_cifrado'))

    nombre_seguro = cifrador.encrypt(nombre_real.encode()).decode()

    conn    = get_db_connection()
    existe  = conn.execute(
        "SELECT id FROM alumnos WHERE matricula = ?", (matricula,)
    ).fetchone()

    if existe:
        conn.close()
        return redirect(url_for('admin_panel', alerta='duplicado'))

    try:
        conn.execute(
            'INSERT INTO alumnos (matricula, nombre, strikes, bloqueado) VALUES (?, ?, 0, 0)',
            (matricula, nombre_seguro)
        )
    except sqlite3.OperationalError:
        conn.execute(
            'INSERT INTO alumnos (matricula, nombre) VALUES (?, ?)',
            (matricula, nombre_seguro)
        )

    conn.commit()
    conn.close()
    return redirect(url_for('admin_panel', alerta='exito'))

# ─── SISTEMA DE BLOQUEO MANUAL ────────────────────────────────────────────────

@app.route('/admin/pre_bloqueo', methods=['POST'])
@requiere_admin
def pre_bloqueo():
    matricula = request.form.get('matricula', '').strip().upper()

    conn   = get_db_connection()
    alumno = conn.execute(
        "SELECT * FROM alumnos WHERE matricula = ?", (matricula,)
    ).fetchone()
    conn.close()

    if alumno:
        nombre_real = desencriptar(alumno['nombre']).title()
        return render_template(
            'confirmar_bloqueo.html',
            matricula=matricula,
            nombre=nombre_real,
            estado=alumno['bloqueado']
        )
    else:
        # FIX #16: flash + redirect en lugar de f-string con JS y datos del usuario
        flash(f'❌ La matrícula {matricula} no está registrada en la base de datos.', 'error')
        return redirect(url_for('admin_panel'))

@app.route('/admin/ejecutar_bloqueo/<matricula>', methods=['POST'])
@requiere_admin
def ejecutar_bloqueo(matricula):
    # FIX: Convertido a POST — acción destructiva
    conn = get_db_connection()
    conn.execute("UPDATE alumnos SET bloqueado = 1 WHERE matricula = ?", (matricula,))
    conn.commit()
    conn.close()

    # FIX #16: flash + redirect
    flash(f'✅ El alumno {matricula} ha sido BLOQUEADO con éxito.', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/desbloquear/<matricula>', methods=['POST'])
@requiere_admin
def desbloquear_alumno(matricula):
    conn = get_db_connection()
    conn.execute(
        "UPDATE alumnos SET bloqueado = 0, strikes = 0 WHERE matricula = ?",
        (matricula,)
    )
    conn.commit()
    conn.close()

    # FIX #16: flash + redirect
    flash(f'✅ El alumno {matricula} ha sido DESBLOQUEADO y sus strikes reiniciados.', 'success')
    return redirect(url_for('admin_panel'))

# ─── GESTIÓN DE PRÉSTAMOS (BOTONES ADMIN) ─────────────────────────────────────

@app.route('/admin/entregar/<int:p_id>', methods=['POST'])
@requiere_admin   # FIX #7
def admin_entregar(p_id):
    # FIX: Convertido a POST — acción que modifica estado no debe ejecutarse con GET
    conn = get_db_connection()
    p    = conn.execute(
        'SELECT duracion_solicitada FROM proyectores WHERE id=?', (p_id,)
    ).fetchone()

    if p:
        horas       = p['duracion_solicitada'] if p['duracion_solicitada'] else 2
        ahora       = hora_mexico()
        hora_limite = (ahora + datetime.timedelta(hours=horas)).strftime("%H:%M")
        conn.execute(
            "UPDATE proyectores SET estado='En Uso', hora_limite=? WHERE id=?",
            (hora_limite, p_id)
        )
        conn.commit()
    conn.close()
    return redirect(url_for('admin_panel'))

@app.route('/admin/prestamo_docente', methods=['POST'])
@requiere_admin   # FIX #7
def prestamo_docente():
    p_id           = request.form.get('p_id')
    # FIX #17: Limitar longitud del nombre de docente
    nombre_docente = request.form.get('nombre_docente', '').strip().upper()[:100]

    ahora       = hora_mexico()
    hora_limite = (ahora + datetime.timedelta(hours=2)).strftime("%H:%M")

    conn = get_db_connection()
    conn.execute(
        """UPDATE proyectores
           SET estado='En Uso', usuario=?, maestro=?, hora_limite=?
           WHERE id=? AND (estado='Disponible' OR estado='Reservado')""",
        (f"DOCENTE: {nombre_docente}", nombre_docente, hora_limite, p_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('admin_panel'))

@app.route('/admin/checklist/<int:p_id>')
@requiere_admin
def admin_checklist(p_id):
    conn = get_db_connection()
    p    = conn.execute('SELECT * FROM proyectores WHERE id=?', (p_id,)).fetchone()
    conn.close()
    return render_template('checklist.html', p=p)

@app.route('/admin/finalizar_devolucion', methods=['POST'])
@requiere_admin
def admin_finalizar():
    p_id           = int(request.form['p_id'])
    aplicar_strike = request.form.get('aplicar_strike')
    # FIX: 'marcar_retraso' es ahora un campo separado — antes compartía
    # name="aplicar_strike" con la incidencia, lo que impedía distinguir ambos casos.
    marcar_retraso = request.form.get('marcar_retraso')

    conn = get_db_connection()
    p    = conn.execute("SELECT * FROM proyectores WHERE id=?", (p_id,)).fetchone()

    if p and p['usuario']:
        matricula     = p['usuario']
        telefono      = p['telefono'] if p['telefono'] else "N/A"
        maestro_clase = p['maestro']  if p['maestro']  else "N/A"

        alumno_db     = conn.execute(
            "SELECT nombre FROM alumnos WHERE matricula = ?", (matricula,)
        ).fetchone()
        nombre_alumno = desencriptar(alumno_db['nombre']).title() if alumno_db else matricula

        ahora      = hora_mexico()
        fecha_full = ahora.strftime("%d/%m/%Y %H:%M")

        estatus = "Perfecto"
        sancion = "No se aplicaron sanciones"

        if aplicar_strike:
            estatus = "⚠️ Daño / Incidencia en entrega"
            sancion = "🛑 Strike Impuesto"
            if "DOCENTE" not in matricula:
                conn.execute(
                    "UPDATE alumnos SET strikes = strikes + 1 WHERE matricula = ?",
                    (matricula,)
                )
                # FIX #13: Bloqueo automático al alcanzar el umbral de strikes
                alumno_act = conn.execute(
                    "SELECT strikes FROM alumnos WHERE matricula = ?", (matricula,)
                ).fetchone()
                if alumno_act and alumno_act['strikes'] >= 3:
                    conn.execute(
                        "UPDATE alumnos SET bloqueado = 1 WHERE matricula = ?",
                        (matricula,)
                    )
                    app.logger.info(
                        f"Alumno {matricula} bloqueado automáticamente por alcanzar 3 strikes."
                    )
        elif marcar_retraso:
            # Retraso registrado sin strike — solo nota en historial
            estatus = "⚠️ Entrega con retraso"
            sancion = "⚠️ Retraso registrado (sin strike)"

        try:
            conn.execute(
                '''INSERT INTO historial
                       (fecha, matricula, nombre, proyector, estatus, sancion, telefono, docente_clase)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (fecha_full, matricula, nombre_alumno, f"#{p_id}",
                 estatus, sancion, telefono, maestro_clase)
            )
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE historial ADD COLUMN telefono TEXT DEFAULT 'N/A'")
            conn.execute("ALTER TABLE historial ADD COLUMN docente_clase TEXT DEFAULT 'N/A'")
            conn.execute(
                '''INSERT INTO historial
                       (fecha, matricula, nombre, proyector, estatus, sancion, telefono, docente_clase)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (fecha_full, matricula, nombre_alumno, f"#{p_id}",
                 estatus, sancion, telefono, maestro_clase)
            )

    conn.execute(
        "UPDATE proyectores SET estado='Disponible', usuario=NULL, telefono=NULL, salon=NULL, maestro=NULL WHERE id=?",
        (p_id,)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('admin_panel'))

@app.route('/admin/historial')
@requiere_admin
def admin_historial():
    conn = get_db_connection()

    search_query = request.args.get('q', '').strip()

    # FIX #20: Validar y sanear el parámetro page
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    per_page = 50
    offset   = (page - 1) * per_page

    if search_query:
        wildcard = f"%{search_query}%"
        registros = conn.execute(
            '''SELECT * FROM historial
               WHERE matricula LIKE ? OR nombre LIKE ? OR proyector LIKE ? OR fecha LIKE ?
               ORDER BY id DESC LIMIT ? OFFSET ?''',
            (wildcard, wildcard, wildcard, wildcard, per_page, offset)
        ).fetchall()
        total_records = conn.execute(
            '''SELECT COUNT(*) FROM historial
               WHERE matricula LIKE ? OR nombre LIKE ? OR proyector LIKE ? OR fecha LIKE ?''',
            (wildcard, wildcard, wildcard, wildcard)
        ).fetchone()[0]
    else:
        registros     = conn.execute(
            'SELECT * FROM historial ORDER BY id DESC LIMIT ? OFFSET ?',
            (per_page, offset)
        ).fetchall()
        total_records = conn.execute('SELECT COUNT(*) FROM historial').fetchone()[0]

    conn.close()

    total_pages = max(1, math.ceil(total_records / per_page))

    return render_template(
        'historial.html',
        registros=registros,
        page=page,
        total_pages=total_pages,
        search_query=search_query
    )

@app.route('/admin/cancelar/<int:p_id>', methods=['POST'])
@requiere_admin   # FIX #7
def admin_cancelar(p_id):
    # FIX: Convertido a POST
    conn = get_db_connection()
    conn.execute(
        """UPDATE proyectores
           SET estado='Disponible', usuario=NULL, telefono=NULL, salon=NULL,
               maestro=NULL, hora_reserva=NULL, duracion_solicitada=0
           WHERE id=?""",
        (p_id,)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('admin_panel'))

# ─── INVENTARIO ───────────────────────────────────────────────────────────────

@app.route('/admin/agregar_proyector', methods=['POST'])
@requiere_admin   # FIX #7
def agregar_proyector():
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO proyectores (estado, serie, marca, color, modelo, duracion_solicitada) "
        "VALUES ('Disponible', 'S/N', 'Generico', '-', '-', 0)"
    )
    conn.commit()
    conn.close()
    return redirect(url_for('admin_panel'))

@app.route('/admin/extender_tiempo', methods=['POST'])
@requiere_admin   # FIX #7
def extender_tiempo():
    p_id      = request.form.get('p_id')
    nueva_hora = request.form.get('nueva_hora')

    if p_id and nueva_hora:
        conn = get_db_connection()
        try:
            conn.execute(
                "UPDATE proyectores SET hora_limite=? WHERE id=?",
                (nueva_hora, p_id)
            )
            conn.commit()
        except Exception as e:
            # FIX #19: Logging en lugar de except: pass
            app.logger.error(f"Error al extender tiempo: {e}")
        finally:
            conn.close()

    return redirect(url_for('admin_panel'))

@app.route('/admin/editar_proyector/<int:p_id>', methods=['GET', 'POST'])
@requiere_admin
def editar_proyector(p_id):
    conn = get_db_connection()

    try:
        conn.execute("ALTER TABLE proyectores ADD COLUMN foto TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # La columna ya existe — esto es seguro ignorar

    if request.method == 'POST':
        # FIX #17: Limitar longitud de todos los campos
        marca  = request.form.get('marca',  '').strip()[:100]
        modelo = request.form.get('modelo', '').strip()[:100]
        serie  = request.form.get('serie',  '').strip()[:100]
        color  = request.form.get('color',  '').strip()[:50]

        foto = request.files.get('foto')
        if foto and foto.filename != '':
            # FIX #15: Validar extensión
            if not allowed_file(foto.filename):
                conn.close()
                flash('Tipo de archivo no permitido. Solo PNG, JPG o WEBP.', 'error')
                return redirect(url_for('editar_proyector', p_id=p_id))

            # FIX #15: Validar magic bytes (contenido real del archivo)
            header = foto.read(12)
            foto.seek(0)
            if not validar_magic_bytes(header):
                conn.close()
                flash('El contenido del archivo no corresponde a una imagen válida.', 'error')
                return redirect(url_for('editar_proyector', p_id=p_id))

            filename = secure_filename(f"proyector_{p_id}_{foto.filename}")
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            foto.save(filepath)

            conn.execute(
                'UPDATE proyectores SET marca=?, modelo=?, serie=?, color=?, foto=? WHERE id=?',
                (marca, modelo, serie, color, filename, p_id)
            )
        else:
            conn.execute(
                'UPDATE proyectores SET marca=?, modelo=?, serie=?, color=? WHERE id=?',
                (marca, modelo, serie, color, p_id)
            )

        conn.commit()
        conn.close()
        return redirect(url_for('admin_panel'))

    p = conn.execute('SELECT * FROM proyectores WHERE id=?', (p_id,)).fetchone()
    conn.close()

    if p:
        return render_template('editar_proyector.html', p=p)
    return "No encontrado", 404

@app.route('/admin/eliminar/<int:p_id>', methods=['POST'])
@requiere_admin
def eliminar_proyector(p_id):
    # FIX: Convertido a POST — eliminación no debe ejecutarse con GET
    conn = get_db_connection()
    conn.execute('DELETE FROM proyectores WHERE id=?', (p_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_panel'))

@app.route('/admin/toggle_mantenimiento/<int:p_id>', methods=['POST'])
@requiere_admin   # FIX #7
def toggle_mantenimiento(p_id):
    # FIX: Convertido a POST
    conn = get_db_connection()
    p    = conn.execute('SELECT estado FROM proyectores WHERE id=?', (p_id,)).fetchone()
    nuevo = 'Disponible' if p['estado'] == 'Mantenimiento' else 'Mantenimiento'
    conn.execute('UPDATE proyectores SET estado=? WHERE id=?', (nuevo, p_id))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_panel'))

@app.route('/admin/config', methods=['POST'])
@requiere_admin   # FIX #7
def admin_config():
    try:
        CONFIG["TIEMPO_ESPERA_MINUTOS"] = int(request.form['tiempo_espera'])
    except (ValueError, KeyError) as e:
        app.logger.warning(f"Parámetro de configuración inválido: {e}")
    return redirect(url_for('admin_panel'))

# ─── ARRANQUE ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # FIX #8: debug=False y sin host='0.0.0.0' para evitar exposición del debugger
    app.run(debug=False, port=5000)
