"""
build_data.py — genera todos los datos agregados desde SQLite
Se llama desde app.py en cada request /api/data (con cache opcional)
"""
import sqlite3, json
from datetime import datetime

PART = {'2201': 1.0, '1902': 0.5, '2103': 0.5}

def build_all_data(db_path='gastos.db'):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # ── Historial completo ─────────────────────────────────────────
    hist = []
    for r in conn.execute("""
        SELECT id, fecha, año, mes, planilla, concepto, item,
               monto, tipo, medio_pago, comentario, pagado_por, reembolsado
        FROM movimientos ORDER BY fecha DESC, id DESC
    """):
        hist.append(dict(r))

    # ── Meses disponibles ──────────────────────────────────────────
    meses_raw = conn.execute(
        "SELECT DISTINCT año, mes FROM movimientos WHERE planilla='personal' ORDER BY año, mes"
    ).fetchall()
    meses_all = [f"{r[0]}-{r[1]:02d}" for r in meses_raw]
    meses_18 = meses_all[-18:]

    meses_raw_c = conn.execute(
        "SELECT DISTINCT año, mes FROM movimientos WHERE planilla='casa' ORDER BY año, mes"
    ).fetchall()
    meses_all_casa = [f"{r[0]}-{r[1]:02d}" for r in meses_raw_c]
    meses_18_casa = meses_all_casa[-18:]

    # ── P&L Personal ───────────────────────────────────────────────
    pnl = {}
    for m in meses_all:
        año, mes_n = int(m[:4]), int(m[5:])
        sueldo = conn.execute("SELECT COALESCE(SUM(monto),0) FROM movimientos WHERE planilla='personal' AND subtipo='sueldo' AND año=? AND mes=?", (año,mes_n)).fetchone()[0]
        bono = conn.execute("SELECT COALESCE(SUM(monto),0) FROM movimientos WHERE planilla='personal' AND subtipo='bono_otro' AND año=? AND mes=?", (año,mes_n)).fetchone()[0]
        arr = conn.execute("SELECT concepto, COALESCE(SUM(monto),0) FROM movimientos WHERE planilla='personal' AND tipo='ingreso' AND subtipo LIKE 'arriendo_%' AND año=? AND mes=? GROUP BY concepto", (año,mes_n)).fetchall()
        hip = conn.execute("SELECT item, COALESCE(SUM(monto),0) FROM movimientos WHERE planilla='personal' AND subtipo='hipotecario' AND año=? AND mes=? GROUP BY item", (año,mes_n)).fetchall()
        adm = conn.execute("SELECT COALESCE(SUM(monto),0) FROM movimientos WHERE planilla='personal' AND subtipo='gasto_depto' AND año=? AND mes=?", (año,mes_n)).fetchone()[0]
        pnl[m] = {
            'sueldo': round(sueldo), 'bono': round(bono),
            'arriendos': {r[0].replace('Arriendo ',''): round(r[1]) for r in arr},
            'hipotecarios': {r[0].replace('Hipotecario ',''): round(r[1]) for r in hip},
            'gastos_admin': round(adm),
        }

    # ── Gastos operacionales ───────────────────────────────────────
    gastos_op = {}
    for m in meses_all:
        año, mes_n = int(m[:4]), int(m[5:])
        for r in conn.execute("""
            SELECT concepto, SUM(CASE WHEN tipo='gasto' THEN monto ELSE -monto END) as neto
            FROM movimientos WHERE planilla='personal' AND subtipo='operacional' AND año=? AND mes=?
            GROUP BY concepto
        """, (año,mes_n)):
            neto = round(r[1] or 0)
            if neto > 0:
                if m not in gastos_op: gastos_op[m] = {}
                gastos_op[m][r[0] or 'Otros'] = neto

    # ── Extraordinarios ────────────────────────────────────────────
    extras = {}
    for m in meses_all:
        año, mes_n = int(m[:4]), int(m[5:])
        for r in conn.execute("""
            SELECT item, SUM(monto) FROM movimientos
            WHERE planilla='personal' AND tipo='gasto' AND subtipo='extraordinario'
            AND año=? AND mes=? GROUP BY item
        """, (año,mes_n)):
            if r[1]:
                if m not in extras: extras[m] = {}
                extras[m][r[0] or 'Otros'] = round(r[1])

    # ── Inversiones ────────────────────────────────────────────────
    inversiones_ent = {}
    for m in meses_all[-18:]:
        año, mes_n = int(m[:4]), int(m[5:])
        aportes = {}
        rescates = {}
        for r in conn.execute("""
            SELECT comentario, SUM(monto) FROM movimientos
            WHERE planilla='personal' AND subtipo='hipotecario' AND año=? AND mes=?
            GROUP BY comentario
        """, (año,mes_n)):
            key = r[0] or 'Otros'
            for ent in ['Fintual','Toesca','Racional','Security','Budacom','Capitaria']:
                if ent.upper() in key.upper():
                    aportes[ent] = aportes.get(ent,0) + round(r[1] or 0)
                    break
            else:
                aportes['Otros'] = aportes.get('Otros',0) + round(r[1] or 0)
        for r in conn.execute("""
            SELECT comentario, SUM(monto) FROM movimientos
            WHERE planilla='personal' AND subtipo='rescate_fondo' AND año=? AND mes=?
            GROUP BY comentario
        """, (año,mes_n)):
            key = r[0] or 'Otros'
            for ent in ['Fintual','Toesca','Racional','Security','Budacom','Capitaria']:
                if ent.upper() in key.upper():
                    rescates[ent] = rescates.get(ent,0) + round(r[1] or 0)
                    break
            else:
                rescates['Otros'] = rescates.get('Otros',0) + round(r[1] or 0)
        if aportes or rescates:
            inversiones_ent[m] = {'aportes': aportes, 'rescates': rescates}

    # ── P&L Casa ───────────────────────────────────────────────────
    pnl_casa = {}
    OCIO = {'Comida Afuera','Panoramas','Viajes/Playa','Carrete'}
    for m in meses_all_casa:
        año, mes_n = int(m[:4]), int(m[5:])
        gastos_sin = {}
        gastos_ocio = {}
        for r in conn.execute("""
            SELECT concepto, SUM(CASE WHEN tipo='gasto' THEN monto ELSE -monto END) as neto
            FROM movimientos WHERE planilla='casa' AND año=? AND mes=?
            GROUP BY concepto
        """, (año,mes_n)):
            neto = round(r[1] or 0)
            if neto <= 0: continue
            c = r[0] or 'Otros'
            if c in OCIO: gastos_ocio[c] = neto
            else: gastos_sin[c] = neto
        tot_sin = sum(gastos_sin.values())
        tot_ocio = sum(gastos_ocio.values())
        pnl_casa[m] = {
            'gastos_sin_ocio': gastos_sin,
            'gastos_ocio': gastos_ocio,
            'total_sin_ocio': tot_sin,
            'total_ocio': tot_ocio,
            'total_gastos': tot_sin + tot_ocio,
            'seba': 0, 'bea': 0, 'total_aportes': 0, 'saldo': 0,
        }

    # ── Gastos Casa ────────────────────────────────────────────────
    gastos_casa = {}
    for m in meses_all_casa:
        año, mes_n = int(m[:4]), int(m[5:])
        sin_ocio = {}
        ocio = {}
        for r in conn.execute("""
            SELECT concepto, SUM(CASE WHEN tipo='gasto' THEN monto ELSE -monto END)
            FROM movimientos WHERE planilla='casa' AND año=? AND mes=?
            GROUP BY concepto
        """, (año,mes_n)):
            neto = round(r[1] or 0)
            if neto <= 0: continue
            c = r[0] or 'Otros'
            if c in OCIO: ocio[c] = neto
            else: sin_ocio[c] = neto
        gastos_casa[m] = {'sin_ocio': sin_ocio, 'ocio': ocio}

    # ── Items por mes (drill-down) ─────────────────────────────────
    items_personal = {}
    for r in conn.execute("""
        SELECT año, mes, concepto, item,
            SUM(CASE WHEN tipo='gasto' THEN monto ELSE -monto END) as neto
        FROM movimientos WHERE planilla='personal' AND subtipo='operacional'
        GROUP BY año, mes, concepto, item ORDER BY año, mes
    """):
        k = f"{r[0]}-{r[1]:02d}"
        c, it, neto = r[2] or 'Otros', r[3] or 'Otros', round(r[4] or 0)
        if neto <= 0: continue
        if k not in items_personal: items_personal[k] = {}
        if c not in items_personal[k]: items_personal[k][c] = {}
        items_personal[k][c][it] = items_personal[k][c].get(it, 0) + neto

    items_casa = {}
    for r in conn.execute("""
        SELECT año, mes, concepto, item,
            SUM(CASE WHEN tipo='gasto' THEN monto ELSE -monto END) as neto
        FROM movimientos WHERE planilla='casa'
        GROUP BY año, mes, concepto, item ORDER BY año, mes
    """):
        k = f"{r[0]}-{r[1]:02d}"
        c, it, neto = r[2] or 'Otros', r[3] or 'Otros', round(r[4] or 0)
        if neto <= 0: continue
        if k not in items_casa: items_casa[k] = {}
        if c not in items_casa[k]: items_casa[k][c] = {}
        items_casa[k][c][it] = items_casa[k][c].get(it, 0) + neto

    # ── pm/cm resumen ──────────────────────────────────────────────
    pm = {}
    for r in conn.execute("SELECT año, mes, tipo, SUM(monto) FROM movimientos WHERE planilla='personal' GROUP BY año, mes, tipo"):
        k = f"{r[0]}-{r[1]:02d}"
        if k not in pm: pm[k] = {}
        pm[k][r[2]] = round(r[3] or 0)

    cm = {}
    for r in conn.execute("SELECT año, mes, tipo, SUM(monto) FROM movimientos WHERE planilla='casa' GROUP BY año, mes, tipo"):
        k = f"{r[0]}-{r[1]:02d}"
        if k not in cm: cm[k] = {}
        cm[k][r[2]] = round(r[3] or 0)

    conn.close()

    return {
        'hist': hist,
        'pm': pm, 'cm': cm,
        'pnl': pnl,
        'gastos_op': gastos_op,
        'extras': extras,
        'inversiones_ent': inversiones_ent,
        'pnl_casa': pnl_casa,
        'gastos_casa': gastos_casa,
        'items_personal': items_personal,
        'items_casa': items_casa,
        'meses_all': meses_all,
        'meses_18': meses_18,
        'meses_all_casa': meses_all_casa,
        'meses_18_casa': meses_18_casa,
        'reglas': [],
    }

if __name__ == '__main__':
    data = build_all_data()
    print(f"OK: {len(data['hist'])} registros, {len(data['meses_all'])} meses")
