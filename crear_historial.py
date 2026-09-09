import sqlite3

def crear_tabla_historial():
    print("🚧 Creando tabla de Historial...")
    conn = sqlite3.connect('uat.db')
    cursor = conn.cursor()

    # Creamos la tabla si no existe
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historial (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            matricula TEXT,
            nombre TEXT,
            estatus TEXT,
            sancion TEXT
        )
    ''')

    conn.commit()
    conn.close()
    print("✅ Tabla de historial lista para registrar entregas.")

if __name__ == "__main__":
    crear_tabla_historial()