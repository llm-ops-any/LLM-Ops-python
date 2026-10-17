import base64
import io
import os

import requests

PNG_1X1 = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)

BASE = 'http://llmops-nginx:80/api'
print('[环境变量]',
      'ID=', repr(os.getenv('COS_SECRET_ID')),
      'KEY=', repr(os.getenv('COS_SECRET_KEY')),
      'BUCKET=', repr(os.getenv('COS_BUCKET')),
      'REGION=', repr(os.getenv('COS_REGION')),
      'SCHEME=', repr(os.getenv('COS_SCHEME')),
      'DOMAIN=', repr(os.getenv('COS_DOMAIN')))

token = requests.post(BASE + '/auth/password-login',
                      json={'email': 'admin@llmops.com', 'password': 'Llmops@2026'},
                      timeout=20).json()['data']['access_token']
headers = {'Authorization': 'Bearer ' + token}

buffer = io.BytesIO(PNG_1X1)

resp = requests.post(BASE + '/upload-files/image', headers=headers,
                     files={'file': ('probe.png', buffer, 'image/png')}, timeout=60)
print('[上传图片]', resp.status_code, resp.text[:300])
