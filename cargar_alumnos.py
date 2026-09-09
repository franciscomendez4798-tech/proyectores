import sqlite3
import os

# --- DATOS INICIALES ---
lista_alumnos = [
    ("A123", "ADMINISTRADOR PRUEBA"),
    ("A2223330256", "JUAN PEREZ"),
    ("A213", "MARIA LOPEZ")
]

# Proyectores iniciales (ID, Estado, Serie, Marca, Color, Modelo)
proyectores_base = [
    (1, 'Disponible', 'EPS-001', 'Epson', 'Blanco', 'PowerLite'),
    (5, 'Disponible', 'SNY-992', 'Sony', 'Negro', 'VPL-DX'),
    (6, 'Disponible', 'EPS-001', 'Epson', 'Blanco', 'PowerLite'),
    (7, 'Disponible', 'EPS-001', 'Epson', 'Blanco', 'PowerLite'),
    (8, 'Disponible', 'EPS-001', 'Epson', 'Blanco', 'PowerLite'),
    (9, 'Disponible', 'EPS-001', 'Epson', 'Blanco', 'PowerLite'),
    (10, 'Disponible', 'EPS-001', 'Epson', 'Blanco', 'PowerLite'),
    (11, 'Disponible', 'EPS-001', 'Epson', 'Blanco', 'PowerLite')
]

def inicializar_db():
    print("🚧 Iniciando construcción de base de datos...")

    # Si quieres empezar de cero limpio, descomenta la siguiente linea:
    # if os.path.exists("uat.db"): os.remove("uat.db")

    conn = sqlite3.connect('uat.db')
    cursor = conn.cursor()

    # 1. TABLA ALUMNOS
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alumnos (
            matricula TEXT PRIMARY KEY,
            nombre TEXT
        )
    ''')

    # 2. TABLA PROYECTORES (Esta es la que te faltaba)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS proyectores (
            id INTEGER PRIMARY KEY,
            estado TEXT DEFAULT 'Disponible',
            usuario TEXT,
            telefono TEXT,
            salon TEXT,
            maestro TEXT,
            serie TEXT,
            marca TEXT,
            color TEXT,
            modelo TEXT,
            hora_reserva TEXT,
            hora_limite TEXT,
            duracion_solicitada INTEGER
        )
    ''')

    # 3. INSERTAR DATOS
    print("📥 Insertando alumnos...")
    cursor.executemany('INSERT OR IGNORE INTO alumnos VALUES (?, ?)', lista_alumnos)

    print("📽️ Verificando proyectores...")
    cursor.execute("SELECT count(*) FROM proyectores")
    if cursor.fetchone()[0] == 0:
        print("   -> Creando inventario inicial...")
        cursor.executemany('''
            INSERT INTO proyectores (id, estado, serie, marca, color, modelo, duracion_solicitada)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        ''', proyectores_base)
    else:
        print("   -> El inventario ya existe. No se hicieron cambios.")

    conn.commit()
    conn.close()
    print("✅ ¡LISTO! Base de datos 'uat.db' creada correctamente.")

if __name__ == "__main__":
    inicializar_db()