def main(params):
    import json
    import hashlib
    import base64
    import urllib.parse

    # 1.将RequestData和ApiKey拼接
    request_data = {"LogisticCode": f"{params.get('logistic_code')}"}
    api_key = "" // 需要到官网拿
    combined_data = json.dumps(request_data) + api_key

    # 2.MD5加密并转换成小写
    md5_hash = hashlib.md5(combined_data.encode("utf-8")).hexdigest()

    # 3.Base64编码
    base64_encoded = base64.b64encode(md5_hash.encode("utf-8")).decode("utf-8")

    # 4.URL编码
    url_encoded = urllib.parse.quote(base64_encoded)
    return {
        "RequestType": 8002,
        "EBusinessID": 1880673,
        "DataSign": url_encoded,
        "RequestData": urllib.parse.quote(json.dumps(request_data)),
    }
