import sqlite3
import pandas as pd
import os

# --- CONFIGURACIÓN ---
ARCHIVO_EXCEL = 'alumnos.xlsx'
DB_NAME = 'uat.db'

def importar_alumnos():
    if not os.path.exists(ARCHIVO_EXCEL):
        print(f"❌ Error: No encuentro el archivo '{ARCHIVO_EXCEL}'")
        return

    print("⏳ Leyendo archivo Excel (esto puede tardar unos segundos)...")

    try:
        # Leemos el Excel. Asumimos que no tiene encabezados (header=None)
        # Columna 0 = Matrícula, Columna 1 = Nombre
        df = pd.read_excel(ARCHIVO_EXCEL, header=None)

        # Convertimos a una lista de tuplas para SQL
        # Limpiamos datos: Matrícula a mayúsculas y sin espacios, Nombre en mayúsculas
        datos_alumnos = []
        for index, row in df.iterrows():
            matricula = str(row[0]).strip().upper()
            nombre = str(row[1]).strip().upper()
            datos_alumnos.append((matricula, nombre))

        print(f"✅ Se encontraron {len(datos_alumnos)} alumnos en el Excel.")
        print("📥 Insertando en la Base de Datos...")

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Aseguramos que la tabla exista
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alumnos (
                matricula TEXT PRIMARY KEY,
                nombre TEXT
            )
        ''')

        # Insertamos o Actualizamos (Si la matrícula ya existe, actualiza el nombre)
        cursor.executemany('''
            INSERT INTO alumnos (matricula, nombre) VALUES (?, ?)
            ON CONFLICT(matricula) DO UPDATE SET nombre=excluded.nombre
        ''', datos_alumnos)

        conn.commit()
        conn.close()
        print("🎉 ¡ÉXITO! La base de datos ha sido actualizada con el padrón oficial.")

    except Exception as e:
        print(f"❌ Ocurrió un error crítico: {e}")

if __name__ == "__main__":
    importar_alumnos()