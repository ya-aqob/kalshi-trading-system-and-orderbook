from .Session import Session
import requests
from requests import Response

def send_request(session: Session, method, base_url, path, data=None) -> Response:
    '''Makes request to base_url + path with Kalshi authentication.
       
       Returns Response object. Raises status errors via raise_for_status.
    '''
    timestampt_str = session.gen_timestampstr()

    path_without_query = path.split('?')[0]
    msg_string = timestampt_str + method + path_without_query

    sig = session.sign_pss_text(msg_string)

    headers = {
        'KALSHI-ACCESS-KEY': session.access_key,
        'KALSHI-ACCESS-SIGNATURE': sig,
        'KALSHI-ACCESS-TIMESTAMP': timestampt_str
    }

    match method:
        case "GET":
            response = requests.get(base_url + path, headers=headers, params=data)
        case "PUT":
                response = requests.put(base_url + path, headers=headers, json=data)
        case "POST":
            response = requests.post(base_url + path, headers=headers, json=data)
        case "DELETE":
                response = requests.delete(base_url + path, headers=headers, json=data)

    
    response.raise_for_status()

    return response