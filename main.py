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
        # Manejar diferentes formatos de notificación
        try:
            data = await request.json()
        except:
            data = dict(await request.form())
        
        logger.info(f"Notificación recibida: {data}")

        # Extraer payment_id basado en diferentes formatos
        payment_id = None
        
        # Formato 1: Notificación directa de payment
        if 'data' in data and 'id' in data['data']:
            payment_id = data['data']['id']
        elif 'id' in data:
            payment_id = data['id']
        
        # Formato 2: Resource URL
        elif 'resource' in data:
            resource = data['resource']
            if isinstance(resource, str) and resource.isdigit():
                payment_id = resource
            elif isinstance(resource, str) and '/payments/' in resource:
                payment_id = resource.split('/')[-1]
        
        # Ignorar completamente las merchant_orders
        if not payment_id or 'merchant_order' in str(data.get('topic', '')):
            logger.info("Ignorando notificación de merchant_order")
            return JSONResponse(content={"status": "ignored"}, status_code=200)
        
        # Procesar en segundo plano solo si tenemos un payment_id válido
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
    """Procesa una notificación de pago con un solo intento"""
    try:
        # Verificar si ya fue procesado
        existing = next(
            (p for p in payments_db.values() if p.get('payment_id') == payment_id), 
            None
        )
        if existing and existing.get('procesado_ganamos'):
            logger.info(f"Pago {payment_id} ya fue procesado")
            return

        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        
        # Obtener detalles del pago
        response = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=headers,
            timeout=15
        )
        response.raise_for_status()
        payment_data = response.json()

        external_ref = payment_data.get('external_reference')
        if not external_ref:
            logger.error("No external_reference en pago")
            return

        # Actualizar base de datos
        payment_info = {
            "payment_id": payment_id,
            "status": payment_data.get('status'),
            "monto": payment_data.get('transaction_amount'),
            "fecha_actualizacion": datetime.now().isoformat()
        }

        if external_ref in payments_db:
            payments_db[external_ref].update(payment_info)
        else:
            payments_db[external_ref] = {
                **payment_info,
                "fecha_creacion": datetime.now().isoformat()
            }

        # Solo procesar si está aprobado y no procesado antes
        if (payment_data.get('status') == 'approved' and 
            not payments_db[external_ref].get('procesado_ganamos')):
            
            usuario_id = payments_db[external_ref].get('usuario_id')
            monto = payments_db[external_ref].get('monto')
            
            if usuario_id and monto:
                logger.info(f"Iniciando carga en Ganamos para {usuario_id}")
                
                # Intento único de carga
                try:
                    success, balance = carga_ganamos(usuario_id, float(monto))
                    
                    # Registrar resultado (incluso si falló)
                    payments_db[external_ref].update({
                        "procesado_ganamos": True,
                        "ganamos_success": success,
                        "ganamos_balance": balance if success else None,
                        "ganamos_last_attempt": datetime.now().isoformat()
                    })
                    
                    if success:
                        logger.info(f"Carga exitosa para {usuario_id}")
                    else:
                        logger.error(f"Fallo en carga para {usuario_id}")
                        
                except Exception as e:
                    logger.error(f"Error crítico en carga_ganamos: {str(e)}")
                    payments_db[external_ref].update({
                        "procesado_ganamos": True,
                        "ganamos_success": False,
                        "ganamos_error": str(e),
                        "ganamos_last_attempt": datetime.now().isoformat()
                    })

    except Exception as e:
        logger.error(f"Error procesando pago {payment_id}: {str(e)}")

@app.post("/verificar_pago/")
async def verificar_pago(request: Request):
    try:
        data = await request.json()
        id_pago_unico = data.get("id_pago_unico")
        
        if not id_pago_unico:
            raise HTTPException(status_code=400, detail="Se requiere id_pago_unico")

        # Buscar en base de datos local
        if id_pago_unico in payments_db:
            return payments_db[id_pago_unico]
            
        # Si no está, consultar MP
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        search_url = f"https://api.mercadopago.com/v1/payments/search?external_reference={id_pago_unico}"
        
        response = requests.get(search_url, headers=headers, timeout=15)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Error al consultar MercadoPago")

        results = response.json().get("results", [])
        if not results:
            return {"status": "not_found"}

        latest_payment = max(results, key=lambda x: x["date_created"])
        
        # Guardar en DB
        payments_db[id_pago_unico] = {
            "payment_id": latest_payment["id"],
            "status": latest_payment["status"],
            "monto": latest_payment["transaction_amount"],
            "fecha_creacion": datetime.now().isoformat(),
            "fecha_actualizacion": datetime.now().isoformat()
        }

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
