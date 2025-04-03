import requests
import os
import time

def login_ganamos():
    """Función de login para Ganamos con manejo de errores mejorado"""
    try:
        url = 'https://agents.ganamos.bet/api/user/login'
        data = {"password": '1111aaaa', "username": 'adminflamingo'}
        
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        }

        response = session.post(url, json=data, headers=headers, timeout=10)
        response.raise_for_status()
        
        if "session" not in response.cookies:
            raise Exception("No se encontró cookie de sesión en la respuesta")
        
        session_id = response.cookies["session"]
        
        # Verificar sesión
        headers_check = {
            "accept": "application/json, text/plain, */*",
            "cookie": f"session={session_id}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        }
        
        # Obtener ID del usuario padre
        check_url = "https://agents.ganamos.bet/api/user/check"
        check_response = session.get(check_url, headers=headers_check, timeout=10)
        check_response.raise_for_status()
        parent_id = check_response.json()['result']['id']
        
        # Obtener lista de usuarios
        users_url = 'https://agents.ganamos.bet/api/agent_admin/user/'
        params = {'count': '100', 'page': '0', 'user_id': parent_id}
        users_response = session.get(users_url, params=params, headers=headers_check, timeout=10)
        users_response.raise_for_status()
        
        lista_usuarios = {x['username']: x['id'] for x in users_response.json()["result"]["users"]}
        
        return lista_usuarios, session_id
        
    except Exception as e:
        logger.error(f"Error en login_ganamos2: {str(e)}")
        raise

def carga_ganamos(alias: str, monto: float) -> tuple[bool, float]:
    """Versión mejorada para cargar saldo en Ganamos con manejo de errores"""
    try:
        # 1. Obtener credenciales
        lista_usuarios, session_id = login_ganamos2()
        
        if alias not in lista_usuarios:
            logger.error(f"Usuario '{alias}' no encontrado")
            return False, 0.0
            
        user_id = lista_usuarios[alias]

        # 2. Configurar headers para la carga
        headers = {
            "accept": "application/json, text/plain, */*",
            "cookie": f"session={session_id}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        }

        # 3. Realizar la carga
        payment_url = f"https://agents.ganamos.bet/api/agent_admin/user/{user_id}/payment/"
        payment_data = {"operation": 0, "amount": float(monto)}
        
        payment_response = session.post(
            payment_url,
            json=payment_data,
            headers=headers,
            timeout=10
        )
        payment_response.raise_for_status()

        # 4. Verificar balance después de 2 segundos
        time.sleep(2)
        balance_url = "https://agents.ganamos.bet/api/user/balance"
        balance_response = session.get(balance_url, headers=headers, timeout=10)
        balance_response.raise_for_status()
        
        balance = balance_response.json().get("result", {}).get("balance", 0.0)
        
        return True, balance

    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión en carga_ganamos2: {str(e)}")
        return False, 0.0
    except Exception as e:
        logger.error(f"Error inesperado en carga_ganamos2: {str(e)}")
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


