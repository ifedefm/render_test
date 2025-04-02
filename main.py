from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from threading import Thread
import logging
from datetime import datetime
import uuid

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

# Base de datos mejorada
payments_db = {}

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
        
        # Guardamos toda la información relevante
        payments_db[id_pago_unico] = {
            "preference_id": preference_id,
            "usuario_id": usuario_id,
            "monto": monto,
            "email": email,
            "status": "pending",
            "payment_id": None,
            "merchant_order_id": None,
            "fecha_creacion": datetime.now().isoformat()
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
        # Manejar tanto JSON como form-data
        try:
            data = await request.json()
        except:
            data = await request.form()
            data = dict(data)

        logger.info(f"Notificación recibida: {data}")

        # Manejar diferentes tipos de notificaciones
        if 'merchant_order' in data.get('topic', ''):
            return await handle_merchant_order(data)
        elif 'payment' in data.get('topic', ''):
            return await handle_payment(data)
        else:
            logger.error(f"Tipo de notificación no soportada: {data}")
            return JSONResponse(content={"status": "unsupported_notification"}, status_code=400)

    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}")
        return JSONResponse(content={"status": "error"}, status_code=500)

async def handle_merchant_order(data: dict):
    """Procesa notificaciones de merchant_order"""
    merchant_order_url = data.get('resource')
    if not merchant_order_url:
        logger.error("No se encontró resource en merchant_order")
        return JSONResponse(content={"status": "invalid_data"}, status_code=400)

    try:
        # Obtener detalles de la merchant order
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        response = requests.get(merchant_order_url, headers=headers, timeout=10)
        merchant_order = response.json()

        merchant_order_id = merchant_order.get('id')
        payments = merchant_order.get('payments', [])
        
        if payments:
            payment_id = payments[0].get('id')
            external_ref = merchant_order.get('external_reference')
            
            if payment_id and external_ref:
                Thread(
                    target=process_payment,
                    args=(payment_id, external_ref),
                    daemon=True
                ).start()

        return JSONResponse(content={"status": "processed"})

    except Exception as e:
        logger.error(f"Error al procesar merchant_order: {str(e)}")
        return JSONResponse(content={"status": "error"}, status_code=500)

async def handle_payment(data: dict):
    """Procesa notificaciones de payment"""
    payment_id = data.get('data', {}).get('id') or data.get('id')
    if not payment_id:
        logger.error("No se encontró payment_id en la notificación")
        return JSONResponse(content={"status": "invalid_data"}, status_code=400)

    Thread(
        target=process_payment,
        args=(payment_id, None),  # external_ref se obtendrá al procesar
        daemon=True
    ).start()

    return JSONResponse(content={"status": "received"})

def process_payment(payment_id: str, external_ref: str = None):
    """Procesa un pago y actualiza la base de datos"""
    try:
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        
        # Obtener detalles del pago
        payment_data = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=headers,
            timeout=10
        ).json()

        # Obtener external_reference si no se proporcionó
        external_ref = external_ref or payment_data.get('external_reference')
        if not external_ref:
            logger.error(f"No se encontró external_reference para el pago {payment_id}")
            return

        # Actualizar base de datos
        if external_ref in payments_db:
            payments_db[external_ref].update({
                "payment_id": payment_id,
                "status": payment_data.get('status', 'pending'),
                "fecha_actualizacion": datetime.now().isoformat()
            })
        else:
            payments_db[external_ref] = {
                "payment_id": payment_id,
                "status": payment_data.get('status', 'pending'),
                "fecha_creacion": datetime.now().isoformat(),
                "fecha_actualizacion": datetime.now().isoformat()
            }

        logger.info(f"Pago actualizado - ID: {external_ref}, Payment: {payment_id}")

    except Exception as e:
        logger.error(f"Error al procesar pago {payment_id}: {str(e)}")

@app.post("/verificar_pago/")
async def verificar_pago(request: Request):
    try:
        data = await request.json()
        id_pago_unico = data.get("id_pago_unico")
        
        if not id_pago_unico:
            raise HTTPException(status_code=400, detail="Se requiere id_pago_unico")

        logger.info(f"Verificando pago para ID: {id_pago_unico}")

        # 1. Buscar en base de datos local
        if id_pago_unico in payments_db:
            pago = payments_db[id_pago_unico]
            if pago.get("payment_id"):
                return pago

        # 2. Si no está completo, consultar a MP
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        search_url = f"https://api.mercadopago.com/v1/payments/search?external_reference={id_pago_unico}"
        
        response = requests.get(search_url, headers=headers, timeout=15)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Error al consultar MercadoPago")

        results = response.json().get("results", [])
        if not results:
            return {"status": "pending", "detail": "No se encontraron transacciones"}

        # Tomar el pago más reciente
        latest_payment = max(results, key=lambda x: x["date_created"])
        
        # Actualizar base de datos local
        payments_db[id_pago_unico].update({
            "payment_id": latest_payment["id"],
            "status": latest_payment["status"],
            "monto": latest_payment["transaction_amount"],
            "fecha_actualizacion": datetime.now().isoformat()
        })

        return payments_db[id_pago_unico]

    except Exception as e:
        logger.error(f"Error al verificar pago: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pago_exitoso")
async def pago_exitoso(
    collection_id: str = None,
    collection_status: str = None,
    payment_id: str = None,
    status: str = None,
    external_reference: str = None,
    preference_id: str = None,
    merchant_order_id: str = None
):
    """Endpoint para redirección después de pago exitoso"""
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
