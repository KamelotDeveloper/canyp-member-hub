"""Seed the CANYP database with realistic test data.

Usage: python -m backend.seed
Idempotent: skips if socios already exist.
"""

from datetime import date, timedelta

from sqlalchemy.orm import sessionmaker

from backend.database import Base, SessionLocal, engine as default_engine
from backend.models import (
    Area,
    CanalNotificacion,
    CategoriaParcela,
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

# ── Parcelas ──────────────────────────────────────────────

PARCELAS = [
    # ── Almafuerte: cabañas (Cabañeros) ──
    {"id": "pa1", "nombre": "Cabaña A", "tipo": TipoParcela.CABANA, "tamano": "40m²", "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.CHICA},
    {"id": "pa2", "nombre": "Cabaña B", "tipo": TipoParcela.CABANA, "tamano": "55m²", "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.MEDIANA},
    {"id": "pa3", "nombre": "Cabaña C", "tipo": TipoParcela.CABANA, "tamano": "35m²", "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.CHICA},
    {"id": "pa4", "nombre": "Cabaña D", "tipo": TipoParcela.CABANA, "tamano": "45m²", "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.MEDIANA},
    {"id": "pa7", "nombre": "Cabaña E", "tipo": TipoParcela.CABANA, "tamano": "60m²", "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.ESPECIAL},
    {"id": "pa8", "nombre": "Cabaña F", "tipo": TipoParcela.CABANA, "tamano": "70m²", "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.GRANDE},
    # ── Almafuerte: guardería ──
    {"id": "pa10", "nombre": "Guardería Chica", "tipo": TipoParcela.GUARDERIA, "tamano": None, "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.CHICA},
    {"id": "pa11", "nombre": "Guardería Grande", "tipo": TipoParcela.GUARDERIA, "tamano": None, "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.GRANDE},
    # ── Embalse: balsas (Balseros) ──
    {"id": "pa5", "nombre": "Balsa Principal", "tipo": TipoParcela.BALSA, "tamano": "12m", "predio": Predio.EMBALSE},
    {"id": "pa6", "nombre": "Balsa Norte", "tipo": TipoParcela.BALSA, "tamano": "10m", "predio": Predio.EMBALSE},
    {"id": "pa9", "nombre": "Balsa Sur", "tipo": TipoParcela.BALSA, "tamano": "11m", "predio": Predio.EMBALSE},
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
    """Build membresias with dates relative to today for realistic dashboard."""
    t = _today()
    return [
        # ── Active: far from expiry ──
        {"id": "m1",  "socioId": "s1",  "area": Area.BALSEROS,    "predio": Predio.EMBALSE,    "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=180), "parcelaId": "pa5", "rol": RolMembresia.TITULAR},
        {"id": "m2",  "socioId": "s2",  "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=365), "parcelaId": "pa1", "rol": RolMembresia.TITULAR},
        {"id": "m3",  "socioId": "s3",  "area": Area.GUARDERIA,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=240), "parcelaId": "pa10"},
        # ── Active: por vencer (≤30 days) ──
        {"id": "m4",  "socioId": "s4",  "area": Area.BALSEROS,    "predio": Predio.EMBALSE,    "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=15),  "parcelaId": "pa5", "rol": RolMembresia.INTEGRANTE},
        {"id": "m5",  "socioId": "s5",  "area": Area.WINDSURF,    "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=7),   "parcelaId": None},
        # ── Expired (vencida via date logic) ──
        {"id": "m6",  "socioId": "s6",  "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t - timedelta(days=30),  "parcelaId": "pa2", "rol": RolMembresia.TITULAR},
        {"id": "m7",  "socioId": "s7",  "area": Area.BALSEROS,    "predio": Predio.EMBALSE,    "estado": EstadoMembresia.ACTIVA,       "vencimiento": t - timedelta(days=90),  "parcelaId": "pa6", "rol": RolMembresia.INTEGRANTE},
        # ── Expiring tomorrow (edge case) ──
        {"id": "m8",  "socioId": "s8",  "area": Area.GUARDERIA,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=1),   "parcelaId": None},
        # ── Suspended ──
        {"id": "m9",  "socioId": "s9",  "area": Area.WINDSURF,    "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.SUSPENDIDA,   "vencimiento": t + timedelta(days=60),  "parcelaId": None},
        {"id": "m10", "socioId": "s10", "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.SUSPENDIDA,   "vencimiento": t - timedelta(days=15),  "parcelaId": "pa3", "rol": RolMembresia.INTEGRANTE},
        # ── Baja ──
        {"id": "m11", "socioId": "s11", "area": Area.BALSEROS,    "predio": Predio.EMBALSE,    "estado": EstadoMembresia.BAJA,         "vencimiento": t - timedelta(days=180), "parcelaId": None},
        # ── More active (different areas) ──
        {"id": "m12", "socioId": "s12", "area": Area.WINDSURF,    "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=200), "parcelaId": None},
        {"id": "m13", "socioId": "s1",  "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=120), "parcelaId": "pa4", "rol": RolMembresia.TITULAR},
        {"id": "m14", "socioId": "s2",  "area": Area.GUARDERIA,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=90),  "parcelaId": None},
        {"id": "m15", "socioId": "s3",  "area": Area.WINDSURF,    "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=5),   "parcelaId": None},
        {"id": "m16", "socioId": "s4",  "area": Area.BALSEROS,    "predio": Predio.EMBALSE,    "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=400), "parcelaId": "pa6", "rol": RolMembresia.TITULAR},
        # ── Almafuerte shared units (RQ16): Titular + Integrantes, mixed vencimientos ──
        {"id": "m17", "socioId": "s5",  "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=25),  "parcelaId": "pa3", "rol": RolMembresia.TITULAR},
        {"id": "m18", "socioId": "s12", "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t - timedelta(days=35),  "parcelaId": "pa4", "rol": RolMembresia.INTEGRANTE},
        {"id": "m19", "socioId": "s6",  "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t - timedelta(days=45),  "parcelaId": "pa7", "rol": RolMembresia.TITULAR},
        {"id": "m20", "socioId": "s8",  "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=210), "parcelaId": "pa7", "rol": RolMembresia.INTEGRANTE},
        {"id": "m21", "socioId": "s9",  "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=150), "parcelaId": "pa8", "rol": RolMembresia.TITULAR},
        {"id": "m22", "socioId": "s11", "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=6),   "parcelaId": "pa8", "rol": RolMembresia.INTEGRANTE},
        {"id": "m23", "socioId": "s2",  "area": Area.BALSEROS,    "predio": Predio.EMBALSE,    "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=20),  "parcelaId": "pa9", "rol": RolMembresia.TITULAR},
        {"id": "m24", "socioId": "s3",  "area": Area.BALSEROS,    "predio": Predio.EMBALSE,    "estado": EstadoMembresia.ACTIVA,       "vencimiento": t - timedelta(days=10),  "parcelaId": "pa9", "rol": RolMembresia.INTEGRANTE},
        {"id": "m25", "socioId": "s8",  "area": Area.GUARDERIA,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=180), "parcelaId": "pa11"},
        {"id": "m26", "socioId": "s7",  "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=90),  "parcelaId": "pa1", "rol": RolMembresia.INTEGRANTE},
        {"id": "m27", "socioId": "s4",  "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "estado": EstadoMembresia.ACTIVA,       "vencimiento": t + timedelta(days=45),  "parcelaId": "pa2", "rol": RolMembresia.INTEGRANTE},
    ]


def _build_aranceles():
    """One arancel per area+predio combination with realistic ARS amounts."""
    t = _today()
    return [
        {"id": "a1", "nombre": "Cuota Balseros Embalse",        "area": Area.BALSEROS,    "predio": Predio.EMBALSE,    "monto": 18500.0,  "vigenteDesde": t - timedelta(days=90), "historico": [{"monto": 15000.0, "vigenteDesde": str(t - timedelta(days=365))}]},
        {"id": "a7", "nombre": "Cuota Windsurf Almafuerte",     "area": Area.WINDSURF,    "predio": Predio.ALMAFUERTE, "monto": 19000.0,  "vigenteDesde": t - timedelta(days=15), "historico": []},
        # ── Almafuerte per-categoría aranceles (RQ13/RQ16: resolver_monto finds rows) ──
        {"id": "a8",  "nombre": "Cuota Cabañeros Almafuerte Chica",    "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.CHICA,    "monto": 15000.0, "vigenteDesde": t - timedelta(days=90), "historico": []},
        {"id": "a9",  "nombre": "Cuota Cabañeros Almafuerte Mediana",  "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.MEDIANA,  "monto": 18500.0, "vigenteDesde": t - timedelta(days=90), "historico": []},
        {"id": "a10", "nombre": "Cuota Cabañeros Almafuerte Especial", "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.ESPECIAL, "monto": 21000.0, "vigenteDesde": t - timedelta(days=60), "historico": []},
        {"id": "a11", "nombre": "Cuota Cabañeros Almafuerte Grande",   "area": Area.CABANEROS,   "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.GRANDE,   "monto": 25000.0, "vigenteDesde": t - timedelta(days=60), "historico": []},
        {"id": "a12", "nombre": "Cuota Guardería Almafuerte Chica",    "area": Area.GUARDERIA,   "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.CHICA,    "monto": 10000.0, "vigenteDesde": t - timedelta(days=30), "historico": []},
        {"id": "a13", "nombre": "Cuota Guardería Almafuerte Grande",   "area": Area.GUARDERIA,   "predio": Predio.ALMAFUERTE, "categoria": CategoriaParcela.GRANDE,   "monto": 14000.0, "vigenteDesde": t - timedelta(days=30), "historico": []},
    ]


def _build_pagos():
    """4 pagos with items, sequential numbers, recent dates."""
    t = _today()
    return [
        {
            "pago": {"id": "p1", "numero": "0001-00000001", "socioId": "s1",  "fecha": t - timedelta(days=60), "medio": "efectivo",       "total": 18500.0},
            "items": [{"id": "pi1", "arancelId": "a1", "membresiaId": "m1",  "montoAplicado": 18500.0, "arancelNombre": "Cuota Balseros Embalse"}],
        },
        {
            "pago": {"id": "p2", "numero": "0002-00000002", "socioId": "s2",  "fecha": t - timedelta(days=30), "medio": "transferencia",  "total": 15000.0},
            "items": [{"id": "pi2", "arancelId": "a8", "membresiaId": "m2",  "montoAplicado": 15000.0, "arancelNombre": "Cuota Cabañeros Almafuerte Chica"}],
        },
        {
            "pago": {"id": "p3", "numero": "0003-00000003", "socioId": "s3",  "fecha": t - timedelta(days=7),  "medio": "mercadopago",    "total": 10000.0},
            "items": [{"id": "pi3", "arancelId": "a12", "membresiaId": "m3",  "montoAplicado": 10000.0, "arancelNombre": "Cuota Guardería Almafuerte Chica"}],
        },
        {
            "pago": {"id": "p4", "numero": "0004-00000004", "socioId": "s4",  "fecha": t - timedelta(days=2),  "medio": "transferencia",  "total": 18500.0},
            "items": [{"id": "pi4", "arancelId": "a1", "membresiaId": "m4",  "montoAplicado": 18500.0, "arancelNombre": "Cuota Balseros Embalse"}],
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

        # Membresías
        membresias = _build_membresias()
        for m in membresias:
            db.add(Membresia(**m))
        db.flush()
        print(f"  [OK] {len(membresias)} membresías")

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
