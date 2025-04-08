import requests
import os
import time
import logging
from threading import Thread
from datetime import datetime
import time
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import requests

import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import logging
from datetime import datetime
import time
import streamlit as st

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def login_ganamos(usuario: str, contrasenia: str) -> tuple[dict, str]:
    """Versión optimizada con mejor manejo de errores y headers actualizados"""
    try:
        # Configurar sesión con reintentos
        session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504, 403, 404, 408],
            allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"],
            raise_on_status=False
        )
        session.mount('https://', HTTPAdapter(max_retries=retries))
        
        # Headers actualizados y más realistas
        login_headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://agents.ganamos.bet",
            "Pragma": "no-cache",
            "Referer": "https://agents.ganamos.bet/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest"
        }

        # 1. Realizar login
        url = 'https://agents.ganamos.bet/api/user/login'
        data = {"password": contrasenia, "username": usuario}

        logger.info("Enviando solicitud de login")
        response = session.post(url, json=data, headers=login_headers, timeout=30)
        
        # Verificación robusta de la respuesta
        if not response.text:
            raise Exception("Empty response from server (no data received)")
            
        try:
            response_data = response.json()
        except ValueError as e:
            logger.error(f"Invalid JSON response: {response.text[:500]}")
            raise Exception(f"Server returned invalid JSON (status {response.status_code})")

        if response.status_code == 200 and "session" in response.cookies:
            session_id = response.cookies["session"]
            logger.info("Sesión obtenida correctamente")
        else:
            error_msg = response_data.get('error_message', response.text[:200])
            raise Exception(f"Login failed ({response.status_code}): {error_msg}")

        # 2. Verificar sesión con headers actualizados
        check_headers = {
            **login_headers,  # Hereda los headers base
            "Cookie": f"session={session_id}",
            "Referer": "https://agents.ganamos.bet/",
            "Sec-Ch-Ua": '"Google Chrome";v="127", "Chromium";v="127", "Not-A.Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"'
        }

        check_url = "https://agents.ganamos.bet/api/user/check"
        check_response = session.get(check_url, headers=check_headers, timeout=20)
        
        if check_response.status_code != 200:
            raise Exception(f"Session verification failed ({check_response.status_code}): {check_response.text[:200]}")

        # 3. Obtener lista de usuarios
        parent_id = check_response.json()['result']['id']
        users_url = 'https://agents.ganamos.bet/api/agent_admin/user/'
        params = {
            'count': '10',
            'page': '0',
            'user_id': parent_id,
            'is_banned': 'false',
            'is_direct_structure': 'false'
        }
        
        users_response = session.get(users_url, params=params, headers=check_headers, timeout=20)
        
        if users_response.status_code != 200:
            raise Exception(f"Failed to get users list ({users_response.status_code}): {users_response.text[:200]}")

        usuarios = {u['username']: u['id'] for u in users_response.json()["result"]["users"]}
        logger.info(f"Login exitoso. Usuarios disponibles: {len(usuarios)}")
        
        return usuarios, session_id

    except Exception as e:
        logger.error(f"Error en login_ganamos: {str(e)}", exc_info=True)
        raise

def carga_ganamos(alias: str, monto: float) -> tuple[bool, float]:
    """Versión optimizada para cargar saldo replicando navegador"""
    try:
        logger.info(f"Iniciando carga de saldo para {alias}")
        
        # Configurar sesión con reintentos
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["POST", "GET"]
        )
        session.mount('https://', HTTPAdapter(max_retries=retries))

        # 1. Obtener credenciales
        usuarios, session_id = login_ganamos('adminflamingo', '1111aaaa')
        
        # 2. Verificar usuario
        if alias not in usuarios:
            logger.error(f"Usuario {alias} no encontrado")
            return False, 0.0
            
        user_id = usuarios[alias]

        # 3. Configurar headers para la carga
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "es-419,es;q=0.9,en;q=0.8,pt;q=0.7,it;q=0.6",
            "priority": "u=1, i",
            "referer": "https://agents.ganamos.bet/",
            "sec-ch-ua": "\"Not)A;Brand\";v=\"99\", \"Google Chrome\";v=\"127\", \"Chromium\";v=\"127\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"Windows\"",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
            "cookie": f"session={session_id}"
        }

        # 4. Realizar la carga
        payment_url = f"https://agents.ganamos.bet/api/agent_admin/user/{user_id}/payment/"
        payment_data = {"operation": 0, "amount": float(monto)}
        
        logger.info(f"Enviando carga a {payment_url}")
        response = session.post(
            payment_url,
            json=payment_data,
            headers=headers,
            timeout=15
        )
        
        if response.status_code != 200:
            error_msg = response.json().get('error_message', 'Error desconocido')
            raise Exception(f"Error en carga ({response.status_code}): {error_msg}")

        # 5. Verificar balance
        balance_url = "https://agents.ganamos.bet/api/user/balance"
        time.sleep(2)  # Esperar para asegurar actualización
        balance_response = session.get(balance_url, headers=headers, timeout=10)
        
        balance = 0.0
        if balance_response.status_code == 200:
            balance = balance_response.json().get("result", {}).get("balance", 0.0)
            logger.info(f"Balance actualizado: {balance}")
        
        return True, balance

    except Exception as e:
        logger.error(f"Error en carga_ganamos: {str(e)}")
        return False, 0.0


    
