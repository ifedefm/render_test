from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from threading import Thread
import logging
from datetime import datetime
import uuid  # Importamos uuid para generar identificadores únicos

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

        # Generamos un UUID único para este pago
        id_pago_unico = str(uuid.uuid4())
        logger.info(f"ID único generado para el pago: {id_pago_unico}")

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
            "external_reference": id_pago_unico,  # Usamos el UUID como referencia
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
        
        # Guardamos la relación entre preference_id y nuestro id_pago_unico
        payments_db[id_pago_unico] = {
            "preference_id": preference_id,
            "usuario_id": usuario_id,
            "monto": monto,
            "email": email,
            "status": "pending",  # Estado inicial
            "payment_id": None,   # Se actualizará cuando llegue el webhook
            "fecha_creacion": datetime.now().isoformat()
        }
        
        logger.info(f"Preferencia creada exitosamente. Preference_id: {preference_id}, ID único: {id_pago_unico}")

        return {
            "id_pago_unico": id_pago_unico,  # Devolvemos nuestro ID único
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
        # Aceptar tanto JSON como form-data
        try:
            data = await request.json()
        except:
            form_data = await request.form()
            data = dict(form_data)

        logger.info(f"🔔 Notificación recibida: {data}")

        # Extraer payment_id de diferentes formatos de notificación
        payment_id = data.get('data', {}).get('id') or data.get('id') or data.get('payment_id')
        
        if not payment_id:
            logger.error("No se encontró payment_id en la notificación")
            return JSONResponse(content={"status": "invalid_data"}, status_code=400)

        # Respuesta inmediata (MP requiere <500ms)
        response = JSONResponse(content={"status": "received"})
        
        # Procesar en segundo plano
        Thread(
            target=process_payment_notification,
            args=(payment_id,),
            daemon=True
        ).start()

        return response

    except Exception as e:
        logger.error(f"🚨 Error en webhook: {str(e)}")
        return JSONResponse(content={"status": "error"}, status_code=500)

def process_payment_notification(payment_id: str):
    """Procesa la notificación y actualiza la base de datos"""
    try:
        logger.info(f"🔍 Procesando pago: {payment_id}")
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        
        # 1. Obtener detalles completos del pago desde MP
        payment_data = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=headers,
            timeout=10
        ).json()

        # 2. Verificar estructura de respuesta
        if 'id' not in payment_data:
            logger.error(f"Respuesta inválida de MP: {payment_data}")
            return

        # 3. Obtener nuestro id_pago_unico (external_reference)
        id_pago_unico = payment_data.get('external_reference')
        if not id_pago_unico:
            logger.error(f"No se encontró external_reference en el pago {payment_id}")
            return

        # 4. Actualizar base de datos
        if id_pago_unico in payments_db:
            payments_db[id_pago_unico].update({
                "payment_id": payment_id,
                "status": payment_data.get('status'),
                "monto": payment_data.get('transaction_amount'),
                "fecha_aprobacion": payment_data.get('date_approved'),
                "ultima_actualizacion": datetime.now().isoformat()
            })
        else:
            # Si no existe, creamos un nuevo registro
            payments_db[id_pago_unico] = {
                "payment_id": payment_id,
                "status": payment_data.get('status'),
                "monto": payment_data.get('transaction_amount'),
                "fecha_aprobacion": payment_data.get('date_approved'),
                "ultima_actualizacion": datetime.now().isoformat(),
                "preference_id": None  # No lo tenemos en este caso
            }
        
        logger.info(f"✅ Pago actualizado - ID Único: {id_pago_unico}, Payment: {payment_id}")

    except Exception as e:
        logger.error(f"⚠️ Error al procesar pago {payment_id}: {str(e)}")

@app.post("/verificar_pago/")
async def verificar_pago(request: Request):
    try:
        data = await request.json()
        id_pago_unico = data.get("id_pago_unico")  # Ahora recibimos nuestro UUID
        
        if not id_pago_unico:
            raise HTTPException(status_code=400, detail="Se requiere id_pago_unico")

        logger.info(f"🔎 Verificando pago para id_pago_unico: {id_pago_unico}")

        # 1. Buscar en base de datos local
        if id_pago_unico in payments_db:
            return payments_db[id_pago_unico]
        
        # 2. Si no está local, consultar directamente a MP usando nuestro UUID como external_reference
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        search_url = f"https://api.mercadopago.com/v1/payments/search?external_reference={id_pago_unico}"
        
        try:
            response = requests.get(search_url, headers=headers, timeout=15)
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Error al consultar MercadoPago")

            results = response.json().get("results", [])
            
            if not results:
                return {"status": "pending", "detail": "No se encontraron transacciones"}

            # Tomar el pago más reciente
            latest_payment = max(results, key=lambda x: x["date_created"])
            
            # Actualizar base de datos local
            payments_db[id_pago_unico] = {
                "payment_id": latest_payment["id"],
                "status": latest_payment["status"],
                "monto": latest_payment["transaction_amount"],
                "fecha_aprobacion": latest_payment["date_approved"],
                "ultima_actualizacion": datetime.now().isoformat(),
                "preference_id": None  # No lo tenemos en este caso
            }
            
            return payments_db[id_pago_unico]
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error de conexión con MP: {str(e)}")
            raise HTTPException(status_code=503, detail="Error al conectar con MercadoPago")

    except Exception as e:
        logger.error(f"Error inesperado: {str(e)}")
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
