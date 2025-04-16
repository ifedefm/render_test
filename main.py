from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from threading import Thread
import logging
from datetime import datetime
import uuid
import pandas as pd
app = FastAPI()

# Configuración
ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "APP_USR-6860291365229768-041516-f3062a760f490a74252d13707b749f22-213411347")
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
        plataforma = data.get("plataforma")

        if not all([usuario_id, monto, email, plataforma]):
            raise HTTPException(status_code=400, detail="Faltan campos obligatorios: usuario_id, monto, email o plataforma")

        from funciones_gencb import user_is_valid
        login_data = pd.read_csv('logins.csv')
        login_row = login_data[login_data['plataforma'] == plataforma]

        if login_row.empty:
            raise HTTPException(status_code=400, detail=f"No se encontró configuración para plataforma '{plataforma}'")

        usuario_login = login_row.iloc[0]['usuario']
        contrasenia_login = login_row.iloc[0]['contrasenia']

        is_valid, user_data = user_is_valid(usuario_id, usuario_login, contrasenia_login)

        if not is_valid:
            logger.error(f"Usuario {usuario_id} no es válido en {plataforma}")
            raise HTTPException(
                status_code=400,
                detail=f"El usuario {usuario_id} no existe en la plataforma '{plataforma}'"
            )

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
            "plataforma": plataforma,
            "status": "pending",
            "payment_id": None,
            "user_data": user_data,
            "fecha_creacion": datetime.now().isoformat()
        }

        return {
            "id_pago_unico": id_pago_unico,
            "preference_id": preference_id,
            "url_pago": response.json()["init_point"]
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error al crear pago: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/notificacion/")
async def webhook(request: Request):
    try:
        # Manejar notificación
        data = await request.json()
        logger.info(f"Notificación recibida: {data}")

        # Ignorar merchant_orders
        if 'merchant_order' in str(data.get('topic', '')):
            logger.info("Ignorando notificación de merchant_order")
            return JSONResponse(content={"status": "ignored"}, status_code=200)

        # Extraer payment_id
        payment_id = None
        if 'data' in data and 'id' in data['data']:  # Formato webhook
            payment_id = data['data']['id']
        elif 'id' in data:  # Formato backup
            payment_id = data['id']

        if payment_id:
            Thread(target=process_payment_notification, args=(payment_id,), daemon=True).start()

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
        if existing and existing.get('procesado_gencb'):
            logger.info(f"Pago {payment_id} ya fue procesado")
            return

        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        
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

        if (payment_data.get('status') == 'approved' and 
            not payments_db[external_ref].get('procesado_gencb')):
            
            usuario_id = payments_db[external_ref].get('usuario_id')
            monto = payments_db[external_ref].get('monto')
            plataforma = payments_db[external_ref].get('plataforma')
            
            if usuario_id and monto and plataforma:
                logger.info(f"Iniciando carga en {plataforma} para {usuario_id}")
                
                try:
                    from funciones_gencb import carga_genc
                    import pandas as pd

                    login_data = pd.read_csv('logins.csv')

                    credenciales = login_data[login_data['plataforma'] == plataforma]

                    if credenciales.empty:
                        raise Exception(f"No se encontraron credenciales para la plataforma: {plataforma}")

                    usuario = credenciales.iloc[0]['usuario']
                    contrasenia = credenciales.iloc[0]['contrasenia']

                    result = carga_genc(
                        usuario_name=usuario_id,
                        monto=int(monto),
                        usuario=usuario,
                        contrasenia=contrasenia
                    )

                    if result is None:
                        raise Exception("carga_genc no devolvió resultado")
                    
                    success, balance = result
                    
                    # Registrar resultado
                    payments_db[external_ref].update({
                        "procesado_gencb": True,
                        f"{plataforma}_success": success,
                        f"{plataforma}_balance": balance if success else None,
                        f"{plataforma}_last_attempt": datetime.now().isoformat()
                    })
                    
                    if success:
                        logger.info(f"Carga exitosa en {plataforma} para {usuario_id}")
                    
# Nuevo: actualizar archivo CSV en GitHub 
                        try:
                            from funciones import actualizar_csv_pago
                            actualizar_csv_pago(usuario_id, int(monto))
                            logger.info("Archivo CSV actualizado exitosamente en GitHub")
                        except Exception as e:
                            logger.error(f"Error al actualizar el CSV en GitHub: {str(e)}")

                    else:
                        logger.error(f"Fallo en carga para {usuario_id}")
                        
                except Exception as e:
                    logger.error(f"Error crítico en carga_genc: {str(e)}")
                    payments_db[external_ref].update({
                        "procesado_gencb": True,
                        f"{plataforma}_success": False,
                        f"{plataforma}_error": str(e),
                        f"{plataforma}_last_attempt": datetime.now().isoformat()
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

        if id_pago_unico in payments_db:
            pago_data = payments_db[id_pago_unico]

            plataforma = None
            for key in pago_data:
                if key.endswith("_success"):
                    plataforma = key.replace("_success", "")
                    break

            if plataforma:
                success_key = f"{plataforma}_success"
                pago_data["gencb_success"] = pago_data.get(success_key)
                pago_data["procesado_gencb"] = pago_data.get("procesado_gencb", False)

            return pago_data
            
        # Consultar MP (solo para información)
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        search_url = f"https://api.mercadopago.com/v1/payments/search?external_reference={id_pago_unico}"
        
        response = requests.get(search_url, headers=headers, timeout=15)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Error al consultar MercadoPago")

        results = response.json().get("results", [])
        if not results:
            return {"status": "not_found"}

        latest_payment = max(results, key=lambda x: x["date_created"])
        
        # Guardar solo información (sin marcar como procesado)
        payments_db[id_pago_unico] = {
            "payment_id": latest_payment["id"],
            "status": latest_payment["status"],
            "monto": latest_payment["transaction_amount"],
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
