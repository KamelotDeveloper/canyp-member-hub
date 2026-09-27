"""Seed the CANYP database with realistic test data.

Usage: python -m backend.seed
Idempotent: skips if socios already exist.
"""

from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import sessionmaker

from backend.database import Base, SessionLocal, engine as default_engine
from backend.models import (
    Area,
    CanalNotificacion,
    CategoriaParcela,
    ConceptoCobro,
    ConceptoMembresia,
    EstadoMembresia,
    Predio,
    RolMembresia,
    TipoParcela,
    Arancel,
    Membresia,
    Notificacion,
    Parcela,
    Pago,
    PagoItem,
    Socio,
)
from backend.services.cuota_social import crear_cuota_social
from backend.services.renovacion import dia10

# ── Parcelas ──────────────────────────────────────────────

PARCELAS = [
    # ── Almafuerte: cabañas (Cabañeros) ──
    {"id": "pa1", "nombre": "Cabaña A", "tipo": TipoParcela.CABANA, "tamano": "40m²", "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.CHICA, "cuotaSocialIncluida": False},
    {"id": "pa2", "nombre": "Cabaña B", "tipo": TipoParcela.CABANA, "tamano": "55m²", "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.MEDIANA, "cuotaSocialIncluida": False},
    {"id": "pa3", "nombre": "Cabaña C", "tipo": TipoParcela.CABANA, "tamano": "35m²", "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.CHICA, "cuotaSocialIncluida": False},
    {"id": "pa4", "nombre": "Cabaña D", "tipo": TipoParcela.CABANA, "tamano": "45m²", "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.MEDIANA, "cuotaSocialIncluida": False},
    {"id": "pa7", "nombre": "Cabaña E", "tipo": TipoParcela.CABANA, "tamano": "60m²", "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.ESPECIAL, "cuotaSocialIncluida": False},
    {"id": "pa8", "nombre": "Cabaña F", "tipo": TipoParcela.CABANA, "tamano": "70m²", "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.GRANDE, "cuotaSocialIncluida": False},
    # ── Almafuerte: guardería (cuota social opt-in, OFF — CS-04) ──
    {"id": "pa10", "nombre": "Guardería Chica", "tipo": TipoParcela.GUARDERIA, "tamano": None, "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.CHICA, "cuotaSocialIncluida": False},
    {"id": "pa11", "nombre": "Guardería Grande", "tipo": TipoParcela.GUARDERIA, "tamano": None, "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.GRANDE, "cuotaSocialIncluida": False},
    # ── Embalse: balsas (Balseros) ──
    {"id": "pa5", "nombre": "Balsa Principal", "tipo": TipoParcela.BALSA, "tamano": "12m", "predio": Predio.EMBALSE, "cuotaSocialIncluida": False},
    {"id": "pa6", "nombre": "Balsa Norte", "tipo": TipoParcela.BALSA, "tamano": "10m", "predio": Predio.EMBALSE, "cuotaSocialIncluida": False},
    {"id": "pa9", "nombre": "Balsa Sur", "tipo": TipoParcela.BALSA, "tamano": "11m", "predio": Predio.EMBALSE, "cuotaSocialIncluida": False},
]

# ── Socios ────────────────────────────────────────────────

SOCIOS = [
    {"id": "s1",  "nombre": "Martín González",      "dni": "30123456", "telefono": "3514567890", "email": "martin.gonzalez@gmail.com",     "direccion": "Av. General Paz 1234, Córdoba"},
    {"id": "s2",  "nombre": "Lucía Fernández",      "dni": "27987654", "telefono": "3516123456", "email": "lucia.fernandez@outlook.com",  "direccion": "Calle Urquiza 567, Córdoba"},
    {"id": "s3",  "nombre": "Carlos Rodríguez",     "dni": "32456789", "telefono": "3584561234", "email": "carlos.rodriguez@gmail.com",   "direccion": "Belgrano 890, Villa María"},
    {"id": "s4",  "nombre": "María López",          "dni": "25678901", "telefono": "3517123456", "email": "maria.lopez@yahoo.com",        "direccion": "San Martín 345, Córdoba"},
    {"id": "s5",  "nombre": "Juan Pérez",           "dni": "33789012", "telefono": "3534567890", "email": "juan.perez@gmail.com",         "direccion": "9 de Julio 210, Río Cuarto"},
    {"id": "s6",  "nombre": "Ana Martínez",         "dni": "31234567", "telefono": "3518123456", "email": "ana.martinez@hotmail.com",     "direccion": "Pellegrini 678, Córdoba"},
    {"id": "s7",  "nombre": "Roberto Sánchez",      "dni": "28345678", "telefono": "3585123456", "email": "roberto.sanchez@gmail.com",    "direccion": "Viamonte 456, Alta Gracia"},
    {"id": "s8",  "nombre": "Laura Díaz",           "dni": "34567890", "telefono": "3519123456", "email": "laura.diaz@outlook.com",       "direccion": "Mitre 901, Córdoba"},
    {"id": "s9",  "nombre": "Fernando García",      "dni": "29876543", "telefono": "3586123456", "email": "fernando.garcia@gmail.com",    "direccion": "Sarmiento 123, Jesús María"},
    {"id": "s10", "nombre": "Patricia Romero",      "dni": "31567890", "telefono": "3535123456", "email": "patricia.romero@gmail.com",    "direccion": "España 789, Villa Carlos Paz"},
    {"id": "s11", "nombre": "Diego Torres",         "dni": "36789012", "telefono": "3510123456", "email": "diego.torres@gmail.com",       "direccion": "Catamarca 456, Córdoba"},
    {"id": "s12", "nombre": "Valentina Ruiz",       "dni": "38123456", "telefono": "3511123456", "email": "valentina.ruiz@gmail.com",     "direccion": "Buenos Aires 321, Córdoba"},
]


def _today():
    return date.today()


def _build_membresias():
    """Build area membresias on the 10->10 cycle for a realistic dashboard.

    Every ``vencimiento`` is a day-10, so the seeded padron already lives on
    the monthly cycle instead of on legacy annual dates. ``v(n)`` = the day-10
    ``n`` months away from today, which yields the same three-way mix the
    dashboard needs under the 4-state model (AGENT.md §1):

    * ``v(0)``      -> the 10th of this or the next month, i.e. always al día,
    * ``v(>=2)``    -> far from expiry: al día,
    * ``v(<0)``     -> already past: the socio lands on ⚠️ (área vencida, cuota
      al día) or 🔴 (cuota vencida, because a cuota social inherits the socio's
      most recent área `vencimiento`).
    """
    t = _today()

    def v(meses: int) -> date:
        return dia10(t + relativedelta(months=meses))

    def area(socio, mid, a, p, meses, parcela=None, rol=None, estado=EstadoMembresia.ACTIVA):
        return {
            "id": mid,
            "socioId": socio,
            "area": a,
            "predio": p,
            "estado": estado,
            "concepto": ConceptoMembresia.AREA,
            "vencimiento": v(meses),
            "parcelaId": parcela,
            "rol": rol,
        }

    return [
        # ── Activa: lejos del vencimiento ──
        area("s1",  "m1",  Area.BALSEROS,  Predio.EMBALSE,    6,  "pa5", RolMembresia.TITULAR),
        area("s2",  "m2",  Area.CABANEROS, Predio.ALMAFUERTE, 12, "pa1", RolMembresia.TITULAR),
        area("s3",  "m3",  Area.GUARDERIA, Predio.ALMAFUERTE, 8,  "pa10"),
        # ── Activa: por vencer (dentro de los 30 días) ──
        area("s4",  "m4",  Area.BALSEROS,  Predio.EMBALSE,    0,  "pa5", RolMembresia.INTEGRANTE),
        area("s5",  "m5",  Area.WINDSURF,  Predio.ALMAFUERTE, 0),
        # ── Vencida (por fecha) ──
        area("s6",  "m6",  Area.CABANEROS, Predio.ALMAFUERTE, -1, "pa2", RolMembresia.TITULAR),
        area("s7",  "m7",  Area.BALSEROS,  Predio.EMBALSE,    -3, "pa6", RolMembresia.INTEGRANTE),
        # ── Vence mañana / este mes (borde) ──
        area("s8",  "m8",  Area.GUARDERIA, Predio.ALMAFUERTE, 0),
        # ── Suspendida ──
        area("s9",  "m9",  Area.WINDSURF,  Predio.ALMAFUERTE, 2,  estado=EstadoMembresia.SUSPENDIDA),
        area("s10", "m10", Area.CABANEROS, Predio.ALMAFUERTE, -1, "pa3", RolMembresia.INTEGRANTE, EstadoMembresia.SUSPENDIDA),
        # ── Baja ──
        area("s11", "m11", Area.BALSEROS,  Predio.EMBALSE,    -6, estado=EstadoMembresia.BAJA),
        # ── Más activas (distintas áreas) ──
        area("s12", "m12", Area.WINDSURF,  Predio.ALMAFUERTE, 7),
        area("s1",  "m13", Area.CABANEROS, Predio.ALMAFUERTE, 4,  "pa4", RolMembresia.TITULAR),
        area("s2",  "m14", Area.GUARDERIA, Predio.ALMAFUERTE, 3),
        area("s3",  "m15", Area.WINDSURF,  Predio.ALMAFUERTE, 0),
        area("s4",  "m16", Area.BALSEROS,  Predio.EMBALSE,    13, "pa6", RolMembresia.TITULAR),
        # ── Unidades compartidas Almafuerte (RQ16): Titular + Integrantes, vencimientos mezclados ──
        area("s5",  "m17", Area.CABANEROS, Predio.ALMAFUERTE, 0,  "pa3", RolMembresia.TITULAR),
        area("s12", "m18", Area.CABANEROS, Predio.ALMAFUERTE, -2, "pa4", RolMembresia.INTEGRANTE),
        area("s6",  "m19", Area.CABANEROS, Predio.ALMAFUERTE, -2, "pa7", RolMembresia.TITULAR),
        area("s8",  "m20", Area.CABANEROS, Predio.ALMAFUERTE, 7,  "pa7", RolMembresia.INTEGRANTE),
        area("s9",  "m21", Area.CABANEROS, Predio.ALMAFUERTE, 5,  "pa8", RolMembresia.TITULAR),
        area("s11", "m22", Area.CABANEROS, Predio.ALMAFUERTE, 0,  "pa8", RolMembresia.INTEGRANTE),
        area("s2",  "m23", Area.BALSEROS,  Predio.EMBALSE,    0,  "pa9", RolMembresia.TITULAR),
        area("s3",  "m24", Area.BALSEROS,  Predio.EMBALSE,    -1, "pa9", RolMembresia.INTEGRANTE),
        area("s8",  "m25", Area.GUARDERIA, Predio.ALMAFUERTE, 6,  "pa11"),
        area("s7",  "m26", Area.CABANEROS, Predio.ALMAFUERTE, 3,  "pa1", RolMembresia.INTEGRANTE),
        area("s4",  "m27", Area.CABANEROS, Predio.ALMAFUERTE, 0,  "pa2", RolMembresia.INTEGRANTE),
    ]


def _build_aranceles():
    """One arancel per area+predio combination with realistic ARS amounts.

    Concepto (nombre) describes what the cuota covers — it is a descriptor,
    not a separate amount. The total is a single item per unit/membresía.

    `a14` is the RECARGO **carrier** (ARA-01, CBM-03): its `monto` stays 0 and
    the per-charge amount is entered by the operator, so it never overwrites the
    catalog. Its area/predio are placeholders only — PR 5 resolves the recargo
    by `concepto`, never by area+predio, and no charge logic lives here.

    SERVICIO rows are PLACES, not concepts (D7 / ReQ-002): one per real place
    of the club, `categoria` NULL on all of them. That NULL is what makes one row
    price every unit of its place — a balsa's parcel has no `categoria`, and a
    cabaña's carries one (Chica/Mediana/Especial/Grande), so `categoria IS NULL`
    is the catch-all branch `precio_servicio` falls back to for every parcel size
    instead of pricing only the sizes a row was invented for.

    The three SERVICIO amounts below are DEMO values ("+ valores a configurar
    por admin") that the club admin configures in the catalog. They are NOT
    inferred from the amarre amount (ReQ-105), and the operator can override
    them per charge via `montoAplicado` (ReQ-010). They live in this docstring
    because `Arancel` has no `descripcion` column, and adding one would be a
    schema change this seed does not get to make.
    """
    t = _today()
    return [
        # ── Amarre: the mooring fee, on its own row. It used to be the merged
        #    "Amarre y Servicios" (D6); old receipts still carry that name and
        #    keep it frozen (ReQ-016).
        {"id": "a1", "nombre": "Amarre",                        "area": Area.BALSEROS,    "predio": Predio.EMBALSE,    "monto": 18500.0,  "vigenteDesde": t - timedelta(days=90), "historico": [{"monto": 15000.0, "vigenteDesde": str(t - timedelta(days=365))}]},
        {"id": "a7", "nombre": "Cuota",                        "area": Area.WINDSURF,    "predio": Predio.ALMAFUERTE, "monto": 19000.0,  "vigenteDesde": t - timedelta(days=15), "historico": []},
        # ── Almafuerte per-categoría aranceles (RQ13/RQ16: resolver_monto finds rows) ──
        {"id": "a8",  "nombre": "Parcela",                     "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.CHICA,    "monto": 15000.0, "vigenteDesde": t - timedelta(days=90), "historico": []},
        {"id": "a9",  "nombre": "Parcela",                     "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.MEDIANA,  "monto": 18500.0, "vigenteDesde": t - timedelta(days=90), "historico": []},
        {"id": "a10", "nombre": "Parcela",                     "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.ESPECIAL, "monto": 21000.0, "vigenteDesde": t - timedelta(days=60), "historico": []},
        {"id": "a11", "nombre": "Parcela",                     "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.GRANDE,   "monto": 25000.0, "vigenteDesde": t - timedelta(days=60), "historico": []},
        {"id": "a12", "nombre": "Cuota",                       "area": Area.GUARDERIA,   "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.CHICA,    "monto": 10000.0, "vigenteDesde": t - timedelta(days=30), "historico": []},
        {"id": "a13", "nombre": "Cuota",                       "area": Area.GUARDERIA,   "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.GRANDE,   "monto": 14000.0, "vigenteDesde": t - timedelta(days=30), "historico": []},
        # ── Recargo carrier: monto 0 by design, the operator types the amount ──
        {"id": "a14", "nombre": "Recargo",                     "area": Area.GUARDERIA,   "predio": Predio.ALMAFUERTE, "monto": 0.0,      "vigenteDesde": t - timedelta(days=30), "historico": [], "concepto": ConceptoCobro.RECARGO},
        # ── Cuota social UNIT PRICE: `monto` is ONE member; the charge
        #    multiplies it by the managed unit's member count (CS-03). Like the
        #    recargo carrier its area/predio are placeholders — the resolver
        #    finds it by `concepto` only, never by area+predio.
        {"id": "a15", "nombre": "Cuota social",                "area": Area.GUARDERIA,   "predio": Predio.ALMAFUERTE, "monto": 10000.0,  "vigenteDesde": t - timedelta(days=30), "historico": [], "concepto": ConceptoCobro.CUOTA_SOCIAL},
        # ── Servicio/luz: a REAL catalog price per PLACE, admin-editable
        #    (decision #646, D7). Unlike the recargo carrier these rows carry
        #    an amount, so a charge takes the catalog `monto` (which the
        #    operator may adjust for one charge) and never multiplies it by the
        #    member count. `categoria` is omitted (= NULL) on all three: the
        #    catch-all branch is the one every parcel size of the place lands
        #    on. The old global `a16` placeholder is gone — with per-place
        #    resolution it collided with real Guardería/Almafuerte (D6).
        {"id": "a_serv_balseros",  "nombre": "Servicio",     "area": Area.BALSEROS,  "predio": Predio.EMBALSE,    "monto": 5000.0,  "vigenteDesde": t - timedelta(days=30), "historico": [], "concepto": ConceptoCobro.SERVICIO},
        {"id": "a_serv_cabaneros", "nombre": "Servicio",     "area": Area.CABANEROS, "predio": Predio.ALMAFUERTE, "monto": 4000.0,  "vigenteDesde": t - timedelta(days=30), "historico": [], "concepto": ConceptoCobro.SERVICIO},
        {"id": "a_serv_guarderia", "nombre": "Servicio",     "area": Area.GUARDERIA, "predio": Predio.ALMAFUERTE, "monto": 2500.0,  "vigenteDesde": t - timedelta(days=30), "historico": [], "concepto": ConceptoCobro.SERVICIO},
    ]


def _build_pagos():
    """4 pagos with items, sequential numbers, recent dates.

    ``pi1``/``pi4`` keep the frozen ``"Amarre y Servicios"`` name on purpose:
    ``pago_items.arancelNombre`` is a receipt, not a catalog mirror, and the
    catalog no longer carries that name since the split (ReQ-016).
    """
    t = _today()
    return [
        {
            "pago": {"id": "p1", "numero": "0001-00000001", "socioId": "s1",  "fecha": t - timedelta(days=60), "medio": "efectivo",       "total": 18500.0},
            "items": [{"id": "pi1", "arancelId": "a1", "membresiaId": "m1",  "montoAplicado": 18500.0, "arancelNombre": "Amarre y Servicios"}],
        },
        {
            "pago": {"id": "p2", "numero": "0002-00000002", "socioId": "s2",  "fecha": t - timedelta(days=30), "medio": "transferencia",  "total": 15000.0},
            "items": [{"id": "pi2", "arancelId": "a8", "membresiaId": "m2",  "montoAplicado": 15000.0, "arancelNombre": "Parcela"}],
        },
        {
            "pago": {"id": "p3", "numero": "0003-00000003", "socioId": "s3",  "fecha": t - timedelta(days=7),  "medio": "mercadopago",    "total": 10000.0},
            "items": [{"id": "pi3", "arancelId": "a12", "membresiaId": "m3",  "montoAplicado": 10000.0, "arancelNombre": "Cuota"}],
        },
        {
            "pago": {"id": "p4", "numero": "0004-00000004", "socioId": "s4",  "fecha": t - timedelta(days=2),  "medio": "transferencia",  "total": 18500.0},
            "items": [{"id": "pi4", "arancelId": "a1", "membresiaId": "m4",  "montoAplicado": 18500.0, "arancelNombre": "Amarre y Servicios"}],
        },
    ]


def _build_notificaciones():
    """3 notificaciones: email and whatsapp."""
    t = _today()
    return [
        {"id": "n1", "socioId": "s4", "canal": CanalNotificacion.EMAIL,     "fecha": t - timedelta(days=3),  "motivo": "Membresía por vencer",  "mensaje": "Su membresía de Balseros Embalse vence en 15 días. Renueve a tiempo."},
        {"id": "n2", "socioId": "s5", "canal": CanalNotificacion.WHATSAPP,  "fecha": t - timedelta(days=5),  "motivo": "Recordatorio de pago",  "mensaje": "Hola Juan, le recordamos que su cuota de Windsurf está pendiente de pago."},
        {"id": "n3", "socioId": "s6", "canal": CanalNotificacion.EMAIL,     "fecha": t - timedelta(days=10), "motivo": "Membresía vencida",     "mensaje": "Su membresía de Cabañeros Embalse se encuentra vencida. Contacte al club."},
        {"id": "n4", "socioId": "s9", "canal": CanalNotificacion.WHATSAPP,  "fecha": t - timedelta(days=15), "motivo": "Suspensión notificada", "mensaje": "Fernando, su membresía de Windsurf Embalse ha sido suspendida por falta de pago."},
    ]


def seed(engine=None):
    """Populate the database. Idempotent.

    Args:
        engine: optional SQLAlchemy engine. Tests pass a throwaway in-memory
            engine; defaults to the app engine (python -m backend.seed).
    """
    target = engine or default_engine
    Base.metadata.create_all(bind=target)
    db = SessionLocal() if engine is None else sessionmaker(bind=engine)()

    try:
        # Idempotency check: skip if socios already exist
        existing = db.query(Socio).count()
        if existing > 0:
            print(f"Database already has {existing} socios — skipping seed.")
            return

        print("Seeding CANYP database...")

        # Parcelas
        for p in PARCELAS:
            db.add(Parcela(**p))
        db.flush()
        print(f"  [OK] {len(PARCELAS)} parcelas")

        # Socios
        for s in SOCIOS:
            db.add(Socio(**s))
        db.flush()
        print(f"  [OK] {len(SOCIOS)} socios")

        # Membresías de área
        membresias = _build_membresias()
        for m in membresias:
            db.add(Membresia(**m))
        db.flush()
        print(f"  [OK] {len(membresias)} membresías")

        # Cuota social: one per socio, created through the real service so the
        # seeded padron is produced by the same code path as production (CS-02).
        # `s["id"]` because the socios are plain dicts, already flushed above.
        cuotas = [crear_cuota_social(db, s["id"])[0] for s in SOCIOS]
        db.flush()
        print(f"  [OK] {len(cuotas)} cuotas sociales")

        # Aranceles
        aranceles = _build_aranceles()
        for a in aranceles:
            db.add(Arancel(**a))
        db.flush()
        print(f"  [OK] {len(aranceles)} aranceles")

        # Pagos + items
        pagos_data = _build_pagos()
        for pd in pagos_data:
            pago_data = pd["pago"]
            pago = Pago(**pago_data)
            db.add(pago)
            db.flush()  # ensure pago.id is persisted for FK
            for item in pd["items"]:
                db.add(PagoItem(**item, pagoId=pago_data["id"]))
        db.flush()
        print(f"  [OK] {len(pagos_data)} pagos")

        # Notificaciones
        notifs = _build_notificaciones()
        for n in notifs:
            db.add(Notificacion(**n))
        db.flush()
        print(f"  [OK] {len(notifs)} notificaciones")

        db.commit()
        print("Seed complete!")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
