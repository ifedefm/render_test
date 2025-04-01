from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from threading import Thread

app = FastAPI()

# Configuración
ACCESS_TOKEN = ("APP_USR-5177967231468413-032619-a7b3ab70df053bfb323007e57562341f-324622221")  # Cambia por tu token real
BASE_URL = 'https://streamlit-test-eiu8.onrender.com'  # Tu URL pública

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Base de datos temporal
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

        preference_data = {
            "items": [{
                "title": f"Recarga saldo - {usuario_id}",
                "quantity": 1,
                "unit_price": float(monto),
                "currency_id": "ARS"
            }],
            "payer": {"email": email},
            "payment_methods": {"excluded_payment_types": [{"id": "atm"}]},
            "back_urls": {  # 👈 URLs obligatorias con auto_return
                "success": f"{BASE_URL}/pago_exitoso",
                "failure": f"{BASE_URL}/pago_fallido",
                "pending": f"{BASE_URL}/pago_pendiente"
            },
            "auto_return": "approved",  # Redirige automáticamente al éxito
            "notification_url": f"{BASE_URL}/notificacion/",
            "external_reference": usuario_id,
            "binary_mode": True
        }

        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }

        response = requests.post(
            "https://api.mercadopago.com/checkout/preferences",
            json=preference_data,
            headers=headers
        )

        if response.status_code != 201:
            error_msg = response.json().get("message", "Error en MercadoPago")
            raise HTTPException(status_code=400, detail=error_msg)

        return {
            "preference_id": response.json()["id"],
            "url_pago": response.json()["init_point"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/notificacion/")
async def webhook(request: Request):
    """Endpoint optimizado para MercadoPago"""
    try:
        # Aceptar JSON o form-data
        try:
            data = await request.json()
        except:
            form_data = await request.form()
            data = dict(form_data)
        
        print(f"📩 Notificación recibida: {data}")

        # Validar estructura
        if not data.get("data", {}).get("id"):
            return JSONResponse(content={"status": "invalid_data"}, status_code=400)

        # Procesar en segundo plano
        Thread(
            target=process_payment_notification,
            args=(data["data"]["id"],),
            daemon=True
        ).start()

        # Respuesta inmediata (HTTP 200)
        return JSONResponse(content={"status": "received"})

    except Exception as e:
        print(f"🚨 Error en webhook: {str(e)}")
        return JSONResponse(content={"status": "error"}, status_code=500)

def process_payment_notification(payment_id: str):
    """Procesa el pago en segundo plano"""
    try:
        print(f"🔍 Procesando pago {payment_id}...")
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        
        # 1. Obtener detalles del pago
        payment_data = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=headers,
            timeout=10
        ).json()

        # 2. Guardar en base de datos
        preference_id = payment_data.get("external_reference")
        if preference_id:
            payments_db[preference_id] = {
                "payment_id": payment_id,
                "status": payment_data["status"],
                "monto": payment_data["transaction_amount"],
                "fecha": payment_data["date_approved"]
            }
            print(f"✅ Pago registrado: {preference_id}")

    except Exception as e:
        print(f"⚠️ Error en background: {str(e)}")

@app.post("/verificar_pago/")
async def verificar_pago(request: Request):
    """Verificación manual desde Streamlit"""
    try:
        data = await request.json()
        preference_id = data.get("preference_id")
        
        if not preference_id:
            raise HTTPException(status_code=400, detail="Se requiere preference_id")

        # 1. Buscar en base de datos local
        if preference_id in payments_db:
            return payments_db[preference_id]
        
        # 2. Consultar a MP si no está localmente
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        search_url = f"https://api.mercadopago.com/v1/payments/search?external_reference={preference_id}"
        
        response = requests.get(search_url, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Error al buscar pagos")

        results = response.json().get("results", [])
        if not results:
            return {"status": "pending"}

        latest_payment = max(results, key=lambda x: x["date_created"])
        return {
            "status": latest_payment["status"],
            "payment_id": latest_payment["id"],
            "monto": latest_payment["transaction_amount"],
            "fecha": latest_payment["date_approved"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def health_check():
    return {"status": "API operativa"}
