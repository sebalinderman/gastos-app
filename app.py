import os, json, sqlite3
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__, static_folder='static')
CORS(app)

DB_PATH = os.environ.get('DB_PATH', 'gastos.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── STATIC ────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

# ── HISTORIAL ─────────────────────────────────────────────────────
@app.route('/api/historial')
def get_historial():
    conn = get_db()
    rows = conn.execute("""
        SELECT id, fecha, año, mes, planilla, concepto, item,
               monto, tipo, medio_pago, comentario, pagado_por, reembolsado
        FROM movimientos ORDER BY fecha DESC, id DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/historial/<int:id>', methods=['PUT'])
def update_movimiento(id):
    data = request.json
    conn = get_db()
    conn.execute("""
        UPDATE movimientos SET
            fecha=?, año=?, mes=?, planilla=?, concepto=?, item=?,
            monto=?, tipo=?, medio_pago=?, comentario=?, pagado_por=?
        WHERE id=?
    """, (
        data.get('fecha'), data.get('año'), data.get('mes'),
        data.get('planilla'), data.get('concepto'), data.get('item'),
        data.get('monto'), data.get('tipo'), data.get('medio_pago'),
        data.get('comentario'), data.get('pagado_por'), id
    ))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/historial', methods=['POST'])
def add_movimientos():
    """Confirmar movimientos pendientes - guardar en DB"""
    movs = request.json  # lista de movimientos
    conn = get_db()
    ids = []
    for m in movs:
        fecha = m.get('fecha', datetime.now().strftime('%Y-%m-%d'))
        año = int(fecha[:4]) if fecha else datetime.now().year
        mes = int(fecha[5:7]) if fecha else datetime.now().month
        cur = conn.execute("""
            INSERT INTO movimientos (fecha, año, mes, planilla, concepto, item,
                monto, tipo, medio_pago, comentario, pagado_por)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            fecha, año, mes,
            m.get('planilla','personal'), m.get('concepto'), m.get('item'),
            m.get('monto',0), m.get('tipo','gasto'),
            None, m.get('descripcion'), m.get('pagado_por')
        ))
        ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'ids': ids})

@app.route('/api/historial/bulk', methods=['PUT'])
def bulk_update():
    """Renombrar concepto o ítem en masa"""
    data = request.json
    tipo = data.get('tipo')  # 'concepto' o 'item'
    planilla = data.get('planilla')
    viejo = data.get('viejo')
    nuevo = data.get('nuevo')
    concepto_padre = data.get('concepto')  # solo para items

    conn = get_db()
    if tipo == 'concepto':
        conn.execute("""
            UPDATE movimientos SET concepto=?
            WHERE planilla=? AND concepto=?
        """, (nuevo, planilla, viejo))
    elif tipo == 'item':
        conn.execute("""
            UPDATE movimientos SET item=?
            WHERE planilla=? AND concepto=? AND item=?
        """, (nuevo, planilla, concepto_padre, viejo))
    affected = conn.execute('SELECT changes()').fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'affected': affected})

# ── DATOS AGREGADOS ───────────────────────────────────────────────
@app.route('/api/data')
def get_data():
    """Devuelve todos los datos agregados para el dashboard"""
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from build_data import build_all_data
    data = build_all_data(DB_PATH)
    return jsonify(data)

# ── DUPLICADOS ────────────────────────────────────────────────────
@app.route('/api/duplicados')
def get_duplicados():
    conn = get_db()
    rows = conn.execute("SELECT * FROM duplicados ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
