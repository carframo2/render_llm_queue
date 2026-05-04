#!/usr/bin/env python3
"""
Bridge MCP en Render
Cola de tareas con SQLite + long polling
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import uuid
import time
from datetime import datetime
import json

app = Flask(__name__)
CORS(app)

# Token de autenticación
AUTH_TOKEN = "kienzan"

DB_FILE = "bridge_tasks.db"


def init_db():
    """Inicializar base de datos SQLite"""
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
            timeout INTEGER DEFAULT 30
        )
    """)
    conn.commit()
    conn.close()


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
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT procesado, respuesta FROM tareas WHERE id = ?", (tarea_id,))
        row = c.fetchone()
        conn.close()
        
        if row and row[0] == 1:  # procesado
            respuesta = json.loads(row[1]) if row[1] else {}
            return jsonify({
                "status": "completed",
                "tarea_id": tarea_id,
                "respuesta": respuesta
            })
        
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
        SET procesado = 1, respuesta = ?
        WHERE id = ?
    """, (json.dumps(respuesta), tarea_id))
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


if __name__ == '__main__':
    init_db()
    # En Render usa port del environment
    import os
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
