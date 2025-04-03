import requests
import os
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def login_ganamos():
    """Función mejorada para login en Ganamos con manejo de errores"""
    url = 'https://agents.ganamos.bet/api/user/login'
    
    try:
        # Obtener credenciales de variables de entorno
        username = os.getenv("GANAMOS_USER", "adminflamingo")
        password = os.getenv("GANAMOS_PASS", "1111aaaa")
        
        data = {
            "password": password,
            "username": username    
        }

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Referer": "https://agents.ganamos.bet/"
        }

        # Configuración de reintentos
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504, 403],
            allowed_methods=["POST"]
        )
        session.mount('https://', HTTPAdapter(max_retries=retries))

        # 1. Login
        response = session.post(url, json=data, headers=headers, timeout=10)
        response.raise_for_status()
        
        if 'session' not in response.cookies:
            raise ValueError("No se encontró cookie de sesión en la respuesta")
            
        session_id = response.cookies["session"]

        # 2. Verificar sesión
        header_check = {
            "accept": "application/json, text/plain, */*",
            "cookie": f"session={session_id}",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        }
        
        response_check = session.get(
            "https://agents.ganamos.bet/api/user/check",
            headers=header_check,
            timeout=10
        )
        response_check.raise_for_status()
        
        parent_id = response_check.json()['result']['id']

        # 3. Obtener lista de usuarios
        params_users = {
            'count': '100',  # Aumentamos el límite para obtener todos los usuarios
            'page': '0',
            'user_id': parent_id
        }
        
        response_users = session.get(
            'https://agents.ganamos.bet/api/agent_admin/user/',
            params=params_users,
            headers=header_check,
            timeout=10
        )
        response_users.raise_for_status()
        
        lista_usuarios = {x['username']: x['id'] for x in response_users.json()["result"]["users"]}
        return lista_usuarios, session_id

    except requests.exceptions.RequestException as e:
        raise Exception(f"Error de conexión en login_ganamos: {str(e)}")
    except Exception as e:
        raise Exception(f"Error inesperado en login_ganamos: {str(e)}")

def carga_ganamos(alias: str, monto: float) -> tuple[bool, float]:
    """Versión mejorada para cargar saldo en Ganamos"""
    try:
        # 1. Obtener credenciales y sesión
        lista_usuarios, session_id = login_ganamos()
        
        # 2. Verificar que el alias existe
        if alias not in lista_usuarios:
            raise ValueError(f"El usuario '{alias}' no existe en la lista de usuarios")
            
        user_id = lista_usuarios[alias]

        # 3. Configurar sesión para la carga
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["POST", "GET"]
        )
        session.mount('https://', HTTPAdapter(max_retries=retries))

        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "cookie": f"session={session_id}",
            "referer": "https://agents.ganamos.bet/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        }

        # 4. Realizar la carga
        payment_url = f"https://agents.ganamos.bet/api/agent_admin/user/{user_id}/payment/"
        payment_data = {"operation": 0, "amount": float(monto)}
        
        payment_response = session.post(
            payment_url,
            json=payment_data,
            headers=headers,
            timeout=15
        )
        payment_response.raise_for_status()

        # 5. Verificar balance
        time.sleep(2)  # Espera para asegurar actualización
        
        balance_response = session.get(
            "https://agents.ganamos.bet/api/user/balance",
            headers=headers,
            timeout=10
        )
        balance_response.raise_for_status()
        
        balance = balance_response.json().get("result", {}).get("balance", 0.0)

        # 6. Verificar que no haya mensaje de error
        if payment_response.json().get("error_message"):
            raise ValueError(payment_response.json().get("error_message"))

        return True, balance

    except requests.exceptions.RequestException as e:
        raise Exception(f"Error de conexión en carga_ganamos: {str(e)}")
    except Exception as e:
        raise Exception(f"Error en carga_ganamos: {str(e)}")
    
    
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


