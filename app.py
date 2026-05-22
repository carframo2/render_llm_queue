#!/usr/bin/env python3
"""
Bridge MCP en Render
Cola de tareas con SQLite + long polling
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import sqlite3
import uuid
import time
from datetime import datetime
import json
import os
import sys
import base64

app = Flask(__name__)
CORS(app)

# Token de autenticación
AUTH_TOKEN = "kienzan"

# Path DB - usar /tmp en Render (efímero pero funcional)
DB_FILE = os.environ.get('DB_FILE', '/tmp/bridge_tasks.db')

# Log para debugging
def log(msg):
    print(f"[{datetime.now().isoformat()}] {msg}", file=sys.stderr, flush=True)

@app.route('/tareas/vaciar', methods=['GET'])
def vaciar_tareas():
    """
    Limpieza total: borra TODAS las tareas.
    Requiere auth Bearer.
    GET por comodidad.
    """
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM tareas")
    total_antes = c.fetchone()[0]

    c.execute("DELETE FROM tareas")
    deleted = c.rowcount

    conn.commit()
    conn.close()

    log(f"Tabla tareas vaciada por endpoint GET. Borradas: {deleted}")

    return jsonify({
        "status": "ok",
        "deleted": deleted,
        "total_antes": total_antes,
        "message": f"Tabla tareas limpiada. Borradas {deleted} tareas."
    })

def init_db():
    """Inicializar base de datos SQLite"""
    try:
        log(f"Inicializando DB en: {DB_FILE}")
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS tareas (
                id TEXT PRIMARY KEY,
                endpoint TEXT NOT NULL,
                method TEXT DEFAULT 'POST',
                parametros TEXT,
                procesado INTEGER DEFAULT 0,
                respuesta TEXT,
                timestamp REAL NOT NULL,
                timeout INTEGER DEFAULT 30,
                updated_at REAL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS imagenes (
                id TEXT PRIMARY KEY,
                mime_type TEXT NOT NULL,
                data BLOB NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        
        
        conn.commit()
        conn.close()
        log("DB inicializada correctamente")
    except Exception as e:
        log(f"ERROR inicializando DB: {e}")
        raise



def check_auth():
    """Verificar token Bearer"""
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return False
    token = auth_header[7:]
    return token == AUTH_TOKEN


@app.route('/health', methods=['GET'])
def health():
    """Health check sin auth"""
    return jsonify({"status": "ok", "timestamp": time.time()})


@app.route('/bridge', methods=['POST'])
def bridge():
    """
    Endpoint principal: recibe tarea y devuelve ID INMEDIATAMENTE (sin esperar)
    
    Body:
    {
        "endpoint": "/chat/marea",
        "method": "POST",
        "parametros": {...}
    }
    """
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    endpoint = data.get('endpoint')
    method = data.get('method', 'POST')
    parametros = data.get('parametros', {})
    
    if not endpoint:
        return jsonify({"error": "endpoint requerido"}), 400
    
    # Crear tarea
    tarea_id = str(uuid.uuid4())
    timestamp = time.time()
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO tareas (id, endpoint, method, parametros, timestamp, timeout)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tarea_id, endpoint, method, json.dumps(parametros), timestamp, 30))
    conn.commit()
    conn.close()
    
    log(f"Tarea creada: {tarea_id[:8]} → {method} {endpoint}")
    
    # Devolver ID INMEDIATAMENTE sin esperar
    return jsonify({
        "status": "created",
        "tarea_id": tarea_id,
        "message": "Tarea creada. Consultar /bridge/resultado/<tarea_id> para obtener resultado"
    }), 201


@app.route('/imagenes/guardar', methods=['POST'])
def guardar_imagen():
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json or {}

    image_b64 = data.get("image_base64")
    mime_type = data.get("mime_type", "image/png")

    if not image_b64:
        return jsonify({"error": "image_base64 requerido"}), 400

    if image_b64.startswith("data:image"):
        image_b64 = image_b64.split(",", 1)[1]

    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception as e:
        return jsonify({"error": f"base64 inválido: {e}"}), 400

    image_id = uuid.uuid4().hex

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO imagenes (id, mime_type, data, created_at)
        VALUES (?, ?, ?, ?)
    """, (image_id, mime_type, image_bytes, time.time()))
    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "image_id": image_id,
        "image_url": f"https://render-llm-queue.onrender.com/obtener_imagen/{image_id}.png"
    })


