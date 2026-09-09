import sqlite3
import os
from cryptography.fernet import Fernet

def instalar_blindaje():
    print("🛡️ Iniciando Protocolo de Seguridad...")

    # 1. Generar la Llave Maestra
    llave = Fernet.generate_key()
    cifrador = Fernet(llave)

    # 2. Guardar la llave en un archivo oculto .env
    with open('.env', 'w') as f:
        f.write(f"LLAVE_MAESTRA={llave.decode()}\n")
    print("✅ Llave Maestra generada y guardada en el archivo oculto '.env'")

    # 3. Conectar a la base de datos
    conn = sqlite3.connect('uat.db')
    cursor = conn.cursor()

    # 4. Encriptar nombres de la matriz de alumnos
    alumnos = cursor.execute("SELECT matricula, nombre FROM alumnos").fetchall()

    for matricula, nombre in alumnos:
        # Verificamos que el nombre no esté vacío y no esté ya encriptado (empiezan con gAAAA)
        if nombre and not nombre.startswith('gAAAA'):
            nombre_cifrado = cifrador.encrypt(nombre.encode()).decode()
            cursor.execute("UPDATE alumnos SET nombre = ? WHERE matricula = ?", (nombre_cifrado, matricula))

    conn.commit()
    conn.close()
    print("✅ Base de datos de alumnos encriptada con éxito.")
    print("⚠️ IMPORTANTE: El archivo .env contiene tu llave. Nunca lo borres.")

if __name__ == '__main__':
    instalar_blindaje()