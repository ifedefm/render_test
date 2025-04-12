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
            
        user_found = next((u for u in users if u['alias'] == usuario_name), None
        
        return bool(user_found), search_response.json()
        
    except Exception as e:
        return False, {"error": str(e)}
