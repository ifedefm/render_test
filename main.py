from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from threading import Thread
import logging
from datetime import datetime
import uuid
from funciones_ganamos import carga_ganamos
import time


app = FastAPI()

# Configuración
ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "APP_USR-5177967231468413-032619-a7b3ab70df053bfb323007e57562341f-324622221")
BASE_URL = os.getenv("BASE_URL", "https://streamlit-test-eiu8.onrender.com")

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Base de datos
payments_db = {}

# Configuración de sesión para requests
session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["POST", "GET"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)

@app.post("/crear_pago/")
async def crear_pago(request: Request):
    try:
        data = await request.json()
        usuario_id = data.get("usuario_id")
        monto = data.get("monto")
        email = data.get("email")
        
        if not all([usuario_id, monto, email]):
            raise HTTPException(status_code=400, detail="Se requieren usuario_id, monto y email")

        id_pago_unico = str(uuid.uuid4())
        logger.info(f"Creando pago con ID único: {id_pago_unico}")

        preference_data = {
            "items": [{
                "title": f"Recarga saldo - {usuario_id}",
                "quantity": 1,
                "unit_price": float(monto),
                "currency_id": "ARS"
            }],
            "payer": {"email": email},
            "payment_methods": {"excluded_payment_types": [{"id": "atm"}]},
            "back_urls": {
                "success": f"{BASE_URL}/pago_exitoso",
                "failure": f"{BASE_URL}/pago_fallido",
                "pending": f"{BASE_URL}/pago_pendiente"
            },
            "auto_return": "approved",
            "notification_url": f"{BASE_URL}/notificacion/",
            "external_reference": id_pago_unico,
            "binary_mode": True
        }

        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        response = session.post(
            "https://api.mercadopago.com/checkout/preferences",
            json=preference_data,
            headers=headers,
            timeout=20
        )
        response.raise_for_status()

        preference_id = response.json()["id"]
        
        payments_db[id_pago_unico] = {
            "preference_id": preference_id,
            "usuario_id": usuario_id,
            "monto": monto,
            "email": email,
            "status": "pending",
            "payment_id": None,
            "fecha_creacion": datetime.now().isoformat(),
            "procesado": False,
            "intentos_carga": 0  # Contador de intentos de carga
        }

        return {
            "id_pago_unico": id_pago_unico,
            "preference_id": preference_id,
            "url_pago": response.json()["init_point"]
        }

    except Exception as e:
        logger.error(f"Error al crear pago: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/notificacion/")
async def webhook(request: Request):
    try:
        data = await request.json()
        logger.info(f"Notificación recibida: {data}")

        payment_id = data.get('data', {}).get('id') if 'data' in data else data.get('id')
        if not payment_id:
            return JSONResponse(content={"status": "invalid_data"}, status_code=400)

        Thread(target=process_payment_notification, args=(payment_id,)).start()
        return JSONResponse(content={"status": "received"})

    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}")
        return JSONResponse(content={"status": "error"}, status_code=500)

def get_payment_data(payment_id: str):
    """Obtiene datos de pago con reintentos"""
    try:
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        response = session.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error al obtener pago {payment_id}: {str(e)}")
        return None

