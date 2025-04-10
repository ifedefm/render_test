import requests

def carga_genc(monto,usuario_name):
    session = requests.Session()

    url = 'https://wallet.casinoenvivo.club/api/admin/login'
    payload = { 'alias': 'Cess93',
                'password': 'Dota2dota2**',
                'otp': '' }

    response = session.post(url, json=payload)

    response.json()
    session_id = response.json()['user']['session']
    company_id = response.json()['user']['company']
    if session:                             
        url_usuarios = 'https://wallet.casinoenvivo.club/api/admin/agentsUsersSearch'

        payload_users = {
        'session': f'{session_id}',
        'freeText': f'{usuario_name}',
        'company': 'GECN',
        }

        response_user = session.post(url_usuarios, json=payload_users)
        response_user.json()
        dict_user = response_user.json()['users']
        id_user = dict_user[0]['user']
        name_user = dict_user[0]['alias']
        db_user = dict_user[0]['db']
        if name_user == payload_users['freeText']:
            url_carga = 'https://wallet.casinoenvivo.club/api/admin/manualDeposit'
            monto = int(monto)*100
            payload = {
                        "session": f"{session_id}",
                        "company": f"{company_id}",
                        "user": f"{id_user}",
                        "method": "AGENTS",
                        "amount": monto,
                        "status": "NEW",
                        "comment": "",
                        "db": db_user
                        }

            response_carga = session.post(url_carga, json=payload)
            response_carga.json()
            if response_carga.json()['result'] == 'OK':
                return f'Carga Exitosa para {name_user}', 'success'
            else:
                return f'Error en la carga para {name_user}', 'error'