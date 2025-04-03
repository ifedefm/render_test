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
MAX_RETRIES = 3  # Máximo de reintentos para carga_ganamos

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

def get_payment_data(payment_id: str):
    """Obtiene datos de pago de MercadoPago con manejo de errores"""
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    
    try:
        # Primero intentamos con el endpoint de payments
        response = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
            
        # Si falla, probamos con merchant_orders
        if 'merchant_orders' in payment_id:
            order_id = payment_id.split('/')[-1]
            response = requests.get(
                f"https://api.mercadopago.com/merchant_orders/{order_id}",
                headers=headers,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
                
        response.raise_for_status()
        return None
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error al obtener datos de pago {payment_id}: {str(e)}")
        return None

def process_ganamos_load(usuario_id: str, monto: float, external_ref: str):
    """Ejecuta carga_ganamos con reintentos y manejo de errores"""
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"Intento {attempt + 1} de carga para {usuario_id}")
            success, balance = carga_ganamos(usuario_id, monto)
            
            if success:
                logger.info(f"Carga exitosa. Balance: {balance}")
                payments_db[external_ref].update({
                    "procesado": True,
                    "balance_resultante": balance,
                    "fecha_procesado": datetime.now().isoformat(),
                    "intentos": attempt + 1
                })
                return True
            else:
                logger.warning(f"Error en carga (intento {attempt + 1}). Balance: {balance}")
                time.sleep(2)  # Espera antes de reintentar
                
        except Exception as e:
            logger.error(f"Error en carga_ganamos (intento {attempt + 1}): {str(e)}")
            time.sleep(3)  # Espera más prolongada entre reintentos
    
    payments_db[external_ref].update({
        "error_carga": True,
        "detalle_error": f"Falló después de {MAX_RETRIES} intentos",
        "intentos": MAX_RETRIES
    })
    return False

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
        response = requests.post(
            "https://api.mercadopago.com/checkout/preferences",
            json=preference_data,
            headers=headers,
            timeout=20
        )

        if response.status_code != 201:
            error_msg = response.json().get("message", "Error desconocido de MercadoPago")
            logger.error(f"Error al crear preferencia: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)

        preference_id = response.json()["id"]
        
        payments_db[id_pago_unico] = {
            "preference_id": preference_id,
            "usuario_id": usuario_id,
            "monto": monto,
            "email": email,
            "status": "pending",
            "payment_id": None,
            "merchant_order_id": None,
            "fecha_creacion": datetime.now().isoformat(),
            "procesado": False
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
        content_type = request.headers.get('content-type')
        if content_type == 'application/json':
            data = await request.json()
        else:
            data = await request.form()
            data = dict(data)

        logger.info(f"Notificación recibida: {data}")

        # Extraer payment_id según diferentes formatos
        payment_id = None
        if 'data' in data and 'id' in data['data']:
            payment_id = data['data']['id']
        elif 'id' in data:
            payment_id = data['id']
        elif 'resource' in data:
            payment_id = data['resource']

        if not payment_id:
            logger.error("No se pudo extraer payment_id de la notificación")
            return JSONResponse(content={"status": "invalid_data"}, status_code=400)

        # Procesar en segundo plano
        Thread(
            target=process_payment_notification,
            args=(payment_id,),
            daemon=True
        ).start()

        return JSONResponse(content={"status": "received"})

    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}")
        return JSONResponse(content={"status": "error"}, status_code=500)

def process_payment_notification(payment_id: str):
    """Procesa una notificación de pago"""
    try:
        logger.info(f"Procesando notificación para payment_id: {payment_id}")
        
        payment_data = get_payment_data(payment_id)
        if not payment_data:
            logger.error(f"No se pudieron obtener datos para payment_id {payment_id}")
            return

        external_ref = payment_data.get('external_reference')
        if not external_ref:
            logger.error(f"No se encontró external_reference en los datos del pago")
            return

        if external_ref not in payments_db:
            logger.info(f"Creando nueva entrada para external_ref: {external_ref}")
            payments_db[external_ref] = {
                "fecha_creacion": datetime.now().isoformat(),
                "procesado": False
            }

        pago = payments_db[external_ref]
        
        # Actualizar información del pago
        update_data = {
            "payment_id": payment_id,
            "status": payment_data.get('status', payment_data.get('order_status')),
            "monto": payment_data.get('transaction_amount', payment_data.get('total_amount')),
            "fecha_actualizacion": datetime.now().isoformat()
        }
        
        if 'merchant_order_id' in payment_data:
            update_data["merchant_order_id"] = payment_data['merchant_order_id']

        pago.update(update_data)

        # Procesar carga si está aprobado y no fue procesado
        if pago.get("status") == "approved" and not pago.get("procesado"):
            usuario_id = pago.get("usuario_id")
            monto = pago.get("monto")
            
            if usuario_id and monto:
                Thread(
                    target=process_ganamos_load,
                    args=(usuario_id, monto, external_ref),
                    daemon=True
                ).start()

        logger.info(f"Pago actualizado - ID: {external_ref}, Status: {pago.get('status')}")

    except Exception as e:
        logger.error(f"Error inesperado al procesar notificación: {str(e)}")

@app.post("/verificar_pago/")
async def verificar_pago(request: Request):
    try:
        data = await request.json()
        id_pago_unico = data.get("id_pago_unico")
        
        if not id_pago_unico:
            raise HTTPException(status_code=400, detail="Se requiere id_pago_unico")

        logger.info(f"Verificando pago para ID: {id_pago_unico}")

        if id_pago_unico in payments_db:
            pago = payments_db[id_pago_unico]
            
            if pago.get("payment_id"):
                # Si está aprobado pero no procesado, intentamos carga
                if pago.get("status") == "approved" and not pago.get("procesado"):
                    usuario_id = pago.get("usuario_id")
                    monto = pago.get("monto")
                    
                    if usuario_id and monto:
                        logger.info(f"Iniciando carga para {usuario_id}")
                        success = process_ganamos_load(usuario_id, monto, id_pago_unico)
                        if not success:
                            logger.error("Falló el proceso de carga después de reintentos")
                
                return pago

        # Consultar a MP si no tenemos datos completos
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        search_url = f"https://api.mercadopago.com/v1/payments/search?external_reference={id_pago_unico}"
        
        response = requests.get(search_url, headers=headers, timeout=15)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Error al consultar MercadoPago")

        results = response.json().get("results", [])
        if not results:
            return {"status": "pending", "detail": "No se encontraron transacciones"}

        latest_payment = max(results, key=lambda x: x["date_created"])
        
        if id_pago_unico not in payments_db:
            payments_db[id_pago_unico] = {
                "fecha_creacion": datetime.now().isoformat(),
                "procesado": False
            }

        pago = payments_db[id_pago_unico]
        pago.update({
            "payment_id": latest_payment["id"],
            "status": latest_payment["status"],
            "monto": latest_payment["transaction_amount"],
            "fecha_actualizacion": datetime.now().isoformat()
        })

        # Procesar carga si está aprobado
        if latest_payment["status"] == "approved" and not pago.get("procesado"):
            usuario_id = pago.get("usuario_id")
            monto = latest_payment["transaction_amount"]
            
            if usuario_id and monto:
                logger.info(f"Iniciando carga para {usuario_id}")
                success = process_ganamos_load(usuario_id, monto, id_pago_unico)
                if not success:
                    logger.error("Falló el proceso de carga después de reintentos")

        return pago

    except Exception as e:
        logger.error(f"Error al verificar pago: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Endpoints de redirección (mantener igual)
@app.get("/pago_exitoso")
async def pago_exitoso(collection_id: str = None, collection_status: str = None,
                      payment_id: str = None, status: str = None,
                      external_reference: str = None, preference_id: str = None,
                      merchant_order_id: str = None):
    if external_reference and external_reference in payments_db:
        payments_db[external_reference].update({
            "payment_id": payment_id or collection_id,
            "status": status or collection_status,
            "fecha_actualizacion": datetime.now().isoformat()
        })
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
