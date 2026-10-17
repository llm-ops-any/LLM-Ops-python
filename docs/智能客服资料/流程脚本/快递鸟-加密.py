def main(params):
    import json
    import hashlib
    import base64

    logistic_code = str(params.get("logistic_code") or "").strip()
    shipper_code = str(params.get("shipper_code") or "").strip()
    customer_name = str(params.get("customer_name") or "").strip()
    # 1.将RequestData和ApiKey拼接
    request_data = {"LogisticCode": logistic_code}
    if shipper_code:
        request_data["ShipperCode"] = shipper_code
    if customer_name:
        request_data["CustomerName"] = customer_name

    request_data_str = json.dumps(request_data, ensure_ascii=False)
    # 需要到官网拿
    api_key = ""
    # 2.MD5加密并转换成小写
    md5_hash = hashlib.md5((request_data_str + api_key).encode("utf-8")).hexdigest()
    # 3.Base64编码
    data_sign = base64.b64encode(md5_hash.encode("utf-8")).decode("utf-8")

    return {
        "RequestType": 8002,
        "EBusinessID": 1939839,
        "DataSign": data_sign,
        "RequestData": request_data_str,
    }
