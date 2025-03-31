from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
import requests
import os

app = FastAPI()

# Configuración
ACCESS_TOKEN = "APP_USR-5177967231468413-032619-a7b3ab70df053bfb323007e57562341f-324622221"
BASE_URL = 'https://streamlit-test-eiu8.onrender.com'

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Base de datos temporal
usuarios_saldo = {}

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
            "payment_methods": {
                "excluded_payment_types": [{"id": "atm"}]
            },
            "back_urls": {
                "success": f"{BASE_URL}/success",
                "failure": f"{BASE_URL}/failure",
                "pending": f"{BASE_URL}/pending"
            },
            "auto_return": "approved",
            "notification_url": f"{BASE_URL}/notificacion",
            "statement_descriptor": "RECARGAS APP",
            "binary_mode": True,
            "external_reference": usuario_id
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


@app.post("/verificar_pago/")
async def verificar_pago(request: Request):
    try:
        data = await request.json()
        preference_id = data.get("preference_id")
        
        if not preference_id:
            raise HTTPException(status_code=400, detail="Se requiere preference_id")

        # 1. Buscar en la API de MP los pagos para esta preferencia
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        search_url = f"https://api.mercadopago.com/v1/payments/search?external_reference={preference_id}"
        
        response = requests.get(search_url, headers=headers)
        
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Error al buscar pagos")

        results = response.json().get("results", [])
        
        if not results:
            return {"status": "pending", "detail": "No se encontraron pagos"}

        # 2. Tomar el pago más reciente
        latest_payment = max(results, key=lambda x: x["date_created"])
        
        return {
            "status": latest_payment["status"],
            "payment_id": latest_payment["id"],
            "monto": latest_payment["transaction_amount"],
            "fecha": latest_payment["date_approved"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/notificacion/")
async def webhook(request: Request):
    try:
        # Aceptar tanto JSON como form-data
        try:
            data = await request.json()
        except:
            data = await request.form()
        
        print(f"🔔 Webhook recibido: {data}")  # Debug crucial

        # Respuesta inmediata (MP espera respuesta en <5 segundos)
        response = JSONResponse(content={"status": "received"})
        
        # Procesamiento en segundo plano (async)
        if "data" in data and "id" in data["data"]:
            payment_id = data["data"]["id"]
            
            # Verificar el pago (en background)
            import threading
            threading.Thread(target=process_payment, args=(payment_id,)).start()
        
        return response

    except Exception as e:
        print(f"❌ Error en webhook: {str(e)}")
        return JSONResponse(content={"status": "error"}, status_code=500)

def process_payment(payment_id: str):
    """Procesa el pago en segundo plano"""
    try:
        print(f"🔍 Procesando pago {payment_id}...")
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        
        # 1. Obtener detalles del pago
        payment_info = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=headers
        ).json()
        
        print(f"📊 Estado del pago: {payment_info.get('status')}")
        
        # 2. Guardar en base de datos (ejemplo con diccionario)
        preference_id = payment_info.get("external_reference")
        if preference_id:
            payments_db[preference_id] = {
                "payment_id": payment_id,
                "status": payment_info["status"],
                "monto": payment_info["transaction_amount"]
            }
            print(f"💾 Guardado: {preference_id} → {payment_id}")
            
    except Exception as e:
        print(f"🔥 Error en background: {str(e)}")


@app.get("/")
async def health_check():
    return {"status": "API operativa"}
