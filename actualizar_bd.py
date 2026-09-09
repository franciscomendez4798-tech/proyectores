import sqlite3

def agregar_columnas_strikes():
    print("🚧 Actualizando estructura de la Base de Datos...")
    conn = sqlite3.connect('uat.db')
    cursor = conn.cursor()

    try:
        # Intentamos agregar la columna 'strikes'
        cursor.execute("ALTER TABLE alumnos ADD COLUMN strikes INTEGER DEFAULT 0")
        print("✅ Columna 'strikes' agregada.")
    except sqlite3.OperationalError:
        print("ℹ️ La columna 'strikes' ya existía.")

    try:
        # Intentamos agregar la columna 'bloqueado' (0 = No, 1 = Si)
        cursor.execute("ALTER TABLE alumnos ADD COLUMN bloqueado INTEGER DEFAULT 0")
        print("✅ Columna 'bloqueado' agregada.")
    except sqlite3.OperationalError:
        print("ℹ️ La columna 'bloqueado' ya existía.")

    conn.commit()
    conn.close()
    print("🚀 Base de datos lista para el sistema de sanciones.")

if __name__ == "__main__":
    agregar_columnas_strikes()