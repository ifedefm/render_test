import requests

def carga_genc(monto, usuario_name):
    try:
        session = requests.Session()

        # 1. Login
        url_login = 'https://wallet.casinoenvivo.club/api/admin/login'
        payload_login = {
            'alias': 'Cess93',
            'password': 'Dota2dota2**',
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
            'company': 'GECN',
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
            # Obtener balance actual (ajusta según la API real)
            balance = 0  # Reemplaza con la lógica real para obtener el balance
            return True, balance
        else:
            return False, None


def user_is_valid(usuario_name):
    session = requests.Session()
    
    # Datos de autenticación (considera usar variables de entorno)
    auth_data = {
        'alias': 'Cess93',
        'password': 'Dota2dota2**',
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

    except Exception as e:
        print(f"Error en carga_genc: {str(e)}")
        return False, None
