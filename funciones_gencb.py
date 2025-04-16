import requests
import pandas as pd

#FUNCION UPDATE CSV
import base64    
import os        
from io import StringIO    
# Configuración de GitHub
GITHUB_REPO = "ifedefm/ganamos_test"
GITHUB_BRANCH = "main"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # debe estar seteado en tus env variables de Render
#FUNCION UPDATE CSV

def carga_genc(monto, usuario_name,usuario,contrasenia):
    try:
        session = requests.Session()

        # 1. Login
        url_login = 'https://wallet.casinoenvivo.club/api/admin/login'
        payload_login = {
            'alias': usuario,
            'password': contrasenia,
            'otp': ''
        }

        response = session.post(url_login, json=payload_login)
        response.raise_for_status()  # Lanza excepción si hay error HTTP
        
        login_data = response.json()
        session_id = login_data['user']['session']
        company_id = login_data['user']['company']

        # 2. Buscar usuario
        url_users = 'https://wallet.casinoenvivo.club/api/admin/agentsUsersSearch'
        payload_users = {
            'session': session_id,
            'freeText': usuario_name,
            'company': company_id,
        }

        response_user = session.post(url_users, json=payload_users)
        response_user.raise_for_status()
        
        user_data = response_user.json()
        if not user_data['users']:
            return False, None  # Usuario no encontrado

        target_user = user_data['users'][0]
        if target_user['alias'] != usuario_name:
            return False, None  # Usuario no coincide

        # 3. Realizar carga
        url_deposit = 'https://wallet.casinoenvivo.club/api/admin/manualDeposit'
        payload_deposit = {
            "session": session_id,
            "company": company_id,
            "user": target_user['user'],
            "method": "AGENTS",
            "amount": int(monto) * 100,
            "status": "NEW",
            "comment": "",
            "db": target_user['db']
        }

        response_deposit = session.post(url_deposit, json=payload_deposit)
        response_deposit.raise_for_status()
        
        deposit_result = response_deposit.json()
        if deposit_result.get('result') == 'OK':
            # Obtener balance actual
            balance = deposit_result.get('newBalance', 0) / 100  # Ajusta según la respuesta real
            return True, balance
        else:
            return False, None

    except Exception as e:
        print(f"Error en carga_genc: {str(e)}")
        return False, None

def user_is_valid(usuario_name,usuario,contrasenia):
    session = requests.Session()
    
    # Datos de autenticación (considera usar variables de entorno)
    auth_data = {
        'alias': usuario,
        'password': contrasenia,
        'otp': ''
    }
    
    try:
        # 1. Autenticación
        auth_response = session.post(
            'https://wallet.casinoenvivo.club/api/admin/login',
            json=auth_data,
            timeout=10
        )
        auth_response.raise_for_status()
        
        session_id = auth_response.json()['user']['session']
        company_id = auth_response.json()['user']['company']
        
        # 2. Búsqueda del usuario
        search_data = {
            'session': session_id,
            'freeText': usuario_name,
            'company': company_id
        }
        
        search_response = session.post(
            'https://wallet.casinoenvivo.club/api/admin/agentsUsersSearch',
            json=search_data,
            timeout=10
        )
        search_response.raise_for_status()
        
        users = search_response.json().get('users', [])
        
        # 3. Verificación
        if not users:
            return False, {"error": "Usuario no encontrado"}
            
        user_found = next((u for u in users if u['alias'] == usuario_name), None)
        
        return bool(user_found), search_response.json()
        
    except Exception as e:
        return False, {"error": str(e)}


def actualizar_csv_pago(usuario: str, monto: float, commit_message="Actualizar registros de cargas"):
    file_name = "registros_cargas.csv"
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_name}"

    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    # Obtener archivo actual del repositorio
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        file_info = response.json()
        sha = file_info["sha"]
        content_encoded = file_info["content"]
        csv_str = base64.b64decode(content_encoded).decode('utf-8')
        df = pd.read_csv(StringIO(csv_str))
    elif response.status_code == 404:
        # Si no existe el archivo, se crea uno nuevo
        df = pd.DataFrame(columns=["usuario", "monto_cargado_hasta_la_fecha"])
        sha = None
    else:
        raise Exception(f"Error al obtener el archivo CSV desde GitHub: {response.json()}")

    # Actualizar o agregar fila del usuario
    if usuario in df["usuario"].values:
        df.loc[df["usuario"] == usuario, "monto_cargado_hasta_la_fecha"] += monto
    else:
        df = pd.concat({"usuario": usuario, "monto_cargado_hasta_la_fecha": monto}, ignore_index=True)

    # Convertir de nuevo a CSV
    csv_updated = df.to_csv(index=False)
    encoded_content = base64.b64encode(csv_updated.encode()).decode()

    # Preparar payload para PUT
    data = {
        "message": commit_message,
        "content": encoded_content,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        data["sha"] = sha

    put_response = requests.put(url, headers=headers, json=data)
    if put_response.status_code not in [200, 201]:
        raise Exception(f"Error al actualizar el archivo en GitHub: {put_response.json()}")

    return {"mensaje": "CSV actualizado exitosamente"}