def process_payment_notification(payment_id: str):
    """Procesa la notificación y realiza la carga si es aprobada"""
    try:
        logger.info(f"Procesando notificación para: {payment_id}")
        
        payment_data = get_payment_data(payment_id)
        if not payment_data:
            return

        external_ref = payment_data.get('external_reference')
        status = payment_data.get('status')
        amount = payment_data.get('transaction_amount')

        if not external_ref:
            logger.error("No se encontró external_reference")
            return

        if external_ref not in payments_db:
            payments_db[external_ref] = {
                "fecha_creacion": datetime.now().isoformat(),
                "procesado": False,
                "intentos_carga": 0
            }

        pago = payments_db[external_ref]
        pago.update({
            "payment_id": payment_id,
            "status": status,
            "monto": amount,
            "fecha_actualizacion": datetime.now().isoformat()
        })

        # Procesar carga si está aprobado y no se ha procesado antes
        if status == "approved" and not pago.get("procesado") and pago.get("intentos_carga", 0) < 3:
            usuario_id = pago.get("usuario_id")
            monto = pago.get("monto")
            
            if usuario_id and monto:
                pago["intentos_carga"] += 1
                logger.info(f"Intentando carga #{pago['intentos_carga']} para {usuario_id}")
                
                success, balance = carga_ganamos2(usuario_id, monto)
                
                if success:
                    pago.update({
                        "procesado": True,
                        "balance_resultante": balance,
                        "fecha_procesado": datetime.now().isoformat()
                    })
                    logger.info(f"Carga exitosa. Balance: {balance}")
                else:
                    logger.error(f"Error en carga_ganamos2. Balance: {balance}")
                    pago["error_carga"] = True

    except Exception as e:
        logger.error(f"Error procesando notificación: {str(e)}")

@app.post("/verificar_pago/")
async def verificar_pago(request: Request):
    try:
        data = await request.json()
        id_pago_unico = data.get("id_pago_unico")
        
        if not id_pago_unico:
            raise HTTPException(status_code=400, detail="Se requiere id_pago_unico")

        logger.info(f"Verificando pago para ID: {id_pago_unico}")

        if id_pago_unico not in payments_db:
            # Consultar a MP si no tenemos registro local
            headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
            search_url = f"https://api.mercadopago.com/v1/payments/search?external_reference={id_pago_unico}"
            
            response = session.get(search_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            results = response.json().get("results", [])
            if not results:
                return {"status": "pending", "detail": "No se encontraron transacciones"}

            latest_payment = max(results, key=lambda x: x["date_created"])
            
            payments_db[id_pago_unico] = {
                "payment_id": latest_payment["id"],
                "status": latest_payment["status"],
                "monto": latest_payment["transaction_amount"],
                "fecha_creacion": datetime.now().isoformat(),
                "fecha_actualizacion": datetime.now().isoformat(),
                "procesado": False,
                "intentos_carga": 0
            }

        pago = payments_db[id_pago_unico]
        
        # Si está aprobado pero no procesado y no ha excedido intentos
        if pago.get("status") == "approved" and not pago.get("procesado") and pago.get("intentos_carga", 0) < 3:
            usuario_id = pago.get("usuario_id")
            monto = pago.get("monto")
            
            if usuario_id and monto:
                pago["intentos_carga"] += 1
                logger.info(f"Intentando carga #{pago['intentos_carga']} para {usuario_id}")
                
                success, balance = carga_ganamos2(usuario_id, monto)
                
                if success:
                    pago.update({
                        "procesado": True,
                        "balance_resultante": balance,
                        "fecha_procesado": datetime.now().isoformat()
                    })
                    logger.info(f"Carga exitosa. Balance: {balance}")
                else:
                    logger.error(f"Error en carga_ganamos2. Balance: {balance}")
                    pago["error_carga"] = True

        return pago

    except Exception as e:
        logger.error(f"Error al verificar pago: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Endpoints de redirección
@app.get("/pago_exitoso")
async def pago_exitoso(external_reference: str = None):
    if external_reference and external_reference in payments_db:
        payments_db[external_reference]["status"] = "approved"
    return RedirectResponse(url=f"/?pago=exitoso&id={external_reference}")

@app.get("/pago_fallido")
async def pago_fallido():
    return {"status": "failure"}

@app.get("/pago_pendiente")
async def pago_pendiente():
    return {"status": "pending"}

@app.get("/")
async def health_check():
    return {"status": "API operativa"}

@app.get("/debug/pagos")
async def debug_pagos():
    return {
        "count": len(payments_db),
        "pagos": payments_db
    }