def retirar_ganamos(alias, monto, usuario, contrasenia):
    lista_usuarios, session_id= login_ganamos(usuario,contrasenia)
    id_usuario = lista_usuarios[alias]
    url_carga_ganamos = f'https://agents.ganamos.bet/api/agent_admin/user/{id_usuario}/payment/'

    payload_carga = {"operation":1,
                    "amount":monto}


    header_retiro = {
    "accept": "application/json, text/plain, */*",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "es-419,es;q=0.9,en;q=0.8,pt;q=0.7,it;q=0.6",
    "priority": "u=1, i",
    "referer": "https://agents.ganamos.bet/",
    "sec-ch-ua": "\"Not)A;Brand\";v=\"99\", \"Google Chrome\";v=\"127\", \"Chromium\";v=\"127\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    'cookie': f'session={session_id}'
    }
    response_carga_ganamos = requests.post(url_carga_ganamos,json=payload_carga,headers=header_retiro, cookies={'session':session_id})

    url_balance = 'https://agents.ganamos.bet/api/user/balance'
    header_check= {"accept": "application/json, text/plain, */*",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "es-419,es;q=0.9,en;q=0.8,pt;q=0.7,it;q=0.6",
    "priority": "u=1, i",
    "referer": "https://agents.ganamos.bet/",
    "sec-ch-ua": "\"Not)A;Brand\";v=\"99\", \"Google Chrome\";v=\"127\", \"Chromium\";v=\"127\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    'cookie': f'session={session_id}'
    }
    response_balance = requests.get(url_balance, headers=header_check)
    balance_ganamos = response_balance.json()['result']['balance']
    if response_carga_ganamos.json()['error_message'] is None:
        return True, balance_ganamos
    else:
         return False, balance_ganamos
    

def nuevo_jugador(nueva_contrasenia, nuevo_usuario, usuario, contrasenia ):
    lista_usuarios, session_id= login_ganamos('adminflamingo','1111aaaa')
    print(session_id)

    url_nuevo_usuario = 'https://agents.ganamos.bet/api/agent_admin/user/'

    data = {
        "email": "a",
        "first_name": "a",
        "last_name": "a",
        "password": f"{nueva_contrasenia}",
        "role": 0,
        "username": f"{nuevo_usuario}"
    }

    header_check = {
        "accept": "application/json, text/plain, */*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "es-419,es;q=0.9,en;q=0.8,pt;q=0.7,it;q=0.6",
        "priority": "u=1, i",
        "referer": "https://agents.ganamos.bet/",
        "sec-ch-ua": "\"Not)A;Brand\";v=\"99\", \"Google Chrome\";v=\"127\", \"Chromium\";v=\"127\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        'cookie': f'session={session_id}'
        }

    response = requests.post(url_nuevo_usuario, json=data, headers=header_check)
    if response.json()['status'] == 0:
        return 'Usuario creado',lista_usuarios    
    if 'already exist' in response.json()['error_message']:
        return 'El usuario ya existe, Prueba con otro usuario',lista_usuarios
    

csv_file = 'data.csv'

def guardar_usuario(usuario, contraseña):
        
    if not usuario or not contraseña:
        st.warning('Debe ingresar un usuario y una contraseña.')
        return
    
    resultado, lista_usuarios = nuevo_jugador(nuevo_usuario=usuario, nueva_contrasenia=contraseña, usuario='adminflamingo', contrasenia='1111aaaa')
    
    if 'Usuario creado' in resultado:
        nuevo_dato = pd.DataFrame({'user': [usuario], 'password': [contraseña]})
        
        if os.path.exists(csv_file):
            df = pd.read_csv(csv_file)
            df = pd.concat([df, nuevo_dato], ignore_index=True)
        else:
            df = nuevo_dato
        
        df.to_csv(csv_file, index=False)
        st.success('Usuario creado!!!')
    else:
        st.warning(resultado)


