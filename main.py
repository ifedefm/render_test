from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
import requests
import os

app = FastAPI()

# Configuración
ACCESS_TOKEN = "APP_USR-7399764412139422-042622-5c8000e5a8932bbbdae5e8d418480e65-89912040"
BASE_URL = 'https://render-notify-mp.onrender.com'

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
        print(f"🔧 Token MP usado: {ACCESS_TOKEN[:5]}...")  # Muestra primeros 5 chars
        print(f"🌐 Notification URL: {BASE_URL}/notificacion/")
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
        #Logs Temporales
        print(f"🔧 Token MP usado: {ACCESS_TOKEN[:5]}...")  # Muestra primeros 5 chars
        print(f"🌐 Notification URL: {BASE_URL}/notificacion/")
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
        # Intentar obtener JSON o parámetros de la URL
        data = await request.json() if request.headers.get("content-type") == "application/json" else request.query_params
        payment_id = data.get("data.id") or data.get("id")  # Ajuste para recibir `data.id`
        
        if not payment_id:
            raise HTTPException(status_code=400, detail="Se requiere un payment_id")

        # Log para depuración
        print(f"🔍 Verificando pago con ID: {payment_id}")

        # Consultar el estado del pago
        search_headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        payment_response = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=search_headers
        )

        if payment_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Error al obtener información del pago")

        payment_data = payment_response.json()
        status = payment_data.get("status")
        usuario_id = payment_data.get("external_reference")

        if not usuario_id:
            raise HTTPException(status_code=400, detail="No se encontró usuario_id en el pago")

        print(f"📌 Estado del pago: {status}, Usuario: {usuario_id}")

        if status == "approved":
            monto = payment_data.get("transaction_amount", 0)
            usuarios_saldo[usuario_id] = usuarios_saldo.get(usuario_id, 0) + monto

            try:
                from funciones_ganamos import carga_ganamos
                carga_ganamos(usuario=usuario_id, monto=monto)
            except Exception as e:
                print(f"⚠️ Error en carga_ganamos: {str(e)}")

            return {
                "status": "approved",
                "payment_id": payment_id,
                "monto": monto,
                "fecha": payment_data.get("date_approved"),
                "metodo": payment_data.get("payment_type_id"),
            }

        return {"status": status or "pending"}

    except Exception as e:
        print(f"❌ Error en verificar_pago: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/notificacion/")
async def webhook(request: Request):
    try:
        print("\n🔔 Notificación recibida")  # Debug en logs
        
        # Opción 1: Para content-type: application/json
        try:
            data = await request.json()
            print(f"📦 JSON data: {data}")
        except:
            # Opción 2: Para x-www-form-urlencoded
            form_data = await request.form()
            data = dict(form_data)
            print(f"📦 Form data: {data}")
        
        payment_id = data.get("data.id") or data.get("id")
        if not payment_id:
            print("⚠️ No se encontró payment_id")
            return {"status": "invalid_data"}
        
        print(f"🔍 Verificando pago: {payment_id}")
        
        # Verificar el pago
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        payment_response = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=headers
        )
        
        if payment_response.status_code != 200:
            error_msg = payment_response.json().get("message", "Error en MP")
            print(f"❌ Error MP: {error_msg}")
            return {"status": "error", "detail": error_msg}
        
        payment_data = payment_response.json()
        print(f"📊 Estado del pago: {payment_data.get('status')}")
        
        return {"status": "processed"}
        
    except Exception as e:
        print(f"🔥 Error crítico: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)}
        )


@app.get("/")
async def health_check():
    return {"status": "API operativa"}