@app.route('/obtener_imagen/<image_id>.png', methods=['GET'])
def obtener_imagen(image_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT mime_type, data
        FROM imagenes
        WHERE id = ?
    """, (image_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Imagen no encontrada"}), 404

    mime_type, image_bytes = row

    return Response(
        image_bytes,
        mimetype=mime_type,
        headers={
            "Cache-Control": "public, max-age=3600"
        }
    )


@app.route('/bridge/resultado/<tarea_id>', methods=['GET'])
def resultado_tarea(tarea_id):
    """
    Consultar resultado de una tarea
    
    Devuelve:
    - status: pending | completed | not_found
    - respuesta: resultado si está completada
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT procesado, respuesta FROM tareas WHERE id = ?", (tarea_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return jsonify({
            "status": "not_found",
            "tarea_id": tarea_id
        }), 404
    
    procesado = row[0]
    respuesta_raw = row[1]
    
    if procesado:
        # Tarea completada
        try:
            respuesta = json.loads(respuesta_raw) if respuesta_raw else {}
        except:
            respuesta = {"error": "Error deserializando", "raw": str(respuesta_raw)[:500]}
        
        return jsonify({
            "status": "completed",
            "tarea_id": tarea_id,
            "respuesta": respuesta
        })
    else:
        # Tarea pendiente
        return jsonify({
            "status": "pending",
            "tarea_id": tarea_id,
            "message": "Tarea aún no procesada"
        }), 202


@app.route('/bridge_legacy', methods=['POST'])
def bridge_legacy():
    """
    Endpoint principal: recibe tarea y hace long polling
    
    Body:
    {
        "endpoint": "/chat/marea",
        "method": "POST",
        "parametros": {...},
        "timeout": 30
    }
    """
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    endpoint = data.get('endpoint')
    method = data.get('method', 'POST')
    parametros = data.get('parametros', {})
    timeout = data.get('timeout', 30)
    
    if not endpoint:
        return jsonify({"error": "endpoint requerido"}), 400
    
    # Crear tarea
    tarea_id = str(uuid.uuid4())
    timestamp = time.time()
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO tareas (id, endpoint, method, parametros, timestamp, timeout)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tarea_id, endpoint, method, json.dumps(parametros), timestamp, timeout))
    conn.commit()
    conn.close()
    
    # Long polling: esperar respuesta
    start_time = time.time()
    poll_interval = 0.5  # segundos
    
    while (time.time() - start_time) < timeout:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT procesado, respuesta FROM tareas WHERE id = ?", (tarea_id,))
            row = c.fetchone()
            conn.close()
            
            if row and row[0] == 1:  # procesado
                log(f"Tarea {tarea_id[:8]} encontrada procesada")
                
                # Deserializar respuesta con manejo de errores
                try:
                    if row[1]:
                        log(f"Respuesta raw (primeros 200 chars): {str(row[1])[:200]}")
                        respuesta = json.loads(row[1])
                    else:
                        log("Respuesta es None, usando dict vacío")
                        respuesta = {}
                except json.JSONDecodeError as e:
                    log(f"ERROR deserializando respuesta: {e}")
                    log(f"Respuesta problemática: {row[1]}")
                    respuesta = {"error": "Error deserializando respuesta", "raw": str(row[1])[:500]}
                
                return jsonify({
                    "status": "completed",
                    "tarea_id": tarea_id,
                    "respuesta": respuesta
                })
        
        except Exception as e:
            log(f"ERROR en long polling: {e}")
            # Continuar esperando a pesar del error
        
        time.sleep(poll_interval)
    
    # Timeout alcanzado
    return jsonify({
        "status": "timeout",
        "tarea_id": tarea_id,
        "message": f"Tarea no procesada en {timeout}s"
    }), 408


@app.route('/jobs_pendientes', methods=['GET'])
def jobs_pendientes():
    """
    Testing: ver todas las tareas pendientes
    No requiere auth para debugging rápido
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT id, endpoint, method, parametros, timestamp, timeout, procesado
        FROM tareas
        WHERE procesado = 0
        ORDER BY timestamp ASC
    """)
    rows = c.fetchall()
    conn.close()
    
    tareas = []
    for row in rows:
        tareas.append({
            "id": row[0],
            "endpoint": row[1],
            "method": row[2],
            "parametros": json.loads(row[3]) if row[3] else {},
            "timestamp": row[4],
            "timeout": row[5],
            "edad_segundos": round(time.time() - row[4], 1)
        })
    
    return jsonify({
        "total": len(tareas),
        "tareas": tareas
    })


