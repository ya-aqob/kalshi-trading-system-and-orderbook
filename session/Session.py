import base64
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature
import datetime

class Session:
    path_to_private_key: str
    access_key: str

    def __init__(self, path_to_private_key: str, access_key: str):
        self.path_to_private_key = path_to_private_key
        self.access_key = access_key
        
        try:
            self.private_key = self.load_private_key_from_file(path_to_private_key)
        except:
            raise Exception("Private key could not be loaded")

    def load_private_key_from_file(self, file_path: str):
        '''Loads private key from file_path and returns private key'''
        with open(file_path, "rb") as key_file:
            private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend()
        )
        return private_key
    
    def sign_pss_text(self, text: str):
        '''Signs text with session private key'''
        message = text.encode('utf-8')
        try:
            signature = self.private_key.sign(
                message,
                padding.PSS(
                 mgf=padding.MGF1(hashes.SHA256()),
                 salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256()
            )
            return base64.b64encode(signature).decode('utf-8')
        except InvalidSignature as e:
            raise ValueError("RSA sign PSS failed") from e
    
    def gen_timestampstr(self):
        '''Generates a timestampstr for signing message'''
        current_time = datetime.datetime.now()
        timestamp = current_time.timestamp()
        current_time_milliseconds = int(timestamp * 1000)
        timestampt_str = str(current_time_milliseconds)
        return timestampt_str