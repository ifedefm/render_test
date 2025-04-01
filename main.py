from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from threading import Thread
import logging
from datetime import datetime

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

# Base de datos temporal mejorada
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

        logger.info(f"Creando pago para usuario: {usuario_id}, monto: {monto}")

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
            "external_reference": usuario_id,
            "binary_mode": True
        }

        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }

        # Añadido timeout para la solicitud a MP
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
        logger.info(f"Preferencia creada exitosamente: {preference_id}")

        return {
            "preference_id": preference_id,
            "url_pago": response.json()["init_point"]
        }

    except requests.exceptions.Timeout:
        logger.error("Timeout al conectar con MercadoPago")
        raise HTTPException(status_code=504, detail="Timeout al conectar con MercadoPago")
    except Exception as e:
        logger.error(f"Error inesperado al crear pago: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.post("/notificacion/")
async def webhook(request: Request):
    try:
        # Aceptar JSON o form-data
        try:
            data = await request.json()
        except:
            data = await request.form()
            data = dict(data)

        logger.info(f"Notificación recibida: {data}")

        # Respuesta inmediata (MP requiere <500ms)
        response = JSONResponse(content={"status": "received"})
        
        # Procesar en background si hay payment_id
        if data.get("data", {}).get("id"):
            payment_id = data["data"]["id"]
            
            # Ejecutar en thread separado
            Thread(
                target=process_payment_background,
                args=(payment_id,),
                daemon=True
            ).start()

        return response

    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}")
        return JSONResponse(content={"status": "error"}, status_code=500)

def process_payment_background(payment_id: str):
    """Procesa el pago en segundo plano con reintentos"""
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Procesando pago {payment_id} (intento {attempt + 1})")
            headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
            
            # Obtener detalles del pago con timeout
            payment_response = requests.get(
                f"https://api.mercadopago.com/v1/payments/{payment_id}",
                headers=headers,
                timeout=10
            )
            
            if payment_response.status_code != 200:
                error_msg = payment_response.json().get("message", "Error desconocido")
                logger.error(f"Error al obtener pago {payment_id}: {error_msg}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return

            payment_data = payment_response.json()
            status = payment_data.get("status")
            preference_id = payment_data.get("external_reference")
            
            if not preference_id:
                logger.error(f"No se encontró external_reference para el pago {payment_id}")
                return

            # Guardar en base de datos
            payments_db[preference_id] = {
                "payment_id": payment_id,
                "status": status,
                "monto": payment_data.get("transaction_amount"),
                "fecha": payment_data.get("date_approved"),
                "last_updated": datetime.now().isoformat()
            }
            
            logger.info(f"Pago registrado: {preference_id} -> Estado: {status}")
            break

        except requests.exceptions.RequestException as e:
            logger.warning(f"Error de conexión al procesar pago (intento {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
        except Exception as e:
            logger.error(f"Error inesperado al procesar pago: {str(e)}")
            break

@app.post("/verificar_pago/")
async def verificar_pago(request: Request):
    try:
        data = await request.json()
        preference_id = data.get("preference_id")
        
        if not preference_id:
            raise HTTPException(status_code=400, detail="Se requiere preference_id")

        logger.info(f"Verificando pago para preferencia: {preference_id}")

        # 1. Buscar en base de datos local
        if preference_id in payments_db:
            logger.info(f"Pago encontrado en base local: {payments_db[preference_id]}")
            return payments_db[preference_id]
        
        # 2. Consultar directamente a MP si no está localmente
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        search_url = f"https://api.mercadopago.com/v1/payments/search?external_reference={preference_id}"
        
        response = requests.get(search_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            error_msg = response.json().get("message", "Error al buscar pagos")
            logger.error(f"Error al buscar pagos: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)

        results = response.json().get("results", [])
        
        if not results:
            logger.info(f"No se encontraron pagos para la preferencia {preference_id}")
            return {"status": "pending", "detail": "No se encontraron transacciones"}

        # Tomar el pago más reciente
        latest_payment = max(results, key=lambda x: x["date_created"])
        
        # Actualizar base de datos local
        payments_db[preference_id] = {
            "payment_id": latest_payment["id"],
            "status": latest_payment["status"],
            "monto": latest_payment["transaction_amount"],
            "fecha": latest_payment["date_approved"],
            "last_updated": datetime.now().isoformat()
        }
        
        logger.info(f"Pago actualizado desde MP: {payments_db[preference_id]}")
        return payments_db[preference_id]

    except requests.exceptions.Timeout:
        logger.error("Timeout al consultar MercadoPago")
        raise HTTPException(status_code=504, detail="Timeout al consultar MercadoPago")
    except Exception as e:
        logger.error(f"Error inesperado al verificar pago: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pago_exitoso")
async def pago_exitoso():
    return {"status": "success"}

@app.get("/pago_fallido")
async def pago_fallido():
    return {"status": "failure"}

@app.get("/pago_pendiente")
async def pago_pendiente():
    return {"status": "pending"}

@app.get("/")
async def health_check():
    return {"status": "API operativa"}

# Endpoint para debug (solo en desarrollo)
@app.get("/debug/pagos")
async def debug_pagos():
    return {
        "count": len(payments_db),
        "pagos": payments_db
    }
