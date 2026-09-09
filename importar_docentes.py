import sqlite3
import pandas as pd

def importar_excel():
    print("⚙️ Leyendo archivo Excel...")
    try:
        # Leemos el excel
        df = pd.read_excel('docentes.xlsx')

        conn = sqlite3.connect('uat.db')

        # 1. Creamos la tabla de docentes si no existe
        conn.execute('''
            CREATE TABLE IF NOT EXISTS docentes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT UNIQUE
            )
        ''')

        # 2. Inyectamos los nombres limpios
        agregados = 0
        for index, row in df.iterrows():
            # Limpiamos el texto: quitamos espacios extra y forzamos mayúsculas
            nombre = str(row['Nombre']).strip().upper()

            if nombre and nombre != 'NAN':
                try:
                    conn.execute("INSERT INTO docentes (nombre) VALUES (?)", (nombre,))
                    agregados += 1
                except sqlite3.IntegrityError:
                    # Si el docente ya existe (es duplicado), lo ignoramos y seguimos
                    pass

        conn.commit()
        conn.close()
        print(f"✅ ¡Éxito! Se inyectaron {agregados} docentes nuevos a la base de datos de la FIANS.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == '__main__':
    importar_excel()