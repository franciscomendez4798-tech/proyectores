import sqlite3

# Conectar (o crear) la base de datos
conn = sqlite3.connect('uat.db')
cursor = conn.cursor()

# 1. Crear tabla de ALUMNOS (Matrículas permitidas)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS alumnos (
        matricula TEXT PRIMARY KEY,
        nombre TEXT
    )
''')

# 2. Insertar matrículas reales (Carga masiva)
# Aquí es donde pegarías todas las matrículas que te pase la escuela
lista_alumnos = [
    ("A2223330256", "Alumno Ejemplo"),
    ("A1234567890", "Juan Perez"),  # Ejemplo extra
]

# Insertamos, ignorando si ya existen (OR IGNORE)
cursor.executemany('INSERT OR IGNORE INTO alumnos VALUES (?, ?)', lista_alumnos)

conn.commit()
conn.close()
print("✅ Base de datos de alumnos creada con éxito.")