@app.route('/tareas/pendientes', methods=['GET'])
def tareas_pendientes():
    """
    Daemon consume: obtener tareas pendientes para procesar
    Requiere auth
    """
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT id, endpoint, method, parametros
        FROM tareas
        WHERE procesado = 0
        ORDER BY timestamp ASC
    """)
    rows = c.fetchall()
    conn.close()
    
    tareas = []
    for row in rows:
        tareas.append({
            "id": row[0],
            "endpoint": row[1],
            "method": row[2],
            "parametros": json.loads(row[3]) if row[3] else {}
        })
    
    return jsonify({
        "total": len(tareas),
        "tareas": tareas
    })


@app.route('/tareas/completar', methods=['PUT'])
def completar_tarea():
    """
    Daemon reporta: marcar tarea como completada con respuesta
    
    Body:
    {
        "tarea_id": "uuid",
        "respuesta": {...}
    }
    """
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    tarea_id = data.get('tarea_id')
    respuesta = data.get('respuesta', {})
    
    if not tarea_id:
        return jsonify({"error": "tarea_id requerido"}), 400
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        UPDATE tareas
        SET procesado = 1, respuesta = ?, updated_at = ?
        WHERE id = ?
    """, (json.dumps(respuesta), time.time(), tarea_id))
    affected = c.rowcount
    conn.commit()
    conn.close()
    
    if affected == 0:
        return jsonify({"error": "Tarea no encontrada"}), 404
    
    return jsonify({
        "status": "ok",
        "tarea_id": tarea_id,
        "message": "Tarea completada"
    })


@app.route('/tareas/limpiar', methods=['POST'])
def limpiar_tareas():
    """
    Limpieza: borrar tareas procesadas antiguas
    Requiere auth
    """
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    max_age = request.json.get('max_age_seconds', 3600)  # 1 hora default
    cutoff = time.time() - max_age
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        DELETE FROM tareas
        WHERE procesado = 1 AND timestamp < ?
    """, (cutoff,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    
    return jsonify({
        "status": "ok",
        "deleted": deleted,
        "message": f"Borradas {deleted} tareas antiguas"
    })


@app.route('/stats', methods=['GET'])
def stats():
    """Estadísticas del bridge (sin auth para monitoring)"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM tareas WHERE procesado = 0")
    pendientes = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM tareas WHERE procesado = 1")
    completadas = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM tareas")
    total = c.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        "pendientes": pendientes,
        "completadas": completadas,
        "total": total,
        "timestamp": time.time()
    })


@app.route('/tareas/info/<tarea_id>', methods=['GET'])
def info_tarea(tarea_id):
    """
    Debugging: obtener info completa de una tarea con timestamps
    No requiere auth para debugging rápido
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT id, endpoint, method, parametros, procesado, respuesta, 
               timestamp, timeout, updated_at
        FROM tareas
        WHERE id = ?
    """, (tarea_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"error": "Tarea no encontrada"}), 404
    
    now = time.time()
    created_at = row[6]
    updated_at = row[8]
    
    info = {
        "id": row[0],
        "endpoint": row[1],
        "method": row[2],
        "parametros": json.loads(row[3]) if row[3] else {},
        "procesado": bool(row[4]),
        "respuesta": json.loads(row[5]) if row[5] else None,
        "timeout_config": row[7],
        "timestamps": {
            "created_at": created_at,
            "created_at_human": datetime.fromtimestamp(created_at).isoformat(),
            "updated_at": updated_at,
            "updated_at_human": datetime.fromtimestamp(updated_at).isoformat() if updated_at else None,
            "age_seconds": round(now - created_at, 2),
            "processing_time_seconds": round(updated_at - created_at, 2) if updated_at else None
        }
    }
    
    return jsonify(info)


# Inicializar DB al cargar módulo (CRÍTICO para Render)
init_db()

if __name__ == '__main__':
    # En Render usa port del environment
    import os
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
